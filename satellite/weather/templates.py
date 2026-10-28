"""Текстовые шаблоны погодного блока в стиле «Чайки» (без слова «Чайка»)."""

from __future__ import annotations

import random
from collections.abc import Sequence

from .analyzer import (
    _PRIORITY,
    WARNING_COLD,
    WARNING_HOT,
    WARNING_NORMAL,
    WARNING_RAIN_HIGH,
    WARNING_RAIN_POSSIBLE,
    WARNING_SNOW,
    WARNING_STRONG_WIND,
    WARNING_VERY_COLD,
    WARNING_WIND,
)
from .models import WeatherSummary


def format_temperature(value: float | int | None) -> str | None:
    if value is None:
        return None
    rounded = int(round(float(value)))
    if rounded > 0:
        return f"+{rounded}°C"
    if rounded == 0:
        return "0°C"
    return f"{rounded}°C"


# Перевод гПа → мм рт. ст. (конвенция ISO 80000-4).
_HPA_TO_MMHG = 0.7500616827041699


def format_surface_pressure_mmhg(hpa: float) -> int:
    return int(round(float(hpa) * _HPA_TO_MMHG))


_PRESSURE_QUIPS: tuple[str, ...] = (
    "давление — {mm} мм рт. ст.",
    "барометр показывает {mm} мм рт. ст.",
    "атмосферное давление — {mm} мм рт. ст.",
    "давление около {mm} мм рт. ст.",
    "на барометре {mm} мм рт. ст.",
)


def _pick_pressure_quip(mm_hg: int, seed: str) -> str:
    idx = random.Random(seed + "|pressure").randrange(0, len(_PRESSURE_QUIPS))
    return _PRESSURE_QUIPS[idx].format(mm=mm_hg)


def build_weather_details(
    current_temperature: float | None,
    max_temperature: float | None,
    precipitation_probability: int | None,
    *,
    is_today: bool,
) -> str:
    """Собирает фрагмент «сейчас …, днём до …, осадки до …» без лишних запятых."""
    parts: list[str] = []
    cur_s = format_temperature(current_temperature)
    max_s = format_temperature(max_temperature)

    if is_today:
        if cur_s:
            parts.append(f"сейчас {cur_s}")
        if max_s:
            parts.append(f"днём до {max_s}")
    else:
        if cur_s:
            parts.append(f"на старте {cur_s}")
        if max_s:
            parts.append(f"днём до {max_s}")

    if precipitation_probability is not None:
        parts.append(f"вероятность осадков до {int(precipitation_probability)}%")

    return ", ".join(parts)


def build_weather_details_text(
    summary: WeatherSummary,
    *,
    is_today: bool,
    phrase_seed: str = "",
) -> str:
    """Фрагмент для подстановки в шаблоны (ощущаемая температура предпочтительнее)."""
    disp_cur = (
        summary.current_apparent_temperature
        if summary.current_apparent_temperature is not None
        else summary.current_temperature
    )
    disp_max = (
        summary.day_max_apparent_temperature
        if summary.day_max_apparent_temperature is not None
        else summary.day_max_temperature
    )
    base = build_weather_details(
        disp_cur,
        disp_max,
        summary.max_precipitation_probability,
        is_today=is_today,
    )
    hpa = summary.current_surface_pressure
    if hpa is None:
        return base
    quip = _pick_pressure_quip(format_surface_pressure_mmhg(hpa), phrase_seed)
    if base:
        return f"{base}, {quip}"
    return quip


def _inject_weather_details(template: str, weather_details: str) -> str:
    wd = weather_details.strip()
    if wd:
        return template.replace("{weatherDetails}", wd)
    cleaned = (
        template.replace(": {weatherDetails}.", ".")
        .replace(": {weatherDetails}", "")
        .replace("{weatherDetails}", "")
    )
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    cleaned = cleaned.replace(" . ", " ").replace("  ", " ").strip()
    return cleaned


def _pick_template(templates: Sequence[str], *, seed: str) -> str:
    """Детерминированный выбор для стабильных тестов."""
    if not templates:
        return ""
    idx = random.Random(seed).randrange(0, len(templates))
    return templates[idx]


_SINGLE: dict[str, list[str]] = {
    WARNING_RAIN_HIGH: [
        "🌧 Вероятен дождь: {weatherDetails}. Возьми зонт — перья лучше оставить сухими.",
        "🌧 Похоже, будет дождь: {weatherDetails}. Зонт пригодится.",
        "🌧 На маршруте вероятен дождь: {weatherDetails}. Лучше взять зонт.",
        "🌧 Высока вероятность дождя: {weatherDetails}. Держи зонт под рукой.",
    ],
    WARNING_RAIN_POSSIBLE: [
        "🌦 Возможен дождь: {weatherDetails}. Зонт может пригодиться.",
        "🌦 На горизонте возможен дождь: {weatherDetails}. Возьми зонт на всякий случай.",
        "🌦 Погода переменчивая: {weatherDetails}. Дождь не исключён — зонт пригодится.",
    ],
    WARNING_SNOW: [
        "❄️ Ожидается снег: {weatherDetails}. Может быть скользко, оставь запас времени на дорогу.",
        "❄️ На маршруте снег: {weatherDetails}. Иди осторожно, может быть скользко.",
        "❄️ Снег на горизонте: {weatherDetails}. Дорога может занять больше времени.",
        "❄️ Снежная погода: {weatherDetails}. Лучше выйти пораньше и не спешить.",
    ],
    WARNING_VERY_COLD: [
        "🥶 Сильный мороз: {weatherDetails}. Пора утеплять перья.",
        "🥶 Очень холодно: {weatherDetails}. Одевайся теплее.",
        "🥶 Морозный день: {weatherDetails}. Тёплая одежда точно пригодится.",
        "🥶 Серьёзный холод: {weatherDetails}. Перед выходом оденься потеплее.",
    ],
    WARNING_COLD: [
        "❄️ На улице холодно: {weatherDetails}. Возьми тёплую одежду, даже если выходишь ненадолго.",
        "❄️ Холодный воздух: {weatherDetails}. Лучше одеться потеплее.",
        "❄️ На берегу прохладно: {weatherDetails}. Летние вещи пока отложим.",
    ],
    WARNING_STRONG_WIND: [
        "💨 Сильный ветер: {weatherDetails}. На улице будь осторожнее.",
        "💨 Сильные порывы ветра: {weatherDetails}. Поездку на самокате лучше отложить.",
        "💨 Ветер с характером: {weatherDetails}. Сегодня лучше обойтись без самоката.",
        "💨 Сильный ветер: {weatherDetails}. Выбирай маршрут осторожно.",
    ],
    WARNING_WIND: [
        "🌬 Ветрено: {weatherDetails}. Учти это, если собираешься надолго на улицу.",
        "🌬 Ветер шевелит перья: {weatherDetails}. На улице будет ветрено.",
        "🌬 Заметный ветер: {weatherDetails}. Выбирай маршрут с учётом погоды.",
    ],
    WARNING_HOT: [
        "🔥 Жарко: {weatherDetails}. Возьми воду и делай перерывы в тени.",
        "🔥 Горячий воздух: {weatherDetails}. В долгую дорогу лучше взять воду.",
        "🔥 Жаркий день: {weatherDetails}. Держись тени и не забывай пить воду.",
        "🔥 На берегу жара: {weatherDetails}. Вода с собой будет кстати.",
    ],
    WARNING_NORMAL: [
        "🌤 Спокойная погода: {weatherDetails}. Погодных предупреждений нет.",
        "🌤 На маршруте без погодных предупреждений: {weatherDetails}.",
        "🌤 Воздух спокоен: {weatherDetails}. Можно планировать день без поправок на непогоду.",
        "🌤 Погода без драмы: {weatherDetails}. Предупреждений нет.",
    ],
}

_COMBINED: dict[frozenset[str], list[str]] = {
    frozenset({WARNING_RAIN_HIGH, WARNING_STRONG_WIND}): [
        "🌧💨 Вероятны дождь и сильный ветер: {weatherDetails}. Возьми зонт, а самокат лучше оставь дома.",
    ],
    frozenset({WARNING_SNOW, WARNING_STRONG_WIND}): [
        "❄️💨 Снег и сильный ветер: {weatherDetails}. На дороге может быть скользко. Оставь запас времени.",
    ],
    frozenset({WARNING_VERY_COLD, WARNING_STRONG_WIND}): [
        "🥶💨 Сильный мороз и ветер: {weatherDetails}. Одевайся теплее и не спеши в дороге.",
    ],
    frozenset({WARNING_RAIN_HIGH, WARNING_VERY_COLD}): [
        "🌧🥶 Вероятен дождь, очень холодно: {weatherDetails}. Оденься теплее и оставь запас времени на дорогу.",
    ],
    frozenset({WARNING_HOT, WARNING_STRONG_WIND}): [
        "🔥💨 Жарко, сильный ветер: {weatherDetails}. Возьми воду и выбирай маршрут осторожно.",
    ],
}


def build_weather_message(
    summary: WeatherSummary,
    *,
    show_normal_weather: bool,
    message_seed: str = "",
    digest_is_today: bool = True,
) -> str | None:
    """Одна-две строки для вставки в дайджест или None."""
    details = build_weather_details_text(
        summary,
        is_today=digest_is_today,
        phrase_seed=message_seed,
    )
    warnings = list(summary.warnings)

    if not warnings:
        if not show_normal_weather:
            return None
        tpl = _pick_template(_SINGLE[WARNING_NORMAL], seed=message_seed + "normal")
        return _inject_weather_details(tpl, details)

    ordered = sorted(warnings, key=lambda w: _PRIORITY.get(w, 99))
    top_two = ordered[:2]

    if len(top_two) == 2:
        key = frozenset(top_two)
        combined = _COMBINED.get(key)
        if combined:
            tpl = _pick_template(combined, seed=message_seed + "|".join(sorted(top_two)))
            return _inject_weather_details(tpl, details)
        primary = top_two[0]
        tpl = _pick_template(_SINGLE[primary], seed=message_seed + primary)
        return _inject_weather_details(tpl, details)

    primary = top_two[0]
    tpl = _pick_template(_SINGLE[primary], seed=message_seed + primary)
    return _inject_weather_details(tpl, details)


def seagull_style_tokens_present(text: str) -> bool:
    """Грубая проверка «морской» стилистики для тестов."""
    lowered = text.lower()
    tokens = (
        "крыл",
        "перь",
        "мачт",
        "берег",
        "пирс",
        "перелёт",
        "перелет",
        "курс",
        "мокр",
        "ветер",
        "взлёт",
        "взлет",
        "горизонт",
        "маршрут",
        "небо",
        "воздух",
        "барометр",
        "плавучест",
        "высоту",
    )
    return any(t in lowered for t in tokens)
