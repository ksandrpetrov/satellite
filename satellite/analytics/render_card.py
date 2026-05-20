"""PNG-инфографика недельной аналитики (Pillow)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Sequence

from ..calendar.period_stats import AnalyticsReport, format_week_range_label

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont

CARD_WIDTH = 1200
CARD_HEIGHT = 1600
MARGIN = 64

COLOR_BG = (248, 250, 252)
COLOR_TEXT = (30, 41, 59)
COLOR_MUTED = (100, 116, 139)
COLOR_BUSY = (59, 130, 246)
COLOR_FREE = (148, 163, 184)
COLOR_TREND_UP = (220, 38, 38)
COLOR_TREND_DOWN = (22, 163, 74)
COLOR_TREND_FLAT = (100, 116, 139)
COLOR_GRID = (226, 232, 240)

_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _pil():
    """Импорт Pillow только при рендере — без него бот должен стартовать."""
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    _, _, ImageFont = _pil()
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else None,
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else None,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    )
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hours_label(minutes: int) -> str:
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)}ч"
    return f"{hours:.1f}ч"


def _trend_arrow(trend: str) -> tuple[str, tuple[int, int, int]]:
    if trend == "up":
        return "↑ больше встреч", COLOR_TREND_UP
    if trend == "down":
        return "↓ меньше встреч", COLOR_TREND_DOWN
    return "→ без изменений", COLOR_TREND_FLAT


def _draw_week_bars(
    draw: ImageDraw.ImageDraw,
    report: AnalyticsReport,
    *,
    top: int,
    height: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_small: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    left = MARGIN + 40
    right = CARD_WIDTH - MARGIN
    chart_bottom = top + height - 48
    chart_top = top + 24
    max_busy = max((d.busy_minutes for d in report.current.days), default=0)
    max_free = max((d.free_minutes for d in report.current.days), default=0)
    max_val = max(max_busy + max_free, 60)
    bar_area_w = right - left
    group_w = bar_area_w / 7
    bar_w = min(36, group_w * 0.28)

    for idx, day in enumerate(report.current.days):
        cx = left + group_w * idx + group_w / 2
        total_h = chart_bottom - chart_top
        busy_h = int(total_h * day.busy_minutes / max_val) if max_val else 0
        free_h = int(total_h * day.free_minutes / max_val) if max_val else 0
        x0 = cx - bar_w - 2
        x1 = cx - 2
        x2 = cx + 2
        x3 = cx + bar_w + 2
        draw.rectangle(
            [x0, chart_bottom - busy_h, x1, chart_bottom],
            fill=COLOR_BUSY,
        )
        draw.rectangle(
            [x2, chart_bottom - free_h, x3, chart_bottom],
            fill=COLOR_FREE,
        )
        label = _WEEKDAY_LABELS[idx]
        draw.text(
            (cx, chart_bottom + 8),
            label,
            fill=COLOR_MUTED,
            font=font_small,
            anchor="mt",
        )

    draw.text((left, chart_top - 8), "Занято", fill=COLOR_BUSY, font=font_small)
    draw.text((left + 70, chart_top - 8), "Свободно", fill=COLOR_FREE, font=font_small)
    draw.line([left, chart_bottom, right, chart_bottom], fill=COLOR_GRID, width=2)


def _draw_sparkline(
    draw: ImageDraw.ImageDraw,
    values: Sequence[int],
    *,
    top: int,
    height: int,
    font_small: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    left = MARGIN + 40
    right = CARD_WIDTH - MARGIN
    bottom = top + height - 40
    top_y = top + 36
    if len(values) < 2:
        return
    max_v = max(values) or 1
    points: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        x = left + (right - left) * i / (len(values) - 1)
        y = bottom - (bottom - top_y) * v / max_v
        points.append((x, y))
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=COLOR_BUSY, width=3)
    draw.ellipse(
        [points[-1][0] - 6, points[-1][1] - 6, points[-1][0] + 6, points[-1][1] + 6],
        fill=COLOR_BUSY,
    )
    draw.text((left, top + 4), "13 недель — часы встреч", fill=COLOR_TEXT, font=font_small)


def render_analytics_card(report: AnalyticsReport) -> bytes:
    Image, ImageDraw, _ = _pil()
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)
    font_title = _load_font(44, bold=True)
    font_sub = _load_font(28)
    font_small = _load_font(22)
    font_badge = _load_font(26, bold=True)

    week_label = format_week_range_label(report.current.week_start)
    draw.text((MARGIN, MARGIN), f"Неделя {week_label}", fill=COLOR_TEXT, font=font_title)

    delta_min = report.current.total_busy - report.previous.total_busy
    if abs(delta_min) >= 30:
        sign = "+" if delta_min > 0 else "−"
        badge = f"{sign}{_hours_label(abs(delta_min))} vs прошлая неделя"
        pct_delta = report.current.load_percent - report.previous.load_percent
        if pct_delta != 0:
            badge += f"  ({pct_delta:+d}% загрузки)"
    else:
        badge = "Как прошлая неделя"
    draw.text((MARGIN, MARGIN + 56), badge, fill=COLOR_MUTED, font=font_sub)

    load_text = (
        f"Загрузка {report.current.load_percent}% · "
        f"встречи {_hours_label(report.current.total_busy)} · "
        f"свободно {_hours_label(report.current.total_free)}"
    )
    draw.text((MARGIN, MARGIN + 100), load_text, fill=COLOR_TEXT, font=font_small)

    _draw_week_bars(draw, report, top=220, height=520, font=font_sub, font_small=font_small)

    trend_text, trend_color = _trend_arrow(report.trend)
    draw.text((MARGIN, 780), f"Квартал: {trend_text}", fill=trend_color, font=font_badge)

    _draw_sparkline(
        draw,
        report.quarter_weekly_busy,
        top=840,
        height=520,
        font_small=font_small,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
