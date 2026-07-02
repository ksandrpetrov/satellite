"""Rich Message рендер дайджеста (Bot API 10.1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, tzinfo

from ..calendar.events import event_index_marker
from ..calendar.stats import DayCalendarStats, NormalizedEvent
from ..messages_ru import (
    format_duration_ru,
)
from ..telegram_bot.rich_message import (
    anchor,
    anchor_link,
    blockquote,
    bold,
    datetime_link,
    details_block,
    divider,
    escape_rich,
    footnote_def,
    footnote_ref,
    join_blocks,
    paragraph,
    pull_quote,
    section_heading,
    table,
    truncate_rich_html,
)
from . import templates as t
from .render import (
    PENDING_MARK,
    TENTATIVE_MARK,
    _ellipsize,
    _meal_stats_lines_from_normalized,
)
from .rules import SeagullTexts

_SCHEDULE_DETAILS_MIN_MEETINGS = 4
_ANCHOR_FORECAST = "forecast"
_ANCHOR_SCHEDULE = "schedule"
_LONG_DAY_MEETINGS = 10


def _relative_forecast_title(stats: DayCalendarStats) -> str:
    date_str = stats.plan_date.strftime("%d.%m.%Y")
    rel_map = {
        t.LABEL_TODAY: "сегодня",
        t.LABEL_TOMORROW: "завтра",
        t.LABEL_DAY_AFTER: "послезавтра",
    }
    rel = rel_map.get(stats.date_label)
    if rel:
        raw = t.FORECAST_HEADER_RELATIVE.format(rel=rel, date=date_str)
    else:
        raw = t.FORECAST_HEADER_PLAIN_DATE.format(date=date_str)
    return f"📬 {raw}"


def _event_start_unix(plan_date: date, start_minutes: int, tz: tzinfo) -> int:
    base = datetime.combine(plan_date, datetime.min.time(), tzinfo=tz)
    return int((base + timedelta(minutes=start_minutes)).timestamp())


def _render_event_rich(
    index: int,
    ev: NormalizedEvent,
    *,
    plan_date: date,
    tz: tzinfo,
) -> str:
    if ev.is_tentative:
        marker = TENTATIVE_MARK
    elif ev.is_pending:
        marker = PENDING_MARK
    else:
        marker = event_index_marker(index)
    title_raw = _ellipsize(ev.title.strip() or t.EVENT_NO_TITLE)
    location_raw = _ellipsize(ev.location or t.ROOM_NONE)
    title = escape_rich(title_raw)
    time_label = f"{ev.start_hhmm}–{ev.end_hhmm}"
    time_html = datetime_link(time_label, _event_start_unix(plan_date, ev.start_minutes, tz))
    lines = paragraph(f"{marker} {bold(time_html)} — {title}")
    lines += paragraph(escape_rich(t.ROOM_LINE.format(location=location_raw)))
    return lines


def _schedule_block(
    stats: DayCalendarStats,
    *,
    tz: tzinfo,
) -> str:
    if stats.meetings_count == 0:
        return paragraph(bold(escape_rich(t.SCHEDULE_TITLE))) + paragraph(
            escape_rich(t.EMPTY_SCHEDULE)
        )

    events = list(stats.events)
    event_blocks = [
        _render_event_rich(index, ev, plan_date=stats.plan_date, tz=tz)
        for index, ev in enumerate(events)
    ]
    body = join_blocks(event_blocks)
    summary = bold(
        escape_rich(
            t.SCHEDULE_TITLE_WITH_COUNT.format(
                title=t.SCHEDULE_TITLE,
                count=stats.meetings_count,
            )
        )
    )
    schedule = anchor(_ANCHOR_SCHEDULE) + (
        details_block(summary, body, open=True)
        if stats.meetings_count >= _SCHEDULE_DETAILS_MIN_MEETINGS
        else paragraph(summary) + body
    )
    return schedule


def _stats_table(stats: DayCalendarStats) -> str:
    """Таблица «Тип / Время»: занято и свободно за день.

    Количество встреч строкой таблицы не дублируем — оно уже в заголовке
    расписания («Расписание — N встреч»), а в колонке «Время» число без
    единиц читалось как ошибка.
    """
    return table(
        [t.RICH_STATS_HEADER_TYPE, t.RICH_STATS_HEADER_TIME],
        [
            [t.RICH_STATS_ROW_BUSY, escape_rich(format_duration_ru(stats.busy_minutes))],
            [t.RICH_STATS_ROW_FREE, escape_rich(format_duration_ru(stats.free_minutes))],
        ],
    )


def render_daily_digest_rich(
    stats: DayCalendarStats,
    texts: SeagullTexts,
    *,
    meal_footer_events: Sequence[NormalizedEvent] = (),
    weather_line: str | None = None,
    tz: tzinfo,
) -> str:
    """Rich HTML дайджест для ``sendRichMessage``."""
    title = escape_rich(_relative_forecast_title(stats))
    heading = section_heading(title, level=2)
    if stats.meetings_count > _LONG_DAY_MEETINGS:
        heading = anchor(_ANCHOR_FORECAST) + heading
    blocks: list[str] = [heading]

    if weather_line:
        blocks.append(blockquote(escape_rich(weather_line)))

    blocks.append(pull_quote(escape_rich(texts.main), author="Чайка"))

    if stats.meetings_count > 0 and texts.overlaps:
        blocks.append(blockquote(escape_rich(texts.overlaps)))

    blocks.append(divider())

    first_val = stats.first_meeting_start or t.NO_VALUE
    blocks.append(paragraph(bold(escape_rich(t.FIRST_LINE.format(value=first_val)))))
    last_template = t.LAST_LINE if stats.last_meeting_end else t.LAST_LINE_EMPTY
    last_val = stats.last_meeting_end or t.NO_VALUE
    blocks.append(paragraph(bold(escape_rich(last_template.format(value=last_val)))))

    blocks.append(_schedule_block(stats, tz=tz))
    blocks.append(_stats_table(stats))

    meal_sources = tuple(stats.events) + tuple(meal_footer_events)
    for meal_line in _meal_stats_lines_from_normalized(meal_sources):
        blocks.append(paragraph(escape_rich(meal_line)))

    if stats.meetings_count > _LONG_DAY_MEETINGS:
        blocks.append(
            paragraph(
                footnote_ref("sched")
                + " "
                + anchor_link("Подробнее о расписании", _ANCHOR_SCHEDULE)
                + " · "
                + anchor_link("↑ К прогнозу", _ANCHOR_FORECAST)
            )
        )
        blocks.append(footnote_def("sched", escape_rich("Полное расписание — в блоке ниже.")))

    html = join_blocks(blocks)
    return truncate_rich_html(html)
