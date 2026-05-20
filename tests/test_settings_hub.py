"""Тесты на новую структуру хаба настроек: разделы и двухшаговый disconnect.

Иерархия:

- ``⚙️ Настройки`` → ``🔔 Дайджест`` / ``📊 Аналитика недели`` / ``📅 Календарь``;
- ``📅 Календарь`` (подэкран) → ``📚 Календари``, ``✅ Проверить``,
  ``🔄 Переподключить`` (Web App), ``🗑 Отключить``;
- ``🗑 Отключить`` → экран подтверждения с двумя кнопками
  (``⚠️ Да, отключить`` и ``⬅️ Отмена``), и только подтверждение реально
  вызывает ``calendar_service.disconnect``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from satellite.messages_ru import (
    BUTTON_ANALYTICS,
    BUTTON_CALENDAR_MENU,
    BUTTON_CALENDAR_SOURCES,
    BUTTON_CHECK_CALENDAR,
    BUTTON_DISCONNECT_CALENDAR,
    BUTTON_DISCONNECT_CALENDAR_CANCEL,
    BUTTON_DISCONNECT_CALENDAR_CONFIRM,
    BUTTON_RECONNECT_CALENDAR,
    BUTTON_SETTINGS,
    CB_SETTINGS_CALENDAR_MENU,
    CB_SETTINGS_DISCONNECT,
    CB_SETTINGS_DISCONNECT_CONFIRM,
    SETTINGS_CALENDAR_MENU_TEXT,
    SETTINGS_DISCONNECT_CONFIRM_TEXT,
    SETTINGS_HUB_TEXT,
    build_settings_calendar_menu_keyboard,
    build_settings_disconnect_confirm_keyboard,
    build_settings_hub_keyboard,
)
from satellite.subscriptions import SubscriptionStore
from satellite.telegram_bot.digest_state import DigestStateStore
from satellite.telegram_bot.handlers import (
    IncomingCallback,
    IncomingMessage,
    handle_callback_query,
    handle_message,
)
from satellite.users import USER_STATUS_APPROVED


_WEBAPP = "https://example.com/connect"


def _approved_user(*, has_calendar: bool = True) -> MagicMock:
    record = MagicMock()
    record.status = USER_STATUS_APPROVED
    record.has_calendar = has_calendar
    return record


def _ctx(tmp_path: Path, *, has_calendar: bool = True) -> MagicMock:
    store = SubscriptionStore(tmp_path / "subs.json")
    state = DigestStateStore()
    record = _approved_user(has_calendar=has_calendar)
    ctx = MagicMock()
    ctx.users = MagicMock()
    ctx.users.get = MagicMock(return_value=record)
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = _WEBAPP
    from satellite.web.connect_token import ConnectTokenStore

    ctx.connect_tokens = ConnectTokenStore()
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.tz = ZoneInfo("Europe/Moscow")
    ctx.subscriptions = store
    ctx.digest_state = state
    ctx.telegram = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 100})
    ctx.telegram.edit_message_text = MagicMock(return_value={})
    ctx.telegram.answer_callback_query = MagicMock(return_value=True)
    ctx.calendar_service = MagicMock()
    ctx.calendar_service.disconnect = MagicMock()
    return ctx


_callback_seq = 0


def _cb(chat_id: int, data: str, *, message_id: int = 42) -> IncomingCallback:
    global _callback_seq
    _callback_seq += 1
    return IncomingCallback(
        update_id=10 + _callback_seq,
        callback_query_id=f"hub-cb-{_callback_seq}",
        chat_id=chat_id,
        message_id=message_id,
        user_id=1,
        username="alice",
        data=data,
    )


# --- структура хаба --------------------------------------------------------


def test_settings_hub_text_uses_seagull_voice():
    """Заголовок хаба упоминает Чайку и кратко перечисляет разделы."""
    assert "Чайка" in SETTINGS_HUB_TEXT or "Чайки" in SETTINGS_HUB_TEXT
    assert "Настройки" in SETTINGS_HUB_TEXT


def test_settings_hub_keyboard_three_sections_when_connected():
    """С подключённым календарём в хабе видны три раздела + закрыть."""
    kb = build_settings_hub_keyboard(webapp_url=_WEBAPP, has_calendar=True)
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert "🔔 Дайджест" in labels
    assert BUTTON_ANALYTICS in labels
    assert BUTTON_CALENDAR_MENU in labels
    # Деструктивный «Отключить» НЕ должен висеть на главном экране настроек,
    # чтобы случайным нажатием не отвязать календарь.
    assert BUTTON_DISCONNECT_CALENDAR not in labels
    # Проверка соединения и переподключение тоже спрятаны в подэкран Календаря.
    assert BUTTON_CHECK_CALENDAR not in labels
    assert BUTTON_RECONNECT_CALENDAR not in labels


def test_settings_hub_keyboard_offers_connect_when_no_calendar():
    """Без календаря единственное календарное действие — подключиться."""
    kb = build_settings_hub_keyboard(webapp_url=_WEBAPP, has_calendar=False)
    flat = [btn for row in kb["inline_keyboard"] for btn in row]
    labels = [btn["text"] for btn in flat]
    assert any("Подключить календарь" in lbl for lbl in labels)
    # Подэкран «Календарь» без подключения не имеет смысла
    assert BUTTON_CALENDAR_MENU not in labels


def test_settings_calendar_menu_groups_all_calendar_actions():
    kb = build_settings_calendar_menu_keyboard(webapp_url=_WEBAPP)
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert BUTTON_CALENDAR_SOURCES in labels
    assert BUTTON_CHECK_CALENDAR in labels
    assert BUTTON_RECONNECT_CALENDAR in labels
    assert BUTTON_DISCONNECT_CALENDAR in labels
    # Возврат в общий хаб
    assert any("В настройки" in lbl for lbl in labels)


# --- двухшаговый disconnect -------------------------------------------------


def test_disconnect_first_click_shows_confirmation_only(tmp_path: Path):
    """Первый клик по «Отключить» — экран подтверждения, без реального disconnect."""
    ctx = _ctx(tmp_path)

    handle_callback_query(ctx, _cb(900, CB_SETTINGS_DISCONNECT))

    ctx.calendar_service.disconnect.assert_not_called()
    edit = ctx.telegram.edit_message_text.call_args
    assert edit.args[2] == SETTINGS_DISCONNECT_CONFIRM_TEXT
    keyboard = edit.kwargs.get("reply_markup") or edit.args[-1]
    labels = [btn["text"] for row in keyboard["inline_keyboard"] for btn in row]
    assert BUTTON_DISCONNECT_CALENDAR_CONFIRM in labels
    assert BUTTON_DISCONNECT_CALENDAR_CANCEL in labels


def test_disconnect_confirm_actually_disconnects(tmp_path: Path):
    """Нажатие «⚠️ Да, отключить» — реально зовём calendar_service.disconnect."""
    ctx = _ctx(tmp_path)

    handle_callback_query(ctx, _cb(900, CB_SETTINGS_DISCONNECT_CONFIRM))

    ctx.calendar_service.disconnect.assert_called_once_with(1)


def test_disconnect_cancel_returns_to_calendar_menu(tmp_path: Path):
    """Отмена ведёт обратно в подэкран «Календарь», календарь не трогаем."""
    ctx = _ctx(tmp_path)

    handle_callback_query(ctx, _cb(900, CB_SETTINGS_CALENDAR_MENU))

    ctx.calendar_service.disconnect.assert_not_called()
    last_edit = ctx.telegram.edit_message_text.call_args
    assert last_edit.args[2] == SETTINGS_CALENDAR_MENU_TEXT


def test_settings_button_opens_hub(tmp_path: Path):
    """Кнопка «⚙️ Настройки» по-прежнему открывает главный экран хаба."""
    ctx = _ctx(tmp_path)
    msg = IncomingMessage(
        update_id=1,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_SETTINGS,
    )
    handle_message(ctx, msg)

    call = ctx.telegram.send_message.call_args
    assert "Настройки Чайки" in call.args[1]


# --- подтверждение всегда отдаёт корректную клавиатуру ---------------------


def test_disconnect_confirm_keyboard_only_has_two_buttons():
    kb = build_settings_disconnect_confirm_keyboard()
    rows = kb["inline_keyboard"]
    assert len(rows) == 2
    assert rows[0][0]["text"] == BUTTON_DISCONNECT_CALENDAR_CONFIRM
    assert rows[1][0]["text"] == BUTTON_DISCONNECT_CALENDAR_CANCEL
