"""Агрегация метрик за рабочую неделю (Пн–Пт) и квартал (без Telegram)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta, tzinfo
from typing import Literal

from .constants import (
    ANALYTICS_WORKDAY_9_18,
    DEFAULT_ANALYTICS_WORKDAY,
)
from .event_kinds import filter_meetings_for_analytics
from .events import Event, event_occurs_on
from .stats import WorkdayOptions, calculate_day_stats, normalize_caldav_event

QUARTER_WEEKS = 13
WORK_WEEK_DAYS = 5  # Пн–Пт; выходные не входят в аналитику


@dataclass(frozen=True)
class DaySlice:
    plan_date: date
    busy_minutes: int
    free_minutes: int
    meetings_count: int
    overlaps_count: int


@dataclass(frozen=True)
class WeekSummary:
    week_start: date
    days: tuple[DaySlice, ...]
    total_busy: int
    total_free: int
    load_percent: int

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)


@dataclass(frozen=True)
class AnalyticsReport:
    reference_date: date
    current: WeekSummary
    previous: WeekSummary
    quarter_weekly_busy: tuple[int, ...]
    workday: WorkdayOptions
    trend: Literal["up", "down", "flat"]


def week_bounds(reference_date: date) -> tuple[date, date]:
    """Понедельник–воскресенье календарной недели, содержащей reference_date."""
    monday = reference_date - timedelta(days=reference_date.weekday())
    return monday, monday + timedelta(days=6)


def workday_options_from_preset(preset: str | None) -> WorkdayOptions:
    key = (preset or DEFAULT_ANALYTICS_WORKDAY).strip()
    if key == ANALYTICS_WORKDAY_9_18:
        return WorkdayOptions(workday_start="09:00", workday_end="18:00")
    return WorkdayOptions(workday_start="10:00", workday_end="19:00")


def _effective_week_capacity(options: WorkdayOptions) -> int:
    return options.to_minutes().effective_minutes * WORK_WEEK_DAYS


def _load_percent(total_busy: int, capacity: int) -> int:
    if capacity <= 0:
        return 0
    return min(100, max(0, round(100 * total_busy / capacity)))


def _day_slice(
    events: Sequence[Event],
    plan_date: date,
    *,
    tz: tzinfo,
    login: str,
    options: WorkdayOptions,
) -> DaySlice:
    day_events = [ev for ev in events if event_occurs_on(ev, plan_date, tz)]
    meetings = filter_meetings_for_analytics(day_events, tz=tz, login=login)
    normalized = []
    for ev in meetings:
        ne = normalize_caldav_event(ev, plan_date, tz, login=login)
        if ne is not None and not ne.is_cancelled and not ne.is_pending and not ne.is_tentative:
            normalized.append(ne)
    stats = calculate_day_stats(
        normalized,
        date_label="",
        plan_date=plan_date,
        options=options,
    )
    return DaySlice(
        plan_date=plan_date,
        busy_minutes=stats.busy_minutes,
        free_minutes=stats.free_minutes,
        meetings_count=stats.meetings_count,
        overlaps_count=stats.overlaps_count,
    )


def build_week_summary(
    events: Sequence[Event],
    week_start: date,
    *,
    tz: tzinfo,
    login: str,
    options: WorkdayOptions,
) -> WeekSummary:
    days = tuple(
        _day_slice(events, week_start + timedelta(days=offset), tz=tz, login=login, options=options)
        for offset in range(WORK_WEEK_DAYS)
    )
    total_busy = sum(d.busy_minutes for d in days)
    total_free = sum(d.free_minutes for d in days)
    capacity = _effective_week_capacity(options)
    return WeekSummary(
        week_start=week_start,
        days=days,
        total_busy=total_busy,
        total_free=total_free,
        load_percent=_load_percent(total_busy, capacity),
    )


def _quarter_trend(weekly_busy: Sequence[int]) -> Literal["up", "down", "flat"]:
    """Сравнивает среднее последних 4 недель с предыдущими 4 (из 13 точек)."""
    if len(weekly_busy) < 8:
        return "flat"
    prev_four = weekly_busy[-8:-4]
    last_four = weekly_busy[-4:]
    prev_avg = sum(prev_four) / len(prev_four)
    last_avg = sum(last_four) / len(last_four)
    if prev_avg <= 0:
        return "flat"
    delta_ratio = (last_avg - prev_avg) / prev_avg
    if delta_ratio > 0.08:
        return "up"
    if delta_ratio < -0.08:
        return "down"
    return "flat"


def build_analytics_report(
    events: Sequence[Event],
    reference_date: date,
    *,
    tz: tzinfo,
    login: str,
    options: WorkdayOptions | None = None,
) -> AnalyticsReport:
    opts = options or WorkdayOptions()
    current_start, _ = week_bounds(reference_date)
    previous_start = current_start - timedelta(days=7)
    quarter_starts = [
        current_start - timedelta(days=7 * offset) for offset in range(QUARTER_WEEKS - 1, -1, -1)
    ]
    quarter_busy = tuple(
        build_week_summary(events, ws, tz=tz, login=login, options=opts).total_busy
        for ws in quarter_starts
    )
    return AnalyticsReport(
        reference_date=reference_date,
        current=build_week_summary(events, current_start, tz=tz, login=login, options=opts),
        previous=build_week_summary(events, previous_start, tz=tz, login=login, options=opts),
        quarter_weekly_busy=quarter_busy,
        workday=opts,
        trend=_quarter_trend(quarter_busy),
    )


_MONTH_GENITIVE_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_week_range_label(week_start: date) -> str:
    end = week_start + timedelta(days=6)
    month = _MONTH_GENITIVE_RU[end.month - 1]
    if week_start.month == end.month:
        return f"{week_start.day}–{end.day} {month}"
    end_month = _MONTH_GENITIVE_RU[end.month - 1]
    return f"{week_start.day} {month} – {end.day} {end_month}"
