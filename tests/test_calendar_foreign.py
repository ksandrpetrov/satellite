"""Тесты чужих (пошаренных) календарей."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.events import format_single_day_events_lines
from satellite.calendar.providers.base import CalendarListEntry, CalendarProviderError
from satellite.calendar.selection import calendar_callback_token, foreign_calendar_entries
from satellite.messages_ru import (
    BUTTON_DAY_AFTER,
    BUTTON_FOREIGN_CALENDARS,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    CB_FOREIGN_BACK,
    CB_FOREIGN_DAY_PREFIX,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    FOREIGN_CALENDARS_EMPTY_HTML,
    FOREIGN_CALENDARS_LOAD_FAIL_HTML,
    build_foreign_day_keyboard,
    button_text_is_foreign_calendars,
)
from satellite.telegram_bot.handlers.calendar_foreign import (
    clear_foreign_list_cache,
    handle_open_foreign_calendars,
    route_foreign_calendars_callback,
)
from satellite.telegram_bot.handlers.context import (
    HandlerContext,
    IncomingCallback,
    IncomingMessage,
)
from satellite.telegram_bot.handlers.routing import is_foreign_calendars_request
from satellite.testing.delivery_helpers import final_message_html
from satellite.users import CALENDAR_CONNECTED, USER_STATUS_APPROVED, UserStore

TZ = ZoneInfo("Europe/Moscow")


def test_foreign_calendar_entries_excludes_primary():
    calendars = [
        CalendarListEntry(name="Мой", url="https://cal/primary"),
        CalendarListEntry(name="Александра Качина", url="https://cal/shared"),
    ]
    foreign = foreign_calendar_entries(calendars, primary_calendar_url="https://cal/primary/")
    assert len(foreign) == 1
    assert foreign[0].name == "Александра Качина"


def test_button_and_command_routing():
    assert button_text_is_foreign_calendars(BUTTON_FOREIGN_CALENDARS)
    assert is_foreign_calendars_request(BUTTON_FOREIGN_CALENDARS)
    assert is_foreign_calendars_request("/foreign")
    assert not is_foreign_calendars_request("/today")


def test_foreign_day_keyboard_offers_today_tomorrow_and_day_after():
    """Под чужим календарём — три дня вперёд, как и в плане Чайки."""
    kb = build_foreign_day_keyboard(calendar_token="abc123456789")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert BUTTON_TODAY in labels
    assert BUTTON_TOMORROW in labels
    assert BUTTON_DAY_AFTER in labels
    # Возврат к списку календарей — отдельная строка
    assert any("списку" in lbl.lower() for lbl in labels)
    # day_offset кодируется в callback_data в формате "{prefix}{idx}:{offset}"
    offsets = set()
    for row in kb["inline_keyboard"]:
        for btn in row:
            data = btn.get("callback_data", "")
            if data.startswith(CB_FOREIGN_DAY_PREFIX):
                payload = data[len(CB_FOREIGN_DAY_PREFIX) :]
                _idx, _, offset = payload.partition(":")
                offsets.add(offset)
    assert offsets == {"0", "1", "2"}


def test_format_single_day_events_lines():
    ref = datetime.now(TZ).date()
    events = [
        {
            "summary": "Созвон",
            "dtstart": datetime(ref.year, ref.month, ref.day, 10, 0, tzinfo=TZ).isoformat(),
            "dtend": datetime(ref.year, ref.month, ref.day, 11, 0, tzinfo=TZ).isoformat(),
        },
    ]
    lines = format_single_day_events_lines(events, TZ, ref, ref)
    assert lines[0].startswith("<b>Сегодня")
    assert lines[1].startswith("1️⃣ ")
    assert "Созвон" in lines[1]


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "users.json")


def _connected_context(
    users: UserStore,
    *,
    user_id: int,
    list_calendars: object,
) -> MagicMock:
    users.upsert_from_telegram(
        telegram_user_id=user_id,
        chat_id=user_id,
        username=f"user{user_id}",
        display_name=f"User {user_id}",
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        user_id,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    users.mark_calendar_status(user_id, status=CALENDAR_CONNECTED)

    ctx = MagicMock(spec=HandlerContext)
    ctx.users = users
    ctx.tz = TZ
    ctx.calendar_service = MagicMock()
    if isinstance(list_calendars, Exception):
        ctx.calendar_service.list_calendars.side_effect = list_calendars
    else:
        ctx.calendar_service.list_calendars.return_value = list_calendars
    ctx.telegram = MagicMock()
    ctx.telegram.edit_message_text = MagicMock()
    ctx.telegram.answer_callback_query = MagicMock()
    ctx.digest_state = MagicMock()
    ctx.digest_state.claim_callback.return_value = True
    return ctx


def test_open_foreign_calendars_empty_state_is_safe(users: UserStore) -> None:
    user_id = 201
    ctx = _connected_context(
        users,
        user_id=user_id,
        list_calendars=[CalendarListEntry(name="Мой", url="https://cal/primary")],
    )

    handle_open_foreign_calendars(
        ctx,
        IncomingMessage(
            update_id=1,
            chat_id=user_id,
            user_id=user_id,
            username=f"user{user_id}",
            display_name=f"User {user_id}",
            text="/foreign",
        ),
    )

    assert final_message_html(ctx.telegram) == FOREIGN_CALENDARS_EMPTY_HTML


def test_open_foreign_calendars_provider_error_is_safe(users: UserStore) -> None:
    user_id = 202
    ctx = _connected_context(
        users,
        user_id=user_id,
        list_calendars=CalendarProviderError("timeout", error_code="CALENDAR_ERROR"),
    )

    handle_open_foreign_calendars(
        ctx,
        IncomingMessage(
            update_id=2,
            chat_id=user_id,
            user_id=user_id,
            username=f"user{user_id}",
            display_name=f"User {user_id}",
            text="/foreign",
        ),
    )

    assert final_message_html(ctx.telegram) == FOREIGN_CALENDARS_LOAD_FAIL_HTML


def test_foreign_back_provider_error_replaces_loading_state(users: UserStore) -> None:
    user_id = 203
    clear_foreign_list_cache(user_id)
    ctx = _connected_context(
        users,
        user_id=user_id,
        list_calendars=CalendarProviderError("timeout", error_code="CALENDAR_ERROR"),
    )
    cb = IncomingCallback(
        update_id=3,
        callback_query_id="cb-back-error",
        chat_id=user_id,
        message_id=5,
        user_id=user_id,
        username=f"user{user_id}",
        data=CB_FOREIGN_BACK,
    )

    assert route_foreign_calendars_callback(ctx, cb)

    assert ctx.telegram.edit_message_text.call_args_list[-1].args[2] == (
        FOREIGN_CALENDARS_LOAD_FAIL_HTML
    )


def test_foreign_day_provider_error_uses_safe_caldav_text(users: UserStore) -> None:
    user_id = 204
    clear_foreign_list_cache(user_id)
    shared_url = "https://cal/shared"
    ctx = _connected_context(
        users,
        user_id=user_id,
        list_calendars=[
            CalendarListEntry(name="Мой", url="https://cal/primary"),
            CalendarListEntry(name="Команда", url=shared_url),
        ],
    )
    ctx.calendar_service.list_events.side_effect = CalendarProviderError(
        "timeout",
        error_code="CALENDAR_ERROR",
    )
    cb = IncomingCallback(
        update_id=4,
        callback_query_id="cb-day-error",
        chat_id=user_id,
        message_id=5,
        user_id=user_id,
        username=f"user{user_id}",
        data=f"{CB_FOREIGN_DAY_PREFIX}{calendar_callback_token(shared_url)}:0",
    )

    assert route_foreign_calendars_callback(ctx, cb)

    assert ctx.telegram.edit_message_text.call_args_list[-1].args[2] == (
        ERR_CALDAV_UNAVAILABLE_TEXT
    )


def test_foreign_calendars_callback_flow(users: UserStore) -> None:
    from satellite.telegram_bot.handlers import (
        HandlerContext,
        IncomingCallback,
        handle_callback_query,
    )

    user_id = 100
    users.upsert_from_telegram(
        telegram_user_id=user_id,
        chat_id=user_id,
        username="petrov",
        display_name="Александр Петров",
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        user_id,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    users.mark_calendar_status(user_id, status=CALENDAR_CONNECTED)

    ctx = MagicMock(spec=HandlerContext)
    ctx.users = users
    ctx.tz = TZ
    ctx.calendar_service = MagicMock()
    ctx.calendar_service.list_calendars.return_value = [
        CalendarListEntry(name="Мой", url="https://cal/primary"),
        CalendarListEntry(name="Александра Качина", url="https://cal/shared"),
    ]
    today = datetime.now(TZ).date()
    ctx.calendar_service.list_events.return_value = [
        {
            "summary": "Встреча",
            "dtstart": datetime(today.year, today.month, today.day, 14, 0, tzinfo=TZ).isoformat(),
            "dtend": datetime(today.year, today.month, today.day, 15, 0, tzinfo=TZ).isoformat(),
        },
    ]
    ctx.telegram = MagicMock()
    ctx.telegram.edit_message_text = MagicMock()
    ctx.telegram.answer_callback_query = MagicMock()
    ctx.digest_state = MagicMock()
    ctx.digest_state.claim_callback.return_value = True

    cb = IncomingCallback(
        update_id=1,
        callback_query_id="cb1",
        chat_id=user_id,
        message_id=5,
        user_id=user_id,
        username="petrov",
        data=f"{CB_FOREIGN_DAY_PREFIX}{calendar_callback_token('https://cal/shared')}:0",
    )

    handle_callback_query(ctx, cb)

    ctx.calendar_service.list_events.assert_called_once()
    call_kw = ctx.calendar_service.list_events.call_args.kwargs
    assert call_kw["calendar_urls"] == ("https://cal/shared",)
    edit_text = ctx.telegram.edit_message_text.call_args_list[-1][0][2]
    assert "Александра Качина" in edit_text
    assert "Встреча" in edit_text


def test_foreign_day_acks_before_caldav(users: UserStore) -> None:
    from satellite.telegram_bot.handlers import (
        HandlerContext,
        IncomingCallback,
        handle_callback_query,
    )

    user_id = 101
    users.upsert_from_telegram(
        telegram_user_id=user_id,
        chat_id=user_id,
        username="petrov",
        display_name="Александр Петров",
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        user_id,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    users.mark_calendar_status(user_id, status=CALENDAR_CONNECTED)

    ctx = MagicMock(spec=HandlerContext)
    ctx.users = users
    ctx.tz = TZ
    ctx.calendar_service = MagicMock()
    ctx.calendar_service.list_calendars.return_value = [
        CalendarListEntry(name="Мой", url="https://cal/primary"),
        CalendarListEntry(name="Александра Качина", url="https://cal/shared"),
    ]
    ctx.telegram = MagicMock()
    ctx.telegram.edit_message_text = MagicMock()
    ctx.telegram.answer_callback_query = MagicMock()
    ctx.digest_state = MagicMock()
    ctx.digest_state.claim_callback.return_value = True

    manager = MagicMock()
    manager.attach_mock(ctx.telegram.answer_callback_query, "ack")
    manager.attach_mock(ctx.calendar_service.list_calendars, "list")

    handle_callback_query(
        ctx,
        IncomingCallback(
            update_id=3,
            callback_query_id="cb3",
            chat_id=user_id,
            message_id=5,
            user_id=user_id,
            username="petrov",
            data=f"{CB_FOREIGN_DAY_PREFIX}{calendar_callback_token('https://cal/shared')}:0",
        ),
    )

    call_names = [call[0] for call in manager.mock_calls]
    assert call_names.index("ack") < call_names.index("list")


def test_foreign_back_acks_before_caldav(users: UserStore) -> None:
    from satellite.messages_ru import CB_FOREIGN_BACK
    from satellite.telegram_bot.handlers import (
        HandlerContext,
        IncomingCallback,
        handle_callback_query,
    )

    user_id = 100
    users.upsert_from_telegram(
        telegram_user_id=user_id,
        chat_id=user_id,
        username="petrov",
        display_name="Александр Петров",
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        user_id,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    users.mark_calendar_status(user_id, status=CALENDAR_CONNECTED)

    ctx = MagicMock(spec=HandlerContext)
    ctx.users = users
    ctx.tz = TZ
    ctx.calendar_service = MagicMock()
    ctx.calendar_service.list_calendars.return_value = [
        CalendarListEntry(name="Мой", url="https://cal/primary"),
        CalendarListEntry(name="Александра Качина", url="https://cal/shared"),
    ]
    ctx.telegram = MagicMock()
    ctx.telegram.edit_message_text = MagicMock()
    ctx.telegram.answer_callback_query = MagicMock()
    ctx.digest_state = MagicMock()
    ctx.digest_state.claim_callback.return_value = True

    manager = MagicMock()
    manager.attach_mock(ctx.telegram.answer_callback_query, "ack")
    manager.attach_mock(ctx.calendar_service.list_calendars, "list")

    handle_callback_query(
        ctx,
        IncomingCallback(
            update_id=2,
            callback_query_id="cb2",
            chat_id=user_id,
            message_id=5,
            user_id=user_id,
            username="petrov",
            data=CB_FOREIGN_BACK,
        ),
    )

    call_names = [call[0] for call in manager.mock_calls]
    assert call_names.index("ack") < call_names.index("list")
