"""Палитра, шрифты и примитивы отрисовки PNG-карточек."""

from __future__ import annotations

from math import cos, radians, sin
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from PIL import Image as PILImage
    from PIL import ImageDraw

CARD_WIDTH = 1200
MARGIN = 64
CARD_RADIUS = 28

_PACKAGE_DIR = Path(__file__).resolve().parent
ASSET_DIR = _PACKAGE_DIR / "assets"
FONT_DIR = ASSET_DIR / "fonts"
LOGO_PATH = _PACKAGE_DIR.parent / "analytics" / "assets" / "logo.png"
LOGO_TARGET_WIDTH = 184

FONT_DISPLAY_PATH = FONT_DIR / "Tektur-Medium.ttf"
FONT_MONO_REGULAR_PATH = FONT_DIR / "GeistMono-Regular.ttf"
FONT_MONO_BOLD_PATH = FONT_DIR / "GeistMono-Bold.ttf"

# «Светлая орбита»: воздушное поле с одним глубоким контрастным якорем.
COLOR_BG_TOP = (251, 253, 253)
COLOR_BG = (241, 246, 248)
COLOR_SURFACE = (255, 255, 255)
COLOR_TEXT = (20, 48, 64)
COLOR_MUTED = (91, 117, 132)
COLOR_FAINT = (133, 155, 166)
COLOR_SEPARATOR = (216, 229, 234)
COLOR_GRID = (232, 240, 243)
COLOR_ACCENT = (0, 112, 153)
COLOR_FREE = (230, 240, 244)
COLOR_BUSY = (41, 180, 220)
COLOR_RING_TRACK = (205, 222, 230)
COLOR_TREND_UP = (190, 63, 67)
COLOR_TREND_DOWN = (24, 126, 88)
COLOR_TREND_FLAT = (93, 117, 131)
COLOR_WARNING = (166, 105, 0)
COLOR_SPARK_FILL = COLOR_ACCENT
COLOR_PILL_BG = (235, 243, 246)

COLOR_HERO_SURFACE = (14, 48, 68)
COLOR_HERO_TEXT = (242, 249, 252)
COLOR_HERO_MUTED = (158, 184, 198)
COLOR_HERO_FAINT = (111, 148, 167)
COLOR_HERO_SEPARATOR = (43, 81, 101)
COLOR_HERO_PILL = (23, 65, 87)
COLOR_HERO_ACCENT = (54, 214, 255)
COLOR_HERO_SUCCESS = (128, 229, 177)
COLOR_HERO_DANGER = (255, 108, 105)

FontFamily = Literal["sans", "display", "mono"]


def pil():
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def create_card_canvas(height: int):
    """Create the canonical light canvas with a restrained vertical gradient."""
    Image, _, _ = pil()
    img = Image.new("RGB", (CARD_WIDTH, height), COLOR_BG)
    pixels = img.load()
    denominator = max(1, height - 1)
    for y in range(height):
        ratio = y / denominator
        color = tuple(
            round(COLOR_BG_TOP[index] + (COLOR_BG[index] - COLOR_BG_TOP[index]) * ratio)
            for index in range(3)
        )
        for x in range(CARD_WIDTH):
            pixels[x, y] = color
    return img


def draw_technical_grid(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    step: int = 64,
) -> None:
    """Draw a quiet coordinate field behind the foreground composition."""
    x0, y0, x1, y1 = box
    x = x0
    while x <= x1:
        draw.line((x, y0, x, y1), fill=COLOR_GRID, width=1)
        x += step
    y = y0
    while y <= y1:
        draw.line((x0, y, x1, y), fill=COLOR_GRID, width=1)
        y += step


def draw_reference_mark(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    *,
    size: int = 8,
    color: tuple[int, int, int] = COLOR_FAINT,
) -> None:
    draw.line((x - size, y, x + size, y), fill=color, width=1)
    draw.line((x, y - size, x, y + size), fill=color, width=1)


_LOGO_CACHE: dict[tuple[int, tuple[int, int, int] | None], PILImage.Image] = {}


def load_brand_logo(
    *,
    target_width: int = LOGO_TARGET_WIDTH,
    tint: tuple[int, int, int] | None = None,
) -> PILImage.Image | None:
    key = (target_width, tint)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    if not LOGO_PATH.exists():
        return None
    Image, _, _ = pil()
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except OSError:
        return None
    ratio = target_width / logo.width
    new_size = (target_width, max(1, round(logo.height * ratio)))
    logo = logo.resize(new_size, Image.Resampling.LANCZOS)
    if tint is not None:
        alpha = logo.getchannel("A")
        tinted = Image.new("RGBA", logo.size, (*tint, 0))
        tinted.putalpha(alpha)
        logo = tinted
    _LOGO_CACHE[key] = logo
    return logo


def paste_brand_logo(
    img,
    *,
    x: int | None = None,
    y: int = 44,
    target_width: int = LOGO_TARGET_WIDTH,
    tint: tuple[int, int, int] | None = COLOR_ACCENT,
) -> None:
    logo = load_brand_logo(target_width=target_width, tint=tint)
    if logo is None:
        return
    left = CARD_WIDTH - MARGIN - logo.width if x is None else x
    img.paste(logo, (left, y), logo)


def load_font(
    size: int,
    *,
    bold: bool = False,
    family: FontFamily = "sans",
):
    _, _, ImageFont = pil()
    bundled: tuple[Path, ...]
    if family == "display":
        bundled = (FONT_DISPLAY_PATH,)
    elif family == "mono":
        bundled = (FONT_MONO_BOLD_PATH if bold else FONT_MONO_REGULAR_PATH,)
    else:
        bundled = ()

    regular = (
        "/System/Library/Fonts/Supplemental/SF-Pro-Text-Regular.otf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "arial.ttf",
    )
    heavy = (
        "/System/Library/Fonts/Supplemental/SF-Pro-Text-Bold.otf",
        "/System/Library/Fonts/Supplemental/SF-Pro-Display-Bold.otf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "arialbd.ttf",
    )
    mono = (
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    )
    mono_bold = (
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    )
    fallback: tuple[str, ...]
    if family == "mono":
        fallback = mono_bold if bold else mono
    else:
        fallback = heavy if bold else regular
    paths: tuple[str | Path, ...] = (*bundled, *fallback)
    for path in paths:
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            continue
        if _font_supports_required_glyphs(font):
            return font
    return ImageFont.load_default()


def _font_supports_required_glyphs(font) -> bool:
    """Reject fonts that Pillow would render as visible tofu squares."""

    def signature(char: str) -> tuple[tuple[int, int], bytes]:
        mask = font.getmask(char)
        return mask.size, bytes(mask)

    missing = signature(chr(0x10FFFF))
    required = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯая–—→−·↑↓"
    return all(signature(char) != missing for char in required)


def hours_label(minutes: int) -> str:
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)} ч"
    return f"{hours:.1f} ч"


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill,
        outline=outline,
        width=width if outline else 0,
    )


def draw_surface_card(
    img,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = CARD_RADIUS,
    fill: tuple[int, int, int] = COLOR_SURFACE,
    outline: tuple[int, int, int] = COLOR_SEPARATOR,
) -> ImageDraw.ImageDraw:
    del img  # kept in the signature for callers shared with earlier card renderers
    rounded_rect(draw, box, radius, fill=fill, outline=outline)
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
    outline: tuple[int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    label = text
    if max_width is not None:
        while label and text_width(draw, label + "…", font) + pad_x * 2 > max_width:
            label = label[:-1]
        if len(label) < len(text):
            label = (label or text[:1]) + "…"
    tw = text_width(draw, label, font)
    th = int(getattr(font, "size", 16)) + 4
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    rounded_rect(
        draw,
        box,
        (th + pad_y * 2) // 2,
        fill=fill,
        outline=outline,
    )
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
    accent: tuple[int, int, int] = COLOR_ACCENT,
    track: tuple[int, int, int] = COLOR_RING_TRACK,
    text_color: tuple[int, int, int] = COLOR_TEXT,
    muted_color: tuple[int, int, int] = COLOR_MUTED,
    tick_color: tuple[int, int, int] = COLOR_FAINT,
) -> None:
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.arc(bbox, start=270, end=630, fill=track, width=18)
    sweep = int(360 * min(100, max(0, percent)) / 100)
    if sweep > 0:
        draw.arc(bbox, start=270, end=270 + max(4, sweep), fill=accent, width=18)
    for index in range(36):
        angle = index * 10
        if angle % 30:
            continue
        rad = radians(angle - 90)
        outer = radius + 24
        inner = radius + 15
        draw.line(
            (
                cx + inner * cos(rad),
                cy + inner * sin(rad),
                cx + outer * cos(rad),
                cy + outer * sin(rad),
            ),
            fill=tick_color,
            width=2,
        )
    draw.text((cx, cy - 15), f"{percent}%", fill=text_color, font=font_pct, anchor="mm")
    draw.text((cx, cy + 48), "ЗАГРУЗКА", fill=muted_color, font=font_label, anchor="mm")
