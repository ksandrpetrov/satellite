"""Юнит-тесты на satellite.plan_service."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from satellite.config import PlanConfig
from satellite.plan_service import PlanBuilder

TZ = ZoneInfo("Europe/Moscow")


def _caldav_ev(summary: str, start_h: int, start_m: int, end_h: int, end_m: int, **extra) -> dict:
    return {
        "summary": summary,
        "location": "",
        "dtstart": datetime(2026, 5, 11, start_h, start_m, tzinfo=TZ).isoformat(),
        "dtend": datetime(2026, 5, 11, end_h, end_m, tzinfo=TZ).isoformat(),
        **extra,
    }


class _FakeCalendarService:
    def __init__(self, events, login="me@mail.ru"):
        self._events = events
        self.login = login
        self.calls: list[dict] = []

    def fetch_events_for_day(self, telegram_user_id, target_date, *, tz):
        self.calls.append(
            {
                "telegram_user_id": telegram_user_id,
                "target_date": target_date,
                "tz": tz,
            }
        )
        return self._events, self.login


def test_plan_builder_renders_seagull_digest_for_user():
    fake = _FakeCalendarService(events=[])
    cfg = PlanConfig()
    builder = PlanBuilder(calendar_service=fake, plan_config=cfg, tz=TZ)
    text = builder.build_text(
        telegram_user_id=42,
        target_date=date(2026, 5, 11),
        reference_date=date(2026, 5, 11),
    )
    assert text.startswith("📬 <b>Прогноз на сегодня (11.05.2026)</b>")
    assert fake.calls[0]["telegram_user_id"] == 42
    assert fake.calls[0]["target_date"] == date(2026, 5, 11)


def test_plan_builder_filters_cancelled_and_lunch_and_renders_footer():
    events = [
        _caldav_ev("Дейли", 10, 0, 10, 30),
        _caldav_ev("🍕 Обед", 13, 0, 14, 0),
        _caldav_ev("[SMB] Demo", 16, 30, 18, 0, status="CANCELLED"),
    ]
    fake = _FakeCalendarService(events=events)
    cfg = PlanConfig(
        hide_all_day_events=True,
        hide_lunch_events=True,
    )
    builder = PlanBuilder(calendar_service=fake, plan_config=cfg, tz=TZ)
    text = builder.build_text(
        telegram_user_id=7,
        target_date=date(2026, 5, 11),
        reference_date=date(2026, 5, 11),
    )
    assert "Дейли" in text
    assert "[SMB] Demo" not in text
    assert "10:00–10:30</b> — 🍕 Обед" not in text
    assert "🍕 Обед: 13:00 – 14:00" in text
