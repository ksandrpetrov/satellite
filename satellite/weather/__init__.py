"""Публичные точки входа погодного слоя."""

from .analyzer import (
    WARNING_HOT,
    WARNING_RAIN_HIGH,
    WARNING_RAIN_POSSIBLE,
    WARNING_SNOW,
    WARNING_STRONG_WIND,
    WARNING_VERY_COLD,
    WARNING_WIND,
    aggregate_hourly,
    collect_warnings,
    summarize_for_digest_day,
)
from .client import WeatherForecastClient
from .models import HourlyWeather, WeatherConfig, WeatherSummary
from .templates import (
    build_weather_details,
    build_weather_details_text,
    build_weather_message,
    format_temperature,
)

__all__ = [
    "HourlyWeather",
    "WeatherConfig",
    "WeatherForecastClient",
    "WeatherSummary",
    "aggregate_hourly",
    "build_weather_details",
    "build_weather_details_text",
    "build_weather_message",
    "collect_warnings",
    "format_temperature",
    "summarize_for_digest_day",
    "WARNING_HOT",
    "WARNING_RAIN_HIGH",
    "WARNING_RAIN_POSSIBLE",
    "WARNING_SNOW",
    "WARNING_STRONG_WIND",
    "WARNING_VERY_COLD",
    "WARNING_WIND",
]
