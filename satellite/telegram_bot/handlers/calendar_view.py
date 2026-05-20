"""Общие хелперы UI для списка календарей (sources / foreign / settings hub)."""

from __future__ import annotations

import logging

from ...calendar.providers.base import CalendarListEntry, CalendarProviderError
from ...calendar.selection import effective_enabled_calendar_urls
from ...users import UserRecord
from .context import HandlerContext

log = logging.getLogger(__name__)


def normalize_calendar_url(url: str) -> str:
    return url.strip().rstrip("/")


def enabled_url_set(record: UserRecord) -> set[str]:
    return {normalize_calendar_url(url) for url in effective_enabled_calendar_urls(record)}


def screen_lines(
    calendars: list[CalendarListEntry], enabled_urls: set[str]
) -> list[str]:
    lines: list[str] = []
    for entry in calendars:
        mark = "✅" if normalize_calendar_url(entry.url) in enabled_urls else "⬜️"
        lines.append(f"{mark} {entry.name}")
    return lines


def fetch_calendars(
    ctx: HandlerContext, user_id: int
) -> list[CalendarListEntry] | None:
    try:
        return ctx.calendar_service.list_calendars(user_id)
    except CalendarProviderError:
        log.warning("Failed to list calendars for user_id=%s", user_id)
        return None
