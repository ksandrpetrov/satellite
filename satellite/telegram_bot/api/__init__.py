"""Telegram Bot API facade."""

from .client import TelegramClient
from .errors import (
    TelegramError,
    is_custom_emoji_rejected,
    is_html_entities_rejected,
    is_message_effect_rejected,
    is_rich_message_unavailable,
)

__all__ = [
    "TelegramClient",
    "TelegramError",
    "is_custom_emoji_rejected",
    "is_html_entities_rejected",
    "is_message_effect_rejected",
    "is_rich_message_unavailable",
]
