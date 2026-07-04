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


def test_rich_digest_stats_table_speaks_type_and_time():
    """Таблица метрик — «Тип / Время»; счётчик встреч не дублируется строкой.

    Абстрактные «Показатель / Значение» читались как тех-жаргон, а строка
    «Встреч — 4» в колонке времени выглядела ошибкой: количество уже есть
    в заголовке расписания («Расписание — N встреч»).
    """
    events = [
        make_event("A", "10:00", "11:00"),
        make_event("B", "12:00", "13:00"),
        make_event("C", "14:00", "15:00"),
        make_event("D", "16:00", "17:00"),
    ]
    stats = calculate_day_stats(events, date_label="Сегодня", plan_date=date(2026, 6, 12))
    texts = build_seagull_texts(stats)
    html = render_daily_digest_rich(stats, texts, tz=ZoneInfo("Europe/Moscow"))
    assert "<th>Тип</th><th>Время</th>" in html
    assert "👨‍💻 Занято" in html
    assert "🧘 Свободно" in html
    assert "Показатель" not in html
    assert "Значение" not in html
    assert "<td>Встреч</td>" not in html
    assert "— 4 встреч" in html  # количество живёт в заголовке расписания


def test_rich_digest_main_quote_has_no_author_cite():
    """Прогноз уже говорит от лица Чайки — подпись <cite> в pull_quote лишняя."""
    events = [make_event(f"M{i}", f"{10 + i:02d}:00", f"{10 + i:02d}:30") for i in range(10)]
    stats = calculate_day_stats(events, date_label="Сегодня", plan_date=date(2026, 6, 12))
    texts = build_seagull_texts(stats)
    html = render_daily_digest_rich(stats, texts, tz=ZoneInfo("Europe/Moscow"))
    assert "Чайка напрягла крылья" in html
    assert "<cite>Чайка</cite>" not in html


def test_rich_event_with_conference_url_renders_join_link():
    meet = "https://meet.google.com/abc-defg-hij"
    stats = calculate_day_stats(
        [
            make_event(
                "Weekly sync",
                "11:00",
                "12:00",
                location="A1",
                conference_url=meet,
            )
        ],
        date_label="Сегодня",
        plan_date=date(2026, 6, 12),
    )
    texts = build_seagull_texts(stats)
    html = render_daily_digest_rich(stats, texts, tz=ZoneInfo("Europe/Moscow"))
    assert '<a href="https://meet.google.com/abc-defg-hij">Войти в Google Meet</a>' in html
    assert "<i>📹" in html
    assert "Переговорная: A1" in html
