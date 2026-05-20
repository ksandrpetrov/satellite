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
_TYPEWRITER_MAX_FRAMES = 9
_TYPEWRITER_MIN_CHUNK = 60
_TYPEWRITER_FRAME_INTERVAL_SEC = 0.16
_TYPEWRITER_MIN_TEXT_LEN = 120  # короче — не имеет смысла «печатать»

# Описания/коды, при которых черновики недоступны — переходим на legacy.
_DRAFT_UNAVAILABLE_MARKERS = (
    "sendmessagedraft",
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


def _typewriter_chunks(text: str) -> list[str]:
    """Постепенно растущие префиксы текста для эффекта «печатает»."""
    if len(text) < _TYPEWRITER_MIN_TEXT_LEN:
        return []
    target_frames = min(_TYPEWRITER_MAX_FRAMES, max(2, len(text) // _TYPEWRITER_MIN_CHUNK))
    step = max(_TYPEWRITER_MIN_CHUNK, len(text) // target_frames)
    chunks: list[str] = []
    cursor = step
    while cursor < len(text):
        chunks.append(_safe_slice(text, cursor))
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
    ) -> None:
        self._telegram = telegram
        self._chat_id = chat_id
        self._draft_id = draft_id
        self._message_thread_id = message_thread_id
        self._parse_mode = parse_mode
        self._disable_web_page_preview = disable_web_page_preview

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
    ) -> StreamingReply:
        """Старт сессии: пробует черновик, иначе loading-сообщение.

        ``initial_text=""`` (по умолчанию) показывает нативный «Thinking…»
        placeholder из Bot API 10.0. Если ботом-серверу < 10.0, мы повторяем
        старт с непустым текстом (см. ``_try_start_draft``).
        """
        resolved_draft_id = draft_id if draft_id else _stable_draft_id(
            chat_id=chat_id,
            seed=int(time.time() * 1000) % 1_000_000_007,
        )
        session = cls(
            telegram,
            chat_id,
            draft_id=resolved_draft_id,
            message_thread_id=message_thread_id,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        clipped = _clip_telegram_text(initial_text)
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

    def push(self, text: str) -> None:
        """Промежуточное обновление: throttle по времени и приросту."""
        if self._closed:
            return
        clipped = _clip_telegram_text(text)
        if not self._should_push(clipped):
            return
        self._last_pushed = clipped
        if self._mode == "draft":
            self._push_draft(clipped)
        elif self._loading_message_id is not None:
            self._push_legacy_edit(clipped)

    def dismiss(self) -> None:
        """Завершить сессию без финального текста (например, перед sendPhoto).

        В draft-режиме сбрасывает черновик пустым кадром. В legacy — удаляет
        loading-сообщение через ``deleteMessage``. Best-effort.
        """
        if self._closed:
            return
        self._closed = True
        self._stop_typing()
        if self._mode == "draft":
            try:
                self._telegram.send_message_draft(
                    self._chat_id,
                    self._draft_id,
                    "" if self._empty_text_supported else " ",
                    message_thread_id=self._message_thread_id,
                    parse_mode=self._parse_mode,
                )
            except Exception as exc:  # noqa: BLE001 - best-effort
                log.debug("Draft dismiss failed: %s", exc)
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
        clipped = _clip_telegram_text(text)
        if self._mode == "draft":
            if typewriter:
                self._run_typewriter(clipped)
            return self._finish_draft(
                clipped,
                reply_markup=reply_markup,
                message_effect_id=message_effect_id,
            )
        return self._finish_legacy(clipped, reply_markup=reply_markup)

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

    def _try_start_draft(self, initial_text: str) -> bool:
        try:
            ok = self._telegram.send_message_draft(
                self._chat_id,
                self._draft_id,
                initial_text,
                message_thread_id=self._message_thread_id,
                parse_mode=self._parse_mode,
            )
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

    def _push_draft(self, text: str) -> None:
        try:
            self._telegram.send_message_draft(
                self._chat_id,
                self._draft_id,
                text,
                message_thread_id=self._message_thread_id,
                parse_mode=self._parse_mode,
            )
            self._last_draft_at = time.monotonic()
        except TelegramError as exc:
            if _draft_unavailable(exc):
                log.info("Draft stream lost mid-flight, switching to legacy: %s", exc)
                self._fallback_draft_to_legacy(text)
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
        if self._loading_message_id is None:
            self._start_legacy_loading(current_text or "⏳")
        else:
            self._push_legacy_edit(current_text)

    def _run_typewriter(self, final_text: str) -> None:
        """Анимация роста текста в черновике перед финалом.

        Не использует ``_should_push`` (там throttle — а здесь мы наоборот
        хотим равномерные кадры). Каждый кадр проходит через ``_safe_slice``
        в ``_typewriter_chunks``, поэтому HTML остаётся валидным.
        """
        for chunk in _typewriter_chunks(final_text):
            if chunk == self._last_pushed:
                continue
            try:
                self._telegram.send_message_draft(
                    self._chat_id,
                    self._draft_id,
                    chunk,
                    message_thread_id=self._message_thread_id,
                    parse_mode=self._parse_mode,
                )
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
    ) -> dict[str, Any] | None:
        # message_effect_id Telegram принимает только в личных чатах; для групп
        # и каналов гасим эффект здесь, чтобы не тратить попытку и не получать
        # ошибку API. Fallback на «без эффекта» при отказе Telegram (включая
        # `PREMIUM_ACCOUNT_REQUIRED`) живёт в `TelegramClient.send_message`.
        effect = message_effect_id if is_private_chat(self._chat_id) else None
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
    )
