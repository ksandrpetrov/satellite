"""PNG-инфографика недельной аналитики (Apple Health–style).

Примитивы (палитра, шрифты, фон, карточка-surface, ring, pill, stat-row)
живут в :mod:`satellite.visual_cards.base` — единственное место правды для
всех карточек. В этом модуле остаются только аналитика-специфичные блоки:
бейджи трендов, недельная диаграмма «Пн–Пт» и квартальный sparkline.
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

_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт")


def _trend_badge(trend: str) -> tuple[str, str, tuple[int, int, int]]:
    if trend == "up":
        return "↑", "Нагрузка растёт", vc.COLOR_TREND_UP
    if trend == "down":
        return "↓", "Нагрузка снижается", vc.COLOR_TREND_DOWN
    return "→", "Стабильный ритм", vc.COLOR_TREND_FLAT


def _week_delta_badge(report: AnalyticsReport) -> tuple[str, tuple[int, int, int]]:
    delta_min = report.current.total_busy - report.previous.total_busy
    pct_delta = report.current.load_percent - report.previous.load_percent
    if abs(delta_min) < 30:
        return "Как на прошлой неделе", vc.COLOR_MUTED
    sign = "+" if delta_min > 0 else "−"
    hours = vc.hours_label(abs(delta_min))
    text = f"{sign}{hours} встреч"
    if pct_delta != 0:
        text += f"  ·  {pct_delta:+d}% загрузки"
    color = vc.COLOR_TREND_UP if delta_min > 0 else vc.COLOR_TREND_DOWN
    return text, color


def _draw_week_chart(
    draw: ImageDraw.ImageDraw,
    report: AnalyticsReport,
    box: tuple[int, int, int, int],
    *,
    font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_small: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    pad = 36
    chart_left = x0 + pad + 8
    chart_right = x1 - pad
    chart_bottom = y1 - pad - 28

    title_x = x0 + pad
    draw.text((title_x, y0 + pad), "Пн–Пт", fill=vc.COLOR_TEXT, font=font_title)
    draw.text(
        (title_x, y0 + pad + 34),
        "Занято и свободное время в рабочем окне",
        fill=vc.COLOR_MUTED,
        font=font_small,
    )

    leg_y = y0 + pad + 62
    leg_x = chart_left
    for color, name in (
        (vc.COLOR_BUSY, "Занято"),
        ((200, 230, 255), "Свободно"),
    ):
        draw.ellipse((leg_x, leg_y, leg_x + 12, leg_y + 12), fill=color)
        draw.text((leg_x + 18, leg_y - 2), name, fill=vc.COLOR_MUTED, font=font_small)
        leg_x += 18 + vc.text_width(draw, name, font_small) + 28

    chart_top = leg_y + 32

    max_val = max(
        (d.busy_minutes + d.free_minutes for d in report.current.days),
        default=60,
    )
    max_val = max(max_val, 60)
    n_days = len(report.current.days)
    bar_area_w = chart_right - chart_left
    group_w = bar_area_w / max(n_days, 1)
    bar_w = min(44, int(group_w * 0.36))

    for idx, day in enumerate(report.current.days):
        cx = chart_left + group_w * idx + group_w / 2
        total_h = chart_bottom - chart_top
        busy_h = int(total_h * day.busy_minutes / max_val)
        free_h = int(total_h * day.free_minutes / max_val)
        bx0 = int(cx - bar_w / 2)
        bx1 = int(cx + bar_w / 2)
        if busy_h > 0:
            vc.rounded_rect(
                draw,
                (bx0, chart_bottom - busy_h, bx1, chart_bottom),
                min(10, bar_w // 4),
                fill=vc.COLOR_BUSY,
            )
        if free_h > 0:
            top_free = chart_bottom - busy_h - free_h
            vc.rounded_rect(
                draw,
                (bx0, top_free, bx1, chart_bottom - busy_h),
                min(10, bar_w // 4),
                fill=(200, 230, 255),
            )
        label = _WEEKDAY_LABELS[idx] if idx < len(_WEEKDAY_LABELS) else ""
        draw.text((cx, chart_bottom + 12), label, fill=vc.COLOR_MUTED, font=font_small, anchor="mt")
        if day.meetings_count > 0:
            meet = str(day.meetings_count)
            draw.text(
                (cx, chart_bottom + 36),
                meet,
                fill=vc.COLOR_ACCENT,
                font=font_small,
                anchor="mt",
            )

    draw.line(
        [chart_left, chart_bottom, chart_right, chart_bottom],
        fill=vc.COLOR_SEPARATOR,
        width=2,
    )


def _draw_sparkline_card(
    draw: ImageDraw.ImageDraw,
    img,
    values: Sequence[int],
    box: tuple[int, int, int, int],
    *,
    trend_arrow: str,
    trend_label: str,
    trend_color: tuple[int, int, int],
    font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_small: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_badge: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    pad = 36
    left = x0 + pad
    right = x1 - pad
    bottom = y1 - pad - 20

    header_y = y0 + pad
    draw.text((left, header_y), "13 недель", fill=vc.COLOR_TEXT, font=font_title)
    draw.text(
        (left, header_y + 34),
        "Суммарные часы встреч по неделям",
        fill=vc.COLOR_MUTED,
        font=font_small,
    )

    badge_text = f"{trend_arrow}  {trend_label}"

    def _lighten(c: int) -> int:
        return min(255, c + (255 - c) * 85 // 100)

    pill_fill: tuple[int, int, int] = (
        _lighten(trend_color[0]),
        _lighten(trend_color[1]),
        _lighten(trend_color[2]),
    )
    badge_pad_x, badge_pad_y = 18, 10
    badge_tw = vc.text_width(draw, badge_text, font_badge)
    badge_th = int(getattr(font_badge, "size", 16)) + 4
    badge_w = badge_tw + badge_pad_x * 2
    badge_h = badge_th + badge_pad_y * 2
    badge_x = right - badge_w
    vc.draw_pill(
        draw,
        (badge_x, header_y),
        badge_text,
        fill=pill_fill,
        text_color=trend_color,
        font=font_badge,
        pad_x=badge_pad_x,
        pad_y=badge_pad_y,
    )

    top_chart = max(header_y + 96, header_y + badge_h + 24)

    if len(values) < 2:
        return

    max_v = max(values) or 1
    points: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        x = left + (right - left) * i / (len(values) - 1)
        y = bottom - (bottom - top_chart) * v / max_v
        points.append((x, y))

    area = [(left, bottom), *points, (right, bottom)]
    fill_rgba = (*vc.COLOR_SPARK_FILL, 28)
    Image, ImageDraw, _ = vc.pil()
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(area, fill=fill_rgba)
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, overlay)
    img.paste(img_rgba.convert("RGB"))
    draw = ImageDraw.Draw(img)

    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=vc.COLOR_ACCENT, width=4)
    last = points[-1]
    r = 8
    draw.ellipse([last[0] - r, last[1] - r, last[0] + r, last[1] + r], fill=vc.COLOR_ACCENT)
    draw.line([left, bottom, right, bottom], fill=vc.COLOR_SEPARATOR, width=2)

    last_h = vc.hours_label(values[-1])
    draw.text(
        (right, top_chart - 8),
        f"Сейчас {last_h}",
        fill=vc.COLOR_MUTED,
        font=font_small,
        anchor="rt",
    )


def render_analytics_card(report: AnalyticsReport) -> bytes:
    Image, ImageDraw, _ = vc.pil()
    img = Image.new("RGB", (vc.CARD_WIDTH, CARD_HEIGHT), vc.COLOR_BG)
    draw = ImageDraw.Draw(img)

    font_eyebrow = vc.load_font(20)
    font_title = vc.load_font(48, bold=True)
    font_sub = vc.load_font(26)
    font_stat_value = vc.load_font(40, bold=True)
    font_stat_label = vc.load_font(18)
    font_stat_sub = vc.load_font(22)
    font_ring_pct = vc.load_font(56, bold=True)
    font_ring_label = vc.load_font(22)
    font_card_title = vc.load_font(30, bold=True)
    font_small = vc.load_font(20)
    font_badge = vc.load_font(24, bold=True)
    font_footer = vc.load_font(20)

    vc.paste_brand_logo(img)
    draw = ImageDraw.Draw(img)

    y = vc.MARGIN
    draw.text((vc.MARGIN, y), "ЧАЙКА · НЕДЕЛЬНАЯ АНАЛИТИКА", fill=vc.COLOR_MUTED, font=font_eyebrow)
    y += 32
    week_label = format_week_range_label(report.current.week_start)
    draw.text((vc.MARGIN, y), week_label, fill=vc.COLOR_TEXT, font=font_title)
    y += font_title.size + 16

    delta_text, delta_color = _week_delta_badge(report)
    vc.draw_pill(
        draw,
        (vc.MARGIN, y),
        delta_text,
        fill=(240, 240, 245),
        text_color=delta_color,
        font=font_sub,
        pad_x=20,
        pad_y=12,
    )
    y += 56

    hero_h = 280
    hero_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + hero_h)
    draw = vc.draw_surface_card(img, draw, hero_box)

    ring_cx = vc.MARGIN + 48 + 110
    ring_cy = y + hero_h // 2
    vc.draw_load_ring(
        draw,
        ring_cx,
        ring_cy,
        100,
        report.current.load_percent,
        font_pct=font_ring_pct,
        font_label=font_ring_label,
    )

    stats_left = vc.MARGIN + 300
    stats_top = y + 36
    meetings_total = sum(d.meetings_count for d in report.current.days)
    vc.draw_stat_row(
        draw,
        stats_left,
        stats_top,
        label="Встречи",
        value=vc.hours_label(report.current.total_busy),
        sub=vc.meetings_label(meetings_total),
        font_label=font_stat_label,
        font_value=font_stat_value,
        font_sub=font_stat_sub,
        accent=vc.COLOR_ACCENT,
    )
    mid = stats_top + 108
    vc.draw_stat_row(
        draw,
        stats_left,
        mid,
        label="Свободно",
        value=vc.hours_label(report.current.total_free),
        sub=f"Было {report.previous.load_percent}% → сейчас {report.current.load_percent}%",
        font_label=font_stat_label,
        font_value=font_stat_value,
        font_sub=font_stat_sub,
        accent=vc.COLOR_FREE,
    )

    y += hero_h + 28

    week_h = 560
    week_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + week_h)
    draw = vc.draw_surface_card(img, draw, week_box)
    _draw_week_chart(
        draw,
        report,
        week_box,
        font_title=font_card_title,
        font_small=font_small,
    )
    y += week_h + 28

    spark_h = 480
    trend_arrow, trend_label, trend_color = _trend_badge(report.trend)
    spark_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + spark_h)
    draw = vc.draw_surface_card(img, draw, spark_box)
    _draw_sparkline_card(
        draw,
        img,
        report.quarter_weekly_busy,
        spark_box,
        trend_arrow=trend_arrow,
        trend_label=trend_label,
        trend_color=trend_color,
        font_title=font_card_title,
        font_small=font_small,
        font_badge=font_badge,
    )
    y += spark_h + 24

    wd = report.workday
    footer = f"Рабочий день {wd.workday_start}–{wd.workday_end}"
    draw.text(
        (vc.CARD_WIDTH // 2, y),
        footer,
        fill=vc.COLOR_MUTED,
        font=font_footer,
        anchor="mt",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
