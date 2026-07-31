"""Подпись к PNG недельной аналитики (Telegram HTML)."""

from __future__ import annotations

from typing import Literal

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


_CompareKind = Literal["same", "previous_lighter", "previous_denser"]

_CONFLICT_DAY_LABELS = (
    "в понедельник",
    "во вторник",
    "в среду",
    "в четверг",
    "в пятницу",
)


def _comparison(report: AnalyticsReport) -> tuple[_CompareKind, str | None]:
    delta_min = report.current.total_busy - report.previous.total_busy
    if abs(delta_min) < 30:
        return "same", None
    delta_str = format_duration_ru(abs(delta_min))
    if delta_min > 0:
        return "previous_lighter", delta_str
    return "previous_denser", delta_str


def _compare_line(report: AnalyticsReport) -> str:
    kind, delta = _comparison(report)
    if kind == "same":
        return t.COMPARE_SAME
    assert delta is not None
    if kind == "previous_lighter":
        return t.COMPARE_PREVIOUS_LIGHTER.format(delta=delta)
    return t.COMPARE_PREVIOUS_DENSER.format(delta=delta)


def _trend_line(report: AnalyticsReport) -> str:
    if report.trend == "up":
        return t.TREND_UP
    if report.trend == "down":
        return t.TREND_DOWN
    return t.TREND_FLAT


def format_overlap_count_ru(count: int) -> str:
    value = max(0, int(count))
    n = value % 100
    n1 = value % 10
    if 11 <= n <= 19:
        word = "пересечений встреч"
    elif n1 == 1:
        word = "пересечение встреч"
    elif 2 <= n1 <= 4:
        word = "пересечения встреч"
    else:
        word = "пересечений встреч"
    return f"{value} {word}"


def format_event_count_ru(count: int) -> str:
    value = max(0, int(count))
    n = value % 100
    n1 = value % 10
    if 11 <= n <= 19:
        word = "событий"
    elif n1 == 1:
        word = "событие"
    elif 2 <= n1 <= 4:
        word = "событий"
    else:
        word = "событий"
    return f"{value} {word}"


def _quality_line(report: AnalyticsReport) -> str | None:
    count = report.quality.unverified_partstat_events
    if count <= 0:
        return None
    return t.QUALITY_UNVERIFIED.format(count=format_event_count_ru(count))


def _overlap_details(report: AnalyticsReport) -> tuple[str, str, str] | None:
    day = report.current.most_conflicted_day
    if day is None:
        return None
    weekday = day.plan_date.weekday()
    day_label = _CONFLICT_DAY_LABELS[weekday] if weekday < 5 else day.plan_date.strftime("%d.%m")
    return (
        format_overlap_count_ru(report.current.total_overlaps),
        day_label,
        format_overlap_count_ru(day.overlaps_count),
    )


def _overlaps_line(report: AnalyticsReport) -> str | None:
    details = _overlap_details(report)
    if details is None:
        return None
    count, day_label, day_count = details
    return t.OVERLAPS_LINE.format(
        count=count,
        day=day_label,
        day_count=day_count,
    )


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
        t.SCOPE_LINE,
    ]
    overlaps = _overlaps_line(report)
    if overlaps is not None:
        lines.append(overlaps)
    quality = _quality_line(report)
    if quality is not None:
        lines.append(quality)
    return "\n".join(lines)
