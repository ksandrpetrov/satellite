"""Высокоуровневый API: события календаря → готовое сообщение дайджеста.

Тонкая обёртка над `calculate_day_stats + build_seagull_texts + render_daily_digest`.
Принимает события в формате проекта (`summary/dtstart/dtend/location`) и сама
адаптирует их к минутам от полуночи относительно локального часового пояса.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, tzinfo

from ..calendar.stats import (
    DayCalendarStats,
    NormalizedEvent,
    WorkdayOptions,
    calculate_day_stats,
    normalize_caldav_event,
)
from . import templates as t
from .render import render_daily_digest
from .rules import build_seagull_texts

_LABEL_BY_DELTA = {
    0: t.LABEL_TODAY,
    1: t.LABEL_TOMORROW,
    2: t.LABEL_DAY_AFTER,
}


def prepare_seagull_stats(
    events: Sequence[Mapping[str, object]],
    plan_date: date,
    *,
    tz: tzinfo,
    options: WorkdayOptions | None = None,
    reference_date: date | None = None,
    login: str | None = None,
    hidden_meal_events: Sequence[Mapping[str, object]] = (),
) -> tuple[DayCalendarStats, tuple[NormalizedEvent, ...]]:
    """Нормализация событий и расчёт метрик дня (без текстов и без рендера)."""
    ref = reference_date if reference_date is not None else datetime.now(tz=tz).date()
    label = _date_label(plan_date, ref)
    opts = options or WorkdayOptions()

    normalized: list[NormalizedEvent] = []
    for ev in events:
        ne = normalize_caldav_event(ev, plan_date, tz, login=login)
        if ne is None or ne.is_cancelled:
            continue
        normalized.append(ne)

    meal_footer: list[NormalizedEvent] = []
    for ev in hidden_meal_events:
        ne = normalize_caldav_event(ev, plan_date, tz, login=login)
        if ne is None or ne.is_cancelled:
            continue
        meal_footer.append(ne)

    stats = calculate_day_stats(normalized, date_label=label, plan_date=plan_date, options=opts)
    return stats, tuple(meal_footer)


def render_digest_from_stats(
    stats: DayCalendarStats,
    meal_footer: Sequence[NormalizedEvent] = (),
    *,
    escape_html: bool = True,
    weather_line: str | None = None,
) -> str:
    """Финальный рендер сообщения из уже посчитанных метрик.

    Точка переиспользования между ``build_seagull_digest`` (тесты, чистый путь
    без CalDAV) и ``PlanBuilder`` (production: stats нужны раньше — для погоды).
    Хранится единая логика «правила → рендер» в одном месте.
    """
    texts = build_seagull_texts(stats)
    return render_daily_digest(
        stats,
        texts,
        meal_footer_events=meal_footer,
        escape_html=escape_html,
        weather_line=weather_line,
    )


def build_seagull_digest(
    events: Sequence[Mapping[str, object]],
    plan_date: date,
    *,
    tz: tzinfo,
    options: WorkdayOptions | None = None,
    reference_date: date | None = None,
    escape_html: bool = True,
    login: str | None = None,
    hidden_meal_events: Sequence[Mapping[str, object]] = (),
    weather_line: str | None = None,
) -> str:
    """Сборка сообщения «чайки» из проектных событий на конкретную дату.

    Семантика:
    - `tz` — локальный часовой пояс пользователя (CalDAV даёт UTC/aware-datetime).
    - `reference_date` — «сегодня» для выбора метки "Сегодня/Завтра/Послезавтра".
      Если не задано, берётся текущая дата в `tz`.
    - `options` — окна рабочего дня и обеда. По умолчанию 10:00–19:00 / 13:00–14:00.
    - `hidden_meal_events` — «🍕+завтрак/обед/ужин», не попавшие в `events`
      (например отфильтрованные ``HIDE_LUNCH_EVENTS``): по ним строятся строки
      внизу дайджеста с интервалами из календаря.
    - `login` — e-mail пользователя; если указан, неподтверждённые встречи
      (PARTSTAT != ACCEPTED) помечаются ⚠️ вместо номера в расписании.
    - `weather_line` — опциональная строка погодного комментария (уже отформатированная).
    """
    stats, meal_footer = prepare_seagull_stats(
        events,
        plan_date,
        tz=tz,
        options=options,
        reference_date=reference_date,
        login=login,
        hidden_meal_events=hidden_meal_events,
    )
    return render_digest_from_stats(
        stats,
        meal_footer,
        escape_html=escape_html,
        weather_line=weather_line,
    )


def _date_label(plan_date: date, reference_date: date) -> str:
    delta = (plan_date - reference_date).days
    if delta in _LABEL_BY_DELTA:
        return _LABEL_BY_DELTA[delta]
    return plan_date.strftime("%d.%m.%Y")
