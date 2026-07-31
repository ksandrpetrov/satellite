from __future__ import annotations

from datetime import UTC, date
from types import SimpleNamespace
from unittest.mock import MagicMock

from satellite.analytics.service import build_week_analytics
from satellite.calendar.event_exclusions import EventExclusionPolicy, EventTitleOverride


def test_build_week_analytics_applies_exclusion_policy(monkeypatch):
    reference_date = date(2026, 5, 14)
    calendar_service = MagicMock()
    calendar_service.require_connection.return_value = SimpleNamespace(
        context=SimpleNamespace(login="user@test.ru"),
        record=SimpleNamespace(analytics_workday="10-19"),
    )
    calendar_service.list_events.return_value = [
        {
            "summary": "Weekly Placeholder",
            "dtstart": "2026-05-11T10:00:00+00:00",
            "dtend": "2026-05-11T12:00:00+00:00",
            "attendees": ["mailto:user@test.ru;PARTSTAT=ACCEPTED"],
        }
    ]
    captured: dict = {}

    def fake_render(report):
        captured["report"] = report
        return b"png"

    monkeypatch.setattr("satellite.analytics.service.render_analytics_card", fake_render)
    monkeypatch.setattr(
        "satellite.analytics.service.build_analytics_caption",
        lambda _report: "caption",
    )
    monkeypatch.setattr(
        "satellite.analytics.service.build_analytics_rich_caption",
        lambda _report: "rich caption",
    )
    policy = EventExclusionPolicy([EventTitleOverride("weekly placeholder", excluded=True)])

    result = build_week_analytics(
        telegram_user_id=1,
        reference_date=reference_date,
        tz=UTC,
        calendar_service=calendar_service,
        users=MagicMock(),
        exclusion_policy=policy,
    )

    assert result == (b"png", "caption", "rich caption")
    assert captured["report"].current.total_busy == 0
    assert captured["report"].quarter_weekly_busy == (0,) * 13
