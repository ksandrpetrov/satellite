"""PARTSTAT respond dedup via ActionGuard."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from satellite.calendar.callback_tokens import event_callback_token
from satellite.messages_ru import CB_INV_RESPOND_PREFIX
from satellite.telegram_bot.handlers.context import IncomingCallback
from satellite.telegram_bot.handlers.partstat_flow import (
    PartstatFlow,
    _partstat_respond_guard,
    respond_partstat,
)


@pytest.fixture(autouse=True)
def _reset_guard() -> None:
    _partstat_respond_guard.reset()


def test_partstat_respond_dedup_within_cooldown() -> None:
    url = "https://cal/e/1.ics"
    token = event_callback_token(url)
    data = f"{CB_INV_RESPOND_PREFIX}{token}:a"
    events = [
        {
            "url": url,
            "uid": "u1",
            "summary": "Meet",
            "attendees": ["mailto:me@mail.ru;PARTSTAT=NEEDS-ACTION"],
        }
    ]

    ctx = MagicMock()
    ctx.users = MagicMock()
    ctx.tz = MagicMock()
    ctx.calendar_service = MagicMock()
    ctx.calendar_service.set_attendee_partstat = MagicMock()
    ctx.telegram = MagicMock()
    ctx.telegram.answer_callback_query = MagicMock(return_value=True)

    cb = IncomingCallback(
        update_id=1,
        callback_query_id="cb1",
        chat_id=10,
        message_id=20,
        user_id=30,
        username="alice",
        data=data,
    )

    flow = PartstatFlow(
        prefix=CB_INV_RESPOND_PREFIX,
        fail_text="fail",
        toast_by_code={"a": "ok"},
        log_name="Test",
        fetch_events=lambda _ctx, _uid: events,
        optimistic_refresh_view=MagicMock(),
        on_not_found=MagicMock(),
        on_fail=MagicMock(),
    )

    respond_partstat(ctx, cb, data, flow)
    assert ctx.calendar_service.set_attendee_partstat.call_count == 1

    respond_partstat(ctx, cb, data, flow)
    assert ctx.calendar_service.set_attendee_partstat.call_count == 1
