"""Агрегация недельной аналитики."""

from __future__ import annotations

from datetime import UTC, date, timedelta

from satellite.calendar.event_exclusions import EventExclusionPolicy, EventTitleOverride
from satellite.calendar.period_stats import (
    _quarter_trend,
    build_analytics_report,
    build_week_summary,
    format_week_range_label,
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


def test_week_range_label_uses_both_months_at_month_boundary():
    assert format_week_range_label(date(2026, 7, 27)) == "27 июля – 2 августа"


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


def test_excluded_meetings_do_not_affect_any_report_aggregate():
    ref = date(2026, 5, 14)
    current_mon, _ = week_bounds(ref)
    previous_mon = current_mon - timedelta(weeks=1)
    oldest_mon = current_mon - timedelta(weeks=12)
    included = [
        _caldav_ev("Current", current_mon, 10, 11),
        _caldav_ev("Previous", previous_mon, 11, 13),
        _caldav_ev("Oldest", oldest_mon, 15, 16),
    ]
    excluded = [
        _caldav_ev("Ignore Me", current_mon, 10, 12),
        _caldav_ev("Ignore Me", previous_mon, 11, 15),
        _caldav_ev("Ignore Me", oldest_mon, 14, 18),
    ]
    policy = EventExclusionPolicy([EventTitleOverride(" ignore   me ", excluded=True)])

    expected = build_analytics_report(included, ref, tz=TZ, login=LOGIN)
    actual = build_analytics_report(
        [*included, *excluded],
        ref,
        tz=TZ,
        login=LOGIN,
        exclusion_policy=policy,
    )

    assert actual == expected
    assert actual.current.total_meetings == 1
    assert actual.current.total_overlaps == 0
    assert actual.current.most_conflicted_day is None


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


def test_current_week_includes_future_weekday_events():
    monday = date(2026, 5, 11)
    friday = monday + timedelta(days=4)
    report = build_analytics_report(
        [_caldav_ev("Friday", friday, 10, 12)],
        monday,
        tz=TZ,
        login=LOGIN,
    )

    assert report.current.total_busy == 120
    assert report.current.days[4].meetings_count == 1


def test_duplicate_occurrence_across_calendars_is_counted_once():
    monday = date(2026, 5, 11)
    event = _caldav_ev("Shared", monday, 10, 11)
    event["uid"] = "same-uid"
    copy = {**event, "calendar": "Shared calendar"}

    report = build_analytics_report([event, copy], monday, tz=TZ, login=LOGIN)

    assert report.current.total_busy == 60
    assert report.current.total_meetings == 1
    assert report.current.total_overlaps == 0
    assert report.quality.duplicate_occurrences_dropped == 1


def test_duplicate_prefers_partstat_evidence_over_missing_attendees():
    monday = date(2026, 5, 11)
    unknown = _caldav_ev("Shared", monday, 10, 11)
    unknown["uid"] = "same-uid"
    unknown["attendees"] = []
    pending = {
        **unknown,
        "calendar": "Invitations",
        "attendees": [f"mailto:{LOGIN};PARTSTAT=NEEDS-ACTION"],
    }

    report = build_analytics_report([unknown, pending], monday, tz=TZ, login=LOGIN)

    assert report.current.total_busy == 0
    assert report.current.total_meetings == 0
    assert report.quality.duplicate_occurrences_dropped == 1
    assert report.quality.unverified_partstat_events == 0


def test_recurring_uid_with_different_start_is_two_occurrences():
    monday = date(2026, 5, 11)
    first = _caldav_ev("Daily", monday, 10, 11)
    second = _caldav_ev("Daily", monday + timedelta(days=1), 10, 11)
    first["uid"] = second["uid"] = "series-uid"

    report = build_analytics_report([first, second], monday, tz=TZ, login=LOGIN)

    assert report.current.total_busy == 120
    assert report.current.total_meetings == 2


def test_multiday_occurrence_counts_once_but_occupies_each_day():
    monday = date(2026, 5, 11)
    event = {
        "uid": "overnight",
        "summary": "Release",
        "dtstart": f"{monday.isoformat()}T18:00:00+00:00",
        "dtend": f"{(monday + timedelta(days=1)).isoformat()}T11:00:00+00:00",
        "attendees": [f"mailto:{LOGIN};PARTSTAT=ACCEPTED"],
    }

    report = build_analytics_report([event], monday, tz=TZ, login=LOGIN)

    assert report.current.days[0].busy_minutes == 60
    assert report.current.days[1].busy_minutes == 60
    assert report.current.days[0].meetings_count == 1
    assert report.current.days[1].meetings_count == 1
    assert report.current.total_meetings == 1


def test_missing_partstat_is_counted_and_disclosed():
    monday = date(2026, 5, 11)
    event = _caldav_ev("Own block", monday, 10, 11)
    event["attendees"] = []

    report = build_analytics_report([event], monday, tz=TZ, login=LOGIN)

    assert report.current.total_busy == 60
    assert report.quality.unverified_partstat_events == 1


def test_quarter_trend_handles_zero_baseline_truthfully():
    assert _quarter_trend((0, 0, 0, 0, 60, 60, 60, 60)) == "up"
    assert _quarter_trend((0,) * 8) == "flat"


def test_regular_meeting_during_lunch_counts_as_load():
    monday = date(2026, 5, 11)
    report = build_analytics_report(
        [_caldav_ev("Customer call", monday, 13, 14)],
        monday,
        tz=TZ,
        login=LOGIN,
    )

    assert report.current.total_busy == 60
    assert report.current.total_free == 5 * 480 - 60
