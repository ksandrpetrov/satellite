"""Чистые парсеры и нормализация Telegram-апдейтов.

Все функции — без I/O, дружелюбные к юнит-тестам.
"""

from __future__ import annotations

import re

from ...messages_ru import (
    button_text_is_calendar_sources,
    button_text_is_check_calendar,
    button_text_is_connect_calendar,
    button_text_is_create_event,
    button_text_is_digest_settings,
    button_text_is_disconnect_calendar,
    button_text_is_subscribe,
    button_text_is_unsubscribe,
    button_text_is_upcoming,
    button_text_to_mode,
)
from .context import IncomingCallback, IncomingMessage, PlanMode, SubscriptionAction


# Длинные алиасы (/today, /tomorrow, /aftertomorrow) появились вместе с
# переходом на меню команд Telegram; короткие td/tm/dat остаются рабочими.
_CMD_TODAY = re.compile(r"(?:/?td|/today)(?:@[a-z0-9_]+)?\Z")
_CMD_TOMORROW = re.compile(r"(?:/?tm|/tomorrow)(?:@[a-z0-9_]+)?\Z")
_CMD_DAT = re.compile(r"(?:/?dat|/aftertomorrow|/after_tomorrow)(?:@[a-z0-9_]+)?\Z")
_CMD_START = re.compile(r"/start(?:@[a-z0-9_]+)?\Z")
_CMD_HELP = re.compile(r"/help(?:@[a-z0-9_]+)?\Z")
# /digest теперь включает подписку, /stopdigest — выключает. Старые алиасы
# /sub /subscribe /unsub /unsubscribe оставлены для обратной совместимости.
_CMD_SUBSCRIBE = re.compile(r"/(?:sub|subscribe|digest)(?:@[a-z0-9_]+)?\Z")
_CMD_UNSUBSCRIBE = re.compile(r"/(?:unsub|unsubscribe|stopdigest)(?:@[a-z0-9_]+)?\Z")
# /settings — единственный путь к экрану настроек дайджеста; /digest больше
# его не открывает, а сразу включает подписку.
_CMD_DIGEST_SETTINGS = re.compile(r"/settings(?:@[a-z0-9_]+)?\Z")
_CMD_UPCOMING = re.compile(r"/(?:upcoming|events)(?:@[a-z0-9_]+)?\Z")
_CMD_CREATE = re.compile(r"/(?:create|addevent)(?:@[a-z0-9_]+)?\Z")
_CMD_CONNECT = re.compile(r"/connect(?:@[a-z0-9_]+)?\Z")
_CMD_CALENDARS = re.compile(r"/(?:calendars|calendar_sources)(?:@[a-z0-9_]+)?\Z")


def _command_part(text: str) -> str:
    return text.strip().split(maxsplit=1)[0].lower()


def parse_command_mode(text: str | None) -> PlanMode | None:
    raw = (text or "").strip()
    if not raw:
        return None
    button_mode = button_text_to_mode(raw)
    if button_mode is not None:
        return button_mode
    command_part = raw.split(maxsplit=1)[0].lower()
    if _CMD_TODAY.fullmatch(command_part):
        return "today"
    if _CMD_TOMORROW.fullmatch(command_part):
        return "tomorrow"
    if _CMD_DAT.fullmatch(command_part):
        return "day_after_tomorrow"
    return None


def is_start_command(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CMD_START.fullmatch(_command_part(text)))


def is_help_command(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CMD_HELP.fullmatch(_command_part(text)))


def is_start_or_help_command(text: str | None) -> bool:
    return is_start_command(text) or is_help_command(text)


def parse_subscription_action(text: str | None) -> SubscriptionAction | None:
    if not text:
        return None
    raw = text.strip()
    if button_text_is_subscribe(raw):
        return "subscribe"
    if button_text_is_unsubscribe(raw):
        return "unsubscribe"
    command_part = raw.split(maxsplit=1)[0].lower()
    if _CMD_SUBSCRIBE.fullmatch(command_part):
        return "subscribe"
    if _CMD_UNSUBSCRIBE.fullmatch(command_part):
        return "unsubscribe"
    return None


def is_digest_settings_request(text: str | None) -> bool:
    if not text:
        return False
    raw = text.strip()
    if button_text_is_digest_settings(raw):
        return True
    command_part = raw.split(maxsplit=1)[0].lower()
    return bool(_CMD_DIGEST_SETTINGS.fullmatch(command_part))


def is_upcoming_request(text: str | None) -> bool:
    if not text:
        return False
    raw = text.strip()
    if button_text_is_upcoming(raw):
        return True
    return bool(_CMD_UPCOMING.fullmatch(_command_part(raw)))


def is_create_event_request(text: str | None) -> bool:
    if not text:
        return False
    raw = text.strip()
    if button_text_is_create_event(raw):
        return True
    return bool(_CMD_CREATE.fullmatch(_command_part(raw)))


def is_connect_calendar_request(text: str | None) -> bool:
    if not text:
        return False
    raw = text.strip()
    if button_text_is_connect_calendar(raw):
        return True
    return bool(_CMD_CONNECT.fullmatch(_command_part(raw)))


def is_check_calendar_request(text: str | None) -> bool:
    if not text:
        return False
    return button_text_is_check_calendar(text.strip())


def is_disconnect_calendar_request(text: str | None) -> bool:
    if not text:
        return False
    return button_text_is_disconnect_calendar(text.strip())


def is_calendar_sources_request(text: str | None) -> bool:
    if not text:
        return False
    raw = text.strip()
    if button_text_is_calendar_sources(raw):
        return True
    return bool(_CMD_CALENDARS.fullmatch(_command_part(raw)))


def is_command_like_message(text: str) -> bool:
    """Команды (`/td`, кнопки) трактуем как «выход из state», не как ввод времени."""
    if parse_command_mode(text) is not None:
        return True
    if parse_subscription_action(text) is not None:
        return True
    if is_digest_settings_request(text):
        return True
    if is_start_or_help_command(text):
        return True
    if is_upcoming_request(text):
        return True
    if is_create_event_request(text):
        return True
    if is_connect_calendar_request(text):
        return True
    if is_check_calendar_request(text):
        return True
    if is_disconnect_calendar_request(text):
        return True
    if is_calendar_sources_request(text):
        return True
    return False


def _display_name(from_user: dict) -> str | None:
    parts = [
        str(from_user.get("first_name") or "").strip(),
        str(from_user.get("last_name") or "").strip(),
    ]
    name = " ".join(p for p in parts if p).strip()
    return name or None


def extract_message(update: dict) -> IncomingMessage:
    message = update.get("message") or {}
    text = message.get("text", "")
    from_user = message.get("from") or {}
    username_raw = from_user.get("username")
    username = (username_raw or "").lower() or None
    user_id_raw = from_user.get("id")
    chat = message.get("chat") or {}
    chat_id_raw = chat.get("id")
    return IncomingMessage(
        update_id=int(update.get("update_id") or 0),
        chat_id=int(chat_id_raw) if isinstance(chat_id_raw, int) else None,
        user_id=int(user_id_raw) if isinstance(user_id_raw, int) else None,
        username=username,
        display_name=_display_name(from_user),
        text=text,
    )


def extract_callback_query(update: dict) -> IncomingCallback | None:
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return None
    cb_id = str(callback.get("id") or "")
    if not cb_id:
        return None
    from_user = callback.get("from") or {}
    username = (from_user.get("username") or "").lower() or None
    user_id_raw = from_user.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id_raw = chat.get("id")
    message_id_raw = message.get("message_id")
    data_raw = callback.get("data")
    return IncomingCallback(
        update_id=int(update.get("update_id") or 0),
        callback_query_id=cb_id,
        chat_id=int(chat_id_raw) if isinstance(chat_id_raw, int) else None,
        message_id=int(message_id_raw) if isinstance(message_id_raw, int) else None,
        user_id=int(user_id_raw) if isinstance(user_id_raw, int) else None,
        username=username,
        data=str(data_raw) if data_raw is not None else None,
    )


def is_update_message(update: dict) -> bool:
    """True для update'ов с обычным сообщением (а не callback_query и т.п.)."""
    return isinstance(update.get("message"), dict)


def is_update_callback(update: dict) -> bool:
    return isinstance(update.get("callback_query"), dict)
