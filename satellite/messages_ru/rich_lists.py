"""Rich Message HTML для списков событий (/upcoming, /invitations, /manage)."""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Any

from ..calendar.events import build_upcoming_events_groups, format_time_range, parse_iso
from ..telegram_bot.rich_message import (
    bold,
    datetime_link,
    details_block,
    escape_rich,
    join_blocks,
    paragraph,
    section_heading,
    truncate_rich_html,
    unordered_list,
)

_INVITATIONS_DETAILS_MIN = 5
_MANAGE_DETAILS_MIN = 5


def _event_start_unix(event: dict[str, Any], tz: tzinfo) -> int | None:
    start = parse_iso(event.get("dtstart"))
    if not isinstance(start, datetime):
        return None
    if start.tzinfo is None:
        local = start.replace(tzinfo=tz)
    else:
        local = start.astimezone(tz)
    return int(local.timestamp())


def _time_range_rich(event: dict[str, Any], tz: tzinfo) -> str:
    label = format_time_range(event, tz)
    unix = _event_start_unix(event, tz)
    if unix is not None:
        return datetime_link(label, unix)
    return escape_rich(label)


def _events_by_url(events) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for ev in events:
        url = ev.get("url")
        if url:
            lookup[str(url)] = ev
    return lookup


def upcoming_events_rich_html(
    events,
    tz: tzinfo,
    reference_date: date,
    *,
    days: int = 7,
    max_events: int = 30,
    max_groups: int | None = None,
) -> str:
    """Rich HTML тела «Ближайшие события»."""
    groups = build_upcoming_events_groups(
        events, tz, reference_date, days=days, max_events=max_events
    )
    if max_groups is not None:
        groups = groups[:max_groups]
    if not groups:
        return ""

    by_url = _events_by_url(events)
    blocks: list[str] = [section_heading("Ближайшие события", level=2)]
    for group in groups:
        header = escape_rich(str(group["header"]))
        items = group["events"]
        if not items:
            blocks.append(paragraph(bold(header)))
            continue
        li_parts: list[str] = []
        for item in items:
            title = escape_rich(str(item["title"]))
            ev = by_url.get(str(item.get("url") or ""))
            if ev is not None:
                time_html = _time_range_rich(ev, tz)
            else:
                time_html = escape_rich(str(item["time_range"]))
            li_parts.append(f"{item['marker']} {time_html} — {title}")
        body = unordered_list(li_parts)
        summary = bold(f"{header} — {len(items)}")
        if len(items) >= 2:
            blocks.append(details_block(summary, body, open=True))
        else:
            blocks.append(paragraph(summary))
            blocks.append(body)
    return truncate_rich_html(join_blocks(blocks))


def _invitation_items_rich(
    events: list[dict[str, Any]],
    tz: tzinfo,
    reference_date: date,
) -> list[str]:
    from ..calendar.events import (
        event_index_marker,
        event_local_start_date,
        format_upcoming_day_header,
    )

    sections: list[str] = []
    last_day: date | None = None
    day_items: list[str] = []
    day_header = ""

    def flush_day() -> None:
        if not day_items:
            return
        body = unordered_list(day_items)
        summary = bold(escape_rich(day_header))
        open_day = len(day_items) < _INVITATIONS_DETAILS_MIN
        if len(day_items) >= 2:
            sections.append(details_block(summary, body, open=open_day))
        else:
            sections.append(paragraph(summary))
            sections.append(body)

    for idx, ev in enumerate(events):
        day = event_local_start_date(ev, tz)
        if day is not None and day != last_day:
            flush_day()
            day_items = []
            day_header = format_upcoming_day_header(day, reference_date)
            last_day = day
        marker = event_index_marker(idx)
        title = bold(escape_rich(str(ev.get("summary") or "—")))
        when = _time_range_rich(ev, tz)
        day_items.append(f"{marker} {when} — {title}")
    flush_day()
    return sections


def invitations_list_rich_html(
    *,
    body_events: list[dict[str, Any]],
    tz: tzinfo,
    reference_date: date,
    truncated: bool,
) -> str:
    from .settings_ui import INVITATIONS_INTRO_HTML

    blocks: list[str] = [paragraph(INVITATIONS_INTRO_HTML)]
    blocks.extend(_invitation_items_rich(body_events, tz, reference_date))
    if truncated:
        blocks.append(paragraph("<i>Показаны первые встречи — обновите список после ответов.</i>"))
    return truncate_rich_html(join_blocks(blocks))


def manage_list_rich_html(
    *,
    body_events: list[dict[str, Any]],
    tz: tzinfo,
    reference_date: date,
    truncated: bool,
) -> str:
    from ..calendar.events import (
        event_index_marker,
        event_local_start_date,
        format_upcoming_day_header,
    )
    from .settings_ui import MANAGE_INTRO_HTML

    blocks: list[str] = [paragraph(MANAGE_INTRO_HTML)]
    last_day: date | None = None
    day_items: list[str] = []
    day_header = ""

    def flush_day() -> None:
        nonlocal day_items, day_header
        if not day_items:
            return
        body = unordered_list(day_items)
        summary = bold(escape_rich(day_header))
        open_default = len(day_items) < _MANAGE_DETAILS_MIN
        if len(day_items) >= 2:
            blocks.append(details_block(summary, body, open=open_default))
        else:
            blocks.append(paragraph(summary))
            blocks.append(body)
        day_items = []

    for idx, ev in enumerate(body_events):
        day = event_local_start_date(ev, tz)
        if day is not None and day != last_day:
            flush_day()
            day_header = format_upcoming_day_header(day, reference_date)
            last_day = day
        marker = event_index_marker(idx)
        title = bold(escape_rich(str(ev.get("summary") or "—")))
        when = _time_range_rich(ev, tz)
        day_items.append(f"{marker} {when} — {title}")
    flush_day()

    if truncated:
        blocks.append(
            paragraph("<i>Показаны первые встречи — обновите список после изменений.</i>")
        )
    return truncate_rich_html(join_blocks(blocks))


def manage_detail_rich_html(*, title: str, when: str, partstat: str | None) -> str:
    from .settings_ui import manage_partstat_label

    label = manage_partstat_label(partstat) or "—"
    blocks = [
        section_heading(escape_rich(title), level=3),
        paragraph(escape_rich(when)),
        paragraph(f"📌 Сейчас: {bold(escape_rich(label))}"),
        paragraph("<i>Поменять решение можно сколько угодно — Чайка пошлёт ответ в календарь.</i>"),
    ]
    return join_blocks(blocks)
