"""Полный FSM `/create`: title → date → time → duration → confirm/cancel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.providers.base import CalendarProviderError
from satellite.messages_ru import (
    CB_CREATE_CANCEL,
    CB_CREATE_CONFIRM,
    CB_CREATE_DATE_TODAY,
    CB_CREATE_DURATION_PREFIX,
    CREATE_EVENT_ASK_TIME,
    CREATE_EVENT_ASK_TITLE,
    CREATE_EVENT_CANCELLED_HTML,
    CREATE_EVENT_FAILED_HTML,
    CREATE_EVENT_INVALID_DATE,
    CREATE_EVENT_INVALID_DURATION,
    CREATE_EVENT_INVALID_TIME,
    ERR_CALDAV_UNAVAILABLE_TEXT,
)
from satellite.telegram_bot.handlers import handle_callback_query, handle_message
from satellite.telegram_bot.handlers.calendar_state import (
    STATE_CREATE_CONFIRM,
    STATE_CREATE_DATE,
    STATE_CREATE_DURATION,
    STATE_CREATE_TIME,
    STATE_CREATE_TITLE,
    CalendarFlowState,
    CreateEventDraft,
)
from satellite.testing.delivery_helpers import (
    callback_edit_html,
    final_message_html,
    sent_messages_text,
)
from satellite.users import UserStore

from .conftest import freeze_now, make_callback, make_ctx, make_msg, make_user_store

USER_ID = 8201
CHAT_ID = 8201
TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    return make_user_store(tmp_path, approved_with_calendar=[USER_ID])


def _create_ctx(users: UserStore) -> MagicMock:
    ctx = make_ctx(users)
    ctx.tz = TZ
    ctx.calendar_service.create_event = MagicMock()
    return ctx


def _start_create(ctx: MagicMock) -> None:
    handle_message(ctx, make_msg(text="/create", chat_id=CHAT_ID, user_id=USER_ID, update_id=1))


def test_create_fsm_full_text_path(store: UserStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_create", now=fixed_now)

    ctx = _create_ctx(store)
    _start_create(ctx)
    assert CREATE_EVENT_ASK_TITLE in final_message_html(ctx.telegram)

    from satellite.telegram_bot.handlers.calendar_create import handle_create_text_input

    handle_create_text_input(
        ctx, make_msg(text="  ", chat_id=CHAT_ID, user_id=USER_ID, update_id=2)
    )
    assert final_message_html(ctx.telegram) == CREATE_EVENT_ASK_TITLE

    handle_message(ctx, make_msg(text="Standup", chat_id=CHAT_ID, user_id=USER_ID, update_id=3))
    handle_message(ctx, make_msg(text="25.05.2026", chat_id=CHAT_ID, user_id=USER_ID, update_id=4))
    handle_message(ctx, make_msg(text="09:30", chat_id=CHAT_ID, user_id=USER_ID, update_id=5))
    handle_message(ctx, make_msg(text="60", chat_id=CHAT_ID, user_id=USER_ID, update_id=6))

    flow = ctx.calendar_state.get(CHAT_ID)
    assert flow is not None
    assert flow.state == STATE_CREATE_CONFIRM
    assert flow.draft.title == "Standup"
    assert flow.draft.event_date.year == 2026


def test_create_invalid_date_time_duration(
    store: UserStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_create", now=fixed_now)

    ctx = _create_ctx(store)
    _start_create(ctx)
    handle_message(ctx, make_msg(text="Meet", chat_id=CHAT_ID, user_id=USER_ID, update_id=10))
    handle_message(ctx, make_msg(text="вчера", chat_id=CHAT_ID, user_id=USER_ID, update_id=11))
    assert CREATE_EVENT_INVALID_DATE in final_message_html(ctx.telegram)

    handle_message(ctx, make_msg(text="сегодня", chat_id=CHAT_ID, user_id=USER_ID, update_id=12))
    handle_message(ctx, make_msg(text="утром", chat_id=CHAT_ID, user_id=USER_ID, update_id=13))
    assert CREATE_EVENT_INVALID_TIME in final_message_html(ctx.telegram)

    handle_message(ctx, make_msg(text="10:00", chat_id=CHAT_ID, user_id=USER_ID, update_id=14))
    handle_message(ctx, make_msg(text="-5", chat_id=CHAT_ID, user_id=USER_ID, update_id=15))
    assert CREATE_EVENT_INVALID_DURATION in final_message_html(ctx.telegram)


def test_create_date_and_duration_callbacks(
    store: UserStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_create", now=fixed_now)

    ctx = _create_ctx(store)
    _start_create(ctx)
    handle_message(ctx, make_msg(text="Demo", chat_id=CHAT_ID, user_id=USER_ID, update_id=20))
    ctx.calendar_state.set(
        CHAT_ID,
        CalendarFlowState(state=STATE_CREATE_DATE, draft=CreateEventDraft(title="Demo")),
    )
    handle_callback_query(
        ctx,
        make_callback(data=CB_CREATE_DATE_TODAY, chat_id=CHAT_ID, user_id=USER_ID),
    )
    assert CREATE_EVENT_ASK_TIME in final_message_html(ctx.telegram)

    flow = ctx.calendar_state.get(CHAT_ID)
    flow.state = STATE_CREATE_TIME
    flow.draft.start_time = "14:00"
    flow.state = STATE_CREATE_DURATION
    ctx.calendar_state.set(CHAT_ID, flow)
    handle_callback_query(
        ctx,
        make_callback(
            data=f"{CB_CREATE_DURATION_PREFIX}45",
            chat_id=CHAT_ID,
            user_id=USER_ID,
        ),
    )
    assert ctx.calendar_state.get(CHAT_ID).state == STATE_CREATE_CONFIRM


def test_create_confirm_success_and_cancel(
    store: UserStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_create", now=fixed_now)

    ctx = _create_ctx(store)
    draft = CreateEventDraft(
        title="Demo",
        event_date=fixed_now.date(),
        start_time="10:00",
        duration_minutes=30,
    )
    ctx.calendar_state.set(
        CHAT_ID,
        CalendarFlowState(state=STATE_CREATE_CONFIRM, draft=draft),
    )
    handle_callback_query(
        ctx,
        make_callback(data=CB_CREATE_CONFIRM, chat_id=CHAT_ID, user_id=USER_ID, message_id=99),
    )
    ctx.calendar_service.create_event.assert_called_once()
    assert ctx.calendar_state.get(CHAT_ID) is None

    ctx.calendar_state.set(
        CHAT_ID,
        CalendarFlowState(state=STATE_CREATE_CONFIRM, draft=draft),
    )
    handle_callback_query(
        ctx,
        make_callback(data=CB_CREATE_CANCEL, chat_id=CHAT_ID, user_id=USER_ID),
    )
    sent = sent_messages_text(ctx.telegram)
    assert CREATE_EVENT_CANCELLED_HTML in sent


@pytest.mark.parametrize(
    "error_code,expected_fragment",
    [
        ("CREATE_FAILED", CREATE_EVENT_FAILED_HTML),
        ("NO_CALENDAR", "календар"),
        ("CALDAV_UNAVAILABLE", ERR_CALDAV_UNAVAILABLE_TEXT),
    ],
)
def test_create_failure_text_mapping(
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_fragment: str,
) -> None:
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_create", now=fixed_now)

    ctx = _create_ctx(store)
    draft = CreateEventDraft(
        title="X",
        event_date=fixed_now.date(),
        start_time="11:00",
        duration_minutes=30,
    )
    ctx.calendar_state.set(
        CHAT_ID,
        CalendarFlowState(state=STATE_CREATE_CONFIRM, draft=draft),
    )
    ctx.calendar_service.create_event = MagicMock(
        side_effect=CalendarProviderError("boom", error_code=error_code)
    )
    handle_callback_query(
        ctx,
        make_callback(data=CB_CREATE_CONFIRM, chat_id=CHAT_ID, user_id=USER_ID, message_id=100),
    )
    edited = callback_edit_html(ctx.telegram)
    assert expected_fragment[:20] in edited or expected_fragment in edited


def test_recognized_command_clears_create_fsm(store: UserStore) -> None:
    """Любая recognized команда сбрасывает calendar_state (инвариант dispatch)."""
    ctx = _create_ctx(store)
    ctx.calendar_state.set(
        CHAT_ID,
        CalendarFlowState(state=STATE_CREATE_TITLE, draft=CreateEventDraft()),
    )
    handle_message(ctx, make_msg(text="/settings", chat_id=CHAT_ID, user_id=USER_ID, update_id=30))
    assert ctx.calendar_state.get(CHAT_ID) is None


def test_create_state_takes_precedence_over_digest_text(
    store: UserStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Активный create FSM перехватывает текст раньше ожидания времени дайджеста."""
    ctx = _create_ctx(store)
    ctx.digest_state.is_waiting_for_time = MagicMock(return_value=True)
    ctx.calendar_state.set(
        CHAT_ID,
        CalendarFlowState(state=STATE_CREATE_TITLE, draft=CreateEventDraft()),
    )
    digest_handler = MagicMock()
    monkeypatch.setattr(
        "satellite.telegram_bot.handlers.dispatch.handle_digest_time_input",
        digest_handler,
    )
    handle_message(ctx, make_msg(text="09:00", chat_id=CHAT_ID, user_id=USER_ID, update_id=40))
    digest_handler.assert_not_called()
    assert ctx.calendar_state.get(CHAT_ID) is not None
