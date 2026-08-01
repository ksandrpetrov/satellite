"""PNG-карточка недельной аналитики."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import date
from pathlib import Path

from PIL import Image, ImageStat

from satellite.analytics.render_card import render_analytics_card
from satellite.calendar.period_stats import (
    AnalyticsDataQuality,
    AnalyticsReport,
    DaySlice,
    WeekSummary,
    workday_options_from_preset,
)
from satellite.visual_cards import base as vc


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
        total_meetings=10,
    )
    previous = WeekSummary(
        week_start=start - __import__("datetime").timedelta(days=7),
        days=days,
        total_busy=300,
        total_free=3000,
        load_percent=20,
        total_meetings=10,
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
    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (1200, 1920)
        assert image.mode == "RGB"


def test_default_card_is_light_with_one_dark_anchor():
    png = render_analytics_card(_report())
    with Image.open(io.BytesIO(png)).convert("L") as image:
        histogram = image.histogram()
        pixel_count = image.width * image.height
        dark_ratio = sum(histogram[:64]) / pixel_count
        average_luminance = ImageStat.Stat(image).mean[0]

    assert average_luminance >= 170
    assert dark_ratio < 0.30


def test_render_with_overlap_summary_produces_valid_png():
    report = _report()
    first_day = report.current.days[0]
    days = (
        DaySlice(
            first_day.plan_date,
            first_day.busy_minutes,
            first_day.free_minutes,
            first_day.meetings_count,
            2,
        ),
        *report.current.days[1:],
    )
    current = WeekSummary(
        week_start=report.current.week_start,
        days=days,
        total_busy=report.current.total_busy,
        total_free=report.current.total_free,
        load_percent=report.current.load_percent,
        total_meetings=report.current.total_meetings,
    )
    report = AnalyticsReport(
        reference_date=report.reference_date,
        current=current,
        previous=report.previous,
        quarter_weekly_busy=report.quarter_weekly_busy,
        workday=report.workday,
        trend=report.trend,
    )

    png = render_analytics_card(report)

    assert len(png) > 5000
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_selected_fonts_cover_cyrillic_arrows_and_dashes():
    fonts = (
        (vc.FONT_DISPLAY_PATH, vc.load_font(24, family="display")),
        (vc.FONT_MONO_REGULAR_PATH, vc.load_font(24, family="mono")),
        (vc.FONT_MONO_BOLD_PATH, vc.load_font(24, family="mono", bold=True)),
    )
    for expected_path, font in fonts:
        assert expected_path.is_file()
        assert Path(font.path).resolve() == expected_path.resolve()
        assert vc._font_supports_required_glyphs(font)


def test_render_handles_zero_load_and_zero_quarter():
    report = _report()
    days = tuple(
        replace(day, busy_minutes=0, free_minutes=480, meetings_count=0)
        for day in report.current.days
    )
    current = replace(
        report.current,
        days=days,
        total_busy=0,
        total_free=2400,
        load_percent=0,
        total_meetings=0,
    )
    empty = replace(
        report,
        current=current,
        quarter_weekly_busy=(0,) * 13,
    )

    png = render_analytics_card(empty)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_handles_full_load_overlaps_and_quality_warning():
    report = _report()
    days = tuple(
        replace(
            day,
            busy_minutes=480,
            free_minutes=0,
            meetings_count=12,
            overlaps_count=3,
        )
        for day in report.current.days
    )
    current = replace(
        report.current,
        days=days,
        total_busy=2400,
        total_free=0,
        load_percent=100,
        total_meetings=60,
    )
    dense = replace(
        report,
        current=current,
        quarter_weekly_busy=tuple(index * 180 for index in range(13)),
        trend="up",
        quality=AnalyticsDataQuality(unverified_partstat_events=120),
    )

    png = render_analytics_card(dense)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
