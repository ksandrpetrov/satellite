"""Юнит-тесты на расчёт ``DayCalendarStats``.

Покрытие основных продуктовых сценариев (busy/free/overlaps + клиппинг к
рабочему дню). Тесты обедных метрик, фокус-слотов и back-to-back блоков
удалены вместе с соответствующими полями ``DayCalendarStats``.

Все события строятся через ``NormalizedEvent`` напрямую: ``calculate_day_stats``
больше не принимает CalDAV-словари, чтобы у нормализации был один путь
(``normalize_caldav_event``), а юнит-тесты — выражали состояние календаря в
минутах от полуночи без посредников.
"""

from __future__ import annotations

from datetime import date

import pytest

from satellite.calendar.stats import (
    DEFAULT_LUNCH_END,
    DEFAULT_LUNCH_START,
    DEFAULT_WORKDAY_END,
    DEFAULT_WORKDAY_START,
    NormalizedEvent,
    WorkdayOptions,
    calculate_day_stats,
)
from satellite.messages_ru import format_duration_ru

from .conftest import make_event

_PD = date(2026, 5, 11)


# 1. Пустой день -------------------------------------------------------------


def test_empty_day_has_no_meetings_and_only_lunch_subtracted():
    stats = calculate_day_stats([], date_label="Сегодня", plan_date=_PD)
    assert stats.meetings_count == 0
    assert stats.first_meeting_start is None
    assert stats.last_meeting_end is None
    assert stats.busy_minutes == 0
    # Эффективный рабочий день: 540 − 60 = 480 минут = 8ч.
    assert stats.free_minutes == 480
    assert stats.overlaps_count == 0


# 2. Одна встреча ------------------------------------------------------------


def test_single_meeting_matches_section_12_example():
    stats = calculate_day_stats(
        [make_event("SocServ | QA Captains Weekly", "11:00", "12:00")],
        date_label="Сегодня",
        plan_date=_PD,
    )
    assert stats.meetings_count == 1
    assert stats.first_meeting_start == "11:00"
    assert stats.last_meeting_end == "12:00"
    assert stats.busy_minutes == 60
    # workday 540, lunch 60, busy 60 → free = 420 = 7ч.
    assert stats.free_minutes == 420
    assert format_duration_ru(stats.free_minutes) == "7 ч"
    assert stats.overlaps_count == 0


# 3. Несколько встреч без пересечений ----------------------------------------


def test_multiple_non_overlapping_meetings():
    events = [
        make_event("A", "10:00", "10:30"),
        make_event("B", "11:00", "11:30"),
        make_event("C", "15:00", "15:30"),
    ]
    stats = calculate_day_stats(events, date_label="Сегодня", plan_date=_PD)
    assert stats.meetings_count == 3
    assert stats.busy_minutes == 90
    assert stats.overlaps_count == 0
    assert stats.first_meeting_start == "10:00"
    assert stats.last_meeting_end == "15:30"


# 4. Пересекающиеся встречи --------------------------------------------------


def test_overlapping_meetings_do_not_double_count_busy():
    # 10:00–11:00 и 10:30–11:30 → занято 90 мин, не 120 (мердж интервалов).
    events = [
        make_event("A", "10:00", "11:00"),
        make_event("B", "10:30", "11:30"),
    ]
    stats = calculate_day_stats(events, date_label="Сегодня", plan_date=_PD)
    assert stats.busy_minutes == 90
    assert stats.overlaps_count == 1


def test_three_mutually_overlapping_meetings_have_three_pairs():
    events = [
        make_event("A", "10:00", "11:00"),
        make_event("B", "10:30", "11:30"),
        make_event("C", "10:45", "12:00"),
    ]
    stats = calculate_day_stats(events, date_label="Сегодня", plan_date=_PD)
    assert stats.overlaps_count == 3
    # Все три сливаются в 10:00–12:00 (120 мин).
    assert stats.busy_minutes == 120


# 5. Клиппинг к рабочему дню -------------------------------------------------


def test_meeting_before_workday_clipped():
    # 09:30–10:30: внутрь рабочего дня попадают только 30 минут.
    stats = calculate_day_stats(
        [make_event("Early", "09:30", "10:30")],
        date_label="Сегодня",
        plan_date=_PD,
    )
    assert stats.busy_minutes == 30
    assert stats.first_meeting_start == "09:30"


def test_meeting_after_workday_clipped():
    # 18:30–20:00: внутрь рабочего дня попадают только 30 минут (18:30–19:00).
    stats = calculate_day_stats(
        [make_event("Late", "18:30", "20:00")],
        date_label="Сегодня",
        plan_date=_PD,
    )
    assert stats.busy_minutes == 30
    assert stats.last_meeting_end == "20:00"


# 6. Спецслучаи нормализации -------------------------------------------------


def test_cancelled_events_are_ignored():
    stats = calculate_day_stats(
        [
            make_event("Real", "10:00", "11:00"),
            make_event("Off", "12:00", "13:00", is_cancelled=True),
        ],
        date_label="Сегодня",
        plan_date=_PD,
    )
    assert stats.meetings_count == 1
    assert stats.busy_minutes == 60


def test_zero_or_inverted_events_are_dropped():
    # end <= start не должен попасть в метрики (защита от мусора).
    bad = NormalizedEvent(title="zero", start_minutes=600, end_minutes=600)
    stats = calculate_day_stats(
        [bad, make_event("Ok", "11:00", "12:00")],
        date_label="Сегодня",
        plan_date=_PD,
    )
    assert stats.meetings_count == 1
    assert stats.busy_minutes == 60


# 7. Форматирование длительности (см. test_messages для углового) ------------


def test_format_duration_ru_known_values():
    assert format_duration_ru(0) == "0 мин"
    assert format_duration_ru(30) == "30 мин"
    assert format_duration_ru(60) == "1 ч"
    assert format_duration_ru(90) == "1 ч 30 мин"
    assert format_duration_ru(480) == "8 ч"


# 8. WorkdayOptions ----------------------------------------------------------


def test_workday_options_validate_rejects_inverted_workday():
    with pytest.raises(ValueError):
        WorkdayOptions(workday_start="19:00", workday_end="10:00").to_minutes()


def test_defaults_match_tz_spec():
    assert DEFAULT_WORKDAY_START == "10:00"
    assert DEFAULT_WORKDAY_END == "19:00"
    assert DEFAULT_LUNCH_START == "13:00"
    assert DEFAULT_LUNCH_END == "14:00"
