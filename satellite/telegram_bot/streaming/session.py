"""StreamingReply session: draft lifecycle and final delivery."""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from ...messages_ru import DEFAULT_THINKING_TEXT, rich_thinking_status
from ...presentation.delivery import deliver_rich_or_html
from ...presentation.rich import input_rich_message
from ..api import TelegramClient, TelegramError
from ..message_editing import edit_or_send_message
from ..visual import TypingIndicator, is_private_chat
from .helpers import (
    _MIN_DRAFT_CHAR_DELTA,
    _MIN_DRAFT_INTERVAL_SEC,
    _RICH_ONLY_TAG_RE,
    _TYPEWRITER_FRAME_INTERVAL_SEC,
    _clip_text,
    _draft_unavailable,
    _empty_text_rejected,
    _stable_draft_id,
    _typewriter_chunks,
)

log = logging.getLogger(__name__)

_DraftMode = Literal["draft", "legacy"]
_RevealMode = Literal["auto", "blocks", "chars"]


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
        draft_start = (
            rich_thinking_status(DEFAULT_THINKING_TEXT) if rich and not clipped else clipped
        )
        if session._try_start_draft(draft_start):
            session._last_pushed = draft_start
            session._last_draft_at = time.monotonic()
            return session
        # legacy-ветка: нужно непустое loading-сообщение, иначе sendMessage упадёт.
        legacy_text = clipped or "⏳"
        session._start_legacy_loading(legacy_text)
        session._start_typing(chat_action)
        return session

    def push_status(self, text: str, *, fallback_html: str | None = None) -> None:
        """Статус в rich-draft через ``<tg-thinking>`` (или plain в legacy)."""
        if self._rich and self._mode == "draft" and not self._rich_draft_disabled:
            self.push(rich_thinking_status(text), fallback_html=fallback_html or text)
        else:
            self.push(text, fallback_html=fallback_html)

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
        if draft_text is None or not self._should_push(draft_text):
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
        reveal_mode: _RevealMode = "auto",
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
                self._run_typewriter(clipped, rich=use_rich, reveal_mode=reveal_mode)
            if self._mode == "draft":  # typewriter мог уронить сессию в legacy
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

    def _draft_text(self, rich_html: str, fallback_html: str | None) -> str | None:
        """Текст кадра для plain draft / legacy edit; ``None`` — кадр пропустить.

        Когда rich-черновики недоступны, показываем только явный fallback
        этого кадра либо контент без rich-тегов (статусные строки).
        Накопленный ``_last_fallback_html`` сюда сознательно не подставляем:
        кадры в старом оформлении (expandable blockquote, другие отступы)
        «промаргивают» поверх финального rich-сообщения.
        """
        if not (self._rich and self._rich_draft_disabled):
            return rich_html
        if fallback_html:
            return fallback_html
        if not _RICH_ONLY_TAG_RE.search(rich_html):
            return rich_html
        return None

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
        if plain_text is None:
            return False
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
        elif legacy_text:
            self._push_legacy_edit(legacy_text)

    def _run_typewriter(
        self,
        final_text: str,
        *,
        rich: bool = False,
        reveal_mode: _RevealMode = "auto",
    ) -> None:
        """Анимация роста текста в черновике перед финалом.

        Не использует ``_should_push`` (там throttle — а здесь мы наоборот
        хотим равномерные кадры ≥ ~0.2 s: быстрее клиент не успевает дорисовать
        анимацию предыдущего кадра). Если rich-черновики недоступны, кадров
        нет вовсе: plain-черновик не отрисует rich-разметку, а подмена кадров
        legacy fallback-текстом промаргивает старым оформлением поверх
        будущего rich-сообщения.
        """
        if rich and self._rich_draft_disabled:
            return
        for chunk in _typewriter_chunks(final_text, rich=rich, reveal_mode=reveal_mode):
            if rich and self._rich_draft_disabled:
                return  # rich-draft отвалился на предыдущем кадре
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
