"""Чистые функции над словарём события: парсинг времени, фильтры, сортировка."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Literal

from .constants import LUNCH_EMOJI_MARKER, PLAN_ALL_DAY_LABEL

PizzaMealKind = Literal["breakfast", "lunch", "dinner"]

Event = dict[str, Any]


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


def is_declined_event_for_user(event: Event, login: str) -> bool:
    login_norm = (login or "").strip().casefold()
    if not login_norm:
        return False
    for attendee in event.get("attendees", []):
        attendee_norm = str(attendee).casefold()
        if login_norm in attendee_norm and "partstat=declined" in attendee_norm:
            return True
    return False


def user_partstat(event: Event, login: str) -> str | None:
    """Возвращает PARTSTAT пользователя в событии (верхним регистром) или None.

    Если пользователь встречается в attendees несколько раз — выбираем самое
    «доброе» состояние: ``ACCEPTED`` > ``TENTATIVE`` > ``DELEGATED`` >
    ``NEEDS-ACTION`` > ``DECLINED``. Это даёт стабильный ответ для редкого, но
    реального случая дублирующихся ATTENDEE-строк.

    Возвращает None, если пользователь в attendees не найден или PARTSTAT не
    указан — это означает «не знаем», и downstream-логика трактует такое как
    подтверждённое (рисуем обычный номер).
    """
    login_norm = (login or "").strip().casefold()
    if not login_norm:
        return None
    rank = {
        "ACCEPTED": 5,
        "TENTATIVE": 4,
        "DELEGATED": 3,
        "NEEDS-ACTION": 2,
        "DECLINED": 1,
    }
    best: str | None = None
    for attendee in event.get("attendees", []):
        attendee_norm = str(attendee).casefold()
        if login_norm not in attendee_norm:
            continue
        idx = attendee_norm.find("partstat=")
        if idx < 0:
            continue
        tail = attendee_norm[idx + len("partstat="):]
        end = len(tail)
        for sep in (";", ",", ":", " "):
            pos = tail.find(sep)
            if 0 <= pos < end:
                end = pos
        status = tail[:end].strip().upper()
        if not status:
            continue
        if best is None or rank.get(status, 0) > rank.get(best, 0):
            best = status
    return best


def is_cancelled_event(event: Event) -> bool:
    """True для событий с ``STATUS:CANCELLED`` (или булевым флагом из dict-API).

    Mail.ru CalDAV держит отменённые встречи в выдаче REPORT с обычными
    DTSTART/DTEND, помечая их только полем STATUS. Без этой проверки они
    попадают в план как полноценные встречи и пугают пользователя «фантомом».
    Дополнительно учитываем ключи ``isCancelled``/``is_cancelled`` для входов
    из не-CalDAV источников (тесты, ТЗ-совместимый словарь).
    """
    if event.get("isCancelled") or event.get("is_cancelled"):
        return True
    status = event.get("status")
    if not status:
        return False
    return str(status).strip().upper() == "CANCELLED"


def is_all_day_event(event: Event, tz: tzinfo) -> bool:
    start = parse_iso(event.get("dtstart"))
    end = parse_iso(event.get("dtend"))

    if isinstance(start, date) and not isinstance(start, datetime):
        return True

    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return False

    start_local = _to_local(start, tz)
    end_local = _to_local(end, tz)

    is_midnight_bounds = (
        start_local.hour == 0
        and start_local.minute == 0
        and end_local.hour == 0
        and end_local.minute == 0
    )
    if not is_midnight_bounds:
        return False

    duration = end_local - start_local
    if duration <= timedelta(0):
        return True
    return duration >= timedelta(days=1) and duration.total_seconds() % 86400 == 0


def pizza_meal_kind(summary: str) -> PizzaMealKind | None:
    """🍕 и одно из слов «завтрак» / «обед» / «ужин» (без учёта регистра)."""
    if LUNCH_EMOJI_MARKER not in summary:
        return None
    fold = summary.casefold()
    if "завтрак" in fold:
        return "breakfast"
    if "обед" in fold:
        return "lunch"
    if "ужин" in fold:
        return "dinner"
    return None


def is_lunch_event(event: Event) -> bool:
    """True для встреч, которые отфильтровывает ``HIDE_LUNCH_EVENTS``."""
    return pizza_meal_kind(str(event.get("summary") or "")) is not None


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


def day_bounds(target_date: date, tz: tzinfo) -> tuple[datetime, datetime]:
    day_start = datetime.combine(target_date, time.min, tzinfo=tz)
    return day_start, day_start + timedelta(days=1)


def filter_events_for_user(
    events: list[Event],
    target_date: date,
    *,
    tz: tzinfo,
    login: str,
    hide_all_day: bool,
    hide_lunch: bool,
) -> tuple[list[Event], list[Event]]:
    """Возвращает (видимые события, скрытые «🍕+приём пищи») на указанный день.

    Делает один проход по списку — каждая проверка вызывается максимум один раз
    на событие. Это важно: парсинг dtstart/dtend в `parse_iso` не дешевый,
    а в day-fetch'е таких событий бывает по 20–50 штук.
    """
    visible: list[Event] = []
    hidden_lunch: list[Event] = []
    for event in events:
        if not event_occurs_on(event, target_date, tz):
            continue
        if is_cancelled_event(event):
            continue
        if is_declined_event_for_user(event, login):
            continue
        if hide_all_day and is_all_day_event(event, tz):
            continue
        if hide_lunch and is_lunch_event(event):
            hidden_lunch.append(event)
            continue
        visible.append(event)
    return visible, hidden_lunch
