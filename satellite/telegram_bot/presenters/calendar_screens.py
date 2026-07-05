"""Rich + fallback presenter'ы календарных экранов (sources, foreign)."""

from __future__ import annotations

from ...calendar.providers.base import CalendarListEntry
from ...calendar.selection import normalize_calendar_url
from ...messages_ru import (
    CALENDAR_SOURCES_FOOTER,
    CALENDAR_SOURCES_INTRO,
    MARK_DISABLED,
    MARK_ENABLED,
    calendar_sources_screen_text,
)
from ...presentation.rich import bold, join_blocks, paragraph, section_heading, unordered_list
from .bundle import ScreenBundle


def calendar_source_toggle_lines(
    calendars: list[CalendarListEntry],
    enabled_urls: set[str],
) -> list[str]:
    """Строки toggle-списка календарей для legacy HTML."""
    lines: list[str] = []
    for entry in calendars:
        mark = MARK_ENABLED if normalize_calendar_url(entry.url) in enabled_urls else MARK_DISABLED
        lines.append(f"{mark} {entry.name}")
    return lines


def calendar_sources_bundle(
    *,
    calendars: list[CalendarListEntry],
    enabled_urls: set[str],
    reply_markup: dict | None = None,
) -> ScreenBundle:
    lines = calendar_source_toggle_lines(calendars, enabled_urls)
    fallback = calendar_sources_screen_text(lines=lines)
    items: list[str] = []
    for entry in calendars:
        mark = MARK_ENABLED if normalize_calendar_url(entry.url) in enabled_urls else MARK_DISABLED
        items.append(bold(f"{mark} {entry.name}"))
    rich = join_blocks(
        [
            section_heading("📚 Календари в плане", level=3),
            paragraph(CALENDAR_SOURCES_INTRO),
            unordered_list(items),
            paragraph(f"<i>{CALENDAR_SOURCES_FOOTER}</i>"),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)
