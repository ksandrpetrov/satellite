"""HTML/Rich HTML presenter'ы календарных списков."""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from html import escape
from typing import Any

from ..calendar.callback_tokens import event_callback_token
from ..calendar.events import (
    build_upcoming_events_groups,
    event_index_marker,
    event_local_start_date,
    format_time_range,
    format_upcoming_day_header,
    parse_iso,
)
from ..messages_ru import (
    INVITATIONS_INTRO_HTML,
    INVITATIONS_SERIES_LABEL,
    MANAGE_INTRO_HTML,
    UPCOMING_EVENTS_HEADING_HTML,
    UPCOMING_EVENTS_HEADING_PLAIN,
    invitation_response_buttons,
    manage_partstat_label,
)
from .rich import (
    bold,
    callback_buttons,
    datetime_link,
    details_block,
    divider,
    escape_rich,
    join_blocks,
    paragraph,
    section_heading,
    truncate_rich_html,
    unordered_list,
)


def upcoming_events_plain_fallback_html(
    events,
    tz,
    reference_date,
    *,
    days: int = 7,
    max_events: int = 30,
) -> str:
    """Plain HTML fallback без ``<blockquote>`` — не мигает с rich ``<details>``."""
    sections: list[str] = [UPCOMING_EVENTS_HEADING_HTML]
    for group in build_upcoming_events_groups(
        events, tz, reference_date, days=days, max_events=max_events
    ):
        header = f"<b>{group['header']}</b>"
        event_lines: list[str] = []
        for item in group["events"]:
            title = escape(str(item["title"]))
            event_lines.append(f"{item['marker']} {item['time_range']} — {title}")
        if not event_lines:
            sections.append(header)
            continue
        sections.append(f"{header}\n" + "\n".join(event_lines))
    if len(sections) <= 1:
        return ""
    return "\n\n".join(sections)


def _day_header_rich(header: str) -> str:
    return escape_rich(header)


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

    blocks: list[str] = [section_heading(UPCOMING_EVENTS_HEADING_PLAIN, level=2)]
    for group in groups:
        raw_header = str(group["header"])
        header = escape_rich(raw_header)
        items = group["events"]
        if not items:
            blocks.append(paragraph(bold(header)))
            continue
        li_parts: list[str] = []
        for item in items:
            title = escape_rich(str(item["title"]))
            unix = _event_start_unix({"dtstart": item.get("start")}, tz)
            if unix is not None:
                time_html = datetime_link(str(item["time_range"]), unix)
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
    sections: list[str] = []
    for idx, ev in enumerate(events):
        if idx:
            sections.append(divider())
        sections.append(paragraph(bold(escape_rich(str(ev.get("summary") or "—")))))
        day = event_local_start_date(ev, tz)
        when = _time_range_rich(ev, tz)
        if day is not None:
            when = f"{escape_rich(format_upcoming_day_header(day, reference_date))} · {when}"
        sections.append(paragraph(when))
        if ev.get("invitation_series"):
            sections.append(paragraph(escape_rich(INVITATIONS_SERIES_LABEL)))
        token = event_callback_token(str(ev.get("url") or ""))
        sections.append(callback_buttons(invitation_response_buttons(token)))
    return sections


def invitations_list_rich_html(
    *,
    body_events: list[dict[str, Any]],
    tz: tzinfo,
    reference_date: date,
    preview_title: str,
    preview_when: str,
    truncated: bool,
) -> str:
    blocks: list[str] = [
        paragraph(INVITATIONS_INTRO_HTML),
    ]
    blocks.extend(_invitation_items_rich(body_events, tz, reference_date))
    if truncated:
        blocks.append(paragraph("<i>Показаны первые встречи — обновите список после ответов.</i>"))
    return truncate_rich_html(join_blocks(blocks))


def manage_list_body_lines(events, tz, reference_date: date) -> list[str]:
    """Строки legacy HTML тела списка manage (заголовок дня + встречи)."""
    if not events:
        return []
    lines: list[str] = []
    last_day: date | None = None
    for idx, ev in enumerate(events):
        day = event_local_start_date(ev, tz)
        if day is not None and day != last_day:
            if lines:
                lines.append("")
            lines.append(f"<b>{format_upcoming_day_header(day, reference_date)}</b>")
            last_day = day
        marker = event_index_marker(idx)
        title = escape(str(ev.get("summary") or "—"))
        when = format_time_range(ev, tz)
        lines.append(f"{marker} {when} — {title}")
    return lines


def manage_list_rich_html(
    *,
    body_events: list[dict[str, Any]],
    tz: tzinfo,
    reference_date: date,
    truncated: bool,
) -> str:
    blocks: list[str] = [paragraph(MANAGE_INTRO_HTML)]
    last_day: date | None = None
    day_items: list[str] = []
    day_header = ""

    def flush_day() -> None:
        nonlocal day_items, day_header
        if not day_items:
            return
        body = unordered_list(day_items)
        summary = bold(_day_header_rich(day_header))
        if len(day_items) >= 2:
            blocks.append(details_block(summary, body, open=True))
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
    label = manage_partstat_label(partstat) or "—"
    blocks = [
        section_heading(escape_rich(title), level=3),
        paragraph(escape_rich(when)),
        paragraph(f"📌 Сейчас: {bold(escape_rich(label))}"),
        paragraph("<i>Поменять решение можно сколько угодно — Чайка пошлёт ответ в календарь.</i>"),
    ]
    return join_blocks(blocks)
