"""Потоковая доставка длинных ответов: ``sendMessageDraft`` + fallback.

Telegram Bot API 9.3+ (с 9.5 — для всех ботов): черновик в поле ввода
анимируется по мере обновлений с тем же ``draft_id``. После готовности
нужен ``sendMessage`` с финальным текстом — он остаётся в чате.

Если ``sendMessageDraft`` недоступен (старый API, неподдерживаемый чат),
используется прежний паттерн loading → ``editMessageText`` / ``sendMessage``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from .api import TelegramClient, TelegramError
from .message_editing import edit_or_send_message

log = logging.getLogger(__name__)

_DraftMode = Literal["draft", "legacy"]

_MIN_DRAFT_INTERVAL_SEC = 0.28
_MIN_DRAFT_CHAR_DELTA = 24
_TELEGRAM_TEXT_LIMIT = 4096

# Описания/коды, при которых черновики недоступны — переходим на legacy.
_DRAFT_UNAVAILABLE_MARKERS = (
    "sendmessagedraft",
    "textdraft",
    "method is not found",
    "method not found",
    "unknown method",
)


def _draft_unavailable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _DRAFT_UNAVAILABLE_MARKERS)


def _stable_draft_id(*, chat_id: int, seed: int) -> int:
    """Ненулевой стабильный draft_id для анимации обновлений одного ответа."""
    mixed = (int(chat_id) * 1_000_003) ^ int(seed)
    draft_id = (mixed % 2_147_483_646) + 1
    return draft_id


def _clip_telegram_text(text: str) -> str:
    if len(text) <= _TELEGRAM_TEXT_LIMIT:
        return text
    return text[: _TELEGRAM_TEXT_LIMIT - 1] + "…"


class StreamingReply:
    """Сессия одного «потокового» ответа в чат.

    Создавать через :func:`open_streaming_reply` или ``StreamingReply.open``.
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

    @classmethod
    def open(
        cls,
        telegram: TelegramClient,
        chat_id: int,
        initial_text: str,
        *,
        draft_id: int | None = None,
        message_thread_id: int | None = None,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool = True,
    ) -> StreamingReply:
        """Старт сессии: пробует черновик, иначе loading-сообщение."""
        resolved_draft_id = draft_id if draft_id else _stable_draft_id(
            chat_id=chat_id, seed=int(time.time() * 1000) % 1_000_000_007
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
            return session
        session._start_legacy_loading(clipped)
        return session

    def push(self, text: str) -> None:
        """Промежуточное обновление (throttle по времени и приросту текста)."""
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
        """Сбрасывает черновик без финального текста (например, перед ``sendPhoto``)."""
        if self._closed or self._mode != "draft":
            return
        try:
            self._telegram.send_message_draft(
                self._chat_id,
                self._draft_id,
                "",
                message_thread_id=self._message_thread_id,
                parse_mode=self._parse_mode,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort
            log.debug("Draft dismiss failed: %s", exc)

    def finish(
        self,
        text: str,
        *,
        reply_markup: dict | list | str | None = None,
    ) -> dict[str, Any] | None:
        """Финальная доставка: ``sendMessage`` (draft) или edit/send (legacy)."""
        if self._closed:
            return None
        self._closed = True
        clipped = _clip_telegram_text(text)
        if self._mode == "draft":
            return self._finish_draft(clipped, reply_markup=reply_markup)
        return self._finish_legacy(clipped, reply_markup=reply_markup)

    # --- internals --------------------------------------------------------

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
            self._start_legacy_loading(current_text)
        else:
            self._push_legacy_edit(current_text)

    def _finish_draft(
        self,
        text: str,
        *,
        reply_markup: dict | list | str | None,
    ) -> dict[str, Any] | None:
        try:
            return self._telegram.send_message(
                self._chat_id,
                text,
                parse_mode=self._parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=self._disable_web_page_preview,
            )
        except TelegramError as exc:
            log.warning("Final sendMessage after draft failed: %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("Unexpected final sendMessage after draft: %s", exc)
            raise

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
    initial_text: str,
    *,
    draft_id: int | None = None,
    message_thread_id: int | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = True,
) -> StreamingReply:
    """Удобная фабрика для хендлеров (без HandlerContext — меньше связности)."""
    return StreamingReply.open(
        telegram,
        chat_id,
        initial_text,
        draft_id=draft_id,
        message_thread_id=message_thread_id,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )
