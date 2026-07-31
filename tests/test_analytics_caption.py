"""Подпись недельной аналитики."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from satellite.analytics.caption import build_analytics_caption, format_overlap_count_ru
from satellite.analytics.rich_caption import build_analytics_rich_caption
from satellite.calendar.period_stats import (
    AnalyticsDataQuality,
    AnalyticsReport,
    DaySlice,
    WeekSummary,
    workday_options_from_preset,
)


def _week(
    busy: int,
    *,
    start: date,
    overlaps: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
) -> WeekSummary:
    days = tuple(
        DaySlice(
            start + __import__("datetime").timedelta(days=i),
            busy // 5,
            400,
            1,
            overlaps[i],
        )
        for i in range(5)
    )
    return WeekSummary(
        week_start=start,
        days=days,
        total_busy=busy,
        total_free=2800 - busy,
        load_percent=min(100, busy * 100 // 2800),
        total_meetings=5,
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


def _comparison_report(*, current_busy: int, previous_busy: int, trend: str = "flat"):
    start = date(2026, 7, 27)
    return AnalyticsReport(
        reference_date=date(2026, 7, 31),
        current=_week(current_busy, start=start),
        previous=_week(previous_busy, start=date(2026, 7, 20)),
        quarter_weekly_busy=(400,) * 13,
        workday=workday_options_from_preset("10-19"),
        trend=trend,
    )


def test_caption_says_previous_week_was_denser_when_current_is_lighter():
    report = _comparison_report(current_busy=525, previous_busy=750)

    caption = build_analytics_caption(report)

    assert "Прошлая неделя была плотнее на <b>3 ч 45 мин</b> встреч." in caption
    assert "Прошлая неделя была легче" not in caption


def test_caption_says_previous_week_was_lighter_when_current_is_denser():
    report = _comparison_report(current_busy=750, previous_busy=525)

    caption = build_analytics_caption(report)

    assert "Прошлая неделя была легче на <b>3 ч 45 мин</b> встреч." in caption
    assert "Прошлая неделя была плотнее" not in caption


def test_caption_treats_differences_under_thirty_minutes_as_same_load():
    report = _comparison_report(current_busy=600, previous_busy=629)

    caption = build_analytics_caption(report)

    assert "Плановая нагрузка почти как на прошлой неделе." in caption
    assert "План Пн–Пт целиком, включая будущие встречи." in caption


def test_rich_caption_uses_markup_instead_of_printing_legacy_tags():
    report = _comparison_report(current_busy=525, previous_busy=750)

    rich = build_analytics_rich_caption(report)

    assert "&lt;b&gt;" not in rich
    assert "Прошлая неделя была плотнее на <b>3 ч 45 мин</b> встреч." in rich
    assert "За квартал нагрузка <b>держится на одной высоте</b>." in rich


def test_overlap_warning_names_total_and_most_conflicted_day():
    start = date(2026, 7, 27)
    report = AnalyticsReport(
        reference_date=date(2026, 7, 31),
        current=_week(600, start=start, overlaps=(0, 2, 1, 0, 0)),
        previous=_week(600, start=date(2026, 7, 20)),
        quarter_weekly_busy=(600,) * 13,
        workday=workday_options_from_preset("10-19"),
        trend="flat",
    )

    caption = build_analytics_caption(report)
    rich = build_analytics_rich_caption(report)

    expected = "⚠️ <b>3 пересечения встреч</b>; больше всего — во вторник (2 пересечения встреч)."
    assert expected in caption
    assert expected in rich


def test_overlap_warning_is_omitted_when_there_are_no_conflicts():
    report = _comparison_report(current_busy=600, previous_busy=600)

    assert "⚠️" not in build_analytics_caption(report)
    assert "⚠️" not in build_analytics_rich_caption(report)


def test_overlap_count_uses_russian_plural_forms():
    assert format_overlap_count_ru(1) == "1 пересечение встреч"
    assert format_overlap_count_ru(2) == "2 пересечения встреч"
    assert format_overlap_count_ru(5) == "5 пересечений встреч"
    assert format_overlap_count_ru(11) == "11 пересечений встреч"


def test_unverified_partstat_is_disclosed_in_both_captions():
    report = replace(
        _comparison_report(current_busy=600, previous_busy=600),
        quality=AnalyticsDataQuality(unverified_partstat_events=3),
    )

    legacy = build_analytics_caption(report)
    rich = build_analytics_rich_caption(report)

    expected = "Статус участия не удалось проверить для <b>3 событий</b> за 13 недель"
    assert expected in legacy
    assert expected in rich
