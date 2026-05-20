"""Сборка финального сообщения дайджеста (plain text, безопасно для HTML)."""

from __future__ import annotations

from html import escape
from typing import Sequence

from ..calendar.events import event_index_marker, pizza_meal_kind
from ..calendar.stats import DayCalendarStats, NormalizedEvent
from ..calendar.time_utils import format_hhmm, merge_intervals
from ..messages_ru import (
    PLAN_STATS_BREAKFAST,
    PLAN_STATS_DINNER,
    PLAN_STATS_LUNCH,
    format_duration_ru,
)
from . import templates as t
from .rules import SeagullTexts

PENDING_MARK = "⚠️"
TENTATIVE_MARK = "⚖️"
MAX_DIGEST_MESSAGE_LEN = 3800
TRUNCATED_NOTICE = "…\n\nСообщение укорочено: встреч слишком много для одного сообщения."
MAX_EVENT_FIELD_CHARS = 320

_RELATIVE_WORD_LOWER = {
    t.LABEL_TODAY: "сегодня",
    t.LABEL_TOMORROW: "завтра",
    t.LABEL_DAY_AFTER: "послезавтра",
}


def _html_b(fragment: str) -> str:
    """Telegram HTML: жирный текст. Аргумент — без пользовательского HTML."""
    return f"<b>{fragment}</b>"


def _ellipsize(text: str, *, max_chars: int = MAX_EVENT_FIELD_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"


def _join_with_telegram_limit(
    lines: Sequence[str], *, max_len: int = MAX_DIGEST_MESSAGE_LEN
) -> str:
    text = "\n".join(lines)
    if len(text) <= max_len:
        return text

    suffix = "\n" + TRUNCATED_NOTICE
    limit = max(0, max_len - len(suffix))
    kept: list[str] = []
    current_len = 0
    for line in lines:
        addition = len(line) + (1 if kept else 0)
        if kept and current_len + addition > limit:
            break
        if not kept and len(line) > limit:
            kept.append(_ellipsize(line, max_chars=limit))
            break
        kept.append(line)
        current_len += addition

    if not kept:
        return TRUNCATED_NOTICE[:max_len]
    return "\n".join(kept).rstrip() + suffix


def _forecast_header(stats: DayCalendarStats) -> str:
    """Первая строка: «📬 Прогноз на сегодня (11.09.2026)».

    Эмодзи 📬 идёт обычным шрифтом, текст после него — жирным (Telegram HTML).
    """
    date_str = stats.plan_date.strftime("%d.%m.%Y")
    rel = _RELATIVE_WORD_LOWER.get(stats.date_label)
    if rel:
        raw = t.FORECAST_HEADER_RELATIVE.format(rel=rel, date=date_str)
    else:
        raw = t.FORECAST_HEADER_PLAIN_DATE.format(date=date_str)
    return f"📬 {_html_b(raw)}"


def _meal_stats_lines_from_normalized(
    events: Sequence[NormalizedEvent],
) -> list[str]:
    by_kind: dict[str, list[NormalizedEvent]] = {"breakfast": [], "lunch": [], "dinner": []}
    for ev in events:
        kind = pizza_meal_kind(ev.title)
        if kind:
            by_kind[kind].append(ev)
    templates = {
        "breakfast": PLAN_STATS_BREAKFAST,
        "lunch": PLAN_STATS_LUNCH,
        "dinner": PLAN_STATS_DINNER,
    }
    lines: list[str] = []
    for kind in ("breakfast", "lunch", "dinner"):
        group = by_kind[kind]
        if not group:
            continue
        merged = merge_intervals([(e.start_minutes, e.end_minutes) for e in group])
        interval = ", ".join(
            f"{format_hhmm(s)} – {format_hhmm(e)}" for s, e in merged
        )
        lines.append(templates[kind].format(interval=interval))
    return lines


def render_daily_digest(
    stats: DayCalendarStats,
    texts: SeagullTexts,
    *,
    meal_footer_events: tuple[NormalizedEvent, ...] = (),
    escape_html: bool = True,
    weather_line: str | None = None,
) -> str:
    """Собирает текст сообщения «чайки» одной строкой.

    Рассчитано на отправку в Telegram с ``parse_mode="HTML"``: заголовок прогноза,
    строки «Первая/Последняя встреча» (только время), заголовок блока расписания
    и интервал времени в строке события обёрнуты в ``<b>…</b>``.

    Параметры:
    - `meal_footer_events` — события «🍕+приём пищи», исключённые из расписания
      (например из-за ``HIDE_LUNCH_EVENTS``), но нужные для строк внизу сообщения.
    - `escape_html` — экранировать пользовательские поля (title, location).
      Удобно при отправке с parse_mode="HTML"; для plain-text можно выключить.
    - `weather_line` — готовая строка погодного блока (без HTML); вставляется
      сразу после заголовка прогноза, затем основной текст и пересечения,
      строки первой/последней встречи и детальное расписание.
    """
    lines: list[str] = [_forecast_header(stats)]
    lines.append("")

    if weather_line:
        lines.append(weather_line)
        lines.append("")

    lines.append(texts.main)

    if stats.meetings_count > 0 and texts.overlaps:
        lines.append(texts.overlaps)

    lines.append("")
    lines.append(
        _html_b(t.FIRST_LINE.format(value=stats.first_meeting_start or t.NO_VALUE))
    )
    last_template = t.LAST_LINE if stats.last_meeting_end else t.LAST_LINE_EMPTY
    lines.append(
        _html_b(last_template.format(value=stats.last_meeting_end or t.NO_VALUE))
    )
    lines.append("")
    lines.append(_html_b(t.SCHEDULE_TITLE))

    if stats.meetings_count == 0:
        lines.append(t.EMPTY_SCHEDULE)
        lines.append("")
    else:
        events = list(stats.events)
        for index, ev in enumerate(events):
            lines.extend(_render_event(index, ev, escape_html=escape_html))
            if index < len(events) - 1:
                lines.append("")
        lines.append("")

    lines.append(t.BUSY_LINE.format(value=format_duration_ru(stats.busy_minutes)))
    lines.append(t.FREE_LINE.format(value=format_duration_ru(stats.free_minutes)))
    meal_sources = tuple(stats.events) + tuple(meal_footer_events)
    for meal_line in _meal_stats_lines_from_normalized(meal_sources):
        lines.append(meal_line)

    return _join_with_telegram_limit(lines)


def _render_event(index: int, ev: NormalizedEvent, *, escape_html: bool) -> list[str]:
    if ev.is_tentative:
        marker = TENTATIVE_MARK
    elif ev.is_pending:
        marker = PENDING_MARK
    else:
        marker = event_index_marker(index)
    title_raw = _ellipsize(ev.title.strip() or t.EVENT_NO_TITLE)
    location_raw = _ellipsize(ev.location or t.ROOM_NONE)
    title = escape(title_raw) if escape_html else title_raw
    location = escape(location_raw) if escape_html else location_raw
    time_range = f"{ev.start_hhmm}–{ev.end_hhmm}"
    return [
        f"{marker} {_html_b(time_range)} — {title}",
        t.ROOM_LINE.format(location=location),
    ]
