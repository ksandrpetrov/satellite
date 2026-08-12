"""Telegram-хендлеры: routing, сценарии и Telegram delivery.

Публичный API (стабильный для тестов и `telegram_bot.bot`):

- ``handle_message`` / ``handle_callback_query`` — точки входа диспетчера.
- ``extract_message`` / ``extract_callback_query`` — нормализация update'ов.
- ``HandlerContext``, ``IncomingMessage``, ``IncomingCallback`` — DTO.
- ``recognize_message`` — единая точка правды для команд (роутинг, dedup, FSM-exit).

Внутреннее устройство:

- ``context`` — общие DTO и ``HandlerContext`` (нет внутренних зависимостей).
- ``routing`` — парсеры, ``recognize_message``, ``extract_*`` (нет I/O).
- ``calendar_view`` — общие хелперы списка календарей.
- ``delivery`` — обёртки над Telegram API (send/edit/answer).
- ``dispatch`` — диспетчеры, склеивающие сценарии.
"""

from .context import (
    HandlerContext,
    IncomingCallback,
    IncomingMessage,
    PlanMode,
    SubscriptionAction,
)
from .dispatch import handle_callback_query, handle_message
from .routing import (
    extract_callback_query,
    extract_message,
    is_check_calendar_request,
    is_connect_calendar_request,
    is_create_event_request,
    is_disconnect_calendar_request,
    is_help_command,
    is_settings_request,
    is_start_command,
    is_start_or_help_command,
    is_upcoming_request,
    is_update_callback,
    is_update_message,
    parse_command_mode,
    parse_subscription_action,
    recognize_message,
)

__all__ = [
    "HandlerContext",
    "IncomingCallback",
    "IncomingMessage",
    "PlanMode",
    "SubscriptionAction",
    "extract_callback_query",
    "extract_message",
    "handle_callback_query",
    "handle_message",
    "is_update_callback",
    "is_update_message",
    "recognize_message",
]
