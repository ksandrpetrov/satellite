"""Кнопки reply-клавиатуры и матчеры текста (satellite.messages_ru)."""

from __future__ import annotations

import unicodedata

# Реэкспорт доменных констант календаря: сами строки теперь живут в
# ``satellite.calendar.constants``, чтобы календарь не зависел от слоя UI.

# --- Telegram: подписи кнопок ---
BUTTON_TODAY = "📅 Сегодня"
BUTTON_TOMORROW = "➡️ Завтра"
BUTTON_DAY_AFTER = "⏭ Послезавтра"
BUTTON_UPCOMING = "🗓 Ближайшие события"
BUTTON_INVITATIONS = "📨 Приглашения"
BUTTON_MANAGE_EVENTS = "🛠 Изменить статус"
BUTTON_CREATE_EVENT = "➕ Создать событие"
BUTTON_SUBSCRIBE = "🔔 Подписаться на дайджест"
BUTTON_UNSUBSCRIBE = "🔕 Отключить дайджест"
BUTTON_UNSUBSCRIBE_LEGACY = "🔕 Отписаться от дайджеста"
BUTTON_SETTINGS = "⚙️ Настройки"
BUTTON_DIGEST_SETTINGS = "⚙️ Настройки дайджеста"  # legacy reply-кнопка
BUTTON_CONNECT_CALENDAR = "🔌 Подключить календарь"
BUTTON_RECONNECT_CALENDAR = "🔄 Переподключить календарь"
BUTTON_DISCONNECT_CALENDAR = "🗑 Отключить календарь"
BUTTON_CHECK_CALENDAR = "✅ Проверить подключение"
BUTTON_CALENDAR_SOURCES = "📚 Календари"
BUTTON_FOREIGN_CALENDARS = "👥 Чужие календари"

ButtonStyle = str  # "primary" | "success" | "danger"


def styled_button(
    text: str,
    callback_data: str,
    *,
    style: ButtonStyle | None = None,
) -> dict[str, str]:
    """Inline-кнопка с опциональным цветом (Bot API: primary / success / danger)."""
    btn: dict[str, str] = {"text": text, "callback_data": callback_data}
    if style:
        btn["style"] = style
    return btn


BUTTON_TO_PLAN_MODE: dict[str, str] = {
    BUTTON_TODAY: "today",
    BUTTON_TOMORROW: "tomorrow",
    BUTTON_DAY_AFTER: "day_after_tomorrow",
}


_VARIATION_SELECTORS_RANGE = (0xFE00, 0xFE0F)


def _is_invisible_combining(ch: str) -> bool:
    code = ord(ch)
    if _VARIATION_SELECTORS_RANGE[0] <= code <= _VARIATION_SELECTORS_RANGE[1]:
        return True
    return unicodedata.category(ch) == "Cf"


def normalize_button_text(text: str | None) -> str:
    """Нормализует текст кнопки: NFKC + strip + удаление variation selectors / ZWJ.

    Telegram иногда добавляет/убирает невидимые селекторы вариаций (U+FE0F и др.)
    у эмодзи, что ломает прямое сравнение строк.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).strip()
    return "".join(ch for ch in normalized if not _is_invisible_combining(ch))


_NORMALIZED_BUTTON_TO_MODE: dict[str, str] = {
    normalize_button_text(label): mode for label, mode in BUTTON_TO_PLAN_MODE.items()
}

_NORMALIZED_BUTTON_SUBSCRIBE = normalize_button_text(BUTTON_SUBSCRIBE)
_NORMALIZED_BUTTON_UNSUBSCRIBE = {
    normalize_button_text(BUTTON_UNSUBSCRIBE),
    normalize_button_text(BUTTON_UNSUBSCRIBE_LEGACY),
}
_NORMALIZED_BUTTON_SETTINGS = normalize_button_text(BUTTON_SETTINGS)
_NORMALIZED_BUTTON_DIGEST_SETTINGS = normalize_button_text(BUTTON_DIGEST_SETTINGS)
_NORMALIZED_BUTTON_UPCOMING = normalize_button_text(BUTTON_UPCOMING)
_NORMALIZED_BUTTON_INVITATIONS = normalize_button_text(BUTTON_INVITATIONS)
_NORMALIZED_BUTTON_MANAGE_EVENTS = normalize_button_text(BUTTON_MANAGE_EVENTS)
_NORMALIZED_BUTTON_CREATE_EVENT = normalize_button_text(BUTTON_CREATE_EVENT)
_NORMALIZED_BUTTON_CONNECT = normalize_button_text(BUTTON_CONNECT_CALENDAR)
_NORMALIZED_BUTTON_RECONNECT = normalize_button_text(BUTTON_RECONNECT_CALENDAR)
_NORMALIZED_BUTTON_DISCONNECT = normalize_button_text(BUTTON_DISCONNECT_CALENDAR)
_NORMALIZED_BUTTON_CHECK = normalize_button_text(BUTTON_CHECK_CALENDAR)
_NORMALIZED_BUTTON_CALENDAR_SOURCES = normalize_button_text(BUTTON_CALENDAR_SOURCES)
_NORMALIZED_BUTTON_FOREIGN_CALENDARS = normalize_button_text(BUTTON_FOREIGN_CALENDARS)


def button_text_to_mode(text: str | None) -> str | None:
    if not text:
        return None
    return _NORMALIZED_BUTTON_TO_MODE.get(normalize_button_text(text))


def button_text_is_subscribe(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_SUBSCRIBE


def button_text_is_unsubscribe(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) in _NORMALIZED_BUTTON_UNSUBSCRIBE


def button_text_is_settings(text: str | None) -> bool:
    if not text:
        return False
    normalized = normalize_button_text(text)
    return normalized in {
        _NORMALIZED_BUTTON_SETTINGS,
        _NORMALIZED_BUTTON_DIGEST_SETTINGS,
    }


def button_text_is_digest_settings(text: str | None) -> bool:
    """Legacy alias: старая кнопка «Настройки дайджеста» открывает общий экран настроек."""
    return button_text_is_settings(text)


def button_text_is_upcoming(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_UPCOMING


def button_text_is_invitations(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_INVITATIONS


def button_text_is_manage_events(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_MANAGE_EVENTS


def button_text_is_create_event(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_CREATE_EVENT


def button_text_is_connect_calendar(text: str | None) -> bool:
    if not text:
        return False
    normalized = normalize_button_text(text)
    return normalized in {_NORMALIZED_BUTTON_CONNECT, _NORMALIZED_BUTTON_RECONNECT}


def button_text_is_disconnect_calendar(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_DISCONNECT


def button_text_is_check_calendar(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_CHECK


def button_text_is_calendar_sources(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_CALENDAR_SOURCES


def button_text_is_foreign_calendars(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_FOREIGN_CALENDARS
