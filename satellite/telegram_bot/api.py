"""Telegram Bot API клиент: HTTP-сессия, ретраи с backoff, respect 429/Retry-After."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

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


class TelegramError(RuntimeError):
    """Не получилось договориться с Telegram даже после всех ретраев."""


def is_message_effect_rejected(exc: BaseException) -> bool:
    """Telegram отказался применять ``message_effect_id``.

    Возможные причины:

    * подписан как `Bad Request: message_effect_id ...` — невалидный/чужой id;
    * `Bad Request: PREMIUM_ACCOUNT_REQUIRED` — у получателя нет Telegram Premium,
      а анимированные эффекты доступны только премиум-чатам.

    Бот использует ``message_effect_id`` только в личных чатах и без других
    премиум-фич, поэтому такой ответ всегда означает «эффект применить нельзя»;
    повторяем отправку без эффекта.
    """
    text = str(exc).lower()
    return "message_effect" in text or "premium_account_required" in text


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
        self._long_poll_session = self._build_session(
            pool_connections=1, pool_maxsize=2
        )
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

    # --- public API -------------------------------------------------------

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        reply_markup: dict | list | str | None = None,
        disable_web_page_preview: bool = True,
        message_thread_id: int | None = None,
        message_effect_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        if disable_web_page_preview:
            data["disable_web_page_preview"] = "true"
        if message_thread_id is not None:
            data["message_thread_id"] = message_thread_id
        if message_effect_id:
            data["message_effect_id"] = message_effect_id
        if reply_markup is not None:
            data["reply_markup"] = (
                json.dumps(reply_markup, ensure_ascii=False)
                if isinstance(reply_markup, (dict, list))
                else reply_markup
            )
        try:
            return self._call(
                "sendMessage",
                data=data,
                timeout=_SEND_MESSAGE_TIMEOUT_SEC,
                max_retries=_SEND_MESSAGE_MAX_RETRIES,
            )
        except TelegramError as exc:
            if message_effect_id and is_message_effect_rejected(exc):
                log.info(
                    "sendMessage message_effect_id rejected, retrying without effect: %s",
                    exc,
                )
                data.pop("message_effect_id", None)
                return self._call(
                    "sendMessage",
                    data=data,
                    timeout=_SEND_MESSAGE_TIMEOUT_SEC,
                    max_retries=_SEND_MESSAGE_MAX_RETRIES,
                )
            raise

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
        try:
            return self._call(
                "sendPhoto",
                data=data,
                files=files,
                timeout=_SEND_MESSAGE_TIMEOUT_SEC,
                max_retries=_SEND_MESSAGE_MAX_RETRIES,
            )
        except TelegramError as exc:
            if message_effect_id and is_message_effect_rejected(exc):
                log.info(
                    "sendPhoto message_effect_id rejected, retrying without effect: %s",
                    exc,
                )
                data.pop("message_effect_id", None)
                return self._call(
                    "sendPhoto",
                    data=data,
                    files=files,
                    timeout=_SEND_MESSAGE_TIMEOUT_SEC,
                    max_retries=_SEND_MESSAGE_MAX_RETRIES,
                )
            raise

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
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        if disable_web_page_preview:
            data["disable_web_page_preview"] = "true"
        if reply_markup is not None:
            data["reply_markup"] = (
                json.dumps(reply_markup, ensure_ascii=False)
                if isinstance(reply_markup, (dict, list))
                else reply_markup
            )
        return self._call(
            "editMessageText",
            data=data,
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
        session = (
            self._long_poll_session
            if method_name == _LONG_POLL_METHOD
            else self._session
        )
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

    def _parse_response(
        self, response: requests.Response, method_name: str
    ) -> Any | None:
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
            raise requests.RequestException(
                f"{method_name}: HTTP {status}"
            )

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
