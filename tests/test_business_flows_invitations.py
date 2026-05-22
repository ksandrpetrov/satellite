"""`/invitations`: горизонт 60d/14d, лимит 12, PARTSTAT, guard release."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.callback_tokens import event_callback_token
from satellite.calendar.providers.base import CalendarProviderError
from satellite.invitations_view import (
    INVITATION_HORIZON_DAYS,
    INVITATION_LOOKBACK_DAYS,
    MAX_INVITATIONS,
)
from satellite.messages_ru import (
    CB_INV_REFRESH,
    CB_INV_RESPOND_PREFIX,
    CB_SETTINGS_INVITATIONS,
)
from satellite.telegram_bot.handlers import handle_callback_query, handle_message
from satellite.users import USER_STATUS_APPROVED

from .conftest import make_callback, make_msg

TZ = ZoneInfo("Europe/Moscow")
LOGIN = "me@mail.ru"
USER_ID = 8101
CHAT_ID = 8101


def _ev(
    *,
    summary: str = "Meet",
    partstat: str = "NEEDS-ACTION",
    url: str = "https://cal/e/1.ics",
    start: str = "2026-05-22T14:00:00+03:00",
    end: str = "2026-05-22T15:00:00+03:00",
    uid: str = "uid-1",
) -> dict:
    attendees = [f"mailto:{LOGIN};PARTSTAT={partstat}"]
    return {
        "uid": uid,
        "summary": summary,
        "url": url,
        "dtstart": start,
        "dtend": end,
        "attendees": attendees,
    }


def _ctx(*, events: list[dict] | None = None, raise_on_list: Exception | None = None) -> MagicMock:
    record = MagicMock()
    record.status = USER_STATUS_APPROVED
    record.has_calendar = True
    ctx = MagicMock()
    ctx.users = MagicMock()
    ctx.users.get = MagicMock(return_value=record)
    ctx.tz = TZ
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = "https://example.com/connect"
    from satellite.web.connect_token import ConnectTokenStore

    ctx.connect_tokens = ConnectTokenStore()
    ctx.digest_state = MagicMock()
    ctx.digest_state.is_waiting_for_time = MagicMock(return_value=False)
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.subscriptions = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 8100})
    ctx.telegram.edit_message_text = MagicMock(return_value={})
    ctx.telegram.send_message_draft = MagicMock(return_value=True)
    ctx.telegram.answer_callback_query = MagicMock(return_value=True)

    connected = MagicMock()
    connected.context = MagicMock()
    connected.context.login = LOGIN
    ctx.calendar_service.require_connection = MagicMock(return_value=connected)

    def list_invitations(user_id: int, **kwargs):
        if raise_on_list is not None:
            raise raise_on_list
        return list(events or [])

    ctx.calendar_service.list_events_for_invitations = MagicMock(side_effect=list_invitations)
    ctx.calendar_service.set_attendee_partstat = MagicMock()
    return ctx


def test_invitations_list_uses_60d_forward_and_14d_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr("satellite.invitations_view.datetime", _FixedDatetime)

    ctx = _ctx(events=[])
    handle_message(
        ctx, make_msg(text="/invitations", chat_id=CHAT_ID, user_id=USER_ID, update_id=1)
    )

    call = ctx.calendar_service.list_events_for_invitations.call_args
    assert call.kwargs["start_date"] == date(2026, 5, 8)
    assert call.kwargs["end_date"] == date(2026, 7, 21)
    assert INVITATION_LOOKBACK_DAYS == 14
    assert INVITATION_HORIZON_DAYS == 60


def test_invitations_caps_at_twelve_items(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr("satellite.invitations_view.datetime", _FixedDatetime)

    events = [
        _ev(summary=f"E{i}", url=f"https://cal/e/{i}.ics", uid=f"u{i}")
        for i in range(MAX_INVITATIONS + 5)
    ]
    ctx = _ctx(events=events)
    handle_message(
        ctx, make_msg(text="/invitations", chat_id=CHAT_ID, user_id=USER_ID, update_id=2)
    )

    rendered = ctx.telegram.send_message.call_args[0][1]
    # Показываем не больше MAX_INVITATIONS встреч (E12..E16 не должны попасть)
    for i in range(MAX_INVITATIONS):
        assert f"E{i}" in rendered
    assert "E12" not in rendered


def test_settings_invitations_entry_opens_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr("satellite.invitations_view.datetime", _FixedDatetime)

    ctx = _ctx(events=[_ev()])
    handle_callback_query(
        ctx,
        make_callback(
            data=CB_SETTINGS_INVITATIONS, chat_id=CHAT_ID, user_id=USER_ID, message_id=50
        ),
    )
    ctx.telegram.edit_message_text.assert_called()


def test_invitations_respond_accept_updates_partstat(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr("satellite.invitations_view.datetime", _FixedDatetime)

    url = "https://cal/e/accept.ics"
    ctx = _ctx(events=[_ev(url=url)])
    token = event_callback_token(url)
    handle_callback_query(
        ctx,
        make_callback(
            data=f"{CB_INV_RESPOND_PREFIX}{token}:a",
            chat_id=CHAT_ID,
            user_id=USER_ID,
        ),
    )
    ctx.calendar_service.set_attendee_partstat.assert_called_once()
    assert ctx.calendar_service.set_attendee_partstat.call_args.args[2] == "ACCEPTED"


def test_invitations_releases_guard_after_list_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr("satellite.invitations_view.datetime", _FixedDatetime)

    err = CalendarProviderError("boom", error_code="CALDAV_UNAVAILABLE")
    ctx = _ctx()
    ctx.calendar_service.list_events_for_invitations = MagicMock(side_effect=[err, []])
    handle_message(
        ctx, make_msg(text="/invitations", chat_id=CHAT_ID, user_id=USER_ID, update_id=10)
    )
    handle_message(
        ctx, make_msg(text="/invitations", chat_id=CHAT_ID, user_id=USER_ID, update_id=11)
    )
    assert ctx.calendar_service.list_events_for_invitations.call_count == 2


def test_invitations_refresh_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr("satellite.invitations_view.datetime", _FixedDatetime)

    ctx = _ctx(events=[_ev()])
    handle_callback_query(ctx, make_callback(data=CB_INV_REFRESH, chat_id=CHAT_ID, user_id=USER_ID))
    ctx.telegram.edit_message_text.assert_called()
