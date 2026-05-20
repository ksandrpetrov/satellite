"""Calendar provider adapters (Mail.ru, Yandex skeleton)."""

from .base import (
    CalendarConnectionStatus,
    CalendarEventPayload,
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProvider,
    CalendarProviderError,
    ProviderNotImplementedError,
    UserCalendarContext,
)
from .registry import PROVIDER_MAILRU, PROVIDER_YANDEX, get_provider, list_provider_ids

__all__ = [
    "CalendarConnectionStatus",
    "CalendarEventPayload",
    "CalendarEventRef",
    "CalendarNotConnectedError",
    "CalendarProvider",
    "CalendarProviderError",
    "ProviderNotImplementedError",
    "UserCalendarContext",
    "PROVIDER_MAILRU",
    "PROVIDER_YANDEX",
    "get_provider",
    "list_provider_ids",
]
