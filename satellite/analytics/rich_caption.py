"""Rich Message подпись к PNG недельной аналитики."""

from __future__ import annotations

from ..calendar.period_stats import AnalyticsReport
from ..messages_ru import format_duration_ru
from ..telegram_bot.rich_message import (
    bold,
    escape_rich,
    footnote_def,
    join_blocks,
    mark,
    paragraph,
    section_heading,
    table,
    truncate_rich_html,
)
from . import templates as t
from .caption import _compare_line, _trend_line, _week_tone


def _week_label(report: AnalyticsReport) -> str:
    start = report.current.week_start
    end = report.current.week_end
    return t.RICH_WEEK_LABEL.format(
        start=start.strftime("%d.%m"),
        end=end.strftime("%d.%m.%Y"),
    )


def build_analytics_rich_caption(report: AnalyticsReport) -> str:
    busy_cur = format_duration_ru(report.current.total_busy)
    free_cur = format_duration_ru(report.current.total_free)
    busy_prev = format_duration_ru(report.previous.total_busy)
    free_prev = format_duration_ru(report.previous.total_free)

    blocks = [
        section_heading(escape_rich(_week_label(report)), level=3),
        paragraph(escape_rich(_week_tone(report.current.load_percent))),
        table(
            [
                t.RICH_TABLE_HEADER_METRIC,
                t.RICH_TABLE_HEADER_THIS_WEEK,
                t.RICH_TABLE_HEADER_LAST_WEEK,
            ],
            [
                [
                    t.RICH_TABLE_ROW_BUSY,
                    escape_rich(busy_cur),
                    escape_rich(busy_prev),
                ],
                [
                    t.RICH_TABLE_ROW_FREE,
                    escape_rich(free_cur),
                    escape_rich(free_prev),
                ],
                [
                    t.RICH_TABLE_ROW_LOAD,
                    bold(f"{report.current.load_percent}%"),
                    bold(f"{report.previous.load_percent}%"),
                ],
            ],
        ),
        paragraph(_compare_rich(report)),
        paragraph(escape_rich(_trend_line(report))),
        footnote_def(
            "metrics",
            escape_rich(
                "Занято — встречи в рабочем окне (без обедов и all-day); "
                "сравнение — с прошлой неделей."
            ),
        ),
    ]
    return truncate_rich_html(join_blocks(blocks))


def _compare_rich(report: AnalyticsReport) -> str:
    line = _compare_line(report)
    delta_pct = abs(report.current.load_percent - report.previous.load_percent)
    escaped = escape_rich(line)
    if delta_pct > 10:
        return mark(escaped)
    return escaped
