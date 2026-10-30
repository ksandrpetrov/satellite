"""Readable native Telegram blocks, safe fallback, and intact long meeting cards."""

from satellite.messages_ru import ai_report_text
from satellite.presentation.assistant import assistant_message_chunks, assistant_message_html


def test_calendar_cards_group_days_and_keep_time_separate_from_escaped_titles():
    report = {
        "from_date": "2026-10-30",
        "to_date_exclusive": "2026-11-01",
        "timezone": "Europe/Moscow",
        "events": [
            {
                "option": 1,
                "title": "Длинное название <script> & встреча",
                "calendar": "Мой",
                "start": "2026-10-30T12:00:00+03:00",
                "end": "2026-10-30T12:30:00+03:00",
            },
            {
                "option": 2,
                "title": "Выходной",
                "calendar": "Мой",
                "start": "2026-10-31T00:00:00+03:00",
                "end": "2026-11-02T00:00:00+03:00",
                "all_day": True,
            },
        ],
    }
    rich, legacy = assistant_message_html(ai_report_text(report))
    assert "<h3>Пт, 30.10</h3>" in rich and "<h3>Сб, 31.10</h3>" in rich
    assert "<b>1. 12:00–12:30</b><br>Длинное название &lt;script&gt; &amp; встреча" in rich
    assert "<b>2. Весь день · 31.10–01.11</b>" in rich
    assert "Europe/Moscow" not in rich and "МСК" in rich
    assert "<script>" not in rich and "## " not in legacy
    assert legacy.count("Календарь: Мой") == 1


def test_optimization_card_retains_number_and_numeric_benefit():
    report = {
        "from_date": "2026-10-30",
        "to_date": "2026-11-06",
        "timezone": "Europe/Moscow",
        "metrics": {"overlaps": 0, "short_breaks": 2, "focus_windows": 3},
        "candidates": [
            {
                "option": 3,
                "kind": "focus",
                "start": "2026-11-02T10:00:00+03:00",
                "end": "2026-11-02T11:30:00+03:00",
                "after": {"reserved_focus_minutes": 90},
            }
        ],
        "limitations": [],
    }
    rich, legacy = assistant_message_html(ai_report_text(report))
    assert "<b>3. Выделить время для фокуса</b><br>" in rich
    assert "0 → 90 мин" in rich and "0 → 90 мин" in legacy
    assert "<ul><li>Пересечений: 0</li>" in rich
    assert "<h3>Как применить</h3>" in rich
    spaced, _ = assistant_message_html("1. 10:00–11:00\nПервая\n\n2. 12:00–13:00\nВторая")
    assert "</p><hr><p><b>2. 12:00–13:00</b>" in spaced


def test_long_week_splits_between_meetings_and_never_leaves_day_heading_behind():
    cards = [f"{i}. 12:00–13:00\n" + "Длинное название встречи " * 10 for i in range(1, 21)]
    chunks = assistant_message_chunks("## Понедельник\n\n" + "\n\n".join(cards))
    assert len(chunks) > 1
    for card in cards:
        assert sum("\n\n" + card in "\n\n" + chunk for chunk in chunks) == 1
    assert all(not chunk.endswith("## Понедельник") for chunk in chunks)
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 2800 for chunk in chunks)
    emoji_chunks = assistant_message_chunks("🪶" * 3000)
    assert "".join(emoji_chunks) == "🪶" * 3000
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 2800 for chunk in emoji_chunks)
