"""Подпись недельной аналитики."""

from __future__ import annotations

from datetime import date

from satellite.analytics.caption import build_analytics_caption
from satellite.calendar.period_stats import (
    AnalyticsReport,
    DaySlice,
    WeekSummary,
    workday_options_from_preset,
)


def _week(busy: int, *, start: date) -> WeekSummary:
    days = tuple(
        DaySlice(start + __import__("datetime").timedelta(days=i), busy // 7, 400, 1, 0)
        for i in range(7)
    )
    return WeekSummary(
        week_start=start,
        days=days,
        total_busy=busy,
        total_free=2800 - busy,
        load_percent=min(100, busy * 100 // 2800),
    )


def test_caption_contains_hours_and_trend():
    start = date(2026, 5, 11)
    prev = date(2026, 5, 4)
    report = AnalyticsReport(
        reference_date=date(2026, 5, 14),
        current=_week(1200, start=start),
        previous=_week(600, start=prev),
        quarter_weekly_busy=(400,) * 8 + (500,) * 5,
        workday=workday_options_from_preset("10-19"),
        trend="up",
    )
    cap = build_analytics_caption(report)
    assert "20 ч" in cap or "20ч" in cap.replace(" ", "")
    assert "<b>" in cap
    assert "квартал" in cap.casefold() or "Квартал" in cap
