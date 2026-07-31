"""Rich Message подпись к PNG недельной аналитики."""

from __future__ import annotations

from ..calendar.period_stats import AnalyticsReport
from ..messages_ru import format_duration_ru
from ..presentation.rich import (
    bold,
    escape_rich,
    footnote_def,
    join_blocks,
    paragraph,
    section_heading,
    table,
    truncate_rich_html,
)
from . import templates as t
from .caption import (
    _comparison,
    _overlap_details,
    _quality_line,
    _week_tone,
)


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
        paragraph(_trend_rich(report)),
        footnote_def(
            "metrics",
            escape_rich(
                "Занято — встречи в рабочем окне; обычные встречи 13:00–14:00 считаются, "
                "события-приёмы пищи и all-day — нет. Загрузка считается относительно "
                "рабочего окна за вычетом часа обеда; "
                "план охватывает Пн–Пт целиком, включая будущие встречи; "
                "сравнение — с прошлой неделей."
            ),
        ),
    ]
    overlaps = _overlaps_rich(report)
    if overlaps is not None:
        blocks.insert(-1, paragraph(overlaps))
    quality = _quality_line(report)
    if quality is not None:
        blocks.insert(-1, paragraph(quality))
    return truncate_rich_html(join_blocks(blocks))


def _compare_rich(report: AnalyticsReport) -> str:
    kind, delta = _comparison(report)
    if kind == "same":
        return escape_rich(t.COMPARE_SAME)
    assert delta is not None
    emphasized_delta = bold(escape_rich(delta))
    if kind == "previous_lighter":
        return f"Прошлая неделя была легче на {emphasized_delta} встреч."
    return f"Прошлая неделя была плотнее на {emphasized_delta} встреч."


def _trend_rich(report: AnalyticsReport) -> str:
    if report.trend == "up":
        return f"За квартал встречи {bold('набирают высоту')} — небо плотнее."
    if report.trend == "down":
        return f"За квартал встречи {bold('ползут вниз')} — небо светлеет."
    return f"За квартал нагрузка {bold('держится на одной высоте')}."


def _overlaps_rich(report: AnalyticsReport) -> str | None:
    details = _overlap_details(report)
    if details is None:
        return None
    count, day_label, day_count = details
    return (
        f"⚠️ {bold(escape_rich(count))}; больше всего — "
        f"{escape_rich(day_label)} ({escape_rich(day_count)})."
    )
