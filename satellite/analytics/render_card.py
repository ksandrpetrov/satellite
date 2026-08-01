"""PNG-инфографика недельной аналитики в стиле орбитальной телеметрии.

Палитра, шрифты, логотип и универсальные PNG-примитивы живут в
:mod:`satellite.visual_cards.base`. Здесь остаются только композиция отчёта и
аналитика-специфичные графики.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..calendar.period_stats import AnalyticsReport, format_week_range_label
from ..visual_cards import base as vc

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont

CARD_HEIGHT = 1920

_WEEKDAY_LABELS = ("ПН", "ВТ", "СР", "ЧТ", "ПТ")


def _trend_badge(trend: str) -> tuple[str, str, tuple[int, int, int]]:
    if trend == "up":
        return "↑", "НАГРУЗКА РАСТЁТ", vc.COLOR_TREND_UP
    if trend == "down":
        return "↓", "НАГРУЗКА СНИЖАЕТСЯ", vc.COLOR_TREND_DOWN
    return "→", "СТАБИЛЬНЫЙ РИТМ", vc.COLOR_TREND_FLAT


def _week_delta_badge(report: AnalyticsReport) -> tuple[str, tuple[int, int, int]]:
    delta_min = report.current.total_busy - report.previous.total_busy
    pct_delta = report.current.load_percent - report.previous.load_percent
    if abs(delta_min) < 30:
        return "КАК НА ПРОШЛОЙ НЕДЕЛЕ", vc.COLOR_HERO_MUTED
    sign = "+" if delta_min > 0 else "−"
    text = f"{sign}{vc.hours_label(abs(delta_min))} ВСТРЕЧ"
    if pct_delta:
        text += f"  /  {pct_delta:+d}% ЗАГРУЗКИ"
    color = vc.COLOR_HERO_DANGER if delta_min > 0 else vc.COLOR_HERO_SUCCESS
    return text, color


def _draw_section_label(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    number: str,
    title: str,
    subtitle: str,
    font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_micro: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    draw.text((x, y), number, fill=vc.COLOR_ACCENT, font=font_micro)
    draw.text((x + 48, y - 8), title, fill=vc.COLOR_TEXT, font=font_title)
    draw.text((x + 48, y + 31), subtitle, fill=vc.COLOR_MUTED, font=font_micro)


def _draw_metric(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    label: str,
    value: str,
    sub: str,
    value_color: tuple[int, int, int],
    font_label: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_value: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_sub: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    label_color: tuple[int, int, int],
    sub_color: tuple[int, int, int],
) -> None:
    draw.text((x, y), label, fill=label_color, font=font_label)
    draw.text((x, y + 34), value, fill=value_color, font=font_value)
    draw.text((x, y + 92), sub, fill=sub_color, font=font_sub)


def _draw_week_chart(
    draw: ImageDraw.ImageDraw,
    report: AnalyticsReport,
    box: tuple[int, int, int, int],
    *,
    font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_value: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_small: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_micro: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    x0, y0, x1, _ = box
    _draw_section_label(
        draw,
        x=x0 + 32,
        y=y0 + 39,
        number="02",
        title="ДНЕВНАЯ ОРБИТА",
        subtitle="ДОЛЯ ВСТРЕЧ В РАБОЧЕМ ОКНЕ",
        font_title=font_title,
        font_micro=font_micro,
    )

    chart_left = x0 + 96
    chart_right = x1 - 38
    chart_top = y0 + 168
    chart_bottom = y0 + 430
    for ratio, label in ((1.0, "100"), (0.5, "50"), (0.0, "0")):
        line_y = round(chart_bottom - (chart_bottom - chart_top) * ratio)
        draw.line((chart_left, line_y, chart_right, line_y), fill=vc.COLOR_SEPARATOR, width=1)
        draw.text(
            (chart_left - 15, line_y),
            label,
            fill=vc.COLOR_FAINT,
            font=font_micro,
            anchor="rm",
        )

    days = report.current.days
    group_width = (chart_right - chart_left) / max(1, len(days))
    track_width = 58
    for index, day in enumerate(days):
        center_x = chart_left + group_width * index + group_width / 2
        track = (
            round(center_x - track_width / 2),
            chart_top,
            round(center_x + track_width / 2),
            chart_bottom,
        )
        vc.rounded_rect(
            draw,
            track,
            track_width // 2,
            fill=vc.COLOR_FREE,
            outline=vc.COLOR_SEPARATOR,
        )
        capacity = max(1, day.busy_minutes + day.free_minutes)
        busy_height = round((chart_bottom - chart_top) * day.busy_minutes / capacity)
        if day.busy_minutes:
            busy_height = max(6, busy_height)
            busy_box = (
                track[0],
                chart_bottom - busy_height,
                track[2],
                chart_bottom,
            )
            vc.rounded_rect(
                draw,
                busy_box,
                min(track_width // 2, busy_height // 2),
                fill=vc.COLOR_BUSY,
            )

        draw.text(
            (center_x, chart_top - 48),
            vc.hours_label(day.busy_minutes),
            fill=vc.COLOR_TEXT,
            font=font_value,
            anchor="mt",
        )
        weekday = _WEEKDAY_LABELS[index] if index < len(_WEEKDAY_LABELS) else "—"
        draw.text(
            (center_x, chart_bottom + 29),
            f"{weekday} · {day.plan_date.day:02d}",
            fill=vc.COLOR_TEXT,
            font=font_small,
            anchor="mt",
        )
        draw.text(
            (center_x, chart_bottom + 63),
            f"{day.meetings_count} ВСТР.",
            fill=vc.COLOR_MUTED,
            font=font_micro,
            anchor="mt",
        )
        if day.overlaps_count:
            draw.ellipse(
                (center_x - 4, chart_bottom + 93, center_x + 4, chart_bottom + 101),
                fill=vc.COLOR_TREND_UP,
            )


def _draw_quarter_chart(
    draw: ImageDraw.ImageDraw,
    img,
    values: Sequence[int],
    box: tuple[int, int, int, int],
    *,
    trend_arrow: str,
    trend_label: str,
    trend_color: tuple[int, int, int],
    font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_value: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_small: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_micro: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> ImageDraw.ImageDraw:
    x0, y0, x1, _ = box
    _draw_section_label(
        draw,
        x=x0 + 32,
        y=y0 + 39,
        number="03",
        title="КВАРТАЛЬНАЯ ТРАЕКТОРИЯ",
        subtitle="13 НЕДЕЛЬ · ЧАСЫ ВСТРЕЧ",
        font_title=font_title,
        font_micro=font_micro,
    )

    badge_text = f"{trend_arrow}  {trend_label}"
    badge_width = vc.text_width(draw, badge_text, font_micro) + 32
    vc.draw_pill(
        draw,
        (x1 - 32 - badge_width, y0 + 30),
        badge_text,
        fill=vc.COLOR_PILL_BG,
        text_color=trend_color,
        font=font_micro,
        pad_x=16,
        pad_y=8,
        outline=vc.COLOR_SEPARATOR,
    )

    left = x0 + 37
    right = x1 - 37
    top = y0 + 155
    bottom = y0 + 370
    current = values[-1] if values else 0
    draw.text(
        (right, top - 42),
        f"СЕЙЧАС  {vc.hours_label(current)}",
        fill=vc.COLOR_TEXT,
        font=font_value,
        anchor="ra",
    )

    for ratio in (0.0, 0.5, 1.0):
        line_y = round(bottom - (bottom - top) * ratio)
        draw.line((left, line_y, right, line_y), fill=vc.COLOR_SEPARATOR, width=1)

    if not values:
        draw.text(
            ((left + right) // 2, (top + bottom) // 2),
            "НЕТ ДАННЫХ",
            fill=vc.COLOR_MUTED,
            font=font_small,
            anchor="mm",
        )
        return draw

    max_value = max(values) or 1
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = left if len(values) == 1 else left + (right - left) * index / (len(values) - 1)
        y = bottom - (bottom - top) * value / max_value
        points.append((x, y))

    Image, ImageDraw, _ = vc.pil()
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    area = [(left, bottom), *points, (right, bottom)]
    overlay_draw.polygon(area, fill=(*vc.COLOR_SPARK_FILL, 22))
    img_rgba = Image.alpha_composite(img.convert("RGBA"), overlay)
    img.paste(img_rgba.convert("RGB"))
    draw = ImageDraw.Draw(img)

    draw.line(points, fill=vc.COLOR_ACCENT, width=4, joint="curve")
    for index, (point_x, point_y) in enumerate(points):
        radius = 7 if index == len(points) - 1 else 3
        draw.ellipse(
            (point_x - radius, point_y - radius, point_x + radius, point_y + radius),
            fill=vc.COLOR_ACCENT,
        )

    draw.text((left, bottom + 25), "−12", fill=vc.COLOR_FAINT, font=font_micro, anchor="mt")
    draw.text(
        ((left + right) // 2, bottom + 25),
        "−6",
        fill=vc.COLOR_FAINT,
        font=font_micro,
        anchor="mt",
    )
    draw.text((right, bottom + 25), "0", fill=vc.COLOR_ACCENT, font=font_micro, anchor="mt")
    return draw


def render_analytics_card(report: AnalyticsReport) -> bytes:
    _, ImageDraw, _ = vc.pil()
    img = vc.create_card_canvas(CARD_HEIGHT)
    draw = ImageDraw.Draw(img)
    vc.draw_technical_grid(
        draw,
        (vc.MARGIN, 40, vc.CARD_WIDTH - vc.MARGIN, CARD_HEIGHT - 46),
    )

    font_display_lg = vc.load_font(66, family="display")
    load_percent_size = 82 if report.current.load_percent >= 100 else 92
    font_display_pct = vc.load_font(load_percent_size, family="display")
    font_display_metric = vc.load_font(43, family="display")
    font_section = vc.load_font(29, family="display")
    font_mono_bold = vc.load_font(20, family="mono", bold=True)
    font_mono = vc.load_font(18, family="mono")
    font_small = vc.load_font(17, family="mono")
    font_micro = vc.load_font(15, family="mono")
    font_day_value = vc.load_font(21, family="display")

    vc.paste_brand_logo(img, y=42, target_width=176, tint=vc.COLOR_ACCENT)
    draw = ImageDraw.Draw(img)

    iso_year, iso_week, _ = report.current.week_start.isocalendar()
    draw.text(
        (vc.MARGIN, 55),
        "ЧАЙКА / НЕДЕЛЬНАЯ АНАЛИТИКА",
        fill=vc.COLOR_MUTED,
        font=font_mono,
    )
    draw.text(
        (vc.MARGIN, 94),
        format_week_range_label(report.current.week_start).upper(),
        fill=vc.COLOR_TEXT,
        font=font_display_lg,
    )
    draw.text(
        (vc.MARGIN, 180),
        f"W{iso_week:02d}  /  {iso_year}  /  LOCAL TIME",
        fill=vc.COLOR_FAINT,
        font=font_micro,
    )
    draw.line(
        (vc.MARGIN, 218, vc.CARD_WIDTH - vc.MARGIN, 218),
        fill=vc.COLOR_SEPARATOR,
        width=1,
    )
    vc.draw_reference_mark(draw, vc.MARGIN, 218, color=vc.COLOR_ACCENT)
    vc.draw_reference_mark(draw, vc.CARD_WIDTH - vc.MARGIN, 218)

    hero_box = (vc.MARGIN, 250, vc.CARD_WIDTH - vc.MARGIN, 638)
    draw = vc.draw_surface_card(
        img,
        draw,
        hero_box,
        fill=vc.COLOR_HERO_SURFACE,
        outline=vc.COLOR_HERO_SEPARATOR,
    )
    draw.text((96, 283), "01", fill=vc.COLOR_HERO_ACCENT, font=font_micro)
    draw.text((144, 275), "НЕДЕЛЯ", fill=vc.COLOR_HERO_TEXT, font=font_section)
    vc.draw_load_ring(
        draw,
        272,
        456,
        122,
        report.current.load_percent,
        font_pct=font_display_pct,
        font_label=font_micro,
        accent=vc.COLOR_HERO_ACCENT,
        track=vc.COLOR_HERO_SEPARATOR,
        text_color=vc.COLOR_HERO_TEXT,
        muted_color=vc.COLOR_HERO_MUTED,
        tick_color=vc.COLOR_HERO_FAINT,
    )
    draw.line((458, 286, 458, 601), fill=vc.COLOR_HERO_SEPARATOR, width=1)

    overlaps = report.current.total_overlaps
    overlap_sub = f"{overlaps} ПЕРЕС." if overlaps else "БЕЗ ПЕРЕСЕЧЕНИЙ"
    _draw_metric(
        draw,
        x=500,
        y=337,
        label="ЗАНЯТО",
        value=vc.hours_label(report.current.total_busy),
        sub="В РАБОЧЕМ ОКНЕ",
        value_color=vc.COLOR_HERO_ACCENT,
        font_label=font_micro,
        font_value=font_display_metric,
        font_sub=font_micro,
        label_color=vc.COLOR_HERO_MUTED,
        sub_color=vc.COLOR_HERO_FAINT,
    )
    _draw_metric(
        draw,
        x=716,
        y=337,
        label="СВОБОДНО",
        value=vc.hours_label(report.current.total_free),
        sub="ДОСТУПНЫЙ РЕЗЕРВ",
        value_color=vc.COLOR_HERO_SUCCESS,
        font_label=font_micro,
        font_value=font_display_metric,
        font_sub=font_micro,
        label_color=vc.COLOR_HERO_MUTED,
        sub_color=vc.COLOR_HERO_FAINT,
    )
    _draw_metric(
        draw,
        x=952,
        y=337,
        label="ВСТРЕЧИ",
        value=str(report.current.total_meetings),
        sub=overlap_sub,
        value_color=vc.COLOR_HERO_TEXT,
        font_label=font_micro,
        font_value=font_display_metric,
        font_sub=font_micro,
        label_color=vc.COLOR_HERO_MUTED,
        sub_color=vc.COLOR_HERO_FAINT,
    )
    draw.line((500, 503, 1100, 503), fill=vc.COLOR_HERO_SEPARATOR, width=1)
    delta_text, delta_color = _week_delta_badge(report)
    vc.draw_pill(
        draw,
        (500, 531),
        delta_text,
        fill=vc.COLOR_HERO_PILL,
        text_color=delta_color,
        font=font_small,
        pad_x=16,
        pad_y=8,
        max_width=405,
        outline=vc.COLOR_HERO_SEPARATOR,
    )
    draw.text(
        (1100, 544),
        f"ПРОШЛАЯ / {report.previous.load_percent}%",
        fill=vc.COLOR_HERO_MUTED,
        font=font_small,
        anchor="ra",
    )

    week_box = (vc.MARGIN, 676, vc.CARD_WIDTH - vc.MARGIN, 1242)
    draw = vc.draw_surface_card(img, draw, week_box)
    _draw_week_chart(
        draw,
        report,
        week_box,
        font_title=font_section,
        font_value=font_day_value,
        font_small=font_small,
        font_micro=font_micro,
    )

    quarter_box = (vc.MARGIN, 1278, vc.CARD_WIDTH - vc.MARGIN, 1730)
    draw = vc.draw_surface_card(img, draw, quarter_box)
    trend_arrow, trend_label, trend_color = _trend_badge(report.trend)
    draw = _draw_quarter_chart(
        draw,
        img,
        report.quarter_weekly_busy,
        quarter_box,
        trend_arrow=trend_arrow,
        trend_label=trend_label,
        trend_color=trend_color,
        font_title=font_section,
        font_value=font_mono_bold,
        font_small=font_small,
        font_micro=font_micro,
    )

    footer_y = 1770
    draw.line(
        (vc.MARGIN, footer_y, vc.CARD_WIDTH - vc.MARGIN, footer_y),
        fill=vc.COLOR_SEPARATOR,
        width=1,
    )
    vc.draw_reference_mark(draw, vc.MARGIN, footer_y)
    vc.draw_reference_mark(draw, vc.CARD_WIDTH - vc.MARGIN, footer_y)
    workday = report.workday
    draw.text(
        (vc.MARGIN, footer_y + 30),
        f"РАБОЧЕЕ ОКНО / {workday.workday_start}—{workday.workday_end}",
        fill=vc.COLOR_MUTED,
        font=font_small,
    )
    draw.text(
        (vc.CARD_WIDTH - vc.MARGIN, footer_y + 30),
        "ПН—ПТ / ВКЛЮЧАЯ БУДУЩИЕ ВСТРЕЧИ",
        fill=vc.COLOR_MUTED,
        font=font_small,
        anchor="ra",
    )
    quality_count = report.quality.unverified_partstat_events
    if quality_count:
        draw.text(
            (vc.MARGIN, footer_y + 77),
            f"△ КАЧЕСТВО ДАННЫХ / СТАТУС УЧАСТИЯ НЕ ПРОВЕРЕН: {quality_count}",
            fill=vc.COLOR_WARNING,
            font=font_small,
        )
    else:
        draw.text(
            (vc.MARGIN, footer_y + 77),
            "CALDAV / WEEKLY LOAD SYSTEM",
            fill=vc.COLOR_FAINT,
            font=font_micro,
        )
    draw.text(
        (vc.CARD_WIDTH - vc.MARGIN, footer_y + 77),
        "SATELLITE—03",
        fill=vc.COLOR_FAINT,
        font=font_micro,
        anchor="ra",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
