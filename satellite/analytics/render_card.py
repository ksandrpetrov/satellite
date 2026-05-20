"""PNG-инфографика недельной аналитики (Pillow, Apple Health–style)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from ..calendar.period_stats import AnalyticsReport, format_week_range_label

if TYPE_CHECKING:
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont

CARD_WIDTH = 1200
CARD_HEIGHT = 1920
MARGIN = 56
CARD_RADIUS = 28

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"
LOGO_TARGET_WIDTH = 200

# Apple-like palette
COLOR_BG = (245, 245, 247)
COLOR_SURFACE = (255, 255, 255)
COLOR_TEXT = (29, 29, 31)
COLOR_MUTED = (134, 134, 139)
COLOR_SEPARATOR = (229, 229, 234)
COLOR_ACCENT = (0, 122, 255)
COLOR_FREE = (52, 199, 89)
COLOR_BUSY = (0, 122, 255)
COLOR_RING_TRACK = (229, 229, 234)
COLOR_TREND_UP = (255, 59, 48)
COLOR_TREND_DOWN = (52, 199, 89)
COLOR_TREND_FLAT = (134, 134, 139)
COLOR_SPARK_FILL = (0, 122, 255)
COLOR_SHADOW = (0, 0, 0, 18)

_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт")


def _pil():
    """Импорт Pillow только при рендере — без него бот должен стартовать."""
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


_LOGO_CACHE: "PILImage.Image | None" = None


def _load_brand_logo() -> "PILImage.Image | None":
    """Логотип бренда с прозрачным фоном, масштабированный под карточку."""
    global _LOGO_CACHE
    if _LOGO_CACHE is not None:
        return _LOGO_CACHE
    if not LOGO_PATH.exists():
        return None
    Image, _, _ = _pil()
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except OSError:
        return None
    ratio = LOGO_TARGET_WIDTH / logo.width
    new_size = (LOGO_TARGET_WIDTH, max(1, round(logo.height * ratio)))
    _LOGO_CACHE = logo.resize(new_size, Image.LANCZOS)
    return _LOGO_CACHE


def _paste_brand_logo(img) -> None:
    """Лого в правом верхнем углу карточки, чтобы юзер видел бренд."""
    logo = _load_brand_logo()
    if logo is None:
        return
    x = CARD_WIDTH - MARGIN - logo.width
    y = MARGIN - 12
    img.paste(logo, (x, y), logo)


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    _, _, ImageFont = _pil()
    regular = (
        "/System/Library/Fonts/SFNSText.ttf",
        "/System/Library/Fonts/Supplemental/SF-Pro-Text-Regular.otf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    )
    heavy = (
        "/System/Library/Fonts/SFNSText.ttf",
        "/System/Library/Fonts/Supplemental/SF-Pro-Text-Bold.otf",
        "/System/Library/Fonts/Supplemental/SF-Pro-Display-Bold.otf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    )
    paths = heavy if bold else regular
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hours_label(minutes: int) -> str:
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)} ч"
    return f"{hours:.1f} ч"


def _meetings_label(count: int) -> str:
    n = abs(count) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        word = "встреч"
    elif n1 == 1:
        word = "встреча"
    elif 2 <= n1 <= 4:
        word = "встречи"
    else:
        word = "встреч"
    return f"{count} {word}"


def _trend_badge(trend: str) -> tuple[str, str, tuple[int, int, int]]:
    if trend == "up":
        return "↑", "Нагрузка растёт", COLOR_TREND_UP
    if trend == "down":
        return "↓", "Нагрузка снижается", COLOR_TREND_DOWN
    return "→", "Стабильный ритм", COLOR_TREND_FLAT


def _week_delta_badge(report: AnalyticsReport) -> tuple[str, tuple[int, int, int]]:
    delta_min = report.current.total_busy - report.previous.total_busy
    pct_delta = report.current.load_percent - report.previous.load_percent
    if abs(delta_min) < 30:
        return "Как на прошлой неделе", COLOR_MUTED
    sign = "+" if delta_min > 0 else "−"
    hours = _hours_label(abs(delta_min))
    text = f"{sign}{hours} встреч"
    if pct_delta != 0:
        text += f"  ·  {pct_delta:+d}% загрузки"
    color = COLOR_TREND_UP if delta_min > 0 else COLOR_TREND_DOWN
    return text, color


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1 if outline else 0)


def _draw_surface_card(
    img,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = CARD_RADIUS,
) -> None:
    """Белая карточка с мягкой тенью."""
    Image, ImageDraw, _ = _pil()
    x0, y0, x1, y1 = box
    shadow = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        (x0 + 2, y0 + 6, x1 + 2, y1 + 6),
        radius=radius,
        fill=COLOR_SHADOW,
    )
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, shadow)
    img.paste(img_rgba.convert("RGB"))
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, box, radius, fill=COLOR_SURFACE)


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill: tuple[int, int, int],
    text_color: tuple[int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    pad_x: int = 18,
    pad_y: int = 10,
) -> tuple[int, int, int, int]:
    tw = _text_width(draw, text, font)
    th = font.size + 4
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    _rounded_rect(draw, box, (th + pad_y * 2) // 2, fill=fill)
    draw.text((x + pad_x, y + pad_y), text, fill=text_color, font=font)
    return box


def _draw_load_ring(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    percent: int,
    *,
    font_pct: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_label: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    # PIL: углы от 3 ч, по часовой; 12 ч = 270°
    draw.arc(bbox, start=270, end=270 + 360, fill=COLOR_RING_TRACK, width=22)
    sweep = max(4, int(360 * min(100, max(0, percent)) / 100))
    if sweep > 0:
        draw.arc(bbox, start=270, end=270 + sweep, fill=COLOR_ACCENT, width=22)
    pct_text = f"{percent}%"
    draw.text((cx, cy - 28), pct_text, fill=COLOR_TEXT, font=font_pct, anchor="mm")
    draw.text((cx, cy + 22), "загрузка", fill=COLOR_MUTED, font=font_label, anchor="mm")


def _draw_stat_row(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    width: int,
    *,
    label: str,
    value: str,
    sub: str | None,
    font_label: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_value: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_sub: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    accent: tuple[int, int, int] | None = None,
) -> int:
    draw.text((left, top), label.upper(), fill=COLOR_MUTED, font=font_label)
    y = top + 28
    draw.text((left, y), value, fill=accent or COLOR_TEXT, font=font_value)
    y += font_value.size + 8
    if sub:
        draw.text((left, y), sub, fill=COLOR_MUTED, font=font_sub)
        y += font_sub.size + 6
    return y


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
    draw.text((title_x, y0 + pad), "Пн–Пт", fill=COLOR_TEXT, font=font_title)
    draw.text(
        (title_x, y0 + pad + 34),
        "Занято и свободное время в рабочем окне",
        fill=COLOR_MUTED,
        font=font_small,
    )

    leg_y = y0 + pad + 62
    leg_x = chart_left
    for color, name in (
        (COLOR_BUSY, "Занято"),
        ((200, 230, 255), "Свободно"),
    ):
        draw.ellipse((leg_x, leg_y, leg_x + 12, leg_y + 12), fill=color)
        draw.text((leg_x + 18, leg_y - 2), name, fill=COLOR_MUTED, font=font_small)
        leg_x += 18 + _text_width(draw, name, font_small) + 28

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
            _rounded_rect(
                draw,
                (bx0, chart_bottom - busy_h, bx1, chart_bottom),
                min(10, bar_w // 4),
                fill=COLOR_BUSY,
            )
        if free_h > 0:
            top_free = chart_bottom - busy_h - free_h
            _rounded_rect(
                draw,
                (bx0, top_free, bx1, chart_bottom - busy_h),
                min(10, bar_w // 4),
                fill=(200, 230, 255),
            )
        label = _WEEKDAY_LABELS[idx] if idx < len(_WEEKDAY_LABELS) else ""
        draw.text((cx, chart_bottom + 12), label, fill=COLOR_MUTED, font=font_small, anchor="mt")
        if day.meetings_count > 0:
            meet = str(day.meetings_count)
            draw.text(
                (cx, chart_bottom + 36),
                meet,
                fill=COLOR_ACCENT,
                font=font_small,
                anchor="mt",
            )

    draw.line(
        [chart_left, chart_bottom, chart_right, chart_bottom],
        fill=COLOR_SEPARATOR,
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
    draw.text((left, header_y), "13 недель", fill=COLOR_TEXT, font=font_title)
    draw.text(
        (left, header_y + 34),
        "Суммарные часы встреч по неделям",
        fill=COLOR_MUTED,
        font=font_small,
    )

    badge_text = f"{trend_arrow}  {trend_label}"
    pill_fill = tuple(min(255, c + (255 - c) * 85 // 100) for c in trend_color)
    badge_pad_x, badge_pad_y = 18, 10
    badge_tw = _text_width(draw, badge_text, font_badge)
    badge_th = font_badge.size + 4
    badge_w = badge_tw + badge_pad_x * 2
    badge_h = badge_th + badge_pad_y * 2
    badge_x = right - badge_w
    _draw_pill(
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
    fill_rgba = (*COLOR_SPARK_FILL, 28)
    Image, ImageDraw, _ = _pil()
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(area, fill=fill_rgba)
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, overlay)
    img.paste(img_rgba.convert("RGB"))
    draw = ImageDraw.Draw(img)

    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=COLOR_ACCENT, width=4)
    last = points[-1]
    r = 8
    draw.ellipse([last[0] - r, last[1] - r, last[0] + r, last[1] + r], fill=COLOR_ACCENT)
    draw.line([left, bottom, right, bottom], fill=COLOR_SEPARATOR, width=2)

    last_h = _hours_label(values[-1])
    draw.text(
        (right, top_chart - 8),
        f"Сейчас {last_h}",
        fill=COLOR_MUTED,
        font=font_small,
        anchor="rt",
    )


def render_analytics_card(report: AnalyticsReport) -> bytes:
    Image, ImageDraw, _ = _pil()
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    font_eyebrow = _load_font(20)
    font_title = _load_font(48, bold=True)
    font_sub = _load_font(26)
    font_stat_value = _load_font(40, bold=True)
    font_stat_label = _load_font(18)
    font_stat_sub = _load_font(22)
    font_ring_pct = _load_font(56, bold=True)
    font_ring_label = _load_font(22)
    font_card_title = _load_font(30, bold=True)
    font_small = _load_font(20)
    font_badge = _load_font(24, bold=True)
    font_footer = _load_font(20)

    _paste_brand_logo(img)
    draw = ImageDraw.Draw(img)

    y = MARGIN
    draw.text((MARGIN, y), "ЧАЙКА · НЕДЕЛЬНАЯ АНАЛИТИКА", fill=COLOR_MUTED, font=font_eyebrow)
    y += 32
    week_label = format_week_range_label(report.current.week_start)
    draw.text((MARGIN, y), week_label, fill=COLOR_TEXT, font=font_title)
    y += font_title.size + 16

    delta_text, delta_color = _week_delta_badge(report)
    _draw_pill(
        draw,
        (MARGIN, y),
        delta_text,
        fill=(240, 240, 245),
        text_color=delta_color,
        font=font_sub,
        pad_x=20,
        pad_y=12,
    )
    y += 56

    hero_h = 280
    hero_box = (MARGIN, y, CARD_WIDTH - MARGIN, y + hero_h)
    _draw_surface_card(img, draw, hero_box)
    draw = ImageDraw.Draw(img)

    ring_cx = MARGIN + 48 + 110
    ring_cy = y + hero_h // 2
    _draw_load_ring(
        draw,
        ring_cx,
        ring_cy,
        100,
        report.current.load_percent,
        font_pct=font_ring_pct,
        font_label=font_ring_label,
    )

    stats_left = MARGIN + 300
    stats_top = y + 36
    meetings_total = sum(d.meetings_count for d in report.current.days)
    _draw_stat_row(
        draw,
        stats_left,
        stats_top,
        CARD_WIDTH - stats_left - MARGIN,
        label="Встречи",
        value=_hours_label(report.current.total_busy),
        sub=_meetings_label(meetings_total),
        font_label=font_stat_label,
        font_value=font_stat_value,
        font_sub=font_stat_sub,
        accent=COLOR_ACCENT,
    )
    mid = stats_top + 108
    _draw_stat_row(
        draw,
        stats_left,
        mid,
        CARD_WIDTH - stats_left - MARGIN,
        label="Свободно",
        value=_hours_label(report.current.total_free),
        sub=f"Было {report.previous.load_percent}% → сейчас {report.current.load_percent}%",
        font_label=font_stat_label,
        font_value=font_stat_value,
        font_sub=font_stat_sub,
        accent=COLOR_FREE,
    )

    y += hero_h + 28

    week_h = 560
    week_box = (MARGIN, y, CARD_WIDTH - MARGIN, y + week_h)
    _draw_surface_card(img, draw, week_box)
    draw = ImageDraw.Draw(img)
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
    spark_box = (MARGIN, y, CARD_WIDTH - MARGIN, y + spark_h)
    _draw_surface_card(img, draw, spark_box)
    draw = ImageDraw.Draw(img)
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
        (CARD_WIDTH // 2, y),
        footer,
        fill=COLOR_MUTED,
        font=font_footer,
        anchor="mt",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
