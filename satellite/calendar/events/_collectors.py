"""Сборка списков событий: /upcoming, приглашения, фильтрация дня.

Здесь живут «прикладные» функции — те, что вызываются handlers/scheduler.
Все они опираются на чистые примитивы из _time / _partstat / _filters.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from ...messages_ru import format_duration_long_ru
from ..time_utils import merge_intervals, sum_minutes
from ._filters import (
    event_index_marker,
    is_all_day_event,
    is_cancelled_event,
    is_lunch_event,
)
from ._partstat import (
    is_declined_event_for_user,
    is_pending_invitation_for_user,
    user_partstat,
)
from ._time import (
    event_datetime_bounds,
    event_ends_after,
    event_local_start_date,
    event_occurs_on,
    format_time_range,
    sort_key,
)
from ._types import Event

_WEEKDAY_SHORT_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


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


def event_relevant_for_invitations(
    event: Event,
    tz: tzinfo,
    *,
    moment: datetime,
    lookback_days: int = 0,
) -> bool:
    """Встреча ещё идёт или началась не раньше ``lookback_days`` назад (локально).

    Нужна для списка приглашений: неотвеченные встречи за вчера/позавчера не
    должны пропадать сразу после ``dtend``, пока пользователь не ответил.
    """
    if event_ends_after(event, tz, moment=moment):
        return True
    if lookback_days <= 0:
        return False
    day = event_local_start_date(event, tz)
    if day is None:
        return False
    return day >= moment.date() - timedelta(days=lookback_days)


def collect_pending_invitations(
    events: Sequence[Event],
    login: str,
    tz: tzinfo,
    *,
    now: datetime,
    max_events: int = 20,
    lookback_days: int = 0,
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
        and event_relevant_for_invitations(ev, tz, moment=now, lookback_days=lookback_days)
    ]
    pending.sort(key=lambda ev: sort_key(ev, tz))
    return pending[: max(0, max_events)]


def collect_manageable_events(
    events: Sequence[Event],
    login: str,
    tz: tzinfo,
    *,
    now: datetime,
    max_events: int = 30,
) -> list[Event]:
    """Будущие встречи, где пользователь — участник (есть ATTENDEE-запись).

    Это набор для экрана «Изменить статус»: всё, по чему ещё можно поменять
    решение (включая уже ACCEPTED / DECLINED / TENTATIVE / NEEDS-ACTION).
    Отфильтровываем cancelled и уже завершённые встречи; события без URL не
    показываем — без url мы не сможем обновить PARTSTAT на сервере.
    """
    login_norm = (login or "").strip()
    if not login_norm:
        return []
    manageable = [
        ev
        for ev in events
        if (ev.get("url") or "").strip()
        and not is_cancelled_event(ev)
        and user_partstat(ev, login_norm) is not None
        and event_ends_after(ev, tz, moment=now)
    ]
    manageable.sort(key=lambda ev: sort_key(ev, tz))
    return manageable[: max(0, max_events)]


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
            lines.append(f"<b>{format_upcoming_day_header(day, reference_date)}</b>")
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
