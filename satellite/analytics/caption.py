"""Подпись к PNG недельной аналитики (Telegram HTML)."""

from __future__ import annotations

from ..calendar.period_stats import AnalyticsReport
from ..messages_ru import format_duration_ru
from . import templates as t


def _week_tone(load_percent: int) -> str:
    if load_percent <= 25:
        return t.WEEK_LIGHT
    if load_percent <= 50:
        return t.WEEK_NORMAL
    if load_percent <= 75:
        return t.WEEK_DENSE
    return t.WEEK_STORM


def _compare_line(report: AnalyticsReport) -> str:
    delta_min = report.current.total_busy - report.previous.total_busy
    if abs(delta_min) < 30:
        return t.COMPARE_SAME
    delta_str = format_duration_ru(abs(delta_min))
    if delta_min > 0:
        return t.COMPARE_LIGHTER.format(delta=delta_str)
    return t.COMPARE_BUSIER.format(delta=delta_str)


def _trend_line(report: AnalyticsReport) -> str:
    if report.trend == "up":
        return t.TREND_UP
    if report.trend == "down":
        return t.TREND_DOWN
    return t.TREND_FLAT


def build_analytics_caption(report: AnalyticsReport) -> str:
    busy = format_duration_ru(report.current.total_busy)
    free = format_duration_ru(report.current.total_free)
    lines = [
        _week_tone(report.current.load_percent),
        t.SUMMARY_LINE.format(
            busy=busy,
            free=free,
            load=report.current.load_percent,
            prev_load=report.previous.load_percent,
        ),
        _compare_line(report),
        _trend_line(report),
    ]
    return "\n".join(lines)
