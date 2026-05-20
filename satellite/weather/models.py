"""Модели данных для погодного блока (без HTTP и без календарной логики)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WeatherConfig:
    enabled: bool
    location_name: str
    latitude: float
    longitude: float
    timezone: str
    cache_ttl_minutes: int = 30
    show_normal_weather: bool = True


@dataclass(frozen=True)
class CurrentWeatherSnapshot:
    """Мгновенные условия из блока ``current`` ответа Open-Meteo (≈15‑минутная модель)."""

    temperature_2m: float | None = None
    apparent_temperature: float | None = None
    surface_pressure: float | None = None  # гПа (как в Open-Meteo)


@dataclass(frozen=True)
class HourlyWeather:
    time: str
    temperature: float | None
    apparent_temperature: float | None
    precipitation_probability: int | None
    rain: float | None
    snowfall: float | None
    wind_speed: float | None
    surface_pressure: float | None = None  # гПа


@dataclass(frozen=True)
class WeatherForecastForDate:
    """Почасовой прогноз за календарный день и снимок «сейчас» из того же HTTP-запроса."""

    hours: tuple[HourlyWeather, ...]
    current: CurrentWeatherSnapshot | None = None


@dataclass(frozen=True)
class WeatherSummary:
    location_name: str
    date_label: str
    min_temperature: float | None
    max_temperature: float | None
    avg_temperature: float | None
    min_apparent_temperature: float | None
    max_apparent_temperature: float | None
    avg_apparent_temperature: float | None
    max_precipitation_probability: int | None
    total_rain: float | None
    total_snowfall: float | None
    max_wind_speed: float | None
    warnings: tuple[str, ...]
    current_temperature: float | None = None
    current_apparent_temperature: float | None = None
    day_max_temperature: float | None = None
    day_max_apparent_temperature: float | None = None
    message: str | None = None
    current_surface_pressure: float | None = None  # гПа, для отображения в мм рт. ст.
