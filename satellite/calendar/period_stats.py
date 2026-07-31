"""Агрегация метрик за рабочую неделю (Пн–Пт) и квартал (без Telegram)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Literal

from .constants import (
    ANALYTICS_WORKDAY_9_18,
    DEFAULT_ANALYTICS_WORKDAY,
)
from .event_exclusions import EventExclusionPolicy
from .event_kinds import filter_meetings_for_analytics
from .events import Event, event_occurs_on, parse_iso, user_partstat
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
    total_meetings: int

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)

    @property
    def total_overlaps(self) -> int:
        """Число пар пересекающихся встреч за рабочую неделю."""
        return sum(day.overlaps_count for day in self.days)

    @property
    def most_conflicted_day(self) -> DaySlice | None:
        """Первый день с максимальным числом пересечений или None."""
        if not self.days:
            return None
        day = max(self.days, key=lambda item: item.overlaps_count)
        return day if day.overlaps_count > 0 else None


@dataclass(frozen=True)
class AnalyticsDataQuality:
    """Observable limitations of the source data used for the report."""

    duplicate_occurrences_dropped: int = 0
    unverified_partstat_events: int = 0


@dataclass(frozen=True)
class AnalyticsReport:
    reference_date: date
    current: WeekSummary
    previous: WeekSummary
    quarter_weekly_busy: tuple[int, ...]
    workday: WorkdayOptions
    trend: Literal["up", "down", "flat"]
    quality: AnalyticsDataQuality = AnalyticsDataQuality()


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


def _stable_time_key(value: object, tz: tzinfo) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return str(value or "")
    if isinstance(parsed, datetime):
        localized = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
        return localized.isoformat()
    return parsed.isoformat()


def event_occurrence_key(event: Event, tz: tzinfo) -> tuple[str, ...] | None:
    """Cross-calendar identity for one expanded occurrence.

    A recurring series deliberately keeps separate occurrences because DTSTART
    and DTEND are part of the key. Missing UID is not guessed from title/time:
    collapsing unrelated meetings would be worse than retaining a duplicate.
    """
    uid = str(event.get("uid") or "").strip().casefold()
    if not uid:
        return None
    return (
        uid,
        _stable_time_key(event.get("dtstart"), tz),
        _stable_time_key(event.get("dtend"), tz),
    )


def _duplicate_information_score(event: Event, login: str | None) -> tuple[int, int, int]:
    status = user_partstat(event, login or "") if login else None
    status_priority = {
        "DECLINED": 5,
        "NEEDS-ACTION": 4,
        "DELEGATED": 4,
        "TENTATIVE": 3,
        "ACCEPTED": 2,
    }.get(status or "", 0)
    attendees = event.get("attendees") or []
    return status_priority, len(attendees), 1 if event.get("status") else 0


def deduplicate_event_occurrences(
    events: Sequence[Event], tz: tzinfo, *, login: str | None = None
) -> tuple[list[Event], int]:
    positions: dict[tuple[str, ...], int] = {}
    unique: list[Event] = []
    dropped = 0
    for event in events:
        key = event_occurrence_key(event, tz)
        if key is not None and key in positions:
            dropped += 1
            index = positions[key]
            if _duplicate_information_score(event, login) > _duplicate_information_score(
                unique[index], login
            ):
                unique[index] = event
            continue
        if key is not None:
            positions[key] = len(unique)
        unique.append(event)
    return unique, dropped


def _event_count_key(event: Event, tz: tzinfo) -> tuple[object, ...]:
    return event_occurrence_key(event, tz) or ("object", id(event))


def _day_slice(
    events: Sequence[Event],
    plan_date: date,
    *,
    tz: tzinfo,
    login: str,
    options: WorkdayOptions,
    exclusion_policy: EventExclusionPolicy | None = None,
) -> DaySlice:
    day_events = [ev for ev in events if event_occurs_on(ev, plan_date, tz)]
    meetings = filter_meetings_for_analytics(
        day_events,
        tz=tz,
        login=login,
        exclusion_policy=exclusion_policy,
    )
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
    exclusion_policy: EventExclusionPolicy | None = None,
) -> WeekSummary:
    unique_events, _ = deduplicate_event_occurrences(events, tz, login=login)
    days = tuple(
        _day_slice(
            unique_events,
            week_start + timedelta(days=offset),
            tz=tz,
            login=login,
            options=options,
            exclusion_policy=exclusion_policy,
        )
        for offset in range(WORK_WEEK_DAYS)
    )
    total_busy = sum(d.busy_minutes for d in days)
    total_free = sum(d.free_minutes for d in days)
    capacity = _effective_week_capacity(options)
    weekday_events: dict[tuple[object, ...], Event] = {}
    for event in unique_events:
        if not any(
            event_occurs_on(event, week_start + timedelta(days=offset), tz)
            for offset in range(WORK_WEEK_DAYS)
        ):
            continue
        if filter_meetings_for_analytics(
            [event],
            tz=tz,
            login=login,
            exclusion_policy=exclusion_policy,
        ):
            weekday_events[_event_count_key(event, tz)] = event
    return WeekSummary(
        week_start=week_start,
        days=days,
        total_busy=total_busy,
        total_free=total_free,
        load_percent=_load_percent(total_busy, capacity),
        total_meetings=len(weekday_events),
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
        return "up" if last_avg > 0 else "flat"
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
    exclusion_policy: EventExclusionPolicy | None = None,
) -> AnalyticsReport:
    opts = options or WorkdayOptions()
    unique_events, duplicates_dropped = deduplicate_event_occurrences(events, tz, login=login)
    current_start, _ = week_bounds(reference_date)
    previous_start = current_start - timedelta(days=7)
    quarter_starts = [
        current_start - timedelta(days=7 * offset) for offset in range(QUARTER_WEEKS - 1, -1, -1)
    ]
    analytics_dates = tuple(
        week_start + timedelta(days=day_offset)
        for week_start in quarter_starts
        for day_offset in range(WORK_WEEK_DAYS)
    )
    quarter_busy = tuple(
        build_week_summary(
            unique_events,
            ws,
            tz=tz,
            login=login,
            options=opts,
            exclusion_policy=exclusion_policy,
        ).total_busy
        for ws in quarter_starts
    )
    return AnalyticsReport(
        reference_date=reference_date,
        current=build_week_summary(
            unique_events,
            current_start,
            tz=tz,
            login=login,
            options=opts,
            exclusion_policy=exclusion_policy,
        ),
        previous=build_week_summary(
            unique_events,
            previous_start,
            tz=tz,
            login=login,
            options=opts,
            exclusion_policy=exclusion_policy,
        ),
        quarter_weekly_busy=quarter_busy,
        workday=opts,
        trend=_quarter_trend(quarter_busy),
        quality=AnalyticsDataQuality(
            duplicate_occurrences_dropped=duplicates_dropped,
            unverified_partstat_events=sum(
                1
                for event in unique_events
                if any(event_occurs_on(event, plan_date, tz) for plan_date in analytics_dates)
                and user_partstat(event, login) is None
                and filter_meetings_for_analytics(
                    [event],
                    tz=tz,
                    login=login,
                    exclusion_policy=exclusion_policy,
                )
            ),
        ),
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
    start_month = _MONTH_GENITIVE_RU[week_start.month - 1]
    if week_start.month == end.month:
        return f"{week_start.day}–{end.day} {start_month}"
    end_month = _MONTH_GENITIVE_RU[end.month - 1]
    return f"{week_start.day} {start_month} – {end.day} {end_month}"
