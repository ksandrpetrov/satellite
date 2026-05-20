from datetime import date, datetime
from zoneinfo import ZoneInfo

from satellite.messages_ru import (
    BUTTON_CREATE_EVENT,
    BUTTON_DAY_AFTER,
    BUTTON_FOREIGN_CALENDARS,
    BUTTON_MANAGE_EVENTS,
    BUTTON_SETTINGS,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    BUTTON_INVITATIONS,
    BUTTON_UPCOMING,
    build_approved_main_keyboard,
    button_text_to_mode,
    format_duration_ru,
    normalize_button_text,
    upcoming_events_html,
)

TZ = ZoneInfo("Europe/Moscow")


def test_normalize_button_text_strips_variation_selectors():
    assert normalize_button_text("📅\uFE0F Сегодня") == normalize_button_text(BUTTON_TODAY)


def test_button_text_to_mode_handles_known_buttons():
    assert button_text_to_mode(BUTTON_TODAY) == "today"
    assert button_text_to_mode(BUTTON_TOMORROW) == "tomorrow"
    assert button_text_to_mode(BUTTON_DAY_AFTER) == "day_after_tomorrow"


def test_button_text_to_mode_unknown():
    assert button_text_to_mode("td") is None
    assert button_text_to_mode("") is None
    assert button_text_to_mode(None) is None


def test_approved_main_keyboard_layout():
    """Раскладка главной клавиатуры: план дня в первом ряду, виды во втором,
    действия и настройки — отдельными строками. См. AGENTS.md / messages_ru.py.
    """
    kb = build_approved_main_keyboard()
    labels = [btn["text"] for row in kb["keyboard"] for btn in row]
    assert labels == [
        BUTTON_TODAY,
        BUTTON_TOMORROW,
        BUTTON_UPCOMING,
        BUTTON_INVITATIONS,
        BUTTON_MANAGE_EVENTS,
        BUTTON_FOREIGN_CALENDARS,
        BUTTON_CREATE_EVENT,
        BUTTON_SETTINGS,
    ]
    # Сегодня и Завтра — рядом в одном ряду
    first_row = [btn["text"] for btn in kb["keyboard"][0]]
    assert first_row == [BUTTON_TODAY, BUTTON_TOMORROW]
    # «Изменить статус» делит ряд с «Чужие календари» — компактный второй блок
    manage_row = [btn["text"] for btn in kb["keyboard"][2]]
    assert manage_row == [BUTTON_MANAGE_EVENTS, BUTTON_FOREIGN_CALENDARS]


def _ev(**fields):
    return {"summary": "—", **fields}


def test_upcoming_events_html_expandable_per_day_not_whole_list():
    ref = date(2026, 5, 20)
    events = [
        _ev(
            summary="A",
            dtstart=datetime(2026, 5, 20, 9, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 20, 10, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="B1",
            dtstart=datetime(2026, 5, 21, 10, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 11, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="B2",
            dtstart=datetime(2026, 5, 21, 14, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 15, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    html = upcoming_events_html(events, TZ, ref, days=7)
    assert html.count('expandable="true"') == 1
    assert "<b>Сегодня" in html
    assert "<b>Завтра" in html
    assert "A" in html
    assert "B1" in html
    assert "B2" in html
    # Заголовок «Завтра» снаружи единственного expandable-блока этого дня
    tomorrow_header = html.index("<b>Завтра")
    expandable_pos = html.index('expandable="true"')
    assert tomorrow_header < expandable_pos
    block_end = html.index("</blockquote>", expandable_pos)
    assert "Завтра" not in html[expandable_pos:block_end]


def test_upcoming_events_html_single_event_day_plain():
    ref = date(2026, 5, 20)
    events = [
        _ev(
            summary="Solo",
            dtstart=datetime(2026, 5, 20, 12, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 20, 13, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    html = upcoming_events_html(events, TZ, ref, days=7)
    assert 'expandable="true"' not in html
    assert "Solo" in html


def test_format_duration_ru():
    assert format_duration_ru(0) == "0 мин"
    assert format_duration_ru(45) == "45 мин"
    assert format_duration_ru(60) == "1 ч"
    assert format_duration_ru(90) == "1 ч 30 мин"
    assert format_duration_ru(540) == "9 ч"
    assert format_duration_ru(-5) == "0 мин"
