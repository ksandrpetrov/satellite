from satellite.messages_ru import (
    BUTTON_DAY_AFTER,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    button_text_to_mode,
    format_duration_ru,
    normalize_button_text,
)


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


def test_format_duration_ru():
    assert format_duration_ru(0) == "0 мин"
    assert format_duration_ru(45) == "45 мин"
    assert format_duration_ru(60) == "1 ч"
    assert format_duration_ru(90) == "1 ч 30 мин"
    assert format_duration_ru(540) == "9 ч"
    assert format_duration_ru(-5) == "0 мин"
