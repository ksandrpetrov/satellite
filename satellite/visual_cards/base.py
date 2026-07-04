"""Палитра, шрифты и примитивы отрисовки PNG-карточек."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage
    from PIL import ImageDraw

CARD_WIDTH = 1200
MARGIN = 56
CARD_RADIUS = 28

LOGO_PATH = Path(__file__).resolve().parent.parent / "analytics" / "assets" / "logo.png"
LOGO_TARGET_WIDTH = 200

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
COLOR_PILL_BG = (240, 240, 245)


def pil():
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


_LOGO_CACHE: PILImage.Image | None = None


def load_brand_logo() -> PILImage.Image | None:
    global _LOGO_CACHE
    if _LOGO_CACHE is not None:
        return _LOGO_CACHE
    if not LOGO_PATH.exists():
        return None
    Image, _, _ = pil()
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except OSError:
        return None
    ratio = LOGO_TARGET_WIDTH / logo.width
    new_size = (LOGO_TARGET_WIDTH, max(1, round(logo.height * ratio)))
    _LOGO_CACHE = logo.resize(new_size, Image.LANCZOS)
    return _LOGO_CACHE


def paste_brand_logo(img) -> None:
    logo = load_brand_logo()
    if logo is None:
        return
    x = CARD_WIDTH - MARGIN - logo.width
    y = MARGIN - 12
    img.paste(logo, (x, y), logo)


def load_font(size: int, *, bold: bool = False):
    _, _, ImageFont = pil()
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


def hours_label(minutes: int) -> str:
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)} ч"
    return f"{hours:.1f} ч"


def meetings_label(count: int) -> str:
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


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
) -> None:
    draw.rounded_rectangle(
        box, radius=radius, fill=fill, outline=outline, width=1 if outline else 0
    )


def draw_surface_card(
    img,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = CARD_RADIUS,
) -> ImageDraw.ImageDraw:
    Image, ImageDraw, _ = pil()
    x0, y0, x1, y1 = box
    height = img.size[1]
    shadow = Image.new("RGBA", (CARD_WIDTH, height), (0, 0, 0, 0))
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
    rounded_rect(draw, box, radius, fill=COLOR_SURFACE)
    return draw


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0])


def draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill: tuple[int, int, int],
    text_color: tuple[int, int, int],
    font,
    pad_x: int = 18,
    pad_y: int = 10,
    max_width: int | None = None,
) -> tuple[int, int, int, int]:
    label = text
    if max_width is not None:
        while label and text_width(draw, label + "…", font) + pad_x * 2 > max_width:
            label = label[:-1]
        if len(label) < len(text):
            label = (label or text[:1]) + "…"
    tw = text_width(draw, label, font)
    th = font.size + 4
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    rounded_rect(draw, box, (th + pad_y * 2) // 2, fill=fill)
    draw.text((x + pad_x, y + pad_y), label, fill=text_color, font=font)
    return box


def draw_load_ring(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    percent: int,
    *,
    font_pct,
    font_label,
) -> None:
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.arc(bbox, start=270, end=270 + 360, fill=COLOR_RING_TRACK, width=22)
    sweep = max(4, int(360 * min(100, max(0, percent)) / 100))
    if sweep > 0:
        draw.arc(bbox, start=270, end=270 + sweep, fill=COLOR_ACCENT, width=22)
    draw.text((cx, cy - 28), f"{percent}%", fill=COLOR_TEXT, font=font_pct, anchor="mm")
    draw.text((cx, cy + 22), "загрузка", fill=COLOR_MUTED, font=font_label, anchor="mm")


def draw_stat_row(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    *,
    label: str,
    value: str,
    sub: str | None,
    font_label,
    font_value,
    font_sub,
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
