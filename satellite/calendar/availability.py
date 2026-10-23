"""Conservative availability within local working hours."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .events import (
    Event,
    event_datetime_bounds,
    event_occurs_on,
    is_all_day_event,
    is_cancelled_event,
    is_declined_event_for_user,
)
from .time_utils import parse_hhmm


def find_free_slots(
    events: Sequence[Event],
    *,
    start_date: date,
    end_date: date,
    tz: ZoneInfo,
    login: str,
    duration_minutes: int = 30,
    work_start: str = "10:00",
    work_end: str = "19:00",
) -> list[tuple[datetime, datetime]]:
    """Return maximal gaps; end_date is exclusive, all-day events block the day.

    Pending invitations occupy time. Malformed active events fail closed instead
    of silently suggesting a slot that may already be occupied.
    """
    start_min, end_min = parse_hhmm(work_start), parse_hhmm(work_end)
    if start_min is None or end_min is None or end_min <= start_min:
        raise ValueError("Invalid working hours")
    if not 1 <= (end_date - start_date).days <= 31 or not 1 <= duration_minutes <= 1440:
        raise ValueError("Invalid availability range")
    active = [
        event
        for event in events
        if not is_cancelled_event(event) and not is_declined_event_for_user(event, login)
    ]
    slots: list[tuple[datetime, datetime]] = []
    day = start_date
    while day < end_date:
        midnight = datetime.combine(day, time.min, tzinfo=tz)
        window_start = midnight + timedelta(minutes=start_min)
        window_end = midnight + timedelta(minutes=end_min)
        busy: list[tuple[datetime, datetime]] = []
        for event in active:
            if is_all_day_event(event, tz):
                if event_occurs_on(event, day, tz):
                    busy.append((window_start, window_end))
                continue
            start, end = event_datetime_bounds(event, tz)
            if start is None or end is None or end <= start:
                raise ValueError("An event has invalid time bounds")
            begin = max(window_start, start)
            finish = min(window_end, end)
            if finish > begin:
                busy.append((begin, finish))
        cursor = window_start
        for begin, finish in sorted(busy):
            if (
                begin.astimezone(UTC) - cursor.astimezone(UTC)
            ).total_seconds() >= duration_minutes * 60:
                slots.append((cursor, begin))
            cursor = max(cursor, finish)
        if (
            window_end.astimezone(UTC) - cursor.astimezone(UTC)
        ).total_seconds() >= duration_minutes * 60:
            slots.append((cursor, window_end))
        day += timedelta(days=1)
    return slots
