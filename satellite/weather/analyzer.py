"""Агрегация почасовых данных и выбор предупреждений (без HTTP и шаблонов текста)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from statistics import mean
from zoneinfo import ZoneInfo

from ..calendar.stats import DayCalendarStats, WorkdayOptions
from ..calendar.time_utils import parse_hhmm
from .models import CurrentWeatherSnapshot, HourlyWeather, WeatherSummary


def _to_int_or_none(value: object) -> int | None:
    """OpenMeteo может вернуть процент осадков как float — приводим к int.

    Поле ``WeatherSummary.max_precipitation_probability`` типизировано как ``int``
    (это процент), а агрегаторы выше возвращают ``float | int | None``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _hour_to_datetime(time_str: str, tz_name: str) -> datetime:
    zi = ZoneInfo(tz_name)
    raw = time_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zi)
    else:
        dt = dt.astimezone(zi)
    return dt


def _minutes_from_midnight_for_hour(time_str: str, tz_name: str) -> int:
    dt = _hour_to_datetime(time_str, tz_name)
    return dt.hour * 60 + dt.minute


def _pick_nearest_hour(
    hours: Sequence[HourlyWeather],
    tz_name: str,
    target: datetime,
) -> HourlyWeather | None:
    """Ближайшая почасовая точка к ``target`` (в одном календарном дне API)."""
    if not hours:
        return None
    zi = ZoneInfo(tz_name)
    target_a = target.astimezone(zi)
    best: HourlyWeather | None = None
    best_abs: float | None = None
    for h in hours:
        dt = _hour_to_datetime(h.time, tz_name)
        delta = abs((dt - target_a).total_seconds())
        if best_abs is None or delta < best_abs:
            best_abs = delta
            best = h
    return best


def future_day_start_minutes(stats: DayCalendarStats) -> int:
    """Старт полезного интервала для завтра/послезавтра: 10:00 или час первой встречи, если она раньше."""
    default_m = 10 * 60
    if not stats.first_meeting_start:
        return default_m
    fm = parse_hhmm(stats.first_meeting_start)
    if fm < default_m:
        return (fm // 60) * 60
    return default_m


def weather_analysis_window_minutes(
    stats: DayCalendarStats,
    options: WorkdayOptions,
) -> tuple[int, int]:
    """Интервал анализа в минутах от полуночи: рабочий день ± встречи."""
    wm = options.to_minutes()
    work_start = wm.workday_start
    work_end = wm.workday_end

    if stats.first_meeting_start:
        first_m = parse_hhmm(stats.first_meeting_start)
        first_floor = (first_m // 60) * 60
        start_m = min(work_start, first_floor)
    else:
        start_m = work_start

    if stats.last_meeting_end:
        last_m = parse_hhmm(stats.last_meeting_end)
        last_ceil = ((last_m + 59) // 60) * 60
        end_m = max(work_end, last_ceil)
    else:
        end_m = work_end

    if end_m <= start_m:
        end_m = start_m + 60
    return start_m, end_m


def filter_hours_in_window(
    hours: Sequence[HourlyWeather],
    *,
    tz_name: str,
    window_start_m: int,
    window_end_m: int,
) -> list[HourlyWeather]:
    """Часы, чей начальный момент попадает в [window_start_m, window_end_m)."""
    out: list[HourlyWeather] = []
    for h in hours:
        hm = _minutes_from_midnight_for_hour(h.time, tz_name)
        if window_start_m <= hm < window_end_m:
            out.append(h)
    return out


def _avg(values: list[float]) -> float | None:
    return float(mean(values)) if values else None


def _min_v(values: list[float]) -> float | None:
    return min(values) if values else None


def _max_v(values: list[float]) -> float | None:
    return max(values) if values else None


def aggregate_hourly(hours: Sequence[HourlyWeather]) -> dict[str, float | int | None]:
    temps = [h.temperature for h in hours if h.temperature is not None]
    apps = [h.apparent_temperature for h in hours if h.apparent_temperature is not None]
    probs = [h.precipitation_probability for h in hours if h.precipitation_probability is not None]
    rains = [h.rain for h in hours if h.rain is not None]
    snows = [h.snowfall for h in hours if h.snowfall is not None]
    winds = [h.wind_speed for h in hours if h.wind_speed is not None]

    total_rain = float(sum(rains)) if rains else None
    total_snow = float(sum(snows)) if snows else None

    return {
        "min_temperature": _min_v([float(x) for x in temps]),
        "max_temperature": _max_v([float(x) for x in temps]),
        "avg_temperature": _avg([float(x) for x in temps]),
        "min_apparent_temperature": _min_v([float(x) for x in apps]),
        "max_apparent_temperature": _max_v([float(x) for x in apps]),
        "avg_apparent_temperature": _avg([float(x) for x in apps]),
        "max_precipitation_probability": max(probs) if probs else None,
        "total_rain": total_rain,
        "total_snowfall": total_snow,
        "max_wind_speed": _max_v([float(x) for x in winds]),
    }


WARNING_SNOW = "snow"
WARNING_RAIN_HIGH = "rain_high"
WARNING_RAIN_POSSIBLE = "rain_possible"
WARNING_VERY_COLD = "very_cold"
WARNING_COLD = "cold"
WARNING_HOT = "hot"
WARNING_STRONG_WIND = "strong_wind"
WARNING_WIND = "wind"
WARNING_NORMAL = "normal"

_PRIORITY: dict[str, int] = {
    WARNING_SNOW: 1,
    WARNING_RAIN_HIGH: 2,
    WARNING_VERY_COLD: 3,
    WARNING_HOT: 4,
    WARNING_STRONG_WIND: 5,
    WARNING_RAIN_POSSIBLE: 6,
    WARNING_COLD: 7,
    WARNING_WIND: 8,
    WARNING_NORMAL: 9,
}


def collect_warnings(metrics: Mapping[str, float | int | None]) -> list[str]:
    """Возвращает список кодов предупреждений (без normal), отсортированный по приоритету."""
    max_prob = metrics.get("max_precipitation_probability")
    total_rain = float(metrics.get("total_rain") or 0.0)
    total_snow = float(metrics.get("total_snowfall") or 0.0)
    max_wind = metrics.get("max_wind_speed")

    min_app = metrics.get("min_apparent_temperature")
    min_temp = metrics.get("min_temperature")
    min_for_cold = min_app if min_app is not None else min_temp

    max_app = metrics.get("max_apparent_temperature")
    max_temp = metrics.get("max_temperature")
    max_for_hot = max_app if max_app is not None else max_temp

    found: list[str] = []

    if total_snow >= 1.0:
        found.append(WARNING_SNOW)

    rain_high = False
    if max_prob is not None and int(max_prob) >= 70 or total_rain >= 1.0:
        rain_high = True
    if rain_high:
        found.append(WARNING_RAIN_HIGH)
    else:
        rain_possible = False
        if max_prob is not None and int(max_prob) >= 40 or total_rain > 0:
            rain_possible = True
        if rain_possible:
            found.append(WARNING_RAIN_POSSIBLE)

    if min_for_cold is not None:
        if min_for_cold <= -10:
            found.append(WARNING_VERY_COLD)
        elif min_for_cold <= 0:
            found.append(WARNING_COLD)

    if max_for_hot is not None and max_for_hot >= 30:
        found.append(WARNING_HOT)

    if max_wind is not None:
        if max_wind >= 12:
            found.append(WARNING_STRONG_WIND)
        elif max_wind >= 8:
            found.append(WARNING_WIND)

    seen: dict[str, int] = {}
    for w in found:
        p = _PRIORITY.get(w, 99)
        if w not in seen or p < seen[w]:
            seen[w] = p
    return sorted(seen.keys(), key=lambda x: _PRIORITY.get(x, 99))


def build_weather_summary(
    *,
    location_name: str,
    date_label: str,
    hours_in_window: Sequence[HourlyWeather],
    hours_full_day: Sequence[HourlyWeather],
    stats: DayCalendarStats,
    tz_name: str,
    reference_date: date,
    now: datetime | None = None,
    current_conditions: CurrentWeatherSnapshot | None = None,
) -> WeatherSummary:
    """Сводка: предупреждения по рабочему окну, максимумы и «сейчас» — по полному календарному дню."""
    window_agg = aggregate_hourly(hours_in_window)
    warnings_list = collect_warnings(window_agg)
    day_agg = aggregate_hourly(hours_full_day)

    plan_date = stats.plan_date
    is_today = plan_date == reference_date
    zi = ZoneInfo(tz_name)
    cur_temp: float | None = None
    cur_app: float | None = None
    cur_pres: float | None = None
    if is_today and current_conditions is not None:
        cur_temp = current_conditions.temperature_2m
        cur_app = current_conditions.apparent_temperature
        cur_pres = current_conditions.surface_pressure
    elif is_today:
        ref_now = now if now is not None else datetime.now(zi)
        slot = _pick_nearest_hour(hours_full_day, tz_name, ref_now)
        cur_temp = slot.temperature if slot else None
        cur_app = slot.apparent_temperature if slot else None
        cur_pres = slot.surface_pressure if slot else None
    else:
        sm = future_day_start_minutes(stats)
        target = datetime.combine(
            plan_date,
            time(hour=sm // 60, minute=sm % 60),
            tzinfo=zi,
        )
        slot = _pick_nearest_hour(hours_full_day, tz_name, target)
        cur_temp = slot.temperature if slot else None
        cur_app = slot.apparent_temperature if slot else None
        cur_pres = slot.surface_pressure if slot else None

    if cur_pres is None and is_today and hours_full_day:
        ref_now = now if now is not None else datetime.now(zi)
        slot_fb = _pick_nearest_hour(hours_full_day, tz_name, ref_now)
        cur_pres = slot_fb.surface_pressure if slot_fb else None

    return WeatherSummary(
        location_name=location_name,
        date_label=date_label,
        min_temperature=window_agg.get("min_temperature"),
        max_temperature=window_agg.get("max_temperature"),
        avg_temperature=window_agg.get("avg_temperature"),
        min_apparent_temperature=window_agg.get("min_apparent_temperature"),
        max_apparent_temperature=window_agg.get("max_apparent_temperature"),
        avg_apparent_temperature=window_agg.get("avg_apparent_temperature"),
        max_precipitation_probability=_to_int_or_none(day_agg.get("max_precipitation_probability")),
        total_rain=day_agg.get("total_rain"),
        total_snowfall=day_agg.get("total_snowfall"),
        max_wind_speed=day_agg.get("max_wind_speed"),
        warnings=tuple(warnings_list),
        current_temperature=cur_temp,
        current_apparent_temperature=cur_app,
        day_max_temperature=day_agg.get("max_temperature"),
        day_max_apparent_temperature=day_agg.get("max_apparent_temperature"),
        current_surface_pressure=cur_pres,
    )


def summarize_for_digest_day(
    hours_for_date: Sequence[HourlyWeather],
    stats: DayCalendarStats,
    options: WorkdayOptions,
    *,
    location_name: str,
    tz_name: str,
    reference_date: date,
    now: datetime | None = None,
    current_conditions: CurrentWeatherSnapshot | None = None,
) -> WeatherSummary:
    start_m, end_m = weather_analysis_window_minutes(stats, options)
    windowed = filter_hours_in_window(
        hours_for_date,
        tz_name=tz_name,
        window_start_m=start_m,
        window_end_m=end_m,
    )
    return build_weather_summary(
        location_name=location_name,
        date_label=stats.date_label,
        hours_in_window=windowed,
        hours_full_day=hours_for_date,
        stats=stats,
        tz_name=tz_name,
        reference_date=reference_date,
        now=now,
        current_conditions=current_conditions,
    )
