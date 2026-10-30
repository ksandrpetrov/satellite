"""One recurrence only; conditional writes and reconciliation after lost responses."""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from icalendar import Alarm, Calendar, Event

from satellite.calendar.caldav_shared import CalDAVConflictError
from satellite.calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarMutation,
    CalendarProviderError,
)
from satellite.calendar.safe_mutations import apply_mutation, move_occurrence

BASE = datetime(2026, 11, 2, 8, tzinfo=UTC)
URL = "https://calendar.example/own/series.ics"


def series():
    cal = Calendar()
    cal.add("version", "2.0")
    master = Event()
    for key, value in {
        "uid": "series",
        "summary": "Team",
        "dtstart": BASE,
        "dtend": BASE + timedelta(hours=1),
        "organizer": "mailto:me@example.com",
        "description": "Keep this description",
        "sequence": 4,
        "rrule": {"freq": "DAILY", "count": 5},
    }.items():
        master.add(key, value)
    master.add("attendee", "mailto:colleague@example.com", parameters={"PARTSTAT": "ACCEPTED"})
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("trigger", timedelta(minutes=-10))
    alarm.add("description", "Reminder")
    master.add_component(alarm)
    cal.add_component(master)
    override = Event()
    for key, value in {
        "uid": "series",
        "summary": "Existing override",
        "recurrence-id": BASE + timedelta(days=2),
        "dtstart": BASE + timedelta(days=2, hours=1),
        "dtend": BASE + timedelta(days=2, hours=2),
        "organizer": "mailto:me@example.com",
    }.items():
        override.add(key, value)
    cal.add_component(override)
    return cal


def mutation():
    old = BASE + timedelta(days=1)
    return CalendarMutation(
        "a" * 64,
        "reschedule",
        "https://calendar.example/own/",
        "connection",
        CalendarEventPayload("Team", old + timedelta(hours=2), old + timedelta(hours=3)),
        CalendarEventRef("series", URL, "connection"),
        old,
        old + timedelta(hours=1),
    )


def transport(calendar):
    service = MagicMock()
    service._login = "me@example.com"
    service._partstat_update_timeout_sec = 20.0
    service._require_handle.return_value = SimpleNamespace(url="https://calendar.example/own/")
    resource = {"data": calendar.to_ical(), "etag": '"1"'}
    service._get_event_ics_via_http.side_effect = lambda _url, **_kwargs: (
        resource["data"],
        resource["etag"],
    )

    def put(_url, data, *, etag, timeout_sec):
        assert etag == resource["etag"]
        resource.update(data=data, etag='"2"')

    service._put_event_ics_via_http.side_effect = put
    return service, resource


def test_move_one_occurrence_preserves_master_other_override_and_alarm():
    cal = series()
    old = [e.to_ical() for e in cal.walk("vevent")]
    changed, already = move_occurrence(cal, mutation(), "me@example.com")
    assert not already
    assert [e.to_ical() for e in cal.walk("vevent")[:2]] == old
    assert changed.decoded("recurrence-id") == BASE + timedelta(days=1)
    assert changed.decoded("dtstart") == mutation().payload.start
    assert str(changed["description"]) == "Keep this description"
    assert str(changed["attendee"]) == "mailto:colleague@example.com"
    assert changed.walk("valarm")[0].decoded("trigger") == timedelta(minutes=-10)
    assert int(changed["sequence"]) == 5
    assert "rrule" not in changed
    assert len(cal.walk("vevent")) == 3


def test_existing_exception_updates_only_itself_and_preserves_series():
    cal = series()
    master = cal.walk("vevent")[0].to_ical()
    old = BASE + timedelta(days=2, hours=1)
    m = replace(
        mutation(),
        original_start=old,
        original_end=old + timedelta(hours=1),
        recurrence_id=BASE + timedelta(days=2),
        payload=replace(mutation().payload, title="Existing override"),
    )
    changed, _ = move_occurrence(cal, m, "me@example.com")
    assert len(cal.walk("vevent")) == 2
    assert cal.walk("vevent")[0].to_ical() == master
    assert str(changed["summary"]) == "Existing override"


def test_write_readback_replay_and_lost_put_response_do_not_repeat_write():
    service, resource = transport(series())
    original_put = service._put_event_ics_via_http.side_effect

    def lost(*args, **kwargs):
        original_put(*args, **kwargs)
        raise requests.Timeout()

    service._put_event_ics_via_http.side_effect = lost
    ref = apply_mutation(service, mutation(), reconcile_only=False)
    assert ref.uid == "series"
    apply_mutation(service, mutation(), reconcile_only=True)
    apply_mutation(service, mutation(), reconcile_only=False)
    assert service._put_event_ics_via_http.call_count == 1
    assert len(Calendar.from_ical(resource["data"]).walk("vevent")) == 3


@pytest.mark.parametrize(
    "change,code", [("organizer", "NOT_ORGANIZER"), ("removed", "EVENT_CHANGED")]
)
def test_cannot_move_other_organizers_or_missing_occurrence(change, code):
    cal = series()
    if change == "organizer":
        cal.walk("vevent")[0]["organizer"] = "mailto:someone@example.com"
    else:
        cal.walk("vevent")[0].add("exdate", mutation().original_start)
    with pytest.raises(CalendarProviderError, match=code):
        move_occurrence(cal, mutation(), "me@example.com")


def test_version_conflict_and_missing_etag_never_blindly_retry():
    service, resource = transport(series())
    service._put_event_ics_via_http.side_effect = CalDAVConflictError("changed")
    with pytest.raises(CalDAVConflictError):
        apply_mutation(service, mutation(), reconcile_only=False)
    assert service._put_event_ics_via_http.call_count == 1
    resource["etag"] = None
    with pytest.raises(CalendarProviderError, match="MISSING_ETAG"):
        apply_mutation(service, mutation(), reconcile_only=False)
    assert service._put_event_ics_via_http.call_count == 1


def test_recovery_of_uncommitted_write_only_reads():
    service, _ = transport(series())
    with pytest.raises(CalendarProviderError, match="WRITE_UNCONFIRMED"):
        apply_mutation(service, mutation(), reconcile_only=True)
    service._put_event_ics_via_http.assert_not_called()


def test_create_has_stable_uid_and_if_none_match_and_readback():
    service, _ = transport(series())
    service._partstat_update_timeout_sec = 10
    service._created_event_is_saved.return_value = True
    service._http_put.side_effect = requests.Timeout()
    m = replace(mutation(), kind="create", event_ref=None)
    ref = apply_mutation(service, m, reconcile_only=False)
    assert ref.uid == "satellite-ai-" + "a" * 64 + "@satellite.local"
    assert service._http_put.call_args.kwargs["headers"]["If-None-Match"] == "*"
    apply_mutation(service, m, reconcile_only=True)
    assert service._http_put.call_count == 1
    assert service._created_event_is_saved.call_count == 2


def test_resource_cannot_escape_selected_calendar():
    service, _ = transport(series())
    m = replace(
        mutation(), event_ref=CalendarEventRef("series", "https://evil.example/steal", "connection")
    )
    with pytest.raises(CalendarProviderError, match="INVALID_EVENT_IDENTITY"):
        apply_mutation(service, m, reconcile_only=False)
    service._get_event_ics_via_http.assert_not_called()


def test_expired_turn_never_starts_a_calendar_request():
    service, _ = transport(series())
    with pytest.raises(CalendarProviderError, match="AI_DEADLINE"):
        apply_mutation(service, mutation(), reconcile_only=False, deadline=time.monotonic() - 1)
    service._require_handle.assert_not_called()
    service._put_event_ics_via_http.assert_not_called()


def test_server_dropping_alarm_cannot_produce_a_success_receipt():
    service, resource = transport(series())
    original_put = service._put_event_ics_via_http.side_effect

    def drop_alarm(*args, **kwargs):
        original_put(*args, **kwargs)
        saved = Calendar.from_ical(resource["data"])
        saved.walk("vevent")[-1].subcomponents.clear()
        resource["data"] = saved.to_ical()

    service._put_event_ics_via_http.side_effect = drop_alarm
    with pytest.raises(CalendarProviderError, match="WRITE_UNCONFIRMED"):
        apply_mutation(service, mutation(), reconcile_only=False)
