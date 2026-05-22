"""Юнит-тесты на satellite.plan_service."""

from __future__ import annotations

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from satellite.config import PlanConfig, WeatherConfig
from satellite.plan_service import PlanBuilder
from satellite.weather.client import WeatherForecastClient

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


def test_plan_builder_skips_weather_when_user_disabled():
    calls: list[str] = []

    def tracker(url: str):
        calls.append(url)
        return {"hourly": {"time": []}}

    fake = _FakeCalendarService(events=[])
    cfg = PlanConfig()
    weather_cfg = WeatherConfig(
        enabled=True,
        location_name="X",
        latitude=55.0,
        longitude=37.0,
        timezone="Europe/Moscow",
        cache_ttl_minutes=30,
        show_normal_weather=False,
    )
    client = WeatherForecastClient(fetch_json=tracker)
    builder = PlanBuilder(
        calendar_service=fake,
        plan_config=cfg,
        tz=TZ,
        weather_config=weather_cfg,
        weather_client=client,
    )
    builder.build_text(
        telegram_user_id=1,
        target_date=date(2026, 5, 11),
        reference_date=date(2026, 5, 11),
        weather_in_plan_enabled=False,
    )
    assert calls == []


def _open_meteo_payload(plan_date: date) -> dict:
    return {
        "hourly": {
            "time": [f"{plan_date}T{h:02d}:00" for h in range(24)],
            "temperature_2m": [24.0] * 24,
            "apparent_temperature": [24.0] * 24,
            "precipitation_probability": [0] * 24,
            "rain": [0.0] * 24,
            "snowfall": [0.0] * 24,
            "wind_speed_10m": [2.0] * 24,
            "surface_pressure": [1000.0] * 24,
        },
        "current": {
            "temperature_2m": 24.0,
            "apparent_temperature": 24.0,
            "surface_pressure": 1000.0,
        },
    }


def test_plan_builder_weather_after_prefetch_timeout(monkeypatch):
    """Медленный prefetch не должен убирать погоду — догружаем inline."""
    plan_date = date(2026, 5, 22)
    fetch_calls: list[int] = []

    def fetch_json(_url: str) -> dict:
        fetch_calls.append(1)
        if len(fetch_calls) == 1:
            time.sleep(0.25)
        return _open_meteo_payload(plan_date)

    monkeypatch.setattr("satellite.plan_service._WEATHER_PREFETCH_JOIN_SEC", 0.05)

    fake = _FakeCalendarService(events=[])
    weather_cfg = WeatherConfig(
        enabled=True,
        location_name="Сочи",
        latitude=43.6,
        longitude=39.7,
        timezone="Europe/Moscow",
        cache_ttl_minutes=0,
        show_normal_weather=True,
    )
    client = WeatherForecastClient(fetch_json=fetch_json, request_timeout_sec=5.0)
    builder = PlanBuilder(
        calendar_service=fake,
        plan_config=PlanConfig(),
        tz=TZ,
        weather_config=weather_cfg,
        weather_client=client,
    )
    text = builder.build_text(
        telegram_user_id=1,
        target_date=plan_date,
        reference_date=plan_date,
    )
    assert len(fetch_calls) == 2
    assert "🌤" in text or "Воздух" in text


def test_plan_builder_includes_normal_weather_for_tomorrow(monkeypatch):
    plan_date = date(2026, 5, 23)
    reference = date(2026, 5, 22)

    def fetch_json(_url: str) -> dict:
        return _open_meteo_payload(plan_date)

    fake = _FakeCalendarService(events=[])
    weather_cfg = WeatherConfig(
        enabled=True,
        location_name="Сочи",
        latitude=43.6,
        longitude=39.7,
        timezone="Europe/Moscow",
        cache_ttl_minutes=0,
        show_normal_weather=True,
    )
    client = WeatherForecastClient(fetch_json=fetch_json)
    builder = PlanBuilder(
        calendar_service=fake,
        plan_config=PlanConfig(),
        tz=TZ,
        weather_config=weather_cfg,
        weather_client=client,
    )
    text = builder.build_text(
        telegram_user_id=1,
        target_date=plan_date,
        reference_date=reference,
    )
    assert "Прогноз на завтра" in text
    assert "🌤" in text or "Воздух" in text
