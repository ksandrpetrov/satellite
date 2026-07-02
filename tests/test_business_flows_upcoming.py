"""`/upcoming`: 7-дневный горизонт, пустой список, CalDAV-ошибка, ActionGuard."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from satellite.calendar.providers.base import CalendarProviderError
from satellite.messages_ru import (
    BUTTON_UPCOMING,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    UPCOMING_EMPTY_HTML,
)
from satellite.telegram_bot.handlers import handle_message
from satellite.testing.delivery_helpers import sent_messages_text
from satellite.users import UserStore

from .conftest import FakeCalendarService, freeze_now, make_ctx, make_msg, make_user_store

USER_ID = 8001
CHAT_ID = 8001


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    return make_user_store(tmp_path, approved_with_calendar=[USER_ID])


def _upcoming_ctx(users: UserStore, calendar: FakeCalendarService | MagicMock) -> MagicMock:
    ctx = make_ctx(users)
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 8000})
    ctx.telegram.send_message_draft = MagicMock(return_value=True)
    ctx.telegram.send_rich_message_draft = MagicMock(return_value=True)
    ctx.telegram.send_rich_message = MagicMock(return_value={"message_id": 8000})
    ctx.telegram.edit_message_text = MagicMock(return_value={"message_id": 8000})
    ctx.calendar_service = calendar
    return ctx


def test_upcoming_calls_list_events_with_seven_day_horizon(
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_list", now=fixed_now)

    cal = FakeCalendarService(events=[])
    ctx = _upcoming_ctx(store, cal)
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=1))

    assert len(cal.list_calls) == 1
    call = cal.list_calls[0]
    assert call["user_id"] == USER_ID
    assert call["start_date"] == date(2026, 5, 22)
    assert call["end_date"] == date(2026, 5, 29)


def test_upcoming_button_alias(store: UserStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_list", now=fixed_now)

    cal = FakeCalendarService(events=[])
    ctx = _upcoming_ctx(store, cal)
    handle_message(
        ctx, make_msg(text=BUTTON_UPCOMING, chat_id=CHAT_ID, user_id=USER_ID, update_id=2)
    )
    assert len(cal.list_calls) == 1


def test_upcoming_empty_shows_empty_html(store: UserStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_list", now=fixed_now)

    ctx = _upcoming_ctx(store, FakeCalendarService(events=[]))
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=3))

    sent = sent_messages_text(ctx.telegram)
    assert UPCOMING_EMPTY_HTML in sent


def test_upcoming_caldav_error_shows_safe_text(
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_list", now=fixed_now)

    cal = FakeCalendarService(
        raise_on_list=CalendarProviderError("boom", error_code="CALDAV_UNAVAILABLE")
    )
    ctx = _upcoming_ctx(store, cal)
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=4))

    sent = sent_messages_text(ctx.telegram)
    assert ERR_CALDAV_UNAVAILABLE_TEXT in sent


def test_upcoming_cooldown_blocks_second_call_after_success(
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_list", now=fixed_now)

    cal = FakeCalendarService(events=[])
    ctx = _upcoming_ctx(store, cal)
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=5))
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=6))
    assert len(cal.list_calls) == 1


def test_upcoming_releases_guard_after_caldav_failure(
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После ошибки CalDAV повторный /upcoming не блокируется cooldown'ом."""
    fixed_now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.calendar_list", now=fixed_now)

    cal = FakeCalendarService(
        raise_on_list=CalendarProviderError("boom", error_code="CALDAV_UNAVAILABLE")
    )
    ctx = _upcoming_ctx(store, cal)
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=7))

    cal.raise_on_list = None
    cal.events = []
    cal.list_calls.clear()
    handle_message(ctx, make_msg(text="/upcoming", chat_id=CHAT_ID, user_id=USER_ID, update_id=8))
    assert len(cal.list_calls) == 1
