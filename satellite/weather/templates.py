"""Текстовые шаблоны погодного блока в стиле «Чайки» (без слова «Чайка»)."""

from __future__ import annotations

import random
from collections.abc import Sequence

from .analyzer import (
    WARNING_COLD,
    WARNING_HOT,
    WARNING_NORMAL,
    WARNING_RAIN_HIGH,
    WARNING_RAIN_POSSIBLE,
    WARNING_SNOW,
    WARNING_STRONG_WIND,
    WARNING_VERY_COLD,
    WARNING_WIND,
    _PRIORITY,
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
    "барометр на клюве — {mm} мм рт. ст.",
    "атмосфера с запасом плавучести: {mm} мм рт. ст.",
    "на уровне моря (ну почти): {mm} мм рт. ст.",
    "давление под крылом около {mm} мм рт. ст.",
    "высоту не набираем — {mm} мм рт. ст.",
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
        parts.append(f"осадки до {int(precipitation_probability)}%")

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
        "🌧 Мокрый перелёт: {weatherDetails}. Зонт лучше держать под крылом.",
        "🌧 Небо может протечь: {weatherDetails}. Лучше не лететь с мокрыми перьями.",
        "🌧 На маршруте мокрый воздух: {weatherDetails}. Зонт лучше держать под крылом.",
        "🌧 Дождевой фронт на горизонте: {weatherDetails}. Сухой перелёт не гарантирован.",
    ],
    WARNING_RAIN_POSSIBLE: [
        "🌦 Небо выглядит подозрительно: {weatherDetails}. Сухому асфальту сегодня лучше не доверять.",
        "🌦 Возможны капли с неба: {weatherDetails}. Зонт можно взять как запасное крыло.",
        "🌦 Погода колеблется у пирса: {weatherDetails}. Может быть сухо, а может и промочить перья.",
    ],
    WARNING_SNOW: [
        "❄️ Снежный перелёт: {weatherDetails}. Может быть скользко, лучше заложить запас по времени.",
        "❄️ На маршруте белые хлопья: {weatherDetails}. Крылья держать аккуратно, шаг не ускорять.",
        "❄️ Снег на горизонте: {weatherDetails}. Перелёт может стать медленнее и скользче.",
        "❄️ Берег заметает: {weatherDetails}. Лучше выйти с запасом и не планировать героический взлёт.",
    ],
    WARNING_VERY_COLD: [
        "🥶 Серьёзный холод: {weatherDetails}. Перья лучше утеплить.",
        "🥶 Морозный воздух: {weatherDetails}. Вылетать без тёплого слоя — сомнительное решение.",
        "🥶 Холод кусает за крылья: {weatherDetails}. Лучше одеться плотнее.",
        "🥶 Погода не для тонких перьев: {weatherDetails}. Утепление обязательно.",
    ],
    WARNING_COLD: [
        "❄️ Прохладно: {weatherDetails}. Лучше не выходить в режиме «я быстро».",
        "❄️ Воздух бодрый: {weatherDetails}. Лёгкая куртка спасёт крылья от лишней драмы.",
        "❄️ На берегу свежо: {weatherDetails}. Лучше не изображать летнюю птицу.",
    ],
    WARNING_STRONG_WIND: [
        "💨 Ветер толкает в крыло: {weatherDetails}. На улице лучше держать курс аккуратнее.",
        "💨 Порывы серьёзные: {weatherDetails}. Лёгкий транспорт может унести в сторону пирса.",
        "💨 Сильный ветер: {weatherDetails}. Самокат сегодня выглядит как спорное архитектурное решение.",
        "💨 Ветер с характером: {weatherDetails}. Сегодня лучше без героических манёвров.",
    ],
    WARNING_WIND: [
        "🌬 Ветер заметный: {weatherDetails}. Лучше держать курс аккуратнее.",
        "🌬 Воздух шевелит перья: {weatherDetails}. Ничего страшного, но маршрут лучше не усложнять.",
        "🌬 Лёгкая болтанка на маршруте: {weatherDetails}. Курс держать спокойно.",
    ],
    WARNING_HOT: [
        "🔥 На берегу жарит: {weatherDetails}. Воду лучше взять, крылья не перегревать.",
        "🔥 Воздух горячий: {weatherDetails}. Дальний перелёт без воды — плохая идея.",
        "🔥 Жаркое небо: {weatherDetails}. Вода пригодится, героизм на солнце — нет.",
        "🔥 Солнце работает без выходных: {weatherDetails}. Лучше держаться тени и пить воду.",
    ],
    WARNING_NORMAL: [
        "🌤 Небо спокойное: {weatherDetails}. Перелёт по погоде без сюрпризов.",
        "🌤 На маршруте чисто: {weatherDetails}. Крылья можно не напрягать.",
        "🌤 Воздух ровный, берег спокоен: {weatherDetails}. Погодных тревог нет.",
        "🌤 Погода без драмы: {weatherDetails}. Поводов кричать с мачты нет.",
    ],
}

_COMBINED: dict[frozenset[str], list[str]] = {
    frozenset({WARNING_RAIN_HIGH, WARNING_STRONG_WIND}): [
        "🌧💨 Мокрый и ветреный перелёт: {weatherDetails}. Зонт лучше взять, самокат — под вопросом.",
    ],
    frozenset({WARNING_SNOW, WARNING_STRONG_WIND}): [
        "❄️💨 Снег и ветер: {weatherDetails}. Маршрут может быть скользким, холодным и немного злым.",
    ],
    frozenset({WARNING_VERY_COLD, WARNING_STRONG_WIND}): [
        "🥶💨 Холодный ветер: {weatherDetails}. Перья утеплить, скорость не геройствовать.",
    ],
    frozenset({WARNING_RAIN_HIGH, WARNING_VERY_COLD}): [
        "🌧🥶 Мокро и холодно: {weatherDetails}. Лучший день для тёплого слоя и запасного времени.",
    ],
    frozenset({WARNING_HOT, WARNING_STRONG_WIND}): [
        "🔥💨 Жарко и ветрено: {weatherDetails}. Воду взять, крылья не перегревать, маршрут не усложнять.",
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
