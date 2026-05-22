import logging
from datetime import date
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.providers.base import CalendarProviderError
from satellite.digest_utils import resolve_target_date
from satellite.messages_ru import (
    ACCESS_REQUEST_SENT_HTML,
    BOT_HELP_HTML,
    BUTTON_DAY_AFTER,
    BUTTON_SUBSCRIBE,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    BUTTON_UNSUBSCRIBE,
    BUTTON_UNSUBSCRIBE_LEGACY,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    ERR_DIGEST_BUILD_FAILED_TEXT,
    ERR_GENERIC_HANDLER_TEXT,
    PLAN_FETCH_STATUS_TEXT,
    REPLY_KEYBOARD_REMOVE,
)
from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.handlers import (
    HandlerContext,
    IncomingMessage,
    extract_message,
    handle_message,
    is_help_command,
    is_start_command,
    is_start_or_help_command,
    parse_command_mode,
    parse_subscription_action,
    recognize_message,
)
from satellite.telegram_bot.handlers.calendar_state import (
    STATE_CREATE_TITLE,
    CalendarFlowState,
)
from satellite.telegram_bot.handlers.routing import (
    CalendarSourcesCommand,
    CheckCommand,
    ConnectCommand,
    CreateCommand,
    DisconnectCommand,
    ForeignCalendarsCommand,
    InvitationsCommand,
    PendingCommand,
    PlanCommand,
    SettingsCommand,
    StartOrHelpCommand,
    SubscriptionCommand,
    UpcomingCommand,
)
from satellite.users import USER_STATUS_APPROVED, USER_STATUS_PENDING


def _access_ctx(*, approved: bool = True, has_calendar: bool = True) -> MagicMock:
    record = MagicMock()
    record.status = USER_STATUS_APPROVED if approved else USER_STATUS_PENDING
    record.has_calendar = has_calendar
    ctx = MagicMock(spec=HandlerContext)
    ctx.users = MagicMock()
    ctx.users.get = MagicMock(return_value=record if approved else record)
    ctx.users.upsert_from_telegram = MagicMock(return_value=record)
    ctx.users.submit_access_request = MagicMock(return_value=(record, True))
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.admin.telegram_ids = ()
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = "https://example.com/connect"
    from satellite.web.connect_token import ConnectTokenStore

    ctx.connect_tokens = ConnectTokenStore()
    ctx.digest_state = MagicMock()
    ctx.digest_state.is_waiting_for_time = MagicMock(return_value=False)
    ctx.digest_state.clear = MagicMock()
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.calendar_state.clear = MagicMock()
    ctx.telegram = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={})
    ctx.subscriptions = MagicMock()
    ctx.subscriptions.is_subscribed = MagicMock(return_value=False)
    return ctx


def _enable_draft_telegram(telegram: MagicMock) -> None:
    """Эмулирует Bot API с ``sendMessageDraft`` (основной путь доставки)."""
    telegram.send_message_draft = MagicMock(return_value=True)
    telegram.send_chat_action = MagicMock(return_value=True)
    telegram.set_message_reaction = MagicMock(return_value=True)


def _plan_handler_context() -> MagicMock:
    ctx = _access_ctx(approved=True, has_calendar=True)
    ctx.tz = ZoneInfo("UTC")
    ctx.plan_config = MagicMock()
    ctx.weather_config = MagicMock()
    ctx.weather_config.enabled = False
    ctx.weather_client = None
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 501})
    ctx.telegram.edit_message_text = MagicMock(return_value={})
    _enable_draft_telegram(ctx.telegram)
    pb = MagicMock()
    pb.build_text = MagicMock(return_value="<b>Plan HTML</b>")
    ctx.plan_builder = MagicMock(return_value=pb)
    return ctx


def test_parse_command_mode_buttons():
    assert parse_command_mode(BUTTON_TODAY) == "today"
    assert parse_command_mode(BUTTON_TOMORROW) == "tomorrow"
    assert parse_command_mode(BUTTON_DAY_AFTER) == "day_after_tomorrow"


def test_parse_command_mode_buttons_with_variation_selectors():
    # Telegram иногда добавляет/убирает невидимые U+FE0F селекторы вариаций
    tampered = BUTTON_TODAY.replace("📅", "📅\ufe0f")
    assert parse_command_mode(tampered) == "today"


def test_parse_command_mode_text_commands():
    assert parse_command_mode("td") == "today"
    assert parse_command_mode("/td") == "today"
    assert parse_command_mode("/td@MyBot") == "today"
    assert parse_command_mode("tm something") == "tomorrow"
    assert parse_command_mode("/dat") == "day_after_tomorrow"
    assert parse_command_mode("DAT") == "day_after_tomorrow"


def test_parse_command_mode_long_aliases_from_command_menu():
    """Длинные алиасы из меню Telegram — рядом с короткими td/tm/dat."""
    assert parse_command_mode("/today") == "today"
    assert parse_command_mode("/today@MyBot") == "today"
    assert parse_command_mode("/TOMORROW") == "tomorrow"
    assert parse_command_mode("/aftertomorrow") == "day_after_tomorrow"
    assert parse_command_mode("/after_tomorrow") == "day_after_tomorrow"
    assert parse_command_mode("/aftertomorrow@MyBot") == "day_after_tomorrow"
    assert parse_command_mode("/after_tomorrow@MyBot") == "day_after_tomorrow"


@pytest.mark.parametrize(
    "text,expected_type",
    [
        ("/start", StartOrHelpCommand),
        ("/help", StartOrHelpCommand),
        (BUTTON_TODAY, PlanCommand),
        (BUTTON_SUBSCRIBE, SubscriptionCommand),
        ("/settings", SettingsCommand),
        ("/upcoming", UpcomingCommand),
        ("/invitations", InvitationsCommand),
        ("/create", CreateCommand),
        ("/connect", ConnectCommand),
        ("/pending", PendingCommand),
    ],
)
def test_recognize_message_covers_dispatch_commands(text, expected_type):
    cmd = recognize_message(text)
    assert cmd is not None
    assert isinstance(cmd, expected_type)


def test_recognize_message_foreign_and_calendar_sources():
    from satellite.messages_ru import (
        BUTTON_CALENDAR_SOURCES,
        BUTTON_CHECK_CALENDAR,
        BUTTON_DISCONNECT_CALENDAR,
        BUTTON_FOREIGN_CALENDARS,
    )

    assert isinstance(recognize_message(BUTTON_FOREIGN_CALENDARS), ForeignCalendarsCommand)
    assert isinstance(recognize_message(BUTTON_CALENDAR_SOURCES), CalendarSourcesCommand)
    assert isinstance(recognize_message(BUTTON_CHECK_CALENDAR), CheckCommand)
    assert isinstance(recognize_message(BUTTON_DISCONNECT_CALENDAR), DisconnectCommand)


def test_connect_command_sends_intro_with_webapp_keyboard():
    """`/connect` отправляет интро + Web App-кнопку, не падает на reply_markup."""
    from satellite.messages_ru import (
        BUTTON_CONNECT_CALENDAR,
        BUTTON_RECONNECT_CALENDAR,
        CALENDAR_NOT_CONNECTED_HTML,
        CALENDAR_RECONNECT_INTRO_HTML,
    )

    ctx = _access_ctx(approved=True, has_calendar=False)
    msg = IncomingMessage(
        update_id=401,
        chat_id=7777,
        user_id=7777,
        username="alice",
        display_name=None,
        text="/connect",
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message.assert_called_once()
    call = ctx.telegram.send_message.call_args
    assert call[0][0] == 7777
    assert call[0][1] == CALENDAR_NOT_CONNECTED_HTML
    markup = call.kwargs.get("reply_markup")
    assert isinstance(markup, dict)
    assert markup["inline_keyboard"][0][0]["text"] == BUTTON_CONNECT_CALENDAR
    assert "web_app" in markup["inline_keyboard"][0][0]
    webapp_url = markup["inline_keyboard"][0][0]["web_app"]["url"]
    path_part = webapp_url.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    assert ctx.connect_tokens.resolve(path_part) == 7777

    ctx2 = _access_ctx(approved=True, has_calendar=True)
    handle_message(
        ctx2,
        IncomingMessage(
            update_id=402,
            chat_id=7778,
            user_id=7778,
            username="alice",
            display_name=None,
            text="/connect",
        ),
    )
    call2 = ctx2.telegram.send_message.call_args
    assert call2[0][1] == CALENDAR_RECONNECT_INTRO_HTML
    markup2 = call2.kwargs.get("reply_markup")
    assert isinstance(markup2, dict)
    assert markup2["inline_keyboard"][0][0]["text"] == BUTTON_RECONNECT_CALENDAR


def test_settings_command_clears_create_fsm_and_opens_hub():
    from satellite.messages_ru import BUTTON_SETTINGS

    ctx = _access_ctx(approved=True, has_calendar=True)
    ctx.calendar_state.get = MagicMock(return_value=CalendarFlowState(state=STATE_CREATE_TITLE))
    msg = IncomingMessage(
        update_id=301,
        chat_id=9001,
        user_id=9001,
        username="alice",
        display_name=None,
        text=BUTTON_SETTINGS,
    )
    handle_message(ctx, msg)
    ctx.calendar_state.clear.assert_called_once_with(9001)
    ctx.digest_state.clear.assert_any_call(9001)
    sent = [c.args[1] for c in ctx.telegram.send_message.call_args_list]
    assert any("Настройки Чайки" in t for t in sent)


def test_parse_command_mode_returns_none_for_garbage():
    assert parse_command_mode("") is None
    assert parse_command_mode(None) is None
    assert parse_command_mode("hello there") is None
    # длинная команда без слэша не считается командой, чтобы случайный текст
    # «today» в чате не отстреливал план
    assert parse_command_mode("today") is None


def test_is_start_or_help_command():
    assert is_start_or_help_command("/start")
    assert is_start_or_help_command("/start@MyBot")
    assert is_start_or_help_command("/help extra args")
    assert is_start_or_help_command("/HELP")
    assert not is_start_or_help_command("td")
    assert not is_start_or_help_command(None)


def test_is_start_and_help_command_split():
    assert is_start_command("/start")
    assert not is_start_command("/help")
    assert is_help_command("/help")
    assert not is_help_command("/start")
    assert not is_start_command(None)
    assert not is_help_command(None)


def test_help_sends_help_text_even_when_user_is_new():
    """`/help` доходит до текста справки без одобренного доступа."""
    ctx = _access_ctx(approved=False)
    pending = MagicMock()
    pending.status = USER_STATUS_PENDING
    ctx.users.upsert_from_telegram = MagicMock(return_value=pending)

    msg = IncomingMessage(
        update_id=99,
        chat_id=5001,
        user_id=5001,
        username="not_in_map",
        display_name=None,
        text="/help",
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message.assert_called_once()
    call_kw = ctx.telegram.send_message.call_args
    assert call_kw[0][0] == 5001
    assert call_kw[0][1] == BOT_HELP_HTML
    assert call_kw.kwargs.get("reply_markup") == REPLY_KEYBOARD_REMOVE


def test_start_sends_access_request_for_pending_user():
    """`/start` создаёт заявку на доступ для нового пользователя."""
    ctx = _access_ctx(approved=False)
    pending = MagicMock()
    pending.status = USER_STATUS_PENDING
    ctx.users.upsert_from_telegram = MagicMock(return_value=pending)

    msg = IncomingMessage(
        update_id=98,
        chat_id=5002,
        user_id=5002,
        username="not_in_map",
        display_name=None,
        text="/start",
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message.assert_called_once()
    call_kw = ctx.telegram.send_message.call_args
    assert call_kw[0][1] == ACCESS_REQUEST_SENT_HTML


def test_target_date_for_mode():
    today = date(2026, 5, 11)
    assert resolve_target_date("today", today) == date(2026, 5, 11)
    assert resolve_target_date("tomorrow", today) == date(2026, 5, 12)
    assert resolve_target_date("day_after_tomorrow", today) == date(2026, 5, 13)


def test_extract_message_handles_missing_fields():
    msg = extract_message({"update_id": 42})
    assert msg.update_id == 42
    assert msg.chat_id is None
    assert msg.username is None
    assert msg.user_id is None
    assert msg.text == ""


def test_extract_message_lowercases_username():
    msg = extract_message(
        {
            "update_id": 7,
            "message": {
                "from": {"username": "AleksanderPetrov", "id": 1},
                "chat": {"id": 1001},
                "text": "td",
            },
        }
    )
    assert msg.username == "aleksanderpetrov"
    assert msg.user_id == 1
    assert msg.chat_id == 1001
    assert msg.text == "td"


def test_parse_subscription_action_buttons():
    assert parse_subscription_action(BUTTON_SUBSCRIBE) == "subscribe"
    assert parse_subscription_action(BUTTON_UNSUBSCRIBE) == "unsubscribe"
    assert parse_subscription_action(BUTTON_UNSUBSCRIBE_LEGACY) == "unsubscribe"


def test_parse_subscription_action_buttons_with_variation_selectors():
    tampered = BUTTON_SUBSCRIBE.replace("🔔", "🔔\ufe0f")
    assert parse_subscription_action(tampered) == "subscribe"


def test_parse_subscription_action_text_commands():
    assert parse_subscription_action("/sub") == "subscribe"
    assert parse_subscription_action("/subscribe") == "subscribe"
    assert parse_subscription_action("/subscribe@MyBot") == "subscribe"
    assert parse_subscription_action("/unsub") == "unsubscribe"
    assert parse_subscription_action("/UNSUBSCRIBE") == "unsubscribe"


def test_parse_subscription_action_digest_and_stopdigest():
    """/digest и /stopdigest — основные команды меню для (раз)подписки."""
    assert parse_subscription_action("/digest") == "subscribe"
    assert parse_subscription_action("/DIGEST@MyBot") == "subscribe"
    assert parse_subscription_action("/stopdigest") == "unsubscribe"
    assert parse_subscription_action("/stopdigest@MyBot") == "unsubscribe"


def test_parse_subscription_action_no_match():
    assert parse_subscription_action("") is None
    assert parse_subscription_action(None) is None
    assert parse_subscription_action("td") is None
    assert parse_subscription_action(BUTTON_TODAY) is None
    assert parse_subscription_action("/subway") is None
    # /settings не должен оборачиваться в subscribe — он только открывает экран
    assert parse_subscription_action("/settings") is None


def test_plan_uses_send_message_draft_when_supported():
    """При поддержке API — черновик + финальный sendMessage, без edit."""
    ctx = _plan_handler_context()
    ctx.telegram.send_message_draft = MagicMock(return_value=True)
    msg = IncomingMessage(
        update_id=2, chat_id=9001, user_id=1, username="alice", display_name=None, text="/td"
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message_draft.assert_called()
    ctx.telegram.send_message.assert_called_once()
    assert ctx.telegram.send_message.call_args[0][1] == "<b>Plan HTML</b>"
    ctx.telegram.edit_message_text.assert_not_called()


def test_plan_dedup_blocks_second_call_within_cooldown():
    """Двойной /td в один чат шлёт план один раз: cooldown отбивает повтор.

    Реальный кейс: пользователь нажал кнопку «Сегодня» два раза подряд (или
    Telegram переотдал тот же текст другим update_id из-за гонки между
    инстансами). Без guard'а оба вызова доходили до ``stream.finish`` и
    в чате появлялось два одинаковых плана.
    """
    ctx = _plan_handler_context()
    msg1 = IncomingMessage(
        update_id=2, chat_id=9001, user_id=1, username="alice", display_name=None, text="/td"
    )
    msg2 = IncomingMessage(
        update_id=3, chat_id=9001, user_id=1, username="alice", display_name=None, text="/td"
    )
    handle_message(ctx, msg1)
    handle_message(ctx, msg2)

    final_sends = [
        call
        for call in ctx.telegram.send_message.call_args_list
        if call[0][1] == "<b>Plan HTML</b>"
    ]
    assert len(final_sends) == 1
    ctx.plan_builder.return_value.build_text.assert_called_once()
    from satellite.messages_ru import PLAN_BUSY_TEXT

    busy = [c for c in ctx.telegram.send_message.call_args_list if c[0][1] == PLAN_BUSY_TEXT]
    assert len(busy) == 1


def test_plan_legacy_loading_then_edit_when_draft_unavailable():
    """Без ``sendMessageDraft`` — прежний паттерн loading → edit."""
    ctx = _plan_handler_context()
    ctx.telegram.send_message_draft = MagicMock(return_value=False)
    msg = IncomingMessage(
        update_id=2, chat_id=9001, user_id=1, username="alice", display_name=None, text="/td"
    )
    handle_message(ctx, msg)

    assert ctx.telegram.send_message.call_count == 1
    assert ctx.telegram.send_message.call_args[0][1] == "⏳"
    assert ctx.telegram.edit_message_text.call_count >= 1
    assert ctx.telegram.edit_message_text.call_args[0][2] == "<b>Plan HTML</b>"
    ctx.plan_builder.return_value.build_text.assert_called_once()


def test_plan_legacy_falls_back_to_new_message_when_edit_fails():
    """Legacy (без draft): если edit не удался — дайджест новым сообщением."""

    ctx = _plan_handler_context()
    ctx.telegram.send_message_draft = MagicMock(return_value=False)
    ctx.telegram.edit_message_text = MagicMock(side_effect=TelegramError("message is not modified"))
    msg = IncomingMessage(
        update_id=10, chat_id=9100, user_id=1, username="alice", display_name=None, text="/td"
    )

    handle_message(ctx, msg)

    assert ctx.telegram.edit_message_text.call_count >= 1
    assert ctx.telegram.send_message.call_count == 2
    final_call = ctx.telegram.send_message.call_args_list[-1]
    assert final_call[0][1] == "<b>Plan HTML</b>"
    assert final_call.kwargs.get("reply_markup") is None


def test_plan_replaces_loading_with_caldav_error_text(
    caplog: pytest.LogCaptureFixture,
):
    """CalDAV-ошибка не должна оставлять loading-сообщение или показывать стек."""
    ctx = _plan_handler_context()
    ctx.plan_builder.return_value.build_text = MagicMock(
        side_effect=CalendarProviderError("boom", error_code="caldav_failed")
    )
    msg = IncomingMessage(
        update_id=4, chat_id=9003, user_id=1, username="alice", display_name=None, text="/td"
    )

    with caplog.at_level(logging.ERROR, logger="satellite.telegram_bot.handlers"):
        handle_message(ctx, msg)

    ctx.telegram.send_message.assert_called_once()
    assert ctx.telegram.send_message.call_args[0][1] == ERR_CALDAV_UNAVAILABLE_TEXT
    ctx.telegram.edit_message_text.assert_not_called()
    assert "boom" not in (ctx.telegram.send_message.call_args[0][1] or "")
    assert any("boom" in record.getMessage() for record in caplog.records)


def test_plan_replaces_loading_with_generic_error_on_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
):
    """Любая нештатная ошибка построения дайджеста заменяется ласковым текстом."""
    ctx = _plan_handler_context()
    ctx.plan_builder.return_value.build_text = MagicMock(
        side_effect=RuntimeError("token expired: secret123")
    )
    msg = IncomingMessage(
        update_id=5, chat_id=9004, user_id=1, username="alice", display_name=None, text="/td"
    )

    with caplog.at_level(logging.ERROR, logger="satellite.telegram_bot.handlers"):
        handle_message(ctx, msg)

    ctx.telegram.send_message.assert_called_once()
    assert ctx.telegram.send_message.call_args[0][1] == ERR_DIGEST_BUILD_FAILED_TEXT
    ctx.telegram.edit_message_text.assert_not_called()
    assert "token expired" not in (ctx.telegram.send_message.call_args[0][1] or "")
    # Стек должен попасть в лог (exc_info), но не в пользовательский текст.
    assert any(record.exc_info is not None for record in caplog.records)


def test_plan_button_uses_error_text_when_build_fails():
    """Для кнопок поведение симметричное: loading заменяется ошибкой, спама нет."""
    ctx = _plan_handler_context()
    ctx.plan_builder.return_value.build_text = MagicMock(side_effect=RuntimeError("kaboom"))
    msg = IncomingMessage(
        update_id=6,
        chat_id=9005,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_TOMORROW,
    )

    handle_message(ctx, msg)

    ctx.telegram.send_message.assert_called_once()
    assert ctx.telegram.send_message.call_args[0][1] == ERR_DIGEST_BUILD_FAILED_TEXT
    ctx.telegram.edit_message_text.assert_not_called()


def test_plan_legacy_skips_edit_when_loading_send_failed():
    """Legacy: если loading не ушёл — дайджест только ``sendMessage``."""

    ctx = _plan_handler_context()
    ctx.telegram.send_message_draft = MagicMock(return_value=False)
    final_send_response = {"message_id": 777}

    def _send_message_side_effect(chat_id, text, **_kwargs):
        if text == "⏳":
            raise TelegramError("loading send failed")
        return final_send_response

    ctx.telegram.send_message = MagicMock(side_effect=_send_message_side_effect)
    msg = IncomingMessage(
        update_id=7, chat_id=9006, user_id=1, username="alice", display_name=None, text="/td"
    )

    handle_message(ctx, msg)

    assert ctx.telegram.send_message.call_args[0][1] == "<b>Plan HTML</b>"
    ctx.telegram.edit_message_text.assert_not_called()


# --- меню команд Telegram: /today /tomorrow /aftertomorrow ------------------


@pytest.mark.parametrize(
    "command, mode_text",
    [
        ("/today", PLAN_FETCH_STATUS_TEXT["today"]),
        ("/tomorrow", PLAN_FETCH_STATUS_TEXT["tomorrow"]),
        ("/aftertomorrow", PLAN_FETCH_STATUS_TEXT["day_after_tomorrow"]),
    ],
)
def test_long_menu_commands_invoke_correct_day_offset(command, mode_text):
    ctx = _plan_handler_context()
    msg = IncomingMessage(
        update_id=100, chat_id=8010, user_id=1, username="alice", display_name=None, text=command
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message_draft.assert_called()
    ctx.telegram.send_message.assert_called_once()
    ctx.telegram.edit_message_text.assert_not_called()


@pytest.mark.parametrize(
    "command, mode_text",
    [
        ("td", PLAN_FETCH_STATUS_TEXT["today"]),
        ("tm", PLAN_FETCH_STATUS_TEXT["tomorrow"]),
        ("dat", PLAN_FETCH_STATUS_TEXT["day_after_tomorrow"]),
    ],
)
def test_short_aliases_still_work_after_migration(command, mode_text):
    """td/tm/dat должны продолжить работать даже без слэша."""
    ctx = _plan_handler_context()
    msg = IncomingMessage(
        update_id=110, chat_id=8011, user_id=1, username="alice", display_name=None, text=command
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message_draft.assert_called()
    ctx.telegram.send_message.assert_called_once()
    ctx.telegram.edit_message_text.assert_not_called()


def test_unknown_text_does_not_send_old_reply_keyboard():
    """Неизвестный текст не должен возвращать старую нижнюю Reply-клавиатуру."""
    ctx = _plan_handler_context()
    msg = IncomingMessage(
        update_id=120, chat_id=8012, user_id=1, username="alice", display_name=None, text="привет!"
    )
    handle_message(ctx, msg)

    assert ctx.telegram.send_message.call_count == 1
    call = ctx.telegram.send_message.call_args
    # сообщение-подсказка отправляется без reply_markup (None — значит
    # клиент сохранит то, что было; новых ReplyKeyboardMarkup мы не шлём)
    sent_markup = call.kwargs.get("reply_markup")
    assert sent_markup is None or sent_markup == REPLY_KEYBOARD_REMOVE
    # и точно НЕ кастомная клавиатура (`keyboard` поле)
    if isinstance(sent_markup, dict):
        assert "keyboard" not in sent_markup


# --- generic safe error для непредвиденных сбоев в диспетчере --------------


def test_unexpected_error_in_subscription_sends_generic_notice(
    caplog: pytest.LogCaptureFixture,
):
    """Любой `Exception` из сценария → пользователь видит безопасный текст."""
    ctx = _plan_handler_context()
    ctx.subscriptions.get_or_create = MagicMock(
        side_effect=RuntimeError("db is on fire: token=secret123")
    )
    msg = IncomingMessage(
        update_id=200, chat_id=8200, user_id=1, username="alice", display_name=None, text="/digest"
    )

    with caplog.at_level(logging.ERROR, logger="satellite.telegram_bot.handlers"):
        handle_message(ctx, msg)

    # Последнее отправленное сообщение — нейтральный текст без техдеталей.
    sent_texts = [c.args[1] for c in ctx.telegram.send_message.call_args_list]
    assert ERR_GENERIC_HANDLER_TEXT in sent_texts
    assert all("secret123" not in (t or "") for t in sent_texts)
    # Стек обязан попасть в лог.
    assert any(record.exc_info is not None for record in caplog.records)


def test_unexpected_error_in_welcome_sends_generic_notice():
    """`/start` тоже должен не молчать, если что-то сломалось внутри."""
    ctx = _access_ctx(approved=False)
    ctx.users.upsert_from_telegram = MagicMock(side_effect=RuntimeError("boom"))
    ctx.telegram.send_message = MagicMock(return_value={})

    msg = IncomingMessage(
        update_id=201,
        chat_id=8201,
        user_id=8201,
        username="anyone",
        display_name=None,
        text="/start",
    )
    handle_message(ctx, msg)

    assert ctx.telegram.send_message.call_count == 1
    assert ctx.telegram.send_message.call_args.args[1] == ERR_GENERIC_HANDLER_TEXT
