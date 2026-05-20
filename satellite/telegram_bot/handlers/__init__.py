"""Telegram-хендлеры: routing, сценарии и Telegram delivery.

Публичный API (стабильный для тестов и `telegram_bot.bot`):

- ``handle_message`` / ``handle_callback_query`` — точки входа диспетчера.
- ``extract_message`` / ``extract_callback_query`` — нормализация update'ов.
- ``HandlerContext``, ``IncomingMessage``, ``IncomingCallback`` — DTO.
- ``parse_command_mode``, ``parse_subscription_action`` и распознаватели —
  чистые функции, удобно тестировать.

Внутреннее устройство:

- ``context`` — общие DTO и ``HandlerContext`` (нет внутренних зависимостей).
- ``routing`` — парсеры и ``extract_*`` (нет I/O).
- ``delivery`` — обёртки над Telegram API (send/edit/answer).
- ``plan`` — сценарий «команда → план дня → ответ».
- ``subscription`` — подписка/отписка.
- ``settings`` — экраны и callback-кнопки настроек дайджеста.
- ``dispatch`` — диспетчеры, склеивающие всё выше.
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
    is_digest_settings_request,
    is_disconnect_calendar_request,
    is_help_command,
    is_start_command,
    is_start_or_help_command,
    is_upcoming_request,
    is_update_callback,
    is_update_message,
    parse_command_mode,
    parse_subscription_action,
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
    "is_check_calendar_request",
    "is_connect_calendar_request",
    "is_create_event_request",
    "is_digest_settings_request",
    "is_disconnect_calendar_request",
    "is_help_command",
    "is_start_command",
    "is_start_or_help_command",
    "is_upcoming_request",
    "is_update_callback",
    "is_update_message",
    "parse_command_mode",
    "parse_subscription_action",
]
