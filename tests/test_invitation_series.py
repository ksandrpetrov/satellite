"""Recurring invitations use the same resource boundary as answer callbacks."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from icalendar import Calendar

from satellite.calendar.caldav_client import CalDAVService
from satellite.calendar.callback_tokens import event_callback_token
from satellite.calendar.event_token_cache import EventTokenCache
from satellite.invitations_view import collect_pending_from_events, load_pending_invitations_screen
from satellite.messages_ru import CB_INV_RESPOND_PREFIX, INVITATIONS_SERIES_LABEL
from satellite.telegram_bot.handlers import handle_callback_query

from .conftest import make_callback
from .test_business_flows_invitations import CHAT_ID, LOGIN, TZ, USER_ID, _ctx, _ev

NOW = datetime(2026, 5, 22, 10, tzinfo=TZ)


def occurrence(day, **kwargs):
    start = NOW + timedelta(days=day, hours=1)
    return _ev(start=start.isoformat(), end=(start + timedelta(hours=1)).isoformat(), **kwargs)


def test_series_group_before_limit_and_render_without_mutating_events():
    events = [occurrence(day) for day in range(30)]
    events += [occurrence(1, url=f"https://cal/{i}.ics") for i in range(12)]
    service = MagicMock()
    service.require_connection.return_value.context.login = LOGIN
    service.list_events_for_invitations.return_value = events
    screen = load_pending_invitations_screen(
        service, USER_ID, event_tokens=EventTokenCache(), tz=TZ, now=NOW
    )
    assert len(screen.pending) == 12
    assert screen.truncated
    rows = screen.keyboard["inline_keyboard"][:-2]
    assert len(rows) == 12
    assert len({row[0]["callback_data"] for row in rows}) == 12
    assert screen.text.count(INVITATIONS_SERIES_LABEL) == 1
    assert screen.rich_text.count(INVITATIONS_SERIES_LABEL) == 1
    assert all("invitation_series" not in ev for ev in events)
    pending, truncated = collect_pending_from_events(events[:30], LOGIN, TZ, now=NOW)
    assert len(pending) == 1
    assert not truncated


@pytest.mark.parametrize("days,expected", [([-3, -1, 2, 5], 2), ([-3, -1], -1)])
def test_representative_uses_nearest_unfinished_or_latest_past(days, expected):
    events = [occurrence(day) for day in reversed(days)]
    cancelled = occurrence(0)
    cancelled["status"] = "CANCELLED"
    events.append(cancelled)
    pending, _ = collect_pending_from_events(events, LOGIN, TZ, now=NOW)
    assert len(pending) == 1
    assert pending[0]["dtstart"] == occurrence(expected)["dtstart"]


@pytest.mark.parametrize(
    "metadata", [{"rrule": {"FREQ": ["WEEKLY"]}}, {"raw_keys": ["RECURRENCE-ID"]}]
)
def test_single_visible_repeat_is_marked_as_series(metadata):
    event = occurrence(2) | metadata
    pending, _ = collect_pending_from_events([event], LOGIN, TZ, now=NOW)
    assert pending[0]["invitation_series"]


@pytest.mark.parametrize("code,status", [("a", "ACCEPTED"), ("d", "DECLINED"), ("t", "TENTATIVE")])
@pytest.mark.parametrize("fails", [False, True])
def test_series_answer_updates_once_and_removes_only_on_success(code, status, fails):
    events = [occurrence(day) for day in range(3)]
    ctx = _ctx(events=events)
    load_pending_invitations_screen(
        ctx.calendar_service, USER_ID, event_tokens=ctx.runtime.event_tokens, tz=TZ, now=NOW
    )
    if fails:
        from satellite.calendar.providers.base import CalendarProviderError

        ctx.calendar_service.set_attendee_partstat.side_effect = CalendarProviderError("failed")
    token = event_callback_token(events[0]["url"])
    handle_callback_query(
        ctx,
        make_callback(
            data=f"{CB_INV_RESPOND_PREFIX}{token}:{code}", chat_id=CHAT_ID, user_id=USER_ID
        ),
    )
    ctx.calendar_service.set_attendee_partstat.assert_called_once()
    assert ctx.calendar_service.set_attendee_partstat.call_args.args[2] == status
    snapshot = ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID)
    assert snapshot is not None
    assert len(snapshot.pending) == (1 if fails else 0)


@pytest.mark.parametrize("status", ["ACCEPTED", "DECLINED", "TENTATIVE"])
def test_series_ics_updates_master_and_exception(status, monkeypatch):
    service = CalDAVService(caldav_url="https://cal/", login=LOGIN, app_password="pw")
    components = []
    for recurrence in ["", "RECURRENCE-ID:20260529T110000Z\r\n"]:
        components.append(
            "BEGIN:VEVENT\r\nUID:series\r\nDTSTART:20260522T110000Z\r\n"
            "DTEND:20260522T120000Z\r\n"
            + recurrence
            + ("" if recurrence else "RRULE:FREQ=WEEKLY\r\n")
            + f"ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{LOGIN}\r\n"
            "ATTENDEE;PARTSTAT=ACCEPTED:mailto:other@example.com\r\nEND:VEVENT\r\n"
        )
    payload = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(components) + "END:VCALENDAR\r\n"
    ).encode()
    monkeypatch.setattr(
        service, "_get_event_ics_via_http", MagicMock(return_value=(payload, '"etag"'))
    )
    put = MagicMock()
    monkeypatch.setattr(service, "_put_event_ics_via_http", put)
    service.set_attendee_partstat("https://cal/series.ics", status)
    put.assert_called_once()
    assert put.call_args.kwargs["etag"] == '"etag"'
    updated = Calendar.from_ical(put.call_args.args[1]).walk("VEVENT")
    assert len(updated) == 2
    assert "RRULE" in updated[0]
    assert "RECURRENCE-ID" in updated[1]
    for component in updated:
        attendees = component.get("ATTENDEE")
        assert str(attendees[0].params["PARTSTAT"]) == status
        assert str(attendees[1].params["PARTSTAT"]) == "ACCEPTED"


def test_ongoing_and_moved_occurrences_use_actual_start():
    ongoing = _ev(
        start=(NOW - timedelta(minutes=30)).isoformat(),
        end=(NOW + timedelta(minutes=30)).isoformat(),
    )
    moved = occurrence(2) | {"raw_keys": ["RECURRENCE-ID"]}
    pending, _ = collect_pending_from_events([moved, ongoing, occurrence(-1)], LOGIN, TZ, now=NOW)
    assert pending[0]["dtstart"] == ongoing["dtstart"]
    pending, _ = collect_pending_from_events([moved, occurrence(-1)], LOGIN, TZ, now=NOW)
    assert pending[0]["dtstart"] == moved["dtstart"]


def test_scheduler_delivers_same_grouped_screen_as_manual_loader(tmp_path):
    from .test_scheduler import _make_scheduler

    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=NOW)
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_enabled=False, pending_digest_enabled=True)
    service = scheduler._calendar_service
    service.require_connection.return_value.context.login = LOGIN
    service.list_events_for_invitations.return_value = [occurrence(day) for day in range(20)]
    manual = load_pending_invitations_screen(
        service, 1, event_tokens=EventTokenCache(), tz=TZ, now=NOW
    )
    assert scheduler.tick() == 1
    call = telegram.send_rich_message.call_args
    assert call is not None
    assert call.args[1]["html"] == manual.rich_text
    assert call.kwargs["reply_markup"] == manual.keyboard
