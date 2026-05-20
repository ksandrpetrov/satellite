"""PNG-карточка недельной аналитики."""

from __future__ import annotations

from datetime import date

from satellite.analytics.render_card import render_analytics_card
from satellite.calendar.period_stats import (
    AnalyticsReport,
    DaySlice,
    WeekSummary,
    workday_options_from_preset,
)


def _report() -> AnalyticsReport:
    start = date(2026, 5, 11)
    days = tuple(
        DaySlice(
            start + __import__("datetime").timedelta(days=i),
            busy_minutes=60 + i * 10,
            free_minutes=400,
            meetings_count=2,
            overlaps_count=0,
        )
        for i in range(5)
    )
    current = WeekSummary(
        week_start=start,
        days=days,
        total_busy=sum(d.busy_minutes for d in days),
        total_free=sum(d.free_minutes for d in days),
        load_percent=35,
    )
    previous = WeekSummary(
        week_start=start - __import__("datetime").timedelta(days=7),
        days=days,
        total_busy=300,
        total_free=3000,
        load_percent=20,
    )
    return AnalyticsReport(
        reference_date=date(2026, 5, 14),
        current=current,
        previous=previous,
        quarter_weekly_busy=tuple(300 + i * 20 for i in range(13)),
        workday=workday_options_from_preset("10-19"),
        trend="flat",
    )


def test_render_produces_valid_png():
    png = render_analytics_card(_report())
    assert len(png) > 5000
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
