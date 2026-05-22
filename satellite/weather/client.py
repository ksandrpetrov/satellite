"""HTTP-клиент Open-Meteo с простым in-memory кэшем по месту и дате."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from .models import CurrentWeatherSnapshot, HourlyWeather, WeatherConfig, WeatherForecastForDate

log = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _cache_key(config: WeatherConfig, plan_date: date) -> tuple[float, float, str, str]:
    return (
        round(float(config.latitude), 6),
        round(float(config.longitude), 6),
        config.timezone,
        plan_date.isoformat(),
    )


def _parse_current_payload(payload: Mapping[str, Any]) -> CurrentWeatherSnapshot | None:
    cur = payload.get("current")
    if not isinstance(cur, Mapping):
        return None
    t_raw = cur.get("temperature_2m")
    a_raw = cur.get("apparent_temperature")
    p_raw = cur.get("surface_pressure")
    return CurrentWeatherSnapshot(
        temperature_2m=float(t_raw) if t_raw is not None else None,
        apparent_temperature=float(a_raw) if a_raw is not None else None,
        surface_pressure=float(p_raw) if p_raw is not None else None,
    )


def _parse_hourly_payload(payload: Mapping[str, Any]) -> list[HourlyWeather]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    n = len(times)
    temps = hourly.get("temperature_2m") or [None] * n
    apparent = hourly.get("apparent_temperature") or [None] * n
    pprob = hourly.get("precipitation_probability") or [None] * n
    rain = hourly.get("rain") or [None] * n
    snow = hourly.get("snowfall") or [None] * n
    wind = hourly.get("wind_speed_10m") or [None] * n
    press = hourly.get("surface_pressure") or [None] * n

    out: list[HourlyWeather] = []
    for i in range(n):
        pp = pprob[i] if i < len(pprob) else None
        pp_int = int(pp) if pp is not None else None
        out.append(
            HourlyWeather(
                time=str(times[i]),
                temperature=float(temps[i]) if i < len(temps) and temps[i] is not None else None,
                apparent_temperature=float(apparent[i])
                if i < len(apparent) and apparent[i] is not None
                else None,
                precipitation_probability=pp_int,
                rain=float(rain[i]) if i < len(rain) and rain[i] is not None else None,
                snowfall=float(snow[i]) if i < len(snow) and snow[i] is not None else None,
                wind_speed=float(wind[i]) if i < len(wind) and wind[i] is not None else None,
                surface_pressure=float(press[i])
                if i < len(press) and press[i] is not None
                else None,
            )
        )
    return out


class WeatherForecastClient:
    """Кэш TTL по ключу (координаты + timezone + календарная дата)."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        monotonic_fn: Callable[[], float] = time.monotonic,
        fetch_json: Callable[[str], Mapping[str, Any]] | None = None,
        request_timeout_sec: float = 15.0,
        retry_attempts: int = 2,
    ) -> None:
        # 15s + один повтор: Open-Meteo с российских сетей стабильно отвечает
        # за ~5.0–5.5 с (TLS handshake + ответ), но изредка проседает до 10–14 с.
        # Прежний 5-секундный таймаут выбивал почти каждый запрос → в логах
        # `weather=0.00s`, прогноз молча пропадал из дайджеста /today и /tomorrow.
        # Join-окно в `plan_service.py` синхронно расширено, чтобы prefetch
        # успел дойти. `retry_attempts=2` означает «попыток всего две» —
        # один основной запрос + один повтор только при сетевых ошибках.
        self._session = session or requests.Session()
        self._monotonic = monotonic_fn
        self._fetch_json = fetch_json
        self._request_timeout_sec = request_timeout_sec
        self._retry_attempts = max(1, int(retry_attempts))
        self._lock = threading.Lock()
        self._cache: dict[
            tuple[float, float, str, str],
            tuple[float, WeatherForecastForDate],
        ] = {}

    def close(self) -> None:
        self._session.close()

    def _default_fetch(self, url: str) -> Mapping[str, Any]:
        # Повтор только на ConnectionError (быстро падающие ошибки сети, DNS,
        # сброс соединения). На Timeout не ретраим — второй 15-секундный
        # запрос всё равно не уложится в join-окно `_WEATHER_PREFETCH_JOIN_SEC`,
        # а пользователь будет ждать дольше необходимого.
        last_exc: Exception | None = None
        for attempt in range(self._retry_attempts):
            try:
                response = self._session.get(url, timeout=self._request_timeout_sec)
                response.raise_for_status()
                return response.json()
            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt + 1 < self._retry_attempts:
                    log.warning(
                        "Open-Meteo connection failed (attempt %d/%d): %s; retrying",
                        attempt + 1,
                        self._retry_attempts,
                        exc,
                    )
                    continue
                raise
        assert last_exc is not None  # unreachable
        raise last_exc

    def get_forecast_for_date(
        self,
        config: WeatherConfig,
        plan_date: date,
    ) -> WeatherForecastForDate | None:
        """Почасовой прогноз за день + снимок ``current`` из Open-Meteo (один запрос)."""
        if not config.enabled:
            return None

        key = _cache_key(config, plan_date)
        ttl_sec = max(0, int(config.cache_ttl_minutes)) * 60
        now = self._monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]

        try:
            url = self._build_url(config)
            payload = self._fetch_json(url) if self._fetch_json else self._default_fetch(url)
            hours = _parse_hourly_payload(payload)
            day_hours = [h for h in hours if self._hour_date(h.time, config.timezone) == plan_date]
            snap = _parse_current_payload(payload)
            bundle = WeatherForecastForDate(hours=tuple(day_hours), current=snap)
        except Exception:  # noqa: BLE001 — пользователю не показываем
            log.exception("Failed to fetch weather forecast")
            return None

        if ttl_sec > 0:
            with self._lock:
                self._cache[key] = (now + ttl_sec, bundle)
        return bundle

    @staticmethod
    def _hour_date(time_str: str, tz_name: str) -> date:
        zi = ZoneInfo(tz_name)
        raw = time_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zi)
        else:
            dt = dt.astimezone(zi)
        return dt.date()

    @staticmethod
    def _build_url(config: WeatherConfig) -> str:
        hourly = (
            "temperature_2m,apparent_temperature,precipitation_probability,"
            "rain,snowfall,wind_speed_10m,surface_pressure"
        )
        current = "temperature_2m,apparent_temperature,surface_pressure"
        params = {
            "latitude": config.latitude,
            "longitude": config.longitude,
            "timezone": config.timezone,
            "forecast_days": 3,
            "hourly": hourly,
            "current": current,
            "wind_speed_unit": "ms",
        }
        return f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"


__all__ = ["WeatherForecastClient", "OPEN_METEO_FORECAST_URL"]
