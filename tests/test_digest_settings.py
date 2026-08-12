"""Тесты per-user настроек дайджеста: store, handlers, callback_query, FSM.

Покрывают сценарии из ТЗ:
- дефолтные значения для нового пользователя,
- открытие экрана настроек,
- переключение дней (только будни / все дни) через inline callback,
- ввод времени: валидация, ошибки, очистка state,
- кнопка «Назад к настройкам» очищает state ожидания времени,
- старые кнопки подписки совместимы с новой моделью настроек.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.time_utils import normalize_hhmm_input
from satellite.messages_ru import (
    BUTTON_DIGEST_SETTINGS,
    BUTTON_SETTINGS,
    CB_DIGEST_BACK,
    CB_DIGEST_CLOSE,
    CB_DIGEST_DAYS,
    CB_DIGEST_DAYS_ALL,
    CB_DIGEST_DAYS_WEEKDAYS,
    CB_DIGEST_SETTINGS,
    CB_DIGEST_TIME,
    CB_DIGEST_TOGGLE,
    CB_DIGEST_WEATHER_TOGGLE,
    CB_SETTINGS_DIGEST,
    DIGEST_DAYS_ALL_APPLIED_TEXT,
    DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
    DIGEST_SETTINGS_CLOSED_TEXT,
    DIGEST_TIME_INVALID_TEXT,
    ERR_SETTINGS_SAVE_FAILED_TEXT,
    build_digest_days_keyboard,
    build_digest_settings_keyboard,
    button_text_is_settings,
    digest_settings_screen_text,
    digest_time_applied_text,
)
from satellite.subscriptions import (
    DEFAULT_DIGEST_DAYS,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DIGEST_TIMEZONE,
    DIGEST_DAYS_ALL,
    DIGEST_DAYS_WEEKDAYS,
    DigestSettings,
    SubscriptionStore,
    SubscriptionStorePersistenceError,
)
from satellite.telegram_bot.handlers import (
    IncomingCallback,
    IncomingMessage,
    handle_callback_query,
    handle_message,
    is_settings_request,
)
from satellite.telegram_bot.handlers.digest_state import DigestStateStore
from satellite.telegram_bot.handlers.settings import handle_digest_time_input
from satellite.testing.delivery_helpers import (
    callback_edit_html,
    callback_edit_markup,
    callback_edit_was_called,
    final_message_html,
    final_reply_markup,
    sent_messages_text,
)

from .conftest import make_fake_telegram

# --- time validation -------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("09:00", "09:00"),
        ("9:00", "09:00"),
        ("8:30", "08:30"),
        ("08:30", "08:30"),
        ("18:25", "18:25"),
        ("23:59", "23:59"),
        ("00:00", "00:00"),
        ("  9:00  ", "09:00"),  # с пробелами вокруг
        ("17 30", "17:30"),  # пробел как разделитель
        ("9 05", "09:05"),
        ("23 59", "23:59"),
        ("  17 30  ", "17:30"),
        ("17  30", "17:30"),  # несколько пробелов как разделитель
    ],
)
def test_normalize_hhmm_input_accepts_valid_values(raw, expected):
    assert normalize_hhmm_input(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "25:00",
        "12:99",
        "утром",
        "9 утра",
        "900",
        "09-00",
        "",
        "   ",
        "9",
        ":30",
        "09:",
        "09:5",  # минуты должны быть две цифры
        "0900",
        "25 00",  # часы вне диапазона (с пробелом-разделителем)
        "9 5",  # минуты должны быть две цифры
        "9  5",  # минуты должны быть две цифры (несколько пробелов)
        " 30",  # без часа
        None,
    ],
)
def test_normalize_hhmm_input_rejects_invalid_values(raw):
    assert normalize_hhmm_input(raw) is None


# --- store / defaults ------------------------------------------------------


def test_new_user_has_default_settings(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    settings = store.get_or_create(123, "alice")
    assert isinstance(settings, DigestSettings)
    assert settings.digest_enabled is False
    assert settings.digest_days == DEFAULT_DIGEST_DAYS == "weekdays"
    assert settings.digest_time == DEFAULT_DIGEST_TIME == "09:00"
    assert settings.digest_timezone == DEFAULT_DIGEST_TIMEZONE == "Europe/Moscow"
    assert settings.last_digest_sent_date is None


def test_get_or_create_updates_username_on_rename(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.get_or_create(1, "old_name")
    updated = store.get_or_create(1, "New_Name")
    assert updated.username == "new_name"


def test_update_settings_persists_changes(tmp_path: Path):
    path = tmp_path / "subs.json"
    store = SubscriptionStore(path)
    store.get_or_create(1, "alice")
    store.update_settings(1, "alice", digest_days=DIGEST_DAYS_ALL, digest_time="08:30")

    reloaded = SubscriptionStore(path)
    settings = reloaded.get(1)
    assert settings is not None
    assert settings.digest_days == DIGEST_DAYS_ALL
    assert settings.digest_time == "08:30"


def test_update_settings_ignores_invalid_time(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.get_or_create(1, "alice")
    store.update_settings(1, "alice", digest_time="08:30")
    store.update_settings(1, "alice", digest_time="25:99")
    assert store.get(1).digest_time == "08:30"


def test_update_settings_ignores_invalid_days(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.get_or_create(1, "alice")
    store.update_settings(1, "alice", digest_days="garbage")
    assert store.get(1).digest_days == DEFAULT_DIGEST_DAYS


def test_subscribe_preserves_existing_custom_settings(tmp_path: Path):
    """Старая кнопка подписки не должна сбрасывать персональные настройки."""
    store = SubscriptionStore(tmp_path / "subs.json")
    store.get_or_create(1, "alice")
    store.update_settings(1, "alice", digest_days=DIGEST_DAYS_ALL, digest_time="10:15")
    store.subscribe(1, "alice")
    settings = store.get(1)
    assert settings.digest_enabled is True
    assert settings.digest_days == DIGEST_DAYS_ALL
    assert settings.digest_time == "10:15"


def test_unsubscribe_does_not_drop_settings_record(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_time="10:15")
    store.unsubscribe(1)
    settings = store.get(1)
    assert settings is not None
    assert settings.digest_enabled is False
    # время сохранилось, чтобы при повторном включении не настраивать заново
    assert settings.digest_time == "10:15"


def test_mark_digest_sent_persists(tmp_path: Path):
    path = tmp_path / "subs.json"
    store = SubscriptionStore(path)
    store.subscribe(1, "alice")
    store.mark_digest_sent(1, "2026-05-11")

    reloaded = SubscriptionStore(path)
    assert reloaded.get(1).last_digest_sent_date == "2026-05-11"


def test_legacy_subscription_file_migrates_to_defaults(tmp_path: Path):
    """Старый формат: только username/subscribed_at, без явных digest_*."""
    import json

    path = tmp_path / "subs.json"
    path.write_text(
        json.dumps(
            {
                "100": {
                    "username": "alice",
                    "subscribed_at": "2024-01-01T00:00:00+00:00",
                }
            }
        )
    )
    store = SubscriptionStore(path)
    settings = store.get(100)
    assert settings is not None
    assert settings.digest_enabled is True  # старая запись = активная подписка
    assert settings.digest_days == DEFAULT_DIGEST_DAYS
    assert settings.digest_time == DEFAULT_DIGEST_TIME
    assert settings.digest_timezone == DEFAULT_DIGEST_TIMEZONE
    assert settings.pending_digest_enabled is False
    assert settings.pending_digest_time == "10:00"
    assert settings.last_pending_digest_sent_date is None


def test_pending_digest_fields_round_trip(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.update_settings(
        100,
        "alice",
        pending_digest_enabled=True,
        pending_digest_days=DIGEST_DAYS_ALL,
        pending_digest_time="11:15",
    )
    store.mark_pending_digest_sent(100, "2026-05-11")
    reloaded = SubscriptionStore(tmp_path / "subs.json")
    rec = reloaded.get(100)
    assert rec is not None
    assert rec.pending_digest_enabled is True
    assert rec.pending_digest_days == DIGEST_DAYS_ALL
    assert rec.pending_digest_time == "11:15"
    assert rec.last_pending_digest_sent_date == "2026-05-11"


def test_corrupted_subscription_file_normalizes_time_and_bool(tmp_path: Path):
    import json

    path = tmp_path / "subs.json"
    path.write_text(
        json.dumps(
            {
                "100": {
                    "username": "alice",
                    "digest_enabled": "false",
                    "digest_time": "9:00",
                    "digest_days": "garbage",
                },
                "101": {
                    "username": "bob",
                    "digest_enabled": "true",
                    "digest_time": "bad",
                },
            }
        ),
        encoding="utf-8",
    )

    store = SubscriptionStore(path)
    alice = store.get(100)
    bob = store.get(101)
    assert alice is not None
    assert alice.digest_enabled is False
    assert alice.digest_time == "09:00"
    assert alice.digest_days == DEFAULT_DIGEST_DAYS
    assert bob is not None
    assert bob.digest_enabled is True
    assert bob.digest_time == DEFAULT_DIGEST_TIME


# --- FSM state -------------------------------------------------------------


def test_digest_state_store_basic_flow():
    from satellite.telegram_bot.handlers.digest_state import DIGEST_KIND_PENDING

    s = DigestStateStore()
    assert not s.is_waiting_for_time(1)
    s.set_waiting_for_time(1, message_id=42)
    assert s.is_waiting_for_time(1)
    assert s.get(1).message_id == 42
    assert s.get(1).digest_kind == "daily"

    s.set_waiting_for_time(2, message_id=99, digest_kind=DIGEST_KIND_PENDING)
    assert s.get(2).digest_kind == DIGEST_KIND_PENDING

    cleared = s.clear(1)
    assert cleared is not None
    assert not s.is_waiting_for_time(1)


# --- helpers ---------------------------------------------------------------


def _ctx(tmp_path: Path, *, username: str = "alice"):
    from satellite.users import USER_STATUS_APPROVED

    store = SubscriptionStore(tmp_path / "subs.json")
    state = DigestStateStore()
    approved = MagicMock()
    approved.status = USER_STATUS_APPROVED
    approved.has_calendar = True
    ctx = MagicMock()
    ctx.users = MagicMock()
    ctx.users.get = MagicMock(return_value=approved)
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = ""
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.tz = ZoneInfo("Europe/Moscow")
    ctx.subscriptions = store
    ctx.digest_state = state
    ctx.telegram = make_fake_telegram()
    return ctx, store, state


# --- открытие экрана настроек --------------------------------------------


def test_settings_screen_opens_from_both_buttons():
    # Старая кнопка «Настройки дайджеста» ведёт на тот же общий экран настроек.
    assert button_text_is_settings(BUTTON_DIGEST_SETTINGS)
    assert button_text_is_settings(BUTTON_SETTINGS)
    assert is_settings_request(BUTTON_DIGEST_SETTINGS)
    assert is_settings_request(BUTTON_SETTINGS)
    # /settings — единственная команда, открывающая экран настроек.
    # /digest теперь сразу включает подписку (см. parse_subscription_action).
    assert is_settings_request("/settings")
    assert not is_settings_request("/digest")
    assert not is_settings_request("/stopdigest")
    assert not is_settings_request("td")


def test_digest_settings_button_sends_inline_settings_screen(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    msg = IncomingMessage(
        update_id=1,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_SETTINGS,
    )
    handle_message(ctx, msg)

    text = final_message_html(ctx.telegram)
    assert "Настройки Чайки" in text
    keyboard = final_reply_markup(ctx.telegram)
    assert keyboard is not None
    assert "inline_keyboard" in keyboard
    labels = [btn["text"] for row in keyboard["inline_keyboard"] for btn in row]
    assert "🔔 Дайджест на сегодня" in labels
    assert "📨 Дайджест непринятых встреч" in labels


def test_settings_hub_digest_button_opens_digest_screen(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    msg = IncomingMessage(
        update_id=1,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_SETTINGS,
    )
    handle_message(ctx, msg)

    handle_callback_query(ctx, _callback(900, CB_SETTINGS_DIGEST))

    text = callback_edit_html(ctx.telegram)
    assert "Настройки дайджеста на сегодня" in text
    assert "🔕" in text
    assert "будни" in text
    assert "09:00 МСК" in text


def test_digest_settings_screen_shows_enabled_status_after_subscribe(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.subscribe(900, "alice")
    msg = IncomingMessage(
        update_id=2,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_SETTINGS,
    )
    handle_message(ctx, msg)
    handle_callback_query(ctx, _callback(900, CB_SETTINGS_DIGEST))

    text = callback_edit_html(ctx.telegram)
    assert "🔔" in text
    assert "включён" in text


# --- callback: дни --------------------------------------------------------


_callback_seq = 0


def _callback(chat_id, data, message_id=42):
    """Каждый вызов получает уникальный callback_query_id — иначе сработает
    dedup и второй callback с тем же id будет проигнорирован.

    В Telegram callback_query_id всегда уникален per click, поэтому в продакшене
    это работает корректно.
    """
    global _callback_seq
    _callback_seq += 1
    return IncomingCallback(
        update_id=10 + _callback_seq,
        callback_query_id=f"cb-{_callback_seq}",
        chat_id=chat_id,
        message_id=message_id,
        user_id=1,
        username="alice",
        data=data,
    )


def test_callback_days_screen_shows_current_value(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")  # weekdays по умолчанию

    handle_callback_query(ctx, _callback(900, CB_DIGEST_DAYS))

    assert callback_edit_was_called(ctx.telegram)
    text = callback_edit_html(ctx.telegram)
    assert "Дни отправки" in text
    assert "будни" in text


def test_callback_select_weekdays_saves_and_acks(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    store.update_settings(900, "alice", digest_days=DIGEST_DAYS_ALL)

    handle_callback_query(ctx, _callback(900, CB_DIGEST_DAYS_WEEKDAYS))

    assert store.get(900).digest_days == DIGEST_DAYS_WEEKDAYS
    # после выбора отправляется подтверждение
    sent_messages = sent_messages_text(ctx.telegram)
    assert DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT in sent_messages
    # и сам inline-экран обновлён на главный (через editMessageText)
    assert callback_edit_was_called(ctx.telegram)


def test_callback_select_all_days_saves_value(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    handle_callback_query(ctx, _callback(900, CB_DIGEST_DAYS_ALL))

    assert store.get(900).digest_days == DIGEST_DAYS_ALL
    sent_messages = sent_messages_text(ctx.telegram)
    assert DIGEST_DAYS_ALL_APPLIED_TEXT in sent_messages


# --- callback: время + state ----------------------------------------------


def test_callback_time_sets_waiting_state(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    handle_callback_query(ctx, _callback(900, CB_DIGEST_TIME, message_id=77))

    assert state.is_waiting_for_time(900)
    assert state.get(900).message_id == 77
    # пользователю показали экран ввода времени (через edit)
    edit_text = callback_edit_html(ctx.telegram)
    assert "Время отправки" in edit_text
    assert "09:30" in edit_text


def test_valid_time_input_saves_and_clears_state(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    state.set_waiting_for_time(900, message_id=77)

    msg = IncomingMessage(
        update_id=20, chat_id=900, user_id=1, username="alice", display_name=None, text="8:30"
    )
    handle_message(ctx, msg)

    assert store.get(900).digest_time == "08:30"
    assert not state.is_waiting_for_time(900)
    # отправили подтверждение успеха
    confirm = final_message_html(ctx.telegram)
    assert confirm == digest_time_applied_text("08:30")


def test_valid_time_input_09_00_stays_normalized(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    state.set_waiting_for_time(900, message_id=77)

    msg = IncomingMessage(
        update_id=21, chat_id=900, user_id=1, username="alice", display_name=None, text="09:00"
    )
    handle_message(ctx, msg)

    assert store.get(900).digest_time == "09:00"


def test_invalid_time_input_keeps_state_and_does_not_change_settings(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    state.set_waiting_for_time(900, message_id=77)
    original_time = store.get(900).digest_time

    msg = IncomingMessage(
        update_id=22, chat_id=900, user_id=1, username="alice", display_name=None, text="25:00"
    )
    handle_message(ctx, msg)

    assert store.get(900).digest_time == original_time
    assert state.is_waiting_for_time(900)  # state НЕ очищен
    invalid_msg = final_message_html(ctx.telegram)
    assert invalid_msg == DIGEST_TIME_INVALID_TEXT


def test_back_to_settings_clears_state(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    state.set_waiting_for_time(900, message_id=77)

    handle_callback_query(ctx, _callback(900, CB_DIGEST_BACK, message_id=77))

    assert not state.is_waiting_for_time(900)


def test_back_callback_does_not_change_time(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    store.update_settings(900, "alice", digest_time="10:15")
    state.set_waiting_for_time(900, message_id=77)

    handle_callback_query(ctx, _callback(900, CB_DIGEST_BACK, message_id=77))

    assert store.get(900).digest_time == "10:15"


# --- callback: toggle -----------------------------------------------------


def test_callback_toggle_enables_and_disables(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    assert store.get(900).digest_enabled is False

    handle_callback_query(ctx, _callback(900, CB_DIGEST_TOGGLE))
    assert store.get(900).digest_enabled is True

    handle_callback_query(ctx, _callback(900, CB_DIGEST_TOGGLE))
    assert store.get(900).digest_enabled is False


def test_callback_toggle_persistence_failure_sends_safe_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    monkeypatch.setattr(
        store,
        "_persist_payload",
        MagicMock(side_effect=SubscriptionStorePersistenceError("disk full")),
    )

    handle_callback_query(ctx, _callback(900, CB_DIGEST_TOGGLE))

    sent_texts = sent_messages_text(ctx.telegram)
    assert ERR_SETTINGS_SAVE_FAILED_TEXT in sent_texts
    ctx.telegram.edit_message_text.assert_not_called()
    ctx.telegram.answer_callback_query.assert_called()


def test_duplicate_callback_query_id_is_dropped(tmp_path: Path):
    """Повторная доставка того же callback_query от Telegram должна быть no-op.

    Раньше это приводило к лавине дубликатов inline-сообщений: каждый дубль
    бил по editMessageText → «message is not modified» → fallback в
    send_message → новое сообщение в чат.
    """
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    cb = IncomingCallback(
        update_id=500,
        callback_query_id="cb-duplicate",
        chat_id=900,
        message_id=42,
        user_id=1,
        username="alice",
        data=CB_DIGEST_TIME,
    )

    handle_callback_query(ctx, cb)
    handle_callback_query(ctx, cb)  # тот же id — должен быть проигнорирован
    handle_callback_query(ctx, cb)

    # edit вызван только один раз; send_message — ни разу
    # (раньше fallback в send_message и был источником спама).
    assert (
        ctx.telegram.edit_message_rich.call_count + ctx.telegram.edit_message_text.call_count
    ) == 1
    ctx.telegram.send_message.assert_not_called()
    ctx.telegram.send_rich_message.assert_not_called()
    assert ctx.telegram.answer_callback_query.call_count == 3


def test_unknown_callback_is_answered_and_ignored(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    handle_callback_query(ctx, _callback(900, "unknown-callback-data"))

    ctx.telegram.answer_callback_query.assert_called_once()
    ctx.telegram.edit_message_text.assert_not_called()


def test_edit_failure_does_not_fallback_to_send_message(tmp_path: Path):
    """`editMessageText` упал — не отправляем дубликат через send_message.

    Регрессия: раньше при «message is not modified» бот слал новое сообщение
    с тем же содержимым → пользователь получал лавину «Напиши новое время…».
    """
    from satellite.telegram_bot.api import TelegramError

    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    ctx.telegram.edit_message_text.side_effect = TelegramError(
        "Bad Request: message is not modified"
    )

    handle_callback_query(ctx, _callback(900, CB_DIGEST_TIME))

    assert callback_edit_was_called(ctx.telegram)
    ctx.telegram.send_message.assert_not_called()


def test_callback_set_days_skips_confirmation_when_value_unchanged(tmp_path: Path):
    """Повторный тап по уже-активному «Только будни» не должен слать «📆 Готово.»."""
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")  # weekdays по умолчанию

    handle_callback_query(ctx, _callback(900, CB_DIGEST_DAYS_WEEKDAYS))

    confirmations = [
        c.args[1] for c in ctx.telegram.send_message.call_args_list if "Готово" in c.args[1]
    ]
    assert confirmations == []


def test_callback_close_clears_state(tmp_path: Path):
    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    state.set_waiting_for_time(900, message_id=77)

    handle_callback_query(ctx, _callback(900, CB_DIGEST_CLOSE))

    assert not state.is_waiting_for_time(900)
    edit_text = callback_edit_html(ctx.telegram)
    assert edit_text == DIGEST_SETTINGS_CLOSED_TEXT


def test_callback_settings_opens_main_screen(tmp_path: Path):
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    handle_callback_query(ctx, _callback(900, CB_DIGEST_SETTINGS))

    edit_text = callback_edit_html(ctx.telegram)
    assert "Настройки дайджеста на сегодня" in edit_text


# --- дайджест непринятых встреч --------------------------------------------


def test_settings_hub_pending_button_opens_pending_screen(tmp_path: Path):
    from satellite.messages_ru import CB_PENDING_DIGEST_SETTINGS

    ctx, store, _state = _ctx(tmp_path)
    handle_callback_query(ctx, _callback(900, CB_PENDING_DIGEST_SETTINGS))

    text = callback_edit_html(ctx.telegram)
    assert "Дайджест непринятых встреч" in text
    assert "🔕" in text


def test_pending_digest_toggle_enables(tmp_path: Path):
    from satellite.messages_ru import CB_PENDING_DIGEST_TOGGLE

    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    handle_callback_query(ctx, _callback(900, CB_PENDING_DIGEST_TOGGLE))

    assert store.get(900).pending_digest_enabled is True
    text = callback_edit_html(ctx.telegram)
    assert "включён" in text


def test_pending_digest_days_bitmask_round_trip(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.update_settings(100, "alice", pending_digest_days="1010100")
    rec = store.get(100)
    assert rec is not None
    assert rec.pending_digest_days == "1010100"

    reloaded = SubscriptionStore(tmp_path / "subs.json")
    assert reloaded.get(100).pending_digest_days == "1010100"


def test_pending_digest_days_toggle_updates_mask(tmp_path: Path):
    from satellite.messages_ru import pending_digest_day_callback_data

    ctx, store, _state = _ctx(tmp_path)
    store.update_settings(900, "alice", pending_digest_days="1111100")

    handle_callback_query(ctx, _callback(900, pending_digest_day_callback_data(5)))

    assert store.get(900).pending_digest_days == "1111110"


def test_pending_digest_days_toggle_blocks_last_day(tmp_path: Path):
    from satellite.messages_ru import (
        PENDING_DIGEST_LAST_DAY_TEXT,
        pending_digest_day_callback_data,
    )

    ctx, store, _state = _ctx(tmp_path)
    store.update_settings(900, "alice", pending_digest_days="1000000")

    handle_callback_query(ctx, _callback(900, pending_digest_day_callback_data(0)))

    assert store.get(900).pending_digest_days == "1000000"
    assert (
        ctx.telegram.answer_callback_query.call_args.kwargs["text"] == PENDING_DIGEST_LAST_DAY_TEXT
    )
    assert ctx.telegram.answer_callback_query.call_args.kwargs["show_alert"] is True


def test_pending_digest_days_keyboard_shows_weekday_toggles(tmp_path: Path):
    from satellite.messages_ru import CB_PENDING_DIGEST_DAYS

    ctx, store, _state = _ctx(tmp_path)
    store.update_settings(900, "alice", pending_digest_days="1000000")

    handle_callback_query(ctx, _callback(900, CB_PENDING_DIGEST_DAYS))

    keyboard = callback_edit_markup(ctx.telegram)
    rows = keyboard["inline_keyboard"]
    assert len(rows) == 9  # 7 дней + пресеты + назад
    assert rows[0][0]["text"] == "✅ Пн"
    assert rows[1][0]["text"] == "Вт"


def test_pending_digest_time_input_updates_field(tmp_path: Path):
    from satellite.messages_ru import CB_PENDING_DIGEST_TIME, PENDING_DIGEST_TIME_INVALID_TEXT
    from satellite.telegram_bot.handlers.digest_state import DIGEST_KIND_PENDING

    ctx, store, state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    handle_callback_query(ctx, _callback(900, CB_PENDING_DIGEST_TIME))
    assert state.get(900).digest_kind == DIGEST_KIND_PENDING

    handle_digest_time_input(
        ctx,
        IncomingMessage(
            update_id=50,
            chat_id=900,
            user_id=1,
            username="alice",
            display_name=None,
            text="bad",
        ),
    )
    assert state.is_waiting_for_time(900)
    assert final_message_html(ctx.telegram) == PENDING_DIGEST_TIME_INVALID_TEXT

    handle_digest_time_input(
        ctx,
        IncomingMessage(
            update_id=51,
            chat_id=900,
            user_id=1,
            username="alice",
            display_name=None,
            text="10 45",
        ),
    )
    assert store.get(900).pending_digest_time == "10:45"
    assert not state.is_waiting_for_time(900)


# --- старые кнопки подписки -----------------------------------------------


def test_legacy_subscribe_button_enables_digest_via_settings_model(tmp_path: Path):
    """🔔 Подписаться — должна включать digest_enabled и использовать текущие настройки."""
    from satellite.messages_ru import BUTTON_SUBSCRIBE

    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    store.update_settings(900, "alice", digest_days=DIGEST_DAYS_ALL, digest_time="10:15")

    msg = IncomingMessage(
        update_id=30,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_SUBSCRIBE,
    )
    handle_message(ctx, msg)

    settings = store.get(900)
    assert settings.digest_enabled is True
    # дни и время не сбросились
    assert settings.digest_days == DIGEST_DAYS_ALL
    assert settings.digest_time == "10:15"

    # подтверждение содержит реальное время пользователя и режим
    confirmation = final_message_html(ctx.telegram)
    assert "10:15" in confirmation
    assert "каждый день" in confirmation


def test_legacy_unsubscribe_button_disables_but_keeps_record(tmp_path: Path):
    from satellite.messages_ru import BUTTON_UNSUBSCRIBE

    ctx, store, _state = _ctx(tmp_path)
    store.subscribe(900, "alice")
    store.update_settings(900, "alice", digest_time="10:15")

    msg = IncomingMessage(
        update_id=31,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_UNSUBSCRIBE,
    )
    handle_message(ctx, msg)

    settings = store.get(900)
    assert settings.digest_enabled is False
    assert settings.digest_time == "10:15"


# --- /digest и /stopdigest как основной интерфейс подписки -----------------


def test_digest_command_enables_subscription_without_resetting_settings(
    tmp_path: Path,
):
    """`/digest` — основной способ включить подписку из меню Telegram."""
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")
    store.update_settings(900, "alice", digest_days=DIGEST_DAYS_ALL, digest_time="10:15")

    msg = IncomingMessage(
        update_id=40, chat_id=900, user_id=1, username="alice", display_name=None, text="/digest"
    )
    handle_message(ctx, msg)

    settings = store.get(900)
    assert settings.digest_enabled is True
    # /digest не сбрасывает индивидуальные дни/время
    assert settings.digest_days == DIGEST_DAYS_ALL
    assert settings.digest_time == "10:15"


def test_digest_command_does_not_open_settings_screen(tmp_path: Path):
    """`/digest` теперь подписывает, а не открывает экран настроек."""
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    msg = IncomingMessage(
        update_id=41, chat_id=900, user_id=1, username="alice", display_name=None, text="/digest"
    )
    handle_message(ctx, msg)

    # на /digest мы шлём подтверждение текстом, без inline-кнопок настроек
    call = ctx.telegram.send_message.call_args
    keyboard = call.kwargs.get("reply_markup")
    assert keyboard is None or "inline_keyboard" not in keyboard


def test_stopdigest_command_disables_but_keeps_days_and_time(tmp_path: Path):
    """`/stopdigest` отключает подписку и сохраняет настройки дней/времени."""
    ctx, store, _state = _ctx(tmp_path)
    store.subscribe(900, "alice")
    store.update_settings(900, "alice", digest_days=DIGEST_DAYS_ALL, digest_time="10:15")

    msg = IncomingMessage(
        update_id=42,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text="/stopdigest",
    )
    handle_message(ctx, msg)

    settings = store.get(900)
    assert settings.digest_enabled is False
    assert settings.digest_days == DIGEST_DAYS_ALL
    assert settings.digest_time == "10:15"


def test_settings_command_opens_inline_screen(tmp_path: Path):
    """`/settings` открывает общий экран настроек."""
    ctx, store, _state = _ctx(tmp_path)
    store.get_or_create(900, "alice")

    msg = IncomingMessage(
        update_id=43, chat_id=900, user_id=1, username="alice", display_name=None, text="/settings"
    )
    handle_message(ctx, msg)

    text = final_message_html(ctx.telegram)
    assert "Настройки Чайки" in text
    keyboard = final_reply_markup(ctx.telegram)
    assert keyboard is not None
    assert "inline_keyboard" in keyboard


# --- screen rendering ------------------------------------------------------


def test_digest_settings_screen_text_enabled():
    text = digest_settings_screen_text(
        digest_enabled=True,
        digest_days="weekdays",
        digest_time="09:00",
        weather_in_plan_enabled=True,
    )
    assert "🔔" in text and "включён" in text
    # Значение дней оборачивается в <b>…</b> для HTML-разметки в Telegram.
    assert "будни" in text
    assert "Дни:" in text
    assert "09:00 МСК" in text
    assert "Погода в дайджесте" in text
    assert "включена" in text


def test_digest_settings_screen_text_disabled():
    text = digest_settings_screen_text(
        digest_enabled=False,
        digest_days="all_days",
        digest_time="08:30",
        weather_in_plan_enabled=False,
    )
    assert "🔕" in text and "отключён" in text
    assert "все дни" in text
    assert "Дни:" in text
    assert "08:30 МСК" in text
    assert "Погода в дайджесте" in text
    assert "выключена" in text


def test_digest_days_keyboard_marks_active():
    kb = build_digest_days_keyboard(digest_days="weekdays")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert any("✅ Только будни" in lbl for lbl in labels)
    assert "Все дни" in labels

    kb = build_digest_days_keyboard(digest_days="all_days")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert any("✅ Все дни" in lbl for lbl in labels)


def test_digest_settings_keyboard_toggle_label():
    kb_on = build_digest_settings_keyboard(digest_enabled=True, weather_in_plan_enabled=True)
    labels_on = [btn["text"] for row in kb_on["inline_keyboard"] for btn in row]
    assert any("Отключить" in lbl for lbl in labels_on)
    assert any("Выключить погоду в плане" in lbl for lbl in labels_on)

    kb_off = build_digest_settings_keyboard(digest_enabled=False, weather_in_plan_enabled=False)
    labels_off = [btn["text"] for row in kb_off["inline_keyboard"] for btn in row]
    assert any("Включить" in lbl for lbl in labels_off)
    assert any("Включить погоду в плане" in lbl for lbl in labels_off)


def test_daily_digest_weather_toggle_updates_user_preference(tmp_path: Path):
    from satellite.users import USER_STATUS_APPROVED, UserStore

    ctx, store, _state = _ctx(tmp_path)
    users = UserStore(tmp_path / "users.json")
    users.upsert_from_telegram(
        telegram_user_id=1,
        chat_id=900,
        username="alice",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    ctx.users = users
    store.get_or_create(900, "alice")

    handle_callback_query(ctx, _callback(900, CB_DIGEST_WEATHER_TOGGLE))

    assert users.get(1) is not None
    assert users.get(1).weather_in_plan_enabled is False
    text = callback_edit_html(ctx.telegram)
    assert "Погода в дайджесте: <b>выключена</b>" in text
