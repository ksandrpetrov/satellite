"""Unit tests for streaming CalDAV scaffold."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from satellite.calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from satellite.messages_ru import ERR_CALDAV_UNAVAILABLE_TEXT, INVITATIONS_BUSY_TEXT
from satellite.telegram_bot.handlers.calendar_invitations import _invitations_open_guard
from satellite.telegram_bot.handlers.context import IncomingMessage
from satellite.telegram_bot.handlers.streaming_caldav import (
    StreamingCaldavResult,
    run_streaming_caldav_message,
)


@pytest.fixture(autouse=True)
def _reset_guard() -> None:
    _invitations_open_guard.reset()


def _msg(update_id: int = 1) -> IncomingMessage:
    return IncomingMessage(
        update_id=update_id,
        chat_id=100,
        user_id=200,
        username="alice",
        display_name="Alice",
        text="/invitations",
    )


def _ctx() -> MagicMock:
    ctx = MagicMock()
    stream = MagicMock()
    stream.push_status = MagicMock()
    stream.finish = MagicMock()
    ctx.telegram = MagicMock()
    ctx._stream = stream
    return ctx


def test_streaming_caldav_guard_busy() -> None:
    ctx = _ctx()
    with (
        patch(
            "satellite.telegram_bot.handlers.streaming_caldav.open_streaming_reply"
        ) as open_stream,
        patch("satellite.telegram_bot.handlers.streaming_caldav.send") as send,
    ):
        assert _invitations_open_guard.try_acquire(100, "invitations:open")
        result = run_streaming_caldav_message(
            ctx,
            _msg(),
            guard=_invitations_open_guard,
            action_key="invitations:open",
            busy_text=INVITATIONS_BUSY_TEXT,
            status_text="loading",
            fetch_fn=lambda _c, _u: StreamingCaldavResult("", "", None),
            log_label="Test",
        )
    assert result is False
    open_stream.assert_not_called()
    send.assert_called_once_with(ctx, 100, INVITATIONS_BUSY_TEXT)


def test_streaming_caldav_calendar_error_finishes_safe_text() -> None:
    ctx = _ctx()

    def _fail(_ctx, _uid):
        raise CalendarNotConnectedError()

    with patch(
        "satellite.telegram_bot.handlers.streaming_caldav.open_streaming_reply",
        return_value=ctx._stream,
    ):
        result = run_streaming_caldav_message(
            ctx,
            _msg(),
            guard=_invitations_open_guard,
            action_key="invitations:open",
            busy_text=INVITATIONS_BUSY_TEXT,
            status_text="loading",
            fetch_fn=_fail,
            log_label="Test",
        )
    assert result is False
    ctx._stream.finish.assert_called_once_with(
        ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False
    )


def test_streaming_caldav_provider_error_releases_guard() -> None:
    ctx = _ctx()

    def _fail(_ctx, _uid):
        raise CalendarProviderError("boom", error_code="CALDAV_UNAVAILABLE")

    with patch(
        "satellite.telegram_bot.handlers.streaming_caldav.open_streaming_reply",
        return_value=ctx._stream,
    ):
        run_streaming_caldav_message(
            ctx,
            _msg(update_id=2),
            guard=_invitations_open_guard,
            action_key="invitations:open",
            busy_text=INVITATIONS_BUSY_TEXT,
            status_text="loading",
            fetch_fn=_fail,
            log_label="Test",
        )
    assert _invitations_open_guard.try_acquire(100, "invitations:open")
