from datetime import date, datetime
from zoneinfo import ZoneInfo

from satellite.messages_ru import (
    BUTTON_CREATE_EVENT,
    BUTTON_DAY_AFTER,
    BUTTON_FOREIGN_CALENDARS,
    BUTTON_INVITATIONS,
    BUTTON_MANAGE_EVENTS,
    BUTTON_SETTINGS,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    BUTTON_UPCOMING,
    build_approved_main_keyboard,
    button_text_to_mode,
    format_duration_ru,
    normalize_button_text,
)
from satellite.presentation.calendar_lists import (
    upcoming_events_plain_fallback_html,
    upcoming_events_rich_html,
)

TZ = ZoneInfo("Europe/Moscow")


def test_normalize_button_text_strips_variation_selectors():
    assert normalize_button_text("📅\ufe0f Сегодня") == normalize_button_text(BUTTON_TODAY)


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
    действия в третьем, создание и настройки — в одном ряду. См. messages_ru.py.
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
    # «Изменить статус» делит ряд с «Чужие календари»
    manage_row = [btn["text"] for btn in kb["keyboard"][2]]
    assert manage_row == [BUTTON_MANAGE_EVENTS, BUTTON_FOREIGN_CALENDARS]
    # «Создать событие» и «Настройки» — в одном ряду
    bottom_row = [btn["text"] for btn in kb["keyboard"][3]]
    assert bottom_row == [BUTTON_CREATE_EVENT, BUTTON_SETTINGS]


def _ev(**fields):
    return {"summary": "—", **fields}


def test_upcoming_fallback_groups_events_by_day_without_blockquote():
    """Fallback-ветка `/upcoming`: дни-заголовки, плоский HTML без ``<blockquote>``.

    Blockquote тут запрещён намеренно: fallback уходит вместо rich-сообщения с
    ``<details>``, и обёртка давала мигание при подмене одного другим.
    """

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
    html = upcoming_events_plain_fallback_html(events, TZ, ref, days=7)
    assert "<blockquote>" not in html
    assert 'expandable="true"' not in html
    assert "<b>Сегодня" in html
    assert "<b>Завтра" in html
    assert "A" in html
    assert "B1" in html
    assert "B2" in html
    # Оба события завтрашнего дня — под одним заголовком «Завтра».
    tomorrow_at = html.index("<b>Завтра")
    assert html.index("B1") > tomorrow_at
    assert html.index("B2") > tomorrow_at


def test_upcoming_fallback_title_spacing():
    """Заголовок «Ближайшие события» отделён от первого дня одной пустой строкой."""
    ref = date(2026, 5, 21)
    events = [
        _ev(
            summary="A",
            dtstart=datetime(2026, 5, 21, 12, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 13, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="B",
            dtstart=datetime(2026, 5, 21, 14, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 15, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    html = upcoming_events_plain_fallback_html(events, TZ, ref, days=7)
    assert html.startswith("🗓 <b>Ближайшие события</b>\n\n<b>Сегодня")
    assert "🗓 <b>Ближайшие события</b>\n\n\n" not in html


def test_upcoming_fallback_empty_returns_empty_string():
    """Без событий fallback пуст — хендлер показывает отдельный «пусто»-текст."""
    assert upcoming_events_plain_fallback_html([], TZ, date(2026, 5, 20), days=7) == ""


def test_upcoming_rich_collapses_multi_event_day_into_details():
    """Rich-ветка: день с 2+ встречами — ``<details>``, одиночный — простой абзац."""
    ref = date(2026, 5, 20)
    events = [
        _ev(
            summary="Solo",
            dtstart=datetime(2026, 5, 20, 12, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 20, 13, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="Pair1",
            dtstart=datetime(2026, 5, 21, 10, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 11, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="Pair2",
            dtstart=datetime(2026, 5, 21, 14, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 15, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    html = upcoming_events_rich_html(events, TZ, ref, days=7)
    assert html.count("<details") == 1
    summary = html[html.index("<summary>") : html.index("</summary>")]
    assert "Завтра" in summary
    # В summary свёрнутого дня — счётчик встреч, чтобы он читался закрытым.
    assert summary.rstrip().endswith("— 2</b>")
    assert "Solo" in html and "Pair1" in html and "Pair2" in html


def test_upcoming_rich_max_groups_limits_days():
    ref = date(2026, 5, 20)
    events = [
        _ev(
            summary="Day1",
            dtstart=datetime(2026, 5, 20, 12, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 20, 13, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="Day2",
            dtstart=datetime(2026, 5, 21, 12, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 21, 13, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    html = upcoming_events_rich_html(events, TZ, ref, days=7, max_groups=1)
    assert "Day1" in html
    assert "Day2" not in html


def test_upcoming_rich_empty_returns_empty_string():
    assert upcoming_events_rich_html([], TZ, date(2026, 5, 20), days=7) == ""


def test_format_duration_ru():
    assert format_duration_ru(0) == "0 мин"
    assert format_duration_ru(45) == "45 мин"
    assert format_duration_ru(60) == "1 ч"
    assert format_duration_ru(90) == "1 ч 30 мин"
    assert format_duration_ru(540) == "9 ч"
    assert format_duration_ru(-5) == "0 мин"
