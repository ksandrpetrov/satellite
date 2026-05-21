"""Registry провайдеров календаря."""

from __future__ import annotations

from .base import CalendarProvider
from .mailru import PROVIDER_ID as PROVIDER_MAILRU
from .mailru import MailruCalendarProvider
from .yandex import PROVIDER_ID as PROVIDER_YANDEX
from .yandex import YandexCalendarProvider

PROVIDER_IDS = frozenset({PROVIDER_MAILRU, PROVIDER_YANDEX})


def get_provider(provider_id: str, *, cache_ttl_sec: int = 300) -> CalendarProvider:
    normalized = (provider_id or "").strip().lower()
    if normalized == PROVIDER_MAILRU:
        return MailruCalendarProvider(cache_ttl_sec=cache_ttl_sec)
    if normalized == PROVIDER_YANDEX:
        return YandexCalendarProvider()
    raise ValueError(f"Unknown calendar provider: {provider_id!r}")


def list_provider_ids() -> tuple[str, ...]:
    return (PROVIDER_MAILRU, PROVIDER_YANDEX)
