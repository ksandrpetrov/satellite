"""Чистые парсеры и нормализация Telegram-апдейтов.

Все функции — без I/O, дружелюбные к юнит-тестам.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Union

from ...messages_ru import (
    button_text_is_calendar_sources,
    button_text_is_check_calendar,
    button_text_is_connect_calendar,
    button_text_is_create_event,
    button_text_is_disconnect_calendar,
    button_text_is_foreign_calendars,
    button_text_is_invitations,
    button_text_is_manage_events,
    button_text_is_settings,
    button_text_is_subscribe,
    button_text_is_unsubscribe,
    button_text_is_upcoming,
    button_text_to_mode,
)
from .context import IncomingCallback, IncomingMessage, PlanMode, SubscriptionAction

# --- единая точка правды для команд (роутинг / dedup / FSM-exit) ------------


@dataclass(frozen=True)
class PlanCommand:
    mode: PlanMode


@dataclass(frozen=True)
class SubscriptionCommand:
    action: SubscriptionAction


@dataclass(frozen=True)
class StartOrHelpCommand:
    is_start: bool


@dataclass(frozen=True)
class SettingsCommand:
    pass


@dataclass(frozen=True)
class UpcomingCommand:
    pass


@dataclass(frozen=True)
class InvitationsCommand:
    pass


@dataclass(frozen=True)
class ManageEventsCommand:
    pass


@dataclass(frozen=True)
class CreateCommand:
    pass


@dataclass(frozen=True)
class ConnectCommand:
    pass


@dataclass(frozen=True)
class DisconnectCommand:
    pass


@dataclass(frozen=True)
class CheckCommand:
    pass


@dataclass(frozen=True)
class CalendarSourcesCommand:
    pass


@dataclass(frozen=True)
class ForeignCalendarsCommand:
    pass


@dataclass(frozen=True)
class PendingCommand:
    pass


RecognizedCommand = Union[
    PlanCommand,
    SubscriptionCommand,
    StartOrHelpCommand,
    SettingsCommand,
    UpcomingCommand,
    CreateCommand,
    ConnectCommand,
    DisconnectCommand,
    CheckCommand,
    CalendarSourcesCommand,
    ForeignCalendarsCommand,
    InvitationsCommand,
    ManageEventsCommand,
    PendingCommand,
]


def _plan_command(text: str) -> PlanCommand | None:
    mode = parse_command_mode(text)
    return PlanCommand(mode=mode) if mode is not None else None


def _subscription_command(text: str) -> SubscriptionCommand | None:
    action = parse_subscription_action(text)
    return SubscriptionCommand(action=action) if action is not None else None


# Порядок важен: первый совпавший выигрывает. Добавление новой команды —
# одна строка в этом списке + dataclass + matcher.
_RECOGNIZERS: list[Callable[[str], RecognizedCommand | None]] = [
    lambda t: StartOrHelpCommand(is_start=True) if is_start_command(t) else None,
    lambda t: StartOrHelpCommand(is_start=False) if is_help_command(t) else None,
    _plan_command,
    _subscription_command,
    lambda t: SettingsCommand() if is_settings_request(t) else None,
    lambda t: UpcomingCommand() if is_upcoming_request(t) else None,
    lambda t: InvitationsCommand() if is_invitations_request(t) else None,
    lambda t: ManageEventsCommand() if is_manage_events_request(t) else None,
    lambda t: CreateCommand() if is_create_event_request(t) else None,
    lambda t: ConnectCommand() if is_connect_calendar_request(t) else None,
    lambda t: CheckCommand() if is_check_calendar_request(t) else None,
    lambda t: DisconnectCommand() if is_disconnect_calendar_request(t) else None,
    lambda t: CalendarSourcesCommand() if is_calendar_sources_request(t) else None,
    lambda t: ForeignCalendarsCommand() if is_foreign_calendars_request(t) else None,
    lambda t: PendingCommand() if _is_pending_command(t) else None,
]


def recognize_message(text: str | None) -> RecognizedCommand | None:
    """Распознаёт команду или текст reply-кнопки. None — свободный ввод / unknown."""
    if not text:
        return None
    for recognizer in _RECOGNIZERS:
        result = recognizer(text)
        if result is not None:
            return result
    return None


def _is_pending_command(text: str | None) -> bool:
    if not text:
        return False
    return text.strip().split()[0].lower().startswith("/pending")


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
_CMD_INVITATIONS = re.compile(r"/(?:invitations|invites|respond)(?:@[a-z0-9_]+)?\Z")
_CMD_MANAGE_EVENTS = re.compile(r"/(?:manage|edit|status)(?:@[a-z0-9_]+)?\Z")
_CMD_CREATE = re.compile(r"/(?:create|addevent)(?:@[a-z0-9_]+)?\Z")
_CMD_CONNECT = re.compile(r"/connect(?:@[a-z0-9_]+)?\Z")
_CMD_CALENDARS = re.compile(r"/(?:calendars|calendar_sources)(?:@[a-z0-9_]+)?\Z")
_CMD_FOREIGN_CALENDARS = re.compile(
    r"/(?:foreign|shared_calendars|foreign_calendars)(?:@[a-z0-9_]+)?\Z"
)


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


def _button_or_command(
    text: str | None,
    *,
    button: Callable[[str], bool] | None = None,
    command: re.Pattern[str] | None = None,
) -> bool:
    """Reply-кнопка ИЛИ слэш-команда: общий шаблон ``is_*_request``."""
    if not text:
        return False
    raw = text.strip()
    if button is not None and button(raw):
        return True
    if command is not None and command.fullmatch(_command_part(raw)):
        return True
    return False


def is_settings_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_settings, command=_CMD_DIGEST_SETTINGS)


def is_digest_settings_request(text: str | None) -> bool:
    """Alias для обратной совместимости тестов и импортов."""
    return is_settings_request(text)


def is_upcoming_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_upcoming, command=_CMD_UPCOMING)


def is_invitations_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_invitations, command=_CMD_INVITATIONS)


def is_manage_events_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_manage_events, command=_CMD_MANAGE_EVENTS)


def is_create_event_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_create_event, command=_CMD_CREATE)


def is_connect_calendar_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_connect_calendar, command=_CMD_CONNECT)


def is_check_calendar_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_check_calendar)


def is_disconnect_calendar_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_disconnect_calendar)


def is_calendar_sources_request(text: str | None) -> bool:
    return _button_or_command(text, button=button_text_is_calendar_sources, command=_CMD_CALENDARS)


def is_foreign_calendars_request(text: str | None) -> bool:
    return _button_or_command(
        text, button=button_text_is_foreign_calendars, command=_CMD_FOREIGN_CALENDARS
    )


def is_command_like_message(text: str) -> bool:
    """Команды (`/td`, кнопки) трактуем как «выход из state», не как ввод времени."""
    return recognize_message(text) is not None


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
    message_id_raw = message.get("message_id")
    web_app_raw = message.get("web_app_data")
    web_app_data: str | None = None
    if isinstance(web_app_raw, dict):
        raw_data = web_app_raw.get("data")
        if isinstance(raw_data, str) and raw_data.strip():
            web_app_data = raw_data
    return IncomingMessage(
        update_id=int(update.get("update_id") or 0),
        chat_id=int(chat_id_raw) if isinstance(chat_id_raw, int) else None,
        message_id=int(message_id_raw) if isinstance(message_id_raw, int) else None,
        user_id=int(user_id_raw) if isinstance(user_id_raw, int) else None,
        username=username,
        display_name=_display_name(from_user),
        text=text,
        web_app_data=web_app_data,
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
