"""Агрегация недельной аналитики."""

from __future__ import annotations

from datetime import UTC, date, timedelta

from satellite.calendar.event_exclusions import EventExclusionPolicy, EventTitleOverride
from satellite.calendar.period_stats import (
    build_analytics_report,
    build_week_summary,
    week_bounds,
    workday_options_from_preset,
)
from satellite.calendar.stats import WorkdayOptions

TZ = UTC
LOGIN = "user@test.ru"


def _caldav_ev(title: str, day: date, start_h: int, end_h: int) -> dict:
    start = f"{day.isoformat()}T{start_h:02d}:00:00+00:00"
    end = f"{day.isoformat()}T{end_h:02d}:00:00+00:00"
    return {
        "summary": title,
        "dtstart": start,
        "dtend": end,
        "attendees": [f"mailto:{LOGIN};PARTSTAT=ACCEPTED"],
    }


def test_week_bounds_monday():
    # 2026-05-14 is Thursday
    ref = date(2026, 5, 14)
    mon, sun = week_bounds(ref)
    assert mon == date(2026, 5, 11)
    assert sun == date(2026, 5, 17)


def test_build_week_summary_busy_and_free():
    mon = date(2026, 5, 11)
    events = [_caldav_ev("A", mon, 10, 11), _caldav_ev("B", mon, 15, 16)]
    opts = WorkdayOptions()
    summary = build_week_summary(events, mon, tz=TZ, login=LOGIN, options=opts)
    assert summary.total_busy == 120
    assert summary.load_percent > 0
    assert len(summary.days) == 5


def test_weekend_meetings_excluded_from_summary():
    mon = date(2026, 5, 11)
    sat = mon + timedelta(days=5)
    sun = mon + timedelta(days=6)
    events = [
        _caldav_ev("Weekday", mon, 10, 12),
        _caldav_ev("Saturday", sat, 10, 14),
        _caldav_ev("Sunday", sun, 10, 14),
    ]
    summary = build_week_summary(events, mon, tz=TZ, login=LOGIN, options=WorkdayOptions())
    assert summary.total_busy == 120
    assert summary.days[0].busy_minutes == 120
    assert summary.days[4].busy_minutes == 0


def test_analytics_report_quarter_has_13_points():
    ref = date(2026, 5, 14)
    mon, _ = week_bounds(ref)
    events = [_caldav_ev("M", mon, 10, 12)]
    report = build_analytics_report(events, ref, tz=TZ, login=LOGIN)
    assert len(report.quarter_weekly_busy) == 13
    assert report.current.total_busy == 120
    assert report.trend in {"up", "down", "flat"}


def test_workday_preset_9_18():
    opts = workday_options_from_preset("9-18")
    assert opts.workday_start == "09:00"
    assert opts.workday_end == "18:00"


def test_previous_week_comparison():
    ref = date(2026, 5, 14)
    cur_mon, _ = week_bounds(ref)
    prev_mon = cur_mon - timedelta(days=7)
    events = [
        _caldav_ev("Heavy", cur_mon, 10, 18),
        _caldav_ev("Light", prev_mon, 10, 11),
    ]
    report = build_analytics_report(events, ref, tz=TZ, login=LOGIN)
    assert report.current.total_busy > report.previous.total_busy


def test_explicit_exclusion_is_applied_to_current_and_quarter_stats():
    ref = date(2026, 5, 14)
    current_mon, _ = week_bounds(ref)
    oldest_mon = current_mon - timedelta(weeks=12)
    events = [
        _caldav_ev("Weekly Placeholder", current_mon, 10, 12),
        _caldav_ev("Weekly Placeholder", oldest_mon, 10, 13),
    ]
    policy = EventExclusionPolicy([EventTitleOverride(" weekly   placeholder ", excluded=True)])

    report = build_analytics_report(
        events,
        ref,
        tz=TZ,
        login=LOGIN,
        exclusion_policy=policy,
    )

    assert report.current.total_busy == 0
    assert report.current.days[0].meetings_count == 0
    assert report.quarter_weekly_busy == (0,) * 13


def test_explicit_include_counts_builtin_system_title_in_analytics():
    ref = date(2026, 5, 14)
    current_mon, _ = week_bounds(ref)
    policy = EventExclusionPolicy([EventTitleOverride("Focus Time", excluded=False)])

    report = build_analytics_report(
        [_caldav_ev("focus time", current_mon, 10, 11)],
        ref,
        tz=TZ,
        login=LOGIN,
        exclusion_policy=policy,
    )

    assert report.current.total_busy == 60
    assert report.current.days[0].meetings_count == 1
