"""Выбор календарей для отображения плана, дайджеста и /upcoming."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .callback_tokens import calendar_callback_token
from .providers.base import CalendarListEntry

if TYPE_CHECKING:
    from ..users import UserRecord


def normalize_calendar_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/")


def _normalize_url(url: str | None) -> str:
    return normalize_calendar_url(url)


def sort_calendar_entries(
    calendars: list[CalendarListEntry],
) -> list[CalendarListEntry]:
    """Фиксированный порядок списка в UI (CalDAV может отдавать календари вразнобой)."""
    return sorted(
        calendars,
        key=lambda entry: (
            normalize_calendar_url(entry.url).casefold(),
            entry.name.casefold(),
        ),
    )


def find_calendar_entry_by_token(
    calendars: list[CalendarListEntry],
    token: str,
) -> CalendarListEntry | None:
    needle = (token or "").strip()
    if not needle:
        return None
    for entry in calendars:
        if calendar_callback_token(entry.url) == needle:
            return entry
    return None


def effective_enabled_calendar_urls_from_parts(
    *,
    enabled_calendar_urls: tuple[str, ...],
    primary_calendar_url: str | None,
) -> tuple[str, ...]:
    """URL календарей, из которых читаем события."""
    if enabled_calendar_urls:
        return enabled_calendar_urls
    primary = _normalize_url(primary_calendar_url)
    if primary:
        return (primary,)
    return ()


def effective_enabled_calendar_urls(record: UserRecord) -> tuple[str, ...]:
    """URL календарей для ``UserRecord``."""
    return effective_enabled_calendar_urls_from_parts(
        enabled_calendar_urls=record.enabled_calendar_urls,
        primary_calendar_url=record.primary_calendar_url,
    )


def foreign_calendar_entries(
    calendars: list[CalendarListEntry],
    *,
    primary_calendar_url: str | None,
) -> list[CalendarListEntry]:
    """Календари, пошаренные в аккаунт (все, кроме основного)."""
    primary = _normalize_url(primary_calendar_url)
    if not primary:
        return list(calendars)
    return [entry for entry in calendars if _normalize_url(entry.url) != primary]
