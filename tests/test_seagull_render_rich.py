"""Снимковые тесты Rich Message дайджеста."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from satellite.calendar.stats import calculate_day_stats
from satellite.seagull.render_rich import render_daily_digest_rich
from satellite.seagull.rules import build_seagull_texts

from .conftest import make_event


def test_rich_digest_contains_table_and_details():
    events = [
        make_event("A", "10:00", "11:00"),
        make_event("B", "12:00", "13:00"),
        make_event("C", "14:00", "15:00"),
        make_event("D", "16:00", "17:00"),
    ]
    stats = calculate_day_stats(events, date_label="Сегодня", plan_date=date(2026, 6, 12))
    texts = build_seagull_texts(stats)
    html = render_daily_digest_rich(
        stats,
        texts,
        tz=ZoneInfo("Europe/Moscow"),
    )
    assert "<h2>" in html
    assert "<table>" in html
    assert "<details" in html
    assert "<time datetime=" in html
