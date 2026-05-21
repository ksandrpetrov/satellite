"""Парсинг времени/дат и базовые операции с диапазонами события."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from ..constants import PLAN_ALL_DAY_LABEL
from ._types import Event


def parse_iso(value: Any) -> datetime | date | None:
    """Парсит ISO-строку в date (если только дата) либо datetime (если дата+время).

    Важно: `datetime.fromisoformat("2026-05-11")` начиная с Python 3.7 НЕ бросает
    исключение — возвращает datetime в полночь. Если бы мы пробовали datetime
    первым, все all-day события превращались бы в timed-события в полночь.
    Поэтому если в строке нет разделителя времени — сначала пробуем date.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    has_time_separator = "T" in value or " " in value
    if not has_time_separator:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_local(value: datetime, tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def event_datetime_bounds(event: Event, tz: tzinfo) -> tuple[datetime | None, datetime | None]:
    start = parse_iso(event.get("dtstart"))
    end = parse_iso(event.get("dtend"))
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None, None
    return _to_local(start, tz), _to_local(end, tz)


def event_occurs_on(event: Event, target_date: date, tz: tzinfo) -> bool:
    start = parse_iso(event.get("dtstart"))
    end = parse_iso(event.get("dtend"))
    if start is None:
        return False

    if isinstance(start, datetime):
        start_local = _to_local(start, tz)
        start_date = start_local.date()
    else:
        start_date = start

    if end is None:
        end_date = start_date
    elif isinstance(end, datetime):
        end_date = _to_local(end, tz).date()
    else:
        # all-day VEVENT: DTEND эксклюзивен (следующий день после последнего)
        end_date = end - timedelta(days=1)

    return start_date <= target_date <= max(start_date, end_date)


def event_local_start_date(event: Event, tz: tzinfo) -> date | None:
    """Локальная дата начала события (для группировки списка «Ближайшие»)."""
    start = parse_iso(event.get("dtstart"))
    if isinstance(start, datetime):
        return _to_local(start, tz).date()
    if isinstance(start, date):
        return start
    return None


def day_bounds(target_date: date, tz: tzinfo) -> tuple[datetime, datetime]:
    day_start = datetime.combine(target_date, time.min, tzinfo=tz)
    return day_start, day_start + timedelta(days=1)


def format_time_range(event: Event, tz: tzinfo) -> str:
    start = parse_iso(event.get("dtstart"))
    end = parse_iso(event.get("dtend"))

    if isinstance(start, datetime):
        start_local = _to_local(start, tz)
        text = start_local.strftime("%H:%M")
        if isinstance(end, datetime):
            end_local = _to_local(end, tz)
            text += "–" + end_local.strftime("%H:%M")
        return text

    return PLAN_ALL_DAY_LABEL


def event_duration_minutes(event: Event, tz: tzinfo) -> int:
    start_local, end_local = event_datetime_bounds(event, tz)
    if not start_local or not end_local:
        return 0
    delta = end_local - start_local
    return max(0, int(delta.total_seconds() // 60))


def sort_key(event: Event, tz: tzinfo) -> tuple[int, datetime]:
    start = parse_iso(event.get("dtstart"))
    if isinstance(start, datetime):
        return (0, _to_local(start, tz))
    if isinstance(start, date):
        return (1, datetime.combine(start, time.min, tzinfo=tz))
    return (2, datetime.max.replace(tzinfo=tz))


def event_ends_after(event: Event, tz: tzinfo, *, moment: datetime) -> bool:
    """True, если событие ещё не закончилось относительно ``moment`` (локально)."""
    end = parse_iso(event.get("dtend"))
    start = parse_iso(event.get("dtstart"))
    if isinstance(end, datetime):
        return _to_local(end, tz) > moment
    if isinstance(start, date) and not isinstance(start, datetime):
        if isinstance(end, date) and not isinstance(end, datetime):
            last_day = end - timedelta(days=1)
        else:
            last_day = start
        return last_day >= moment.date()
    if isinstance(start, datetime):
        return _to_local(start, tz) >= moment
    return False
