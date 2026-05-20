"""Чистые функции над словарём события: парсинг времени, фильтры, сортировка."""

from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Literal, Sequence

from ..messages_ru import format_duration_long_ru
from .constants import LUNCH_EMOJI_MARKER, PLAN_ALL_DAY_LABEL
from .time_utils import merge_intervals, sum_minutes

PizzaMealKind = Literal["breakfast", "lunch", "dinner"]

Event = dict[str, Any]

NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")


def event_index_marker(index: int) -> str:
    """Маркер порядкового номера встречи (как в дайджесте)."""
    if index < len(NUMBER_EMOJI):
        return NUMBER_EMOJI[index]
    return f"{index + 1}."


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


def is_pending_invitation_for_user(event: Event, login: str) -> bool:
    """True, если пользователю нужно ответить на приглашение (NEEDS-ACTION / DELEGATED)."""
    status = user_partstat(event, login)
    return status in {"NEEDS-ACTION", "DELEGATED"}


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


_WEEKDAY_SHORT_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def event_local_start_date(event: Event, tz: tzinfo) -> date | None:
    """Локальная дата начала события (для группировки списка «Ближайшие»)."""
    start = parse_iso(event.get("dtstart"))
    if isinstance(start, datetime):
        return _to_local(start, tz).date()
    if isinstance(start, date):
        return start
    return None


def format_upcoming_day_header(
    target_date: date,
    reference_date: date,
    *,
    busy_minutes: int = 0,
) -> str:
    """Заголовок дня в /upcoming: «Сегодня, ср 20.05 (занято 1 час)» / «Пт, 22.05»."""
    wd = _WEEKDAY_SHORT_RU[target_date.weekday()]
    date_str = target_date.strftime("%d.%m")
    delta = (target_date - reference_date).days
    if delta == 0:
        head = f"Сегодня, {wd} {date_str}"
    elif delta == 1:
        head = f"Завтра, {wd} {date_str}"
    elif delta == 2:
        head = f"Послезавтра, {wd} {date_str}"
    else:
        head = f"{wd.capitalize()}, {date_str}"
    if busy_minutes > 0:
        head += f" (занято {format_duration_long_ru(busy_minutes)})"
    return head


def _day_busy_minutes(events: Sequence[Event], target_date: date, tz: tzinfo) -> int:
    """Суммарная длительность timed-встреч на дате (с мерджем пересечений).

    All-day события игнорируем — они и так показаны строкой «весь день».
    Клиппируем границы события на сутки [00:00, 24:00) локально, чтобы
    многодневная встреча учитывалась пропорционально.
    """
    day_start = datetime.combine(target_date, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    intervals: list[tuple[int, int]] = []
    for ev in events:
        if is_all_day_event(ev, tz):
            continue
        start_local, end_local = event_datetime_bounds(ev, tz)
        if start_local is None or end_local is None:
            continue
        s = max(start_local, day_start)
        e = min(end_local, day_end)
        if e <= s:
            continue
        start_m = int((s - day_start).total_seconds() // 60)
        end_m = int((e - day_start).total_seconds() // 60)
        intervals.append((start_m, end_m))
    return sum_minutes(merge_intervals(intervals))


def build_upcoming_events_groups(
    events: Sequence[Event],
    tz: tzinfo,
    reference_date: date,
    *,
    days: int = 7,
    max_events: int = 30,
) -> list[dict[str, Any]]:
    """Группы «Ближайшие события» для Web App (та же логика, что /upcoming)."""
    visible = [ev for ev in events if not is_cancelled_event(ev)]
    visible.sort(key=lambda ev: sort_key(ev, tz))
    end = reference_date + timedelta(days=days)
    by_day: dict[date, list[Event]] = {}
    for ev in visible:
        day = event_local_start_date(ev, tz)
        if day is None or day < reference_date or day >= end:
            continue
        by_day.setdefault(day, []).append(ev)

    groups: list[dict[str, Any]] = []
    remaining = max_events
    for offset in range(days):
        if remaining <= 0:
            break
        day = reference_date + timedelta(days=offset)
        day_events = by_day.get(day)
        if not day_events:
            continue
        busy = _day_busy_minutes(day_events, day, tz)
        header = format_upcoming_day_header(day, reference_date, busy_minutes=busy)
        items: list[dict[str, Any]] = []
        for idx, ev in enumerate(day_events):
            if remaining <= 0:
                break
            items.append(
                {
                    "marker": event_index_marker(idx),
                    "time_range": format_time_range(ev, tz),
                    "title": str(ev.get("summary") or ev.get("title") or "—"),
                    "uid": ev.get("uid") or ev.get("id"),
                    "url": ev.get("url"),
                }
            )
            remaining -= 1
        groups.append({"date": day.isoformat(), "header": header, "events": items})
    return groups


def format_upcoming_events_lines(
    events: Sequence[Event],
    tz: tzinfo,
    reference_date: date,
    *,
    days: int = 7,
    max_events: int = 30,
) -> list[str]:
    """Строки тела «Ближайшие события»: заголовки дней и пункты встреч (HTML)."""
    lines: list[str] = []
    first_day = True
    for group in build_upcoming_events_groups(
        events, tz, reference_date, days=days, max_events=max_events
    ):
        if not first_day:
            lines.append("")
        first_day = False
        lines.append(f"<b>{group['header']}</b>")
        for item in group["events"]:
            title = html.escape(str(item["title"]))
            lines.append(f"{item['marker']} {item['time_range']} — {title}")
    return lines


def format_single_day_events_lines(
    events: Sequence[Event],
    tz: tzinfo,
    target_date: date,
    reference_date: date,
    *,
    max_events: int = 50,
) -> list[str]:
    """Строки списка встреч на один день (для чужого календаря)."""
    visible = [
        ev
        for ev in events
        if not is_cancelled_event(ev) and event_local_start_date(ev, tz) == target_date
    ]
    visible.sort(key=lambda ev: sort_key(ev, tz))
    if not visible:
        return []
    busy = _day_busy_minutes(visible, target_date, tz)
    header = format_upcoming_day_header(target_date, reference_date, busy_minutes=busy)
    lines = [f"<b>{header}</b>"]
    for idx, ev in enumerate(visible[:max_events]):
        title = html.escape(str(ev.get("summary") or ev.get("title") or "—"))
        when = format_time_range(ev, tz)
        marker = event_index_marker(idx)
        lines.append(f"{marker} {when} — {title}")
    return lines


def event_ends_after(
    event: Event, tz: tzinfo, *, moment: datetime
) -> bool:
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


def collect_pending_invitations(
    events: Sequence[Event],
    login: str,
    tz: tzinfo,
    *,
    now: datetime,
    max_events: int = 20,
) -> list[Event]:
    """События, по которым пользователю нужно принять решение, отсортированные по началу."""
    login_norm = (login or "").strip()
    if not login_norm:
        return []
    pending = [
        ev
        for ev in events
        if (ev.get("url") or "").strip()
        and not is_cancelled_event(ev)
        and is_pending_invitation_for_user(ev, login_norm)
        and event_ends_after(ev, tz, moment=now)
    ]
    pending.sort(key=lambda ev: sort_key(ev, tz))
    return pending[: max(0, max_events)]


def format_invitation_list_lines(
    events: Sequence[Event],
    tz: tzinfo,
    reference_date: date,
) -> list[str]:
    """HTML-строки списка приглашений (заголовок дня + пункты)."""
    if not events:
        return []
    lines: list[str] = []
    last_day: date | None = None
    for idx, ev in enumerate(events):
        day = event_local_start_date(ev, tz)
        if day is not None and day != last_day:
            if lines:
                lines.append("")
            lines.append(
                f"<b>{format_upcoming_day_header(day, reference_date)}</b>"
            )
            last_day = day
        title = html.escape(str(ev.get("summary") or "—"))
        when = format_time_range(ev, tz)
        marker = event_index_marker(idx)
        lines.append(f"{marker} {when} — {title}")
    return lines


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
