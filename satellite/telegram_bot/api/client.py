"""Telegram Bot API HTTP client."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from ...presentation.html import strip_expandable_blockquote, strip_tg_emoji_tags
from .errors import (
    TelegramError,
    is_custom_emoji_rejected,
    is_html_entities_rejected,
    is_message_effect_rejected,
)

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_SEND_MESSAGE_TIMEOUT_SEC = 8.0
_SEND_MESSAGE_MAX_RETRIES = 1
_EDIT_MESSAGE_TIMEOUT_SEC = 3.0
_EDIT_MESSAGE_MAX_RETRIES = 0
_DRAFT_MESSAGE_TIMEOUT_SEC = 3.0
_DRAFT_MESSAGE_MAX_RETRIES = 0
_LONG_POLL_METHOD = "getUpdates"


class TelegramClient:
    """Тонкий клиент над Bot API. Переиспользует TCP-соединение через Session.

    Ретраит сетевые ошибки и 5xx/429 с экспоненциальным backoff + jitter.
    Уважает `parameters.retry_after` из ответа на 429.

    Использует две независимых ``requests.Session``:

    * ``_long_poll_session`` — только для ``getUpdates``. Long-polling висит на
      соединении до 30 секунд, и его нельзя ставить в общий пул: иначе исходящие
      ``sendMessage``/``editMessageText`` могут оказаться позади long-poll'а и
      ждать его таймаута (наблюдалось в проде: задержка ответа до 60 с).
    * ``_session`` — для всех исходящих запросов (sendMessage, editMessageText).
      Воркер-пул шлёт их параллельно; разделяемого состояния
      у клиента нет, поэтому глобальный мьютекс не нужен —
      ``HTTPAdapter`` с пулом соединений безопасно обслуживает конкурентные вызовы.
    """

    def __init__(
        self,
        bot_token: str,
        *,
        max_retries: int = 4,
        backoff_base_sec: float = 1.5,
        backoff_cap_sec: float = 30.0,
        request_timeout_sec: float = 30.0,
    ) -> None:
        self._token = bot_token
        self._base_url = f"{TELEGRAM_API}/bot{bot_token}"
        self._session = self._build_session(pool_connections=4, pool_maxsize=16)
        self._long_poll_session = self._build_session(pool_connections=1, pool_maxsize=2)
        self._max_retries = max_retries
        self._backoff_base_sec = backoff_base_sec
        self._backoff_cap_sec = backoff_cap_sec
        self._request_timeout_sec = request_timeout_sec

    def _sanitize_error_text(self, text: str) -> str:
        safe = text
        if self._token:
            safe = safe.replace(self._token, "<telegram-token>")
        safe = safe.replace(self._base_url, f"{TELEGRAM_API}/bot<telegram-token>")
        return safe

    @staticmethod
    def _build_session(*, pool_connections: int, pool_maxsize: int) -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=0,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def close(self) -> None:
        self._session.close()
        self._long_poll_session.close()

    @staticmethod
    def _attach_link_preview(
        data: dict[str, Any],
        *,
        link_preview_options: dict[str, Any] | None,
        disable_web_page_preview: bool,
    ) -> None:
        if link_preview_options is not None:
            data["link_preview_options"] = json.dumps(link_preview_options, ensure_ascii=False)
        elif disable_web_page_preview:
            data["link_preview_options"] = json.dumps({"is_disabled": True}, ensure_ascii=False)

    @staticmethod
    def _attach_reply_markup(
        data: dict[str, Any],
        reply_markup: dict | list | str | None,
    ) -> None:
        if reply_markup is None:
            return
        data["reply_markup"] = (
            json.dumps(reply_markup, ensure_ascii=False)
            if isinstance(reply_markup, (dict, list))
            else reply_markup
        )

    @staticmethod
    def _strip_rich_html(text: str) -> str:
        return strip_expandable_blockquote(strip_tg_emoji_tags(text))

    def _retry_html_text(self, data: dict[str, Any], *, method: str, **call_kw: Any) -> Any:
        """Повтор send/edit без ``<tg-emoji>`` и expandable blockquote."""
        retry_data = dict(data)
        if "text" in retry_data:
            retry_data["text"] = self._strip_rich_html(str(retry_data["text"]))
        if "caption" in retry_data:
            retry_data["caption"] = self._strip_rich_html(str(retry_data["caption"]))
        log.info("%s HTML markup rejected, retrying without tg-emoji/expandable", method)
        return self._call(method, data=retry_data, **call_kw)

    def _call_with_fallbacks(
        self,
        method_name: str,
        data: dict[str, Any],
        *,
        strip_html_on_reject: bool,
        **call_kw: Any,
    ) -> Any:
        """``_call`` с деградацией на отказах Telegram.

        1. ``message_effect_id`` отклонён (нет Premium) — повтор без эффекта.
        2. HTML-разметка отклонена (``<tg-emoji>`` / entities) и
           ``strip_html_on_reject`` — повтор без rich-тегов
           (см. :meth:`_retry_html_text`).
        """
        try:
            return self._call(method_name, data=data, **call_kw)
        except TelegramError as exc:
            if data.get("message_effect_id") and is_message_effect_rejected(exc):
                log.info(
                    "%s message_effect_id rejected, retrying without effect: %s",
                    method_name,
                    exc,
                )
                data.pop("message_effect_id", None)
                try:
                    return self._call(method_name, data=data, **call_kw)
                except TelegramError as exc2:
                    exc = exc2
            if strip_html_on_reject and (
                is_custom_emoji_rejected(exc) or is_html_entities_rejected(exc)
            ):
                return self._retry_html_text(data, method=method_name, **call_kw)
            raise

    # --- public API -------------------------------------------------------

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        reply_markup: dict | list | str | None = None,
        disable_web_page_preview: bool = True,
        link_preview_options: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
        message_effect_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        self._attach_link_preview(
            data,
            link_preview_options=link_preview_options,
            disable_web_page_preview=disable_web_page_preview,
        )
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        if message_effect_id:
            data["message_effect_id"] = message_effect_id
        self._attach_reply_markup(data, reply_markup)
        return self._call_with_fallbacks(
            "sendMessage",
            data,
            strip_html_on_reject=True,
            timeout=_SEND_MESSAGE_TIMEOUT_SEC,
            max_retries=_SEND_MESSAGE_MAX_RETRIES,
        )

    def send_photo(
        self,
        chat_id: int | str,
        photo: bytes,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        show_caption_above_media: bool = False,
        message_thread_id: int | None = None,
        message_effect_id: str | None = None,
        reply_markup: dict | list | str | None = None,
    ) -> dict[str, Any]:
        files = {"photo": ("analytics.png", photo, "image/png")}
        data: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if parse_mode:
            data["parse_mode"] = parse_mode
        if show_caption_above_media:
            data["show_caption_above_media"] = "true"
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        if message_effect_id:
            data["message_effect_id"] = message_effect_id
        self._attach_reply_markup(data, reply_markup)
        return self._call_with_fallbacks(
            "sendPhoto",
            data,
            strip_html_on_reject=bool(caption),
            files=files,
            timeout=_SEND_MESSAGE_TIMEOUT_SEC,
            max_retries=_SEND_MESSAGE_MAX_RETRIES,
        )

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> dict[str, Any] | bool:
        """Закрывает «часики» на inline-кнопке. Best-effort: тайм-аут короткий.

        Telegram требует ответ на callback_query в течение ~30с, иначе клиент
        показывает иконку загрузки до этого таймаута. Мы вызываем это после
        того, как уже отредактировали сообщение, поэтому ретраить смысла нет.
        """
        data: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        if show_alert:
            data["show_alert"] = "true"
        return self._call(
            "answerCallbackQuery",
            data=data,
            timeout=_EDIT_MESSAGE_TIMEOUT_SEC,
            max_retries=0,
        )

    def delete_message(self, chat_id: int | str, message_id: int) -> dict[str, Any] | bool:
        return self._call(
            "deleteMessage",
            data={"chat_id": chat_id, "message_id": message_id},
            timeout=_EDIT_MESSAGE_TIMEOUT_SEC,
            max_retries=0,
        )

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        reply_markup: dict | list | str | None = None,
        disable_web_page_preview: bool = True,
        link_preview_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        self._attach_link_preview(
            data,
            link_preview_options=link_preview_options,
            disable_web_page_preview=disable_web_page_preview,
        )
        self._attach_reply_markup(data, reply_markup)
        return self._call_with_fallbacks(
            "editMessageText",
            data,
            strip_html_on_reject=True,
            timeout=_EDIT_MESSAGE_TIMEOUT_SEC,
            max_retries=_EDIT_MESSAGE_MAX_RETRIES,
        )

    def send_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        text: str = "",
        *,
        message_thread_id: int | None = None,
        parse_mode: str | None = "HTML",
    ) -> bool:
        """``sendMessageDraft``: потоковый черновик в поле ввода.

        Bot API 9.3 (31 dec 2025) — метод добавлен; 9.5 (1 mar 2026) — открыт
        для всех ботов и всех типов чатов; 10.0 (8 may 2026) — разрешён
        пустой ``text`` (клиент показывает нативный «Thinking…» placeholder).

        ``chat_id`` по официальной спеке — только Integer (username не
        принимается, в отличие от ``sendMessage``). Возвращает ``True`` при
        успехе. Финальный текст нужно отправить отдельным ``sendMessage`` —
        см. :mod:`streaming_delivery`.
        """
        if not draft_id:
            raise ValueError("draft_id must be non-zero")
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": draft_id,
            "text": text,
        }
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        if parse_mode:
            data["parse_mode"] = parse_mode
        result = self._call(
            "sendMessageDraft",
            data=data,
            timeout=_DRAFT_MESSAGE_TIMEOUT_SEC,
            max_retries=_DRAFT_MESSAGE_MAX_RETRIES,
        )
        return result is True

    def send_rich_message(
        self,
        chat_id: int | str,
        rich_message: dict[str, Any],
        *,
        reply_markup: dict | list | str | None = None,
        disable_notification: bool = False,
        message_thread_id: int | None = None,
        message_effect_id: str | None = None,
    ) -> dict[str, Any]:
        """``sendRichMessage``: структурированное сообщение (Bot API 10.1)."""
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "rich_message": json.dumps(rich_message, ensure_ascii=False),
        }
        if disable_notification:
            data["disable_notification"] = "true"
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        if message_effect_id:
            data["message_effect_id"] = message_effect_id
        self._attach_reply_markup(data, reply_markup)
        return self._call_with_fallbacks(
            "sendRichMessage",
            data,
            strip_html_on_reject=False,
            timeout=_SEND_MESSAGE_TIMEOUT_SEC,
            max_retries=_SEND_MESSAGE_MAX_RETRIES,
        )

    def send_rich_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        rich_message: dict[str, Any],
        *,
        message_thread_id: int | None = None,
    ) -> bool:
        """``sendRichMessageDraft``: потоковый rich-черновик (Bot API 10.1)."""
        if not draft_id:
            raise ValueError("draft_id must be non-zero")
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": draft_id,
            "rich_message": json.dumps(rich_message, ensure_ascii=False),
        }
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        result = self._call(
            "sendRichMessageDraft",
            data=data,
            timeout=_DRAFT_MESSAGE_TIMEOUT_SEC,
            max_retries=_DRAFT_MESSAGE_MAX_RETRIES,
        )
        return result is True

    def edit_message_rich(
        self,
        chat_id: int | str,
        message_id: int,
        rich_message: dict[str, Any],
        *,
        reply_markup: dict | list | str | None = None,
    ) -> dict[str, Any]:
        """``editMessageText`` с ``rich_message`` вместо plain text."""
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "rich_message": json.dumps(rich_message, ensure_ascii=False),
        }
        self._attach_reply_markup(data, reply_markup)
        return self._call(
            "editMessageText",
            data=data,
            timeout=_EDIT_MESSAGE_TIMEOUT_SEC,
            max_retries=_EDIT_MESSAGE_MAX_RETRIES,
        )

    def send_chat_action(
        self,
        chat_id: int | str,
        action: str,
        *,
        message_thread_id: int | None = None,
    ) -> bool:
        """``sendChatAction``: «печатает…» / «отправляет фото…» в шапке чата."""
        data: dict[str, Any] = {"chat_id": chat_id, "action": action}
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        result = self._call(
            "sendChatAction",
            data=data,
            timeout=_DRAFT_MESSAGE_TIMEOUT_SEC,
            max_retries=0,
        )
        return result is True

    def set_message_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        reaction: list[dict[str, Any]] | None = None,
        is_big: bool = False,
    ) -> bool:
        """``setMessageReaction``: эмодзи-реакция на сообщение пользователя."""
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reaction is not None:
            data["reaction"] = json.dumps(reaction, ensure_ascii=False)
        if is_big:
            data["is_big"] = "true"
        result = self._call(
            "setMessageReaction",
            data=data,
            timeout=_DRAFT_MESSAGE_TIMEOUT_SEC,
            max_retries=0,
        )
        return result is True

    def set_my_commands(
        self,
        commands: list[dict[str, str]],
        *,
        scope: dict[str, Any] | None = None,
        language_code: str | None = None,
    ) -> Any:
        """``setMyCommands``: регистрирует команды для меню Telegram.

        ``commands`` — список ``{"command": str, "description": str}``. ``scope``
        и ``language_code`` опциональны; без них Telegram считает командой
        дефолтный набор для всех частных чатов.
        """
        data: dict[str, Any] = {
            "commands": json.dumps(commands, ensure_ascii=False),
        }
        if scope is not None:
            data["scope"] = json.dumps(scope, ensure_ascii=False)
        if language_code:
            data["language_code"] = language_code
        return self._call(
            "setMyCommands",
            data=data,
            timeout=_SEND_MESSAGE_TIMEOUT_SEC,
            max_retries=1,
        )

    def set_chat_menu_button(
        self,
        *,
        chat_id: int | str | None = None,
        menu_button: dict[str, Any] | None = None,
    ) -> Any:
        """``setChatMenuButton``: переключает кнопку «Меню» рядом с полем ввода.

        Без ``chat_id`` применяется ко всем приватным чатам. ``menu_button``
        по умолчанию — ``MenuButtonDefault``; чтобы показывать список команд,
        передаётся ``{"type": "commands"}``.
        """
        data: dict[str, Any] = {}
        if chat_id is not None:
            data["chat_id"] = chat_id
        if menu_button is not None:
            data["menu_button"] = json.dumps(menu_button, ensure_ascii=False)
        return self._call(
            "setChatMenuButton",
            data=data,
            timeout=_SEND_MESSAGE_TIMEOUT_SEC,
            max_retries=1,
        )

    def _set_my(
        self,
        method_name: str,
        *,
        language_code: str | None = None,
        **fields: Any,
    ) -> Any:
        """Общий low-level вызов ``setMy<X>`` методов Bot API.

        Все ``setMyName``/``setMyDescription``/``setMyShortDescription`` имеют
        одинаковый контракт: одно текстовое поле + опциональный
        ``language_code``. Хендлер просто передаёт ``{"name": ...}`` или
        ``{"description": ...}`` через ``**fields``; пустые значения не
        прокидываются (Telegram считает пустую строку «сбросить»).
        """
        data: dict[str, Any] = {key: value for key, value in fields.items() if value is not None}
        if language_code:
            data["language_code"] = language_code
        return self._call(
            method_name,
            data=data,
            timeout=_SEND_MESSAGE_TIMEOUT_SEC,
            max_retries=1,
        )

    def set_my_name(
        self,
        name: str,
        *,
        language_code: str | None = None,
    ) -> Any:
        """``setMyName``: отображаемое имя бота в профиле."""
        return self._set_my("setMyName", name=name, language_code=language_code)

    def set_my_description(
        self,
        description: str,
        *,
        language_code: str | None = None,
    ) -> Any:
        """``setMyDescription``: текст «Описание» в профиле бота."""
        return self._set_my(
            "setMyDescription",
            description=description,
            language_code=language_code,
        )

    def set_my_short_description(
        self,
        short_description: str,
        *,
        language_code: str | None = None,
    ) -> Any:
        """``setMyShortDescription``: краткое описание в списке чатов."""
        return self._set_my(
            "setMyShortDescription",
            short_description=short_description,
            language_code=language_code,
        )

    def get_updates(
        self,
        offset: int,
        *,
        timeout: int,
        allowed_updates: tuple[str, ...] = ("message", "callback_query"),
    ) -> list[dict[str, Any]]:
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(list(allowed_updates)),
        }
        result = self._call(
            "getUpdates",
            method="GET",
            params=params,
            timeout=timeout + 10,
        )
        if isinstance(result, list):
            return result
        return []

    # --- internals --------------------------------------------------------

    def _call(
        self,
        method_name: str,
        *,
        method: str = "POST",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Any:
        url = f"{self._base_url}/{method_name}"
        effective_timeout = timeout or self._request_timeout_sec
        effective_max_retries = (
            self._max_retries if max_retries is None else max(0, int(max_retries))
        )
        # Long-poll держит коннект до 30 с и не должен делить пул с исходящими
        # запросами — иначе sendMessage/editMessageText из воркеров встают в
        # очередь за getUpdates и общий p99 ответа уезжает на десятки секунд.
        session = self._long_poll_session if method_name == _LONG_POLL_METHOD else self._session
        attempt = 0
        while True:
            attempt += 1
            try:
                response = session.request(
                    method,
                    url,
                    data=data,
                    params=params,
                    files=files,
                    timeout=effective_timeout,
                )
                payload = self._parse_response(response, method_name)
                if payload is not None:
                    return payload
                wait = self._wait_after_429(response)
                if attempt > effective_max_retries:
                    raise TelegramError(
                        f"{method_name}: still rate-limited after {effective_max_retries} retries"
                    )
                log.warning(
                    "Telegram %s rate-limited; sleeping %.1fs (attempt %d)",
                    method_name,
                    wait,
                    attempt,
                )
                time.sleep(wait)
                continue
            except (requests.RequestException, OSError) as exc:
                safe_error = self._sanitize_error_text(str(exc))
                if attempt > effective_max_retries:
                    raise TelegramError(
                        f"{method_name}: network error after {effective_max_retries} retries: {safe_error}"
                    ) from exc
                wait = self._compute_backoff(attempt)
                log.warning(
                    "Telegram %s network error (%s); sleeping %.1fs (attempt %d)",
                    method_name,
                    safe_error,
                    wait,
                    attempt,
                )
                time.sleep(wait)
            except TelegramError:
                raise

    def _parse_response(self, response: requests.Response, method_name: str) -> Any | None:
        status = response.status_code
        if status == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise TelegramError(f"{method_name}: invalid JSON response") from exc
            if not payload.get("ok"):
                raise TelegramError(
                    f"{method_name} failed: {self._sanitize_error_text(str(payload))}"
                )
            return payload.get("result")

        if status == 429:
            return None  # сигнал к retry

        if status in _RETRYABLE_STATUS:
            raise requests.RequestException(f"{method_name}: HTTP {status}")

        text = self._sanitize_error_text((response.text or "")[:500])
        raise TelegramError(f"{method_name}: HTTP {status}: {text}")

    def _wait_after_429(self, response: requests.Response) -> float:
        retry_after = 0.0
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            params = payload.get("parameters") or {}
            try:
                retry_after = float(params.get("retry_after") or 0)
            except (TypeError, ValueError):
                retry_after = 0.0
        if retry_after <= 0:
            header_val = response.headers.get("Retry-After")
            if header_val:
                try:
                    retry_after = float(header_val)
                except ValueError:
                    retry_after = 0.0
        if retry_after <= 0:
            retry_after = self._backoff_base_sec
        return min(retry_after + random.uniform(0, 0.5), self._backoff_cap_sec)

    def _compute_backoff(self, attempt: int) -> float:
        delay = min(self._backoff_base_sec * (2 ** (attempt - 1)), self._backoff_cap_sec)
        return delay + random.uniform(0, 0.5)
