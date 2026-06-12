"""Потоковая доставка длинных ответов: ``sendMessageDraft`` + fallback.

Telegram Bot API ``sendMessageDraft`` (9.3+, для всех ботов с 9.5;
с 10.0 — допускает пустой ``text`` для нативного «Thinking…» placeholder).
Черновик в поле ввода анимируется по мере обновлений с тем же ``draft_id``,
ephemeral 30-секундный preview. После готовности — финал отправляется
обычным ``sendMessage`` (он остаётся в чате).

Если ``sendMessageDraft`` недоступен (старый API, неподдерживаемый чат),
используется прежний паттерн: ``sendMessage`` (loading) →
``editMessageText`` (промежуточные) → финал через ``edit_or_send_message``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Literal

from .api import TelegramClient, TelegramError
from .message_editing import edit_or_send_message
from .rich_message import (
    RICH_MESSAGE_SAFETY_CAP,
    _safe_html_prefix,
    input_rich_message,
)
from .visual import TypingIndicator, is_private_chat

log = logging.getLogger(__name__)

_DraftMode = Literal["draft", "legacy"]

# Throttle: Telegram бьёт по rate-limit'у уже на ~1 update/s, а draft-анимация
# выглядит «дёрганой» при < 0.2 s между кадрами. Дросселируем посредине.
_MIN_DRAFT_INTERVAL_SEC = 0.28
_MIN_DRAFT_CHAR_DELTA = 24
_TELEGRAM_TEXT_LIMIT = 4096

# Typewriter: чем короче итоговый текст, тем меньше кадров; чтобы воркер-пул
# хендлеров не блокировался дольше ~1.5 с, выбираем разумный разброс.
_TYPEWRITER_MAX_FRAMES = 12
_TYPEWRITER_MIN_CHUNK = 40
_TYPEWRITER_FRAME_INTERVAL_SEC = 0.14
_TYPEWRITER_MIN_TEXT_LEN = 60  # короче — не имеет смысла «печатать»

# Описания/коды, при которых черновики недоступны — переходим на legacy.
_DRAFT_UNAVAILABLE_MARKERS = (
    "sendmessagedraft",
    "sendrichmessagedraft",
    "textdraft",
    "method is not found",
    "method not found",
    "unknown method",
    "not implemented",
)

# Маркер «пустой text не разрешён» — Bot API < 10.0 (с 8 мая 2026 разрешён).
_EMPTY_TEXT_REJECTED_MARKERS = (
    "text is empty",
    "message text is empty",
    "text must be non-empty",
)

# Регулярки HTML-safe нарезки.
_HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?>")
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")


def _draft_unavailable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _DRAFT_UNAVAILABLE_MARKERS)


def _empty_text_rejected(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _EMPTY_TEXT_REJECTED_MARKERS)


def _stable_draft_id(*, chat_id: int, seed: int) -> int:
    """Ненулевой draft_id для анимации обновлений одного ответа.

    Telegram анимирует обновления только при совпадающем ``draft_id``;
    разные сессии должны получать разные id, иначе анимации перепутаются.
    """
    mixed = (int(chat_id) * 1_000_003) ^ int(seed)
    return (mixed % 2_147_483_646) + 1


def _safe_slice(text: str, length: int) -> str:
    """Префикс длиной ≤ ``length``, не рвущий HTML-теги и сущности.

    Если внутри ``[0, length)`` оказался не закрытый ``<...`` или ``&...``,
    отступаем до начала этой конструкции. Дополнительно закрываем висящие
    парные теги (``<b><i>...``), чтобы Telegram не отверг сообщение.
    """
    if length >= len(text):
        return text
    cut = length

    last_lt = text.rfind("<", 0, cut)
    last_gt = text.rfind(">", 0, cut)
    if last_lt > last_gt:
        cut = last_lt

    last_amp = text.rfind("&", 0, cut)
    last_semi = text.rfind(";", 0, cut)
    if last_amp > last_semi and cut - last_amp <= 10:
        cut = last_amp

    if cut <= 0:
        return ""

    prefix = text[:cut]
    return _close_open_tags(prefix)


def _close_open_tags(html_text: str) -> str:
    """Закрывает незакрытые парные теги (``<b>foo`` → ``<b>foo</b>``).

    Telegram парсит крайне строго; невалидный HTML → 400 BAD REQUEST и
    промежуточный кадр пропадает. Закрываем по LIFO-стеку.
    """
    stack: list[str] = []
    for match in _HTML_TAG_RE.finditer(html_text):
        closing, tag = match.group(1), match.group(2).lower()
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == tag:
                    del stack[i]
                    break
        else:
            stack.append(tag)
    if not stack:
        return html_text
    return html_text + "".join(f"</{tag}>" for tag in reversed(stack))


def _clip_text(text: str, *, rich: bool) -> str:
    limit = RICH_MESSAGE_SAFETY_CAP if rich else _TELEGRAM_TEXT_LIMIT
    if len(text) <= limit:
        return text
    if rich:
        from .rich_message import truncate_rich_html

        return truncate_rich_html(text, max_len=limit)
    return _clip_telegram_text(text)


def _clip_telegram_text(text: str) -> str:
    """Усекает текст до Telegram-лимита 4096, не разрывая HTML-теги/сущности.

    Закрывающие теги, добавленные ``_safe_slice``/``_close_open_tags``, могут
    «съесть» несколько символов сверху — поэтому подбираем cut итеративно.
    """
    if len(text) <= _TELEGRAM_TEXT_LIMIT:
        return text
    budget = _TELEGRAM_TEXT_LIMIT - 1  # резервируем под "…"
    cut = budget
    for _ in range(8):
        candidate = _safe_slice(text, cut) + "…"
        if len(candidate) <= _TELEGRAM_TEXT_LIMIT:
            return candidate
        cut = max(0, cut - (len(candidate) - _TELEGRAM_TEXT_LIMIT) - 4)
    return text[:_TELEGRAM_TEXT_LIMIT]


def _typewriter_chunks(text: str, *, rich: bool = False) -> list[str]:
    """Постепенно растущие префиксы текста для эффекта «печатает»."""
    if len(text) < _TYPEWRITER_MIN_TEXT_LEN:
        return []
    safe_slice = _safe_html_prefix if rich else _safe_slice
    min_chunk = 32 if rich else _TYPEWRITER_MIN_CHUNK
    target_frames = min(_TYPEWRITER_MAX_FRAMES, max(3, len(text) // min_chunk))
    step = max(min_chunk, len(text) // target_frames)
    chunks: list[str] = []
    cursor = step
    while cursor < len(text):
        chunk = safe_slice(text, cursor)
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)
        cursor += step
    return chunks


class StreamingReply:
    """Сессия одного «потокового» ответа в чат.

    Поток жизни (счастливый путь, draft-режим):

    1. ``open`` — отправляем пустой черновик («Thinking…») или начальный текст.
    2. ``push(partial)`` — пока работаем, обновляем черновик; throttle внутри.
    3. ``finish(text)`` — финальный ``sendMessage`` (с опциональным typewriter).

    Legacy fallback (нет ``sendMessageDraft``):

    1. ``open`` — обычный ``sendMessage`` с loading-текстом, запоминаем id.
    2. ``push`` — ``editMessageText`` того же сообщения.
    3. ``finish`` — ``edit_or_send_message`` (правка → или новое сообщение).
    """

    def __init__(
        self,
        telegram: TelegramClient,
        chat_id: int,
        *,
        draft_id: int,
        message_thread_id: int | None = None,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool = True,
        rich: bool = False,
    ) -> None:
        self._telegram = telegram
        self._chat_id = chat_id
        self._draft_id = draft_id
        self._message_thread_id = message_thread_id
        self._parse_mode = parse_mode
        self._disable_web_page_preview = disable_web_page_preview
        self._rich = rich
        self._rich_draft_active = False
        self._rich_draft_disabled = False
        self._last_fallback_html: str | None = None

        self._mode: _DraftMode = "legacy"
        self._loading_message_id: int | None = None
        self._last_pushed = ""
        self._last_draft_at = 0.0
        self._closed = False
        self._empty_text_supported = True
        self._typing: TypingIndicator | None = None

    @classmethod
    def open(
        cls,
        telegram: TelegramClient,
        chat_id: int,
        initial_text: str = "",
        *,
        draft_id: int | None = None,
        message_thread_id: int | None = None,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool = True,
        chat_action: str | None = "typing",
        rich: bool = False,
    ) -> StreamingReply:
        """Старт сессии: пробует черновик, иначе loading-сообщение.

        ``initial_text=""`` (по умолчанию) показывает нативный «Thinking…»
        placeholder из Bot API 10.0. Если ботом-серверу < 10.0, мы повторяем
        старт с непустым текстом (см. ``_try_start_draft``).
        """
        resolved_draft_id = (
            draft_id
            if draft_id
            else _stable_draft_id(
                chat_id=chat_id,
                seed=int(time.time() * 1000) % 1_000_000_007,
            )
        )
        session = cls(
            telegram,
            chat_id,
            draft_id=resolved_draft_id,
            message_thread_id=message_thread_id,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            rich=rich,
        )
        clipped = _clip_text(initial_text, rich=rich)
        if session._try_start_draft(clipped):
            session._last_pushed = clipped
            session._last_draft_at = time.monotonic()
            session._start_typing(chat_action)
            return session
        # legacy-ветка: нужно непустое loading-сообщение, иначе sendMessage упадёт.
        legacy_text = clipped or "⏳"
        session._start_legacy_loading(legacy_text)
        session._start_typing(chat_action)
        return session

    def push(self, text: str, *, fallback_html: str | None = None) -> None:
        """Промежуточное обновление: throttle по времени и приросту."""
        if self._closed:
            return
        clipped_rich = _clip_text(text, rich=self._rich)
        clipped_fallback = (
            _clip_text(fallback_html, rich=False) if fallback_html is not None else None
        )
        if clipped_fallback is not None:
            self._last_fallback_html = clipped_fallback
        draft_text = self._draft_text(clipped_rich, clipped_fallback)
        if not self._should_push(draft_text):
            return
        self._last_pushed = draft_text
        if self._mode == "draft":
            self._push_draft(clipped_rich, fallback_html=clipped_fallback)
        elif self._loading_message_id is not None:
            self._push_legacy_edit(draft_text)

    def dismiss(self) -> None:
        """Завершить сессию без финального текста (например, перед sendPhoto).

        В legacy-режиме удаляем loading-сообщение через ``deleteMessage``.
        В draft-режиме намеренно НЕ дёргаем ``sendMessageDraft``: на Bot API
        10.0+ пустой ``text`` рендерится как нативный «Thinking…» placeholder
        (тот же сценарий, что и в ``open("")``). После реальной доставки
        результата (``sendPhoto`` в аналитике) это даёт фантомный «…» баббл
        под фото, который висит весь 30-секундный TTL черновика. Старый
        статус-черновик («📊 Чайка сводит неделю…») Telegram сам погасит
        по TTL — пользователь его уже не увидит, потому что внимание на
        свежей фотке. Best-effort.
        """
        if self._closed:
            return
        self._closed = True
        self._stop_typing()
        if self._mode == "draft":
            return
        if self._loading_message_id is not None:
            try:
                self._telegram.delete_message(self._chat_id, self._loading_message_id)
            except Exception as exc:  # noqa: BLE001 - best-effort
                log.debug("Legacy loading dismiss failed: %s", exc)

    def finish(
        self,
        text: str,
        *,
        reply_markup: dict | list | str | None = None,
        typewriter: bool = True,
        message_effect_id: str | None = None,
        fallback_html: str | None = None,
        rich: bool | None = None,
    ) -> dict[str, Any] | None:
        """Финальная доставка: ``sendMessage`` (draft) или edit/send (legacy).

        ``typewriter=True`` в draft-режиме перед финальным ``sendMessage``
        быстро прокручивает в черновике несколько растущих кадров — эффект
        «бот печатает». На коротких текстах (< 120 символов) пропускается;
        в legacy-режиме не применяется (там и так одна правка).

        ``message_effect_id`` — анимированный эффект (🎉/🔥/✨) в личных чатах;
        в группах игнорируется.
        """
        if self._closed:
            return None
        self._closed = True
        self._stop_typing()
        use_rich = self._rich if rich is None else rich
        clipped = _clip_text(text, rich=use_rich)
        if fallback_html is not None:
            self._last_fallback_html = _clip_text(fallback_html, rich=False)
        if self._mode == "draft":
            if typewriter:
                self._run_typewriter(clipped, rich=use_rich)
            return self._finish_draft(
                clipped,
                reply_markup=reply_markup,
                message_effect_id=message_effect_id,
                fallback_html=fallback_html,
                rich=use_rich,
            )
        final_legacy = fallback_html if (use_rich and fallback_html) else clipped
        return self._finish_legacy(final_legacy, reply_markup=reply_markup)

    # --- internals --------------------------------------------------------

    def _start_typing(self, chat_action: str | None) -> None:
        if not chat_action:
            return
        self._typing = TypingIndicator(
            self._telegram,
            self._chat_id,
            action=chat_action,
            message_thread_id=self._message_thread_id,
        )
        self._typing.start()

    def _stop_typing(self) -> None:
        if self._typing is not None:
            self._typing.stop()
            self._typing = None

    def _draft_text(self, rich_html: str, fallback_html: str | None) -> str:
        """Текст для plain draft / legacy edit при rich-сессии."""
        if self._rich and self._rich_draft_disabled:
            return fallback_html or self._last_fallback_html or rich_html
        return rich_html

    def _send_draft(self, rich_html: str, *, fallback_html: str | None = None) -> bool:
        if self._rich and not self._rich_draft_disabled:
            try:
                ok = self._telegram.send_rich_message_draft(
                    self._chat_id,
                    self._draft_id,
                    input_rich_message(rich_html),
                    message_thread_id=self._message_thread_id,
                )
            except TelegramError as exc:
                if _draft_unavailable(exc):
                    log.info("sendRichMessageDraft unavailable, using plain draft: %s", exc)
                    self._rich_draft_disabled = True
                    ok = False
                else:
                    log.warning("sendRichMessageDraft failed: %s", exc)
                    ok = False
            if ok is True:
                self._rich_draft_active = True
                return True
            self._rich_draft_disabled = True
        plain_text = self._draft_text(rich_html, fallback_html)
        return self._telegram.send_message_draft(
            self._chat_id,
            self._draft_id,
            plain_text,
            message_thread_id=self._message_thread_id,
            parse_mode=self._parse_mode,
        )

    def _try_start_draft(self, initial_text: str) -> bool:
        try:
            ok = self._send_draft(initial_text)
        except TelegramError as exc:
            if _draft_unavailable(exc):
                log.info("sendMessageDraft unavailable, using legacy delivery: %s", exc)
                return False
            if initial_text == "" and _empty_text_rejected(exc):
                # Bot API < 10.0: повторяем с непустым placeholder.
                log.info("Empty draft text rejected, retrying with placeholder text")
                self._empty_text_supported = False
                return self._try_start_draft("⏳")
            log.warning("sendMessageDraft failed at start, using legacy: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("Unexpected sendMessageDraft start failure: %s", exc)
            return False
        if ok is not True:
            return False
        self._mode = "draft"
        return True

    def _start_legacy_loading(self, initial_text: str) -> None:
        try:
            result = self._telegram.send_message(
                self._chat_id,
                initial_text,
                parse_mode=self._parse_mode,
                disable_web_page_preview=self._disable_web_page_preview,
            )
        except TelegramError as exc:
            log.warning("Failed to send legacy loading message: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Unexpected legacy loading send failure: %s", exc)
            return
        mid = result.get("message_id") if isinstance(result, dict) else None
        self._loading_message_id = int(mid) if isinstance(mid, int) else None
        self._last_pushed = initial_text

    def _should_push(self, text: str) -> bool:
        if text == self._last_pushed:
            return False
        if not self._last_pushed:
            return True
        now = time.monotonic()
        if len(text) - len(self._last_pushed) >= _MIN_DRAFT_CHAR_DELTA:
            return True
        if now - self._last_draft_at >= _MIN_DRAFT_INTERVAL_SEC:
            return True
        return False

    def _push_draft(self, rich_html: str, *, fallback_html: str | None = None) -> None:
        try:
            self._send_draft(rich_html, fallback_html=fallback_html)
            self._last_draft_at = time.monotonic()
        except TelegramError as exc:
            if _draft_unavailable(exc):
                log.info("Draft stream lost mid-flight, switching to legacy: %s", exc)
                self._fallback_draft_to_legacy(rich_html)
                return
            log.warning("sendMessageDraft update failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("Unexpected sendMessageDraft update failure: %s", exc)

    def _push_legacy_edit(self, text: str) -> None:
        if self._loading_message_id is None:
            return
        try:
            self._telegram.edit_message_text(
                self._chat_id,
                self._loading_message_id,
                text,
                parse_mode=self._parse_mode,
                disable_web_page_preview=self._disable_web_page_preview,
            )
            self._last_draft_at = time.monotonic()
        except TelegramError as exc:
            log.debug("Legacy stream edit skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.debug("Unexpected legacy stream edit failure: %s", exc)

    def _fallback_draft_to_legacy(self, current_text: str) -> None:
        """После сбоя черновика продолжаем через loading + edit."""
        self._mode = "legacy"
        legacy_text = self._draft_text(current_text, self._last_fallback_html)
        if self._loading_message_id is None:
            self._start_legacy_loading(legacy_text or "⏳")
        else:
            self._push_legacy_edit(legacy_text)

    def _run_typewriter(self, final_text: str, *, rich: bool = False) -> None:
        """Анимация роста текста в черновике перед финалом.

        Не использует ``_should_push`` (там throttle — а здесь мы наоборот
        хотим равномерные кадры). Каждый кадр проходит через ``_safe_slice``
        в ``_typewriter_chunks``, поэтому HTML остаётся валидным.
        """
        for chunk in _typewriter_chunks(final_text, rich=rich):
            if chunk == self._last_pushed:
                continue
            try:
                self._send_draft(chunk)
            except TelegramError as exc:
                if _draft_unavailable(exc):
                    log.info("Typewriter aborted (draft unsupported): %s", exc)
                    self._fallback_draft_to_legacy(chunk)
                    return
                log.debug("Typewriter frame failed: %s", exc)
                return
            except Exception as exc:  # noqa: BLE001
                log.debug("Typewriter frame unexpected failure: %s", exc)
                return
            self._last_pushed = chunk
            self._last_draft_at = time.monotonic()
            time.sleep(_TYPEWRITER_FRAME_INTERVAL_SEC)

    def _finish_draft(
        self,
        text: str,
        *,
        reply_markup: dict | list | str | None,
        message_effect_id: str | None,
        fallback_html: str | None,
        rich: bool,
    ) -> dict[str, Any] | None:
        effect = message_effect_id if is_private_chat(self._chat_id) else None
        if rich:
            from .message_delivery import deliver_rich_or_html

            legacy = fallback_html or text
            return deliver_rich_or_html(
                self._telegram,
                self._chat_id,
                rich_html=text,
                fallback_html=legacy,
                reply_markup=reply_markup,
                message_effect_id=effect,
            )
        return self._telegram.send_message(
            self._chat_id,
            text,
            parse_mode=self._parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=self._disable_web_page_preview,
            message_thread_id=self._message_thread_id,
            message_effect_id=effect,
        )

    def _finish_legacy(
        self,
        text: str,
        *,
        reply_markup: dict | list | str | None,
    ) -> dict[str, Any] | None:
        return edit_or_send_message(
            self._telegram,
            self._chat_id,
            self._loading_message_id,
            text,
            parse_mode=self._parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=self._disable_web_page_preview,
        )


def open_streaming_reply(
    telegram: TelegramClient,
    chat_id: int,
    initial_text: str = "",
    *,
    draft_id: int | None = None,
    message_thread_id: int | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = True,
    chat_action: str | None = "typing",
    rich: bool = False,
) -> StreamingReply:
    """Удобная фабрика (без ``HandlerContext`` — меньше связности).

    Пустой ``initial_text`` (по умолчанию) → нативный «Thinking…» placeholder
    из Bot API 10.0; на старых серверах автоматически заменяется на «⏳».
    """
    return StreamingReply.open(
        telegram,
        chat_id,
        initial_text,
        draft_id=draft_id,
        message_thread_id=message_thread_id,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        chat_action=chat_action,
        rich=rich,
    )
