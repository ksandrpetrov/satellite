"""Юнит-тесты погодного слоя и интеграции с дайджестом."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from satellite.calendar.stats import NormalizedEvent, WorkdayOptions, calculate_day_stats
from satellite.plan_service import PlanBuilder
from satellite.seagull.digest import build_seagull_digest
from satellite.seagull.render import render_daily_digest
from satellite.seagull.rules import build_seagull_texts
from satellite.weather.analyzer import (
    WARNING_HOT,
    WARNING_RAIN_HIGH,
    WARNING_RAIN_POSSIBLE,
    WARNING_SNOW,
    WARNING_STRONG_WIND,
    WARNING_VERY_COLD,
    summarize_for_digest_day,
)
from satellite.weather.client import WeatherForecastClient
from satellite.weather.models import (
    CurrentWeatherSnapshot,
    HourlyWeather,
    WeatherConfig,
    WeatherSummary,
)
from satellite.weather.templates import (
    build_weather_details,
    build_weather_details_text,
    build_weather_message,
    format_temperature,
    seagull_style_tokens_present,
)

MOSCOW = ZoneInfo("Europe/Moscow")


def _hour(day: str, hour: int, **kw: object) -> HourlyWeather:
    return HourlyWeather(
        time=f"{day}T{hour:02d}:00",
        temperature=kw.get("temperature"),  # type: ignore[arg-type]
        apparent_temperature=kw.get("apparent_temperature"),  # type: ignore[arg-type]
        precipitation_probability=kw.get("precipitation_probability"),  # type: ignore[arg-type]
        rain=kw.get("rain"),  # type: ignore[arg-type]
        snowfall=kw.get("snowfall"),  # type: ignore[arg-type]
        wind_speed=kw.get("wind_speed"),  # type: ignore[arg-type]
        surface_pressure=kw.get("surface_pressure"),  # type: ignore[arg-type]
    )


def _stats_for_day(
    events: list[NormalizedEvent], *, label: str = "Сегодня", plan_date: date | None = None
):
    pd = plan_date or date(2026, 5, 12)
    return calculate_day_stats(events, date_label=label, plan_date=pd)


def _digest_now_may_12_14h() -> datetime:
    return datetime(2026, 5, 12, 14, 0, 0, tzinfo=MOSCOW)


def test_rain_high_probability_80_triggers_umbrella_warning():
    hours = [
        _hour("2026-05-12", h, precipitation_probability=80, apparent_temperature=7.0)
        for h in range(10, 19)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_RAIN_HIGH in s.warnings
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="t1", digest_is_today=True
    )
    assert msg is not None
    assert "зонт" in msg.lower() or "крыл" in msg.lower()
    assert "80%" in msg


def test_rain_probability_30_no_rain_warning():
    hours = [
        _hour("2026-05-12", h, precipitation_probability=30, apparent_temperature=10.0)
        for h in range(10, 19)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_RAIN_HIGH not in s.warnings
    assert WARNING_RAIN_POSSIBLE not in s.warnings


def test_snow_total_over_1_mm_triggers_snow_warning():
    hours = []
    for h in range(10, 19):
        hours.append(_hour("2026-05-12", h, snowfall=0.15, apparent_temperature=-2.0))
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_SNOW in s.warnings


def test_apparent_minus_12_very_cold():
    hours = [_hour("2026-05-12", h, apparent_temperature=-12.0) for h in range(10, 19)]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_VERY_COLD in s.warnings


def test_apparent_minus_2_cold_not_very_cold():
    hours = [_hour("2026-05-12", h, apparent_temperature=-2.0) for h in range(10, 19)]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_VERY_COLD not in s.warnings
    from satellite.weather.analyzer import WARNING_COLD

    assert WARNING_COLD in s.warnings


def test_apparent_plus_31_hot():
    hours = [_hour("2026-05-12", h, apparent_temperature=31.0) for h in range(10, 19)]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_HOT in s.warnings


def test_wind_13_strong():
    hours = [
        _hour("2026-05-12", h, wind_speed=13.0, apparent_temperature=15.0) for h in range(10, 19)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_STRONG_WIND in s.warnings


def test_multiple_warnings_combined_rain_and_wind():
    hours = [
        _hour(
            "2026-05-12",
            h,
            precipitation_probability=85,
            wind_speed=13.0,
            apparent_temperature=7.0,
        )
        for h in range(10, 19)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    assert WARNING_RAIN_HIGH in s.warnings and WARNING_STRONG_WIND in s.warnings
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="combo", digest_is_today=True
    )
    assert msg is not None
    assert "🌧💨" in msg or ("🌧" in msg and "💨" in msg)


def test_api_failure_digest_still_renders():
    fake = MagicMock()
    fake.fetch_events_for_day = MagicMock(return_value=([], "x"))
    cfg = WeatherConfig(
        enabled=True,
        location_name="X",
        latitude=0.0,
        longitude=0.0,
        timezone="Europe/Moscow",
        cache_ttl_minutes=30,
        show_normal_weather=False,
    )

    def boom(_url: str):
        raise ConnectionError("down")

    client = WeatherForecastClient(fetch_json=boom)
    builder = PlanBuilder(
        calendar_service=fake,
        plan_config=MagicMock(hide_all_day_events=True, hide_lunch_events=True),
        tz=ZoneInfo("Europe/Moscow"),
        weather_config=cfg,
        weather_client=client,
    )
    text = builder.build_text(
        telegram_user_id=1,
        target_date=date(2026, 5, 12),
        reference_date=date(2026, 5, 12),
    )
    assert "<b>Прогноз на сегодня (12.05.2026)</b>" in text
    assert "Мокрый перелёт" not in text


def test_weather_disabled_no_fetch():
    calls: list[str] = []

    def tracker(url: str):
        calls.append(url)
        return {"hourly": {"time": []}}

    fake = MagicMock()
    fake.fetch_events_for_day = MagicMock(return_value=([], "x"))
    fake.login = "u@mail.ru"
    cfg = WeatherConfig(
        enabled=False,
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
        plan_config=MagicMock(hide_all_day_events=True, hide_lunch_events=True),
        tz=ZoneInfo("Europe/Moscow"),
        weather_config=cfg,
        weather_client=client,
    )
    builder.build_text(
        telegram_user_id=1,
        target_date=date(2026, 5, 12),
        reference_date=date(2026, 5, 12),
    )
    assert calls == []


def test_current_snapshot_overrides_flat_hourly_for_now_display():
    """«Сейчас» берётся из снимка Open-Meteo current, а не из часового прогноза."""
    hours = [_hour("2026-05-12", h, temperature=5.0, apparent_temperature=5.0) for h in range(24)]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    snap = CurrentWeatherSnapshot(
        temperature_2m=13.7,
        apparent_temperature=13.2,
        surface_pressure=1013.25,
    )
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
        current_conditions=snap,
    )
    details = build_weather_details_text(s, is_today=True)
    # Ощущаемая температура предпочтительнее сырой (13.2°C → +13°C).
    assert "сейчас +13°C" in details
    assert "760" in details and "мм рт. ст." in details


def test_cache_second_call_same_day_no_second_fetch():
    calls: list[str] = []

    def fetch(_url: str):
        calls.append(_url)
        return {
            "hourly": {
                "time": [f"2026-05-12T{h:02d}:00" for h in range(24)],
                "temperature_2m": [10.0] * 24,
                "apparent_temperature": [10.0] * 24,
                "precipitation_probability": [0] * 24,
                "rain": [0.0] * 24,
                "snowfall": [0.0] * 24,
                "wind_speed_10m": [1.0] * 24,
                "surface_pressure": [1013.0] * 24,
            },
            "current": {
                "time": "2026-05-12T14:00",
                "temperature_2m": 10.0,
                "apparent_temperature": 10.0,
                "surface_pressure": 1013.0,
            },
        }

    cfg = WeatherConfig(
        enabled=True,
        location_name="X",
        latitude=55.0,
        longitude=37.0,
        timezone="Europe/Moscow",
        cache_ttl_minutes=30,
        show_normal_weather=False,
    )
    client = WeatherForecastClient(fetch_json=fetch, monotonic_fn=lambda: 0.0)
    client.get_forecast_for_date(cfg, date(2026, 5, 12))
    client.get_forecast_for_date(cfg, date(2026, 5, 12))
    assert len(calls) == 1


def test_tomorrow_vs_day_after_date_filtering():
    cfg = WeatherConfig(
        enabled=True,
        location_name="X",
        latitude=55.0,
        longitude=37.0,
        timezone="Europe/Moscow",
        cache_ttl_minutes=0,
        show_normal_weather=False,
    )

    def fetch(_url: str):
        times = []
        temps = []
        for d, label in [(11, "a"), (12, "b"), (13, "c")]:
            for h in range(10, 12):
                times.append(f"2026-05-{d:02d}T{h:02d}:00")
                temps.append(float(d))
        return {
            "hourly": {
                "time": times,
                "temperature_2m": temps,
                "apparent_temperature": temps,
                "precipitation_probability": [50] * len(times),
                "rain": [0.5] * len(times),
                "snowfall": [0.0] * len(times),
                "wind_speed_10m": [2.0] * len(times),
            }
        }

    client = WeatherForecastClient(fetch_json=fetch)
    s12 = client.get_forecast_for_date(cfg, date(2026, 5, 12))
    s13 = client.get_forecast_for_date(cfg, date(2026, 5, 13))
    assert s12 and all("2026-05-12" in x.time for x in s12.hours)
    assert s13 and all("2026-05-13" in x.time for x in s13.hours)
    assert not any("2026-05-11" in x.time for x in s12.hours)


def test_weather_text_no_chayka_word():
    hours = [
        _hour("2026-05-12", h, precipitation_probability=80, apparent_temperature=7.0)
        for h in range(10, 19)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="x", digest_is_today=True
    )
    assert msg
    assert "чайка" not in msg.lower()


def test_weather_text_has_style_token():
    hours = [
        _hour("2026-05-12", h, precipitation_probability=80, apparent_temperature=7.0)
        for h in range(10, 19)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="x", digest_is_today=True
    )
    assert seagull_style_tokens_present(msg)


def test_details_include_temperature_when_available():
    s = WeatherSummary(
        location_name="",
        date_label="",
        min_temperature=6.0,
        max_temperature=8.0,
        avg_temperature=7.0,
        min_apparent_temperature=6.5,
        max_apparent_temperature=8.5,
        avg_apparent_temperature=7.2,
        max_precipitation_probability=40,
        total_rain=0.1,
        total_snowfall=0.0,
        max_wind_speed=2.0,
        warnings=(WARNING_RAIN_POSSIBLE,),
        current_apparent_temperature=7.2,
        day_max_apparent_temperature=8.5,
        current_surface_pressure=1013.25,
    )
    d = build_weather_details_text(s, is_today=True, phrase_seed="dt")
    assert "°C" in d
    assert "40%" in d
    assert "сейчас" in d
    assert "днём до" in d
    assert "760" in d and "мм рт. ст." in d


def test_details_precip_only():
    s = WeatherSummary(
        location_name="",
        date_label="",
        min_temperature=None,
        max_temperature=None,
        avg_temperature=None,
        min_apparent_temperature=None,
        max_apparent_temperature=None,
        avg_apparent_temperature=None,
        max_precipitation_probability=80,
        total_rain=None,
        total_snowfall=None,
        max_wind_speed=None,
        warnings=(WARNING_RAIN_HIGH,),
    )
    d = build_weather_details_text(s, is_today=True)
    assert "осадки" in d
    assert "°C" not in d


def test_message_no_empty_colon_without_details():
    s = WeatherSummary(
        location_name="",
        date_label="",
        min_temperature=None,
        max_temperature=None,
        avg_temperature=None,
        min_apparent_temperature=None,
        max_apparent_temperature=None,
        avg_apparent_temperature=None,
        max_precipitation_probability=None,
        total_rain=2.0,
        total_snowfall=0.0,
        max_wind_speed=None,
        warnings=(WARNING_RAIN_HIGH,),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="nodet", digest_is_today=True
    )
    assert msg is not None
    assert ": ." not in msg
    assert ": ," not in msg


def test_render_inserts_weather_before_seagull_text():
    ev1 = NormalizedEvent("A", 10 * 60, 11 * 60)
    ev2 = NormalizedEvent("B", 10 * 60 + 30, 11 * 60 + 30)
    stats = calculate_day_stats([ev1, ev2], date_label="Сегодня", plan_date=date(2026, 5, 12))
    texts = build_seagull_texts(stats)
    assert texts.overlaps
    w = "🌧 Тестовый перелёт: около +5°C. Зонт пригодится."
    html = render_daily_digest(stats, texts, weather_line=w)
    assert texts.overlaps in html
    assert w in html
    assert html.index(w) < html.index(texts.main)
    assert html.index(texts.overlaps) > html.index(w)
    assert html.index(w) < html.index("Вот детальное")


def test_build_seagull_digest_accepts_weather_line():
    text = build_seagull_digest(
        [],
        date(2026, 5, 12),
        tz=ZoneInfo("Europe/Moscow"),
        reference_date=date(2026, 5, 12),
        weather_line="🌧 Мокрый перелёт: сейчас +7°C, днём до +12°C, осадки до 80%. Зонт пригодится.",
    )
    assert "Мокрый перелёт" in text
    assert text.index("Мокрый") < text.index("Вот детальное")


def test_today_message_contains_seychas_and_dnyom():
    """Текст содержит «сейчас +7°C» и «днём до +12°C» при полных данных."""
    hours = []
    for h in range(24):
        ap = 7.0 if h == 14 else (12.0 if h == 16 else 4.0)
        pr = 80 if 10 <= h < 19 else 10
        hours.append(
            _hour(
                "2026-05-12",
                h,
                apparent_temperature=ap,
                precipitation_probability=pr,
                rain=0.2 if pr >= 70 else 0.0,
            )
        )
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=datetime(2026, 5, 12, 14, 15, tzinfo=MOSCOW),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="td", digest_is_today=True
    )
    assert msg
    assert "сейчас +7°C" in msg
    assert "днём до +12°C" in msg
    assert "осадки до 80%" in msg


def test_future_day_says_na_starte_not_seychas():
    """Завтрашний дайджест: «на старте», не «сейчас»."""
    hours = []
    for h in range(24):
        ap = 9.0 if h == 10 else (15.0 if h == 14 else 5.0)
        hours.append(
            _hour(
                "2026-05-13",
                h,
                apparent_temperature=ap,
                precipitation_probability=45,
                rain=0.3,
            )
        )
    stats = _stats_for_day([], label="Завтра", plan_date=date(2026, 5, 13))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="tm", digest_is_today=False
    )
    assert msg
    assert "на старте +9°C" in msg
    assert "днём до +15°C" in msg
    assert "сейчас" not in msg


def test_apparent_preferred_over_temperature_2m():
    """Если есть apparent_temperature, показываем её."""
    hours = []
    for h in range(24):
        hours.append(
            _hour(
                "2026-05-12",
                h,
                temperature=3.0,
                apparent_temperature=7.4,
                precipitation_probability=80,
                rain=1.0,
            )
        )
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="ap", digest_is_today=True
    )
    assert msg
    assert "+7°C" in msg
    assert "+3°C" not in msg


def test_fallback_to_temperature_when_no_apparent():
    """Без apparent используется temperature_2m."""
    hours = []
    for h in range(24):
        hours.append(
            _hour(
                "2026-05-12",
                h,
                temperature=8.2,
                apparent_temperature=None,
                precipitation_probability=80,
                rain=1.0,
            )
        )
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="fb", digest_is_today=True
    )
    assert msg
    assert "+8°C" in msg


def test_day_max_over_entire_calendar_date_not_work_window():
    """Максимум за день берётся из всей даты: пик ночью выше, чем в рабочем окне."""
    hours = []
    for h in range(24):
        if 10 <= h < 19:
            ap = 12.0
        elif h == 23:
            ap = 22.0
        else:
            ap = 5.0
        hours.append(
            _hour(
                "2026-05-12",
                h,
                apparent_temperature=ap,
                precipitation_probability=80 if h == 14 else 20,
                rain=1.0 if h == 14 else 0.0,
            )
        )
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="dm", digest_is_today=True
    )
    assert msg
    assert "днём до +22°C" in msg


def test_precip_shown_as_osadki_do_percent():
    hours = [
        _hour("2026-05-12", h, apparent_temperature=10.0, precipitation_probability=80, rain=1.0)
        for h in range(24)
    ]
    stats = _stats_for_day([], plan_date=date(2026, 5, 12))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
        now=_digest_now_may_12_14h(),
    )
    msg = build_weather_message(
        s, show_normal_weather=False, message_seed="pr", digest_is_today=True
    )
    assert msg and "осадки до 80%" in msg


def test_format_temperature_rounding():
    assert format_temperature(4.4) == "+4°C"
    assert format_temperature(4.6) == "+5°C"
    assert format_temperature(0) == "0°C"
    assert format_temperature(-7.2) == "-7°C"
    assert format_temperature(None) is None


def test_build_weather_details_partial_data():
    assert build_weather_details(7.0, None, None, is_today=True) == "сейчас +7°C"
    assert build_weather_details(None, 12.0, None, is_today=True) == "днём до +12°C"
    assert build_weather_details(None, None, 45, is_today=False) == "осадки до 45%"
    assert build_weather_details(None, None, None, is_today=True) == ""


def test_first_meeting_before_10_uses_that_hour_for_start_temperature():
    """Первая встреча до 10:00 — температура «на старте» с часа встречи."""
    hours = [_hour("2026-05-13", h, apparent_temperature=float(h)) for h in range(24)]
    ev = NormalizedEvent("Early", 9 * 60, 9 * 60 + 30)
    stats = calculate_day_stats([ev], date_label="Завтра", plan_date=date(2026, 5, 13))
    s = summarize_for_digest_day(
        hours,
        stats,
        WorkdayOptions(),
        location_name="Москва",
        tz_name="Europe/Moscow",
        reference_date=date(2026, 5, 12),
    )
    msg = build_weather_message(
        s, show_normal_weather=True, message_seed="early", digest_is_today=False
    )
    assert msg
    assert "на старте +9°C" in msg
