"""Юнит-тесты на выбор текстов «чайки» по DayCalendarStats."""

from __future__ import annotations

from datetime import date

from satellite.calendar.stats import DayCalendarStats
from satellite.seagull import templates as t
from satellite.seagull.rules import build_seagull_texts


def _stats(**overrides) -> DayCalendarStats:
    defaults: dict = dict(
        date_label="Сегодня",
        plan_date=date(2026, 5, 11),
        events=tuple(),
        meetings_count=0,
        first_meeting_start=None,
        last_meeting_end=None,
        busy_minutes=0,
        free_minutes=480,
        overlaps_count=0,
    )
    defaults.update(overrides)
    return DayCalendarStats(**defaults)


# --- main по busyMinutes (5.1) ----------------------------------------------


def test_main_empty_when_no_busy():
    texts = build_seagull_texts(_stats(busy_minutes=0))
    assert texts.main == t.MAIN_EMPTY


def test_main_light_for_120_minutes():
    texts = build_seagull_texts(
        _stats(
            busy_minutes=120,
            meetings_count=2,
            first_meeting_start="10:00",
            last_meeting_end="12:00",
        )
    )
    assert texts.main == t.MAIN_LIGHT


def test_main_normal_at_upper_bound():
    texts = build_seagull_texts(_stats(busy_minutes=240, meetings_count=4))
    assert texts.main == t.MAIN_NORMAL


def test_main_dense_at_upper_bound():
    texts = build_seagull_texts(_stats(busy_minutes=360, meetings_count=6))
    assert texts.main == t.MAIN_DENSE


def test_main_storm_above_six_hours():
    texts = build_seagull_texts(_stats(busy_minutes=400, meetings_count=8))
    assert texts.main == t.MAIN_STORM


# --- overlaps (5.4) ---------------------------------------------------------


def test_overlaps_none_with_meetings():
    texts = build_seagull_texts(
        _stats(
            busy_minutes=60, meetings_count=1, first_meeting_start="11:00", last_meeting_end="12:00"
        )
    )
    assert texts.overlaps == t.OVERLAP_NONE


def test_overlaps_one():
    texts = build_seagull_texts(
        _stats(
            busy_minutes=120,
            meetings_count=2,
            overlaps_count=1,
            first_meeting_start="10:00",
            last_meeting_end="11:30",
        )
    )
    assert texts.overlaps == t.OVERLAP_ONE


def test_overlaps_many():
    texts = build_seagull_texts(
        _stats(
            busy_minutes=180,
            meetings_count=3,
            overlaps_count=3,
            first_meeting_start="10:00",
            last_meeting_end="12:00",
        )
    )
    assert texts.overlaps == t.OVERLAP_MANY


def test_overlaps_omitted_when_no_meetings():
    texts = build_seagull_texts(_stats())
    assert texts.overlaps is None


# --- контракт SeagullTexts: только main + overlaps ---------------------------


def test_seagull_texts_contract_is_minimal():
    """Удалены поля 5.2–5.7; остаются только main и overlaps."""
    texts = build_seagull_texts(
        _stats(
            busy_minutes=60,
            meetings_count=1,
            first_meeting_start="11:00",
            last_meeting_end="12:00",
        )
    )
    assert not hasattr(texts, "first_meeting")
    assert not hasattr(texts, "last_meeting")
    assert not hasattr(texts, "lunch")
    assert not hasattr(texts, "meetings_count")
    assert not hasattr(texts, "free_slot")
