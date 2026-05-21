"""PNG-карточки для шаринга."""

from __future__ import annotations

from datetime import date

from satellite.calendar.stats import DayCalendarStats, NormalizedEvent
from satellite.seagull.rules import SeagullTexts
from satellite.share.cards import render_plan_share_card, render_upcoming_share_card


def _stats() -> DayCalendarStats:
    events = (
        NormalizedEvent(
            title="Стендап",
            start_minutes=10 * 60,
            end_minutes=11 * 60,
            location="Zoom",
        ),
        NormalizedEvent(
            title="Ретро",
            start_minutes=15 * 60,
            end_minutes=16 * 60,
        ),
    )
    return DayCalendarStats(
        date_label="Сегодня",
        plan_date=date(2026, 5, 21),
        events=events,
        meetings_count=2,
        first_meeting_start="10:00",
        last_meeting_end="16:00",
        busy_minutes=120,
        free_minutes=300,
        overlaps_count=0,
    )


def test_render_plan_share_png():
    png = render_plan_share_card(
        _stats(),
        SeagullTexts(main="🪶 Чайка видит обычный рабочий маршрут."),
    )
    assert len(png) > 4000
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_upcoming_share_png():
    groups = [
        {
            "header": "Сегодня, ср 21.05 (занято 1 час)",
            "events": [
                {
                    "marker": "1️⃣",
                    "time_range": "10:00–11:00",
                    "title": "Стендап",
                }
            ],
        }
    ]
    png = render_upcoming_share_card(
        groups, days=7, reference_date=date(2026, 5, 21)
    )
    assert len(png) > 4000
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
