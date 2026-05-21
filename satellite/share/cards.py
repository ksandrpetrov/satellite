"""PNG-карточки плана дня и ближайших событий (Apple Health–style)."""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from ..calendar.events import event_index_marker
from ..calendar.stats import DayCalendarStats, NormalizedEvent
from ..seagull.rules import SeagullTexts
from ..visual_cards import base as vc

CARD_MIN_HEIGHT = 1500
CARD_MAX_HEIGHT = 2400
CONTENT_WIDTH = vc.CARD_WIDTH - vc.MARGIN * 2


def _load_percent(stats: DayCalendarStats) -> int:
    total = stats.busy_minutes + stats.free_minutes
    if total <= 0:
        return 0
    return int(round(100 * stats.busy_minutes / total))


def _title_for_plan(stats: DayCalendarStats) -> str:
    date_str = stats.plan_date.strftime("%d.%m.%Y")
    rel = stats.date_label.lower()
    if rel in {"сегодня", "завтра", "послезавтра"}:
        return f"{stats.date_label}, {date_str}"
    return date_str


def _schedule_block_height(
    events: Sequence[NormalizedEvent],
    *,
    line_h: int,
    header_h: int,
    pad: int,
) -> int:
    if not events:
        return header_h + line_h + pad * 2
    return header_h + len(events) * (line_h * 2 + 12) + pad * 2


def render_plan_share_card(
    stats: DayCalendarStats,
    texts: SeagullTexts,
) -> bytes:
    Image, ImageDraw, _ = vc.pil()
    font_eyebrow = vc.load_font(20)
    font_title = vc.load_font(48, bold=True)
    font_quote = vc.load_font(24)
    font_stat_value = vc.load_font(40, bold=True)
    font_stat_label = vc.load_font(18)
    font_stat_sub = vc.load_font(22)
    font_ring_pct = vc.load_font(56, bold=True)
    font_ring_label = vc.load_font(22)
    font_section = vc.load_font(28, bold=True)
    font_event = vc.load_font(24)
    font_event_sub = vc.load_font(20)
    font_footer = vc.load_font(20)

    events = list(stats.events)[:14]
    _measure = ImageDraw.Draw(Image.new("RGB", (vc.CARD_WIDTH, 4)))
    quote_lines = vc.wrap_text_lines(
        _measure,
        vc.strip_markup(texts.main),
        font_quote,
        CONTENT_WIDTH - 80,
        max_lines=2,
    )
    quote_h = max(56, len(quote_lines) * (font_quote.size + 10) + 40)
    hero_h = 280
    schedule_h = _schedule_block_height(
        events, line_h=font_event.size + 6, header_h=48, pad=36
    )
    total_h = (
        vc.MARGIN
        + 32
        + font_title.size
        + 24
        + quote_h
        + 28
        + hero_h
        + 28
        + schedule_h
        + 48
        + vc.MARGIN
    )
    height = max(CARD_MIN_HEIGHT, min(CARD_MAX_HEIGHT, total_h))

    img = Image.new("RGB", (vc.CARD_WIDTH, height), vc.COLOR_BG)
    draw = ImageDraw.Draw(img)
    vc.paste_brand_logo(img)
    draw = ImageDraw.Draw(img)

    y = vc.MARGIN
    draw.text((vc.MARGIN, y), "ЧАЙКА · ПЛАН ДНЯ", fill=vc.COLOR_MUTED, font=font_eyebrow)
    y += 32
    draw.text((vc.MARGIN, y), _title_for_plan(stats), fill=vc.COLOR_TEXT, font=font_title)
    y += font_title.size + 20

    quote_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + quote_h)
    draw = vc.draw_surface_card(img, draw, quote_box)
    qy = y + 20
    for line in quote_lines:
        draw.text((vc.MARGIN + 28, qy), line, fill=vc.COLOR_TEXT, font=font_quote)
        qy += font_quote.size + 10
    y += quote_h + 20

    hero_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + hero_h)
    draw = vc.draw_surface_card(img, draw, hero_box)
    ring_cx = vc.MARGIN + 48 + 100
    ring_cy = y + hero_h // 2
    vc.draw_load_ring(
        draw,
        ring_cx,
        ring_cy,
        92,
        _load_percent(stats),
        font_pct=font_ring_pct,
        font_label=font_ring_label,
    )
    stats_left = vc.MARGIN + 290
    stats_top = y + 36
    vc.draw_stat_row(
        draw,
        stats_left,
        stats_top,
        label="Встречи",
        value=vc.hours_label(stats.busy_minutes),
        sub=vc.meetings_label(stats.meetings_count),
        font_label=font_stat_label,
        font_value=font_stat_value,
        font_sub=font_stat_sub,
        accent=vc.COLOR_ACCENT,
    )
    vc.draw_stat_row(
        draw,
        stats_left,
        stats_top + 108,
        label="Свободно",
        value=vc.hours_label(stats.free_minutes),
        sub=(
            f"Первая {stats.first_meeting_start or '—'} · "
            f"последняя {stats.last_meeting_end or '—'}"
        ),
        font_label=font_stat_label,
        font_value=font_stat_value,
        font_sub=font_stat_sub,
        accent=vc.COLOR_FREE,
    )
    y += hero_h + 28

    sched_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + schedule_h)
    draw = vc.draw_surface_card(img, draw, sched_box)
    pad = 36
    left = vc.MARGIN + pad
    draw.text((left, y + pad), "Расписание", fill=vc.COLOR_TEXT, font=font_section)
    row_y = y + pad + 48
    if not events:
        draw.text(
            (left, row_y),
            "Встреч нет — день свободен для фокуса",
            fill=vc.COLOR_MUTED,
            font=font_event,
        )
    else:
        for index, ev in enumerate(events):
            marker = event_index_marker(index)
            time_range = f"{ev.start_hhmm}–{ev.end_hhmm}"
            title = (ev.title or "—").strip()
            if len(title) > 52:
                title = title[:51] + "…"
            draw.text(
                (left, row_y),
                f"{marker}  {time_range}",
                fill=vc.COLOR_ACCENT,
                font=font_event,
            )
            draw.text(
                (left + 56, row_y),
                title,
                fill=vc.COLOR_TEXT,
                font=font_event,
            )
            if ev.location:
                loc = ev.location.strip()
                if len(loc) > 60:
                    loc = loc[:59] + "…"
                draw.text(
                    (left + 56, row_y + font_event.size + 6),
                    loc,
                    fill=vc.COLOR_MUTED,
                    font=font_event_sub,
                )
                row_y += font_event.size + font_event_sub.size + 16
            else:
                row_y += font_event.size + 14
    y += schedule_h + 24

    draw.text(
        (vc.CARD_WIDTH // 2, height - vc.MARGIN),
        "Сделано в Чайке",
        fill=vc.COLOR_MUTED,
        font=font_footer,
        anchor="mb",
    )
    return vc.png_bytes(img)


def render_upcoming_share_card(
    groups: Sequence[dict[str, Any]],
    *,
    days: int,
    reference_date: date,
) -> bytes:
    Image, ImageDraw, _ = vc.pil()
    font_eyebrow = vc.load_font(20)
    font_title = vc.load_font(48, bold=True)
    font_sub = vc.load_font(26)
    font_day = vc.load_font(26, bold=True)
    font_event = vc.load_font(24)
    font_footer = vc.load_font(20)

    line_h = font_event.size + 10
    day_header_h = font_day.size + 16
    pad = 36
    inner_w = CONTENT_WIDTH - pad * 2
    events_total = sum(len(g.get("events") or []) for g in groups)
    list_h = sum(
        day_header_h + len(g.get("events") or []) * line_h + 24 for g in groups
    )
    list_h = max(list_h, 120)
    total_h = (
        vc.MARGIN
        + 32
        + font_title.size
        + font_sub.size
        + 40
        + list_h
        + pad * 2
        + 56
        + vc.MARGIN
    )
    height = max(CARD_MIN_HEIGHT, min(CARD_MAX_HEIGHT, total_h))

    img = Image.new("RGB", (vc.CARD_WIDTH, height), vc.COLOR_BG)
    draw = ImageDraw.Draw(img)
    vc.paste_brand_logo(img)
    draw = ImageDraw.Draw(img)

    y = vc.MARGIN
    draw.text((vc.MARGIN, y), "ЧАЙКА · БЛИЖАЙШИЕ СОБЫТИЯ", fill=vc.COLOR_MUTED, font=font_eyebrow)
    y += 32
    draw.text((vc.MARGIN, y), f"{days} дней", fill=vc.COLOR_TEXT, font=font_title)
    y += font_title.size + 8
    draw.text(
        (vc.MARGIN, y),
        f"С {reference_date.strftime('%d.%m.%Y')} · {events_total} в календаре",
        fill=vc.COLOR_MUTED,
        font=font_sub,
    )
    y += font_sub.size + 28

    list_box = (vc.MARGIN, y, vc.CARD_WIDTH - vc.MARGIN, y + list_h + pad * 2)
    draw = vc.draw_surface_card(img, draw, list_box)
    left = vc.MARGIN + pad
    row_y = y + pad
    for group in groups:
        header = str(group.get("header") or "—")
        draw.text((left, row_y), header, fill=vc.COLOR_TEXT, font=font_day)
        row_y += day_header_h
        for item in group.get("events") or []:
            title = str(item.get("title") or "—").strip()
            if len(title) > 48:
                title = title[:47] + "…"
            line = f"{item.get('marker', '•')}  {item.get('time_range', '')} — {title}"
            draw.text((left, row_y), line, fill=vc.COLOR_TEXT, font=font_event)
            row_y += line_h
        row_y += 12

    draw.text(
        (vc.CARD_WIDTH // 2, height - vc.MARGIN),
        "Сделано в Чайке",
        fill=vc.COLOR_MUTED,
        font=font_footer,
        anchor="mb",
    )
    return vc.png_bytes(img)
