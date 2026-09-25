"""Real CalDAV HTTP round trips: a successful PUT is not a confirmed response."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from icalendar import Calendar

from satellite.calendar.caldav_client import CalDAVService
from satellite.calendar.caldav_shared import (
    CalDAVError,
    CalDAVPartstatUnconfirmedError,
    _DiscoveryResult,
)
from satellite.calendar.providers.base import (
    CalendarEventRef,
    CalendarProviderError,
    UserCalendarContext,
)
from satellite.calendar.providers.mailru import MailruCalendarProvider
from satellite.security.token_vault import ProviderCredentials

LOGIN = "me@example.com"


def series_ics() -> bytes:
    components = []
    for recurrence in ["RRULE:FREQ=WEEKLY", "RECURRENCE-ID:20260930T100000Z"]:
        components.append(
            "BEGIN:VEVENT\r\nUID:series\r\nDTSTART:20260923T100000Z\r\n"
            "DTEND:20260923T110000Z\r\nSUMMARY:Original\r\nSEQUENCE:4\r\n"
            f"{recurrence}\r\nATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{LOGIN}\r\n"
            "ATTENDEE;PARTSTAT=TENTATIVE:mailto:other@example.com\r\nEND:VEVENT\r\n"
        )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(components) + "END:VCALENDAR\r\n"
    ).encode()


@pytest.fixture
def caldav_http():
    state = SimpleNamespace(payload=series_ics(), version=1, mode="success", calls=[], puts=0)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body=b""):
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            if state.mode != "no_etag" and not (
                state.mode == "head_race" and self.command == "GET"
            ):
                self.send_header("ETag", f'"{state.version}"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            state.calls.append(("GET", None))
            if state.mode == "verify_unavailable" and state.puts:
                self.reply(503)
            elif state.mode == "bad_initial" or (state.mode == "bad_verify" and state.puts):
                self.reply(200, b"not a calendar")
            else:
                self.reply(200, state.payload)

        def do_HEAD(self):
            state.calls.append(("HEAD", None))
            if state.mode == "head_race":
                state.payload = state.payload.replace(
                    b"SUMMARY:Original", b"SUMMARY:Changed before HEAD"
                )
                state.version += 1
            self.reply(200)

        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state.puts += 1
            state.calls.append(("PUT", self.headers.get("If-Match")))
            if state.mode == "unauthorized":
                self.reply(403)
                return
            if state.mode == "conflict_always" or (
                state.mode == "conflict_once" and state.puts == 1
            ):
                state.payload = state.payload.replace(
                    b"SUMMARY:Original", b"SUMMARY:Changed by organizer"
                )
                state.version += 1
                self.reply(412)
                return
            if self.headers.get("If-Match") != f'"{state.version}"':
                self.reply(412)
                return
            commit = state.mode != "ignore" and not (
                state.mode == "timeout_no_commit" and state.puts == 1
            )
            if commit:
                if state.mode in {"partial_series", "missing_exception"}:
                    calendar = Calendar.from_ical(body)
                    if state.mode == "partial_series":
                        calendar.walk("VEVENT")[1]["ATTENDEE"][0].params["PARTSTAT"] = (
                            "NEEDS-ACTION"
                        )
                    else:
                        calendar.subcomponents.pop()
                    body = calendar.to_ical()
                state.payload = body
                state.version += 1
            if state.mode in {"timeout_committed", "timeout_no_commit"} and state.puts == 1:
                time.sleep(0.15)
            self.reply(500 if state.mode == "500_committed" else 204)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/event.ics"
    service = CalDAVService(
        caldav_url=url, login=LOGIN, app_password="test-password", partstat_update_timeout_sec=0.08
    )
    service._cache = _DiscoveryResult(url, [], time.monotonic(), LOGIN)
    # Short test-only timeout: production enforces a three-second minimum.
    service._partstat_update_timeout_sec = 0.08
    try:
        yield service, state, url
    finally:
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("partstat", ["ACCEPTED", "DECLINED", "TENTATIVE"])
def test_series_is_verified_and_other_participants_are_preserved(caldav_http, partstat):
    service, state, url = caldav_http
    service.set_attendee_partstat(url, partstat)
    assert [method for method, _ in state.calls] == ["GET", "PUT", "GET"]
    assert state.calls[1][1] == '"1"'
    components = Calendar.from_ical(state.payload).walk("VEVENT")
    assert len(components) == 2
    assert "RRULE" in components[0] and "RECURRENCE-ID" in components[1]
    for component in components:
        assert component["ATTENDEE"][0].params["PARTSTAT"] == partstat
        assert component["ATTENDEE"][1].params["PARTSTAT"] == "TENTATIVE"
        assert int(component["SEQUENCE"]) == 5
    service.set_attendee_partstat(url, partstat)
    assert state.puts == 1
    assert state.calls[-1][0] == "GET"


@pytest.mark.parametrize("mode", ["timeout_committed", "500_committed"])
def test_lost_write_response_is_reconciled_without_duplicate_put(caldav_http, mode):
    service, state, url = caldav_http
    state.mode = mode
    service.set_attendee_partstat(url, "ACCEPTED")
    assert state.puts == 1
    assert state.calls[-1][0] == "GET"


def test_retry_lost_write_only_after_observing_unchanged_state(caldav_http):
    service, state, url = caldav_http
    state.mode = "timeout_no_commit"
    service.set_attendee_partstat(url, "ACCEPTED")
    assert [method for method, _ in state.calls] == ["GET", "PUT", "GET", "GET", "PUT", "GET"]
    assert state.puts == 2


def test_conflict_reloads_and_preserves_organizer_changes(caldav_http):
    service, state, url = caldav_http
    state.mode = "conflict_once"
    service.set_attendee_partstat(url, "ACCEPTED")
    assert [etag for method, etag in state.calls if method == "PUT"] == ['"1"', '"2"']
    assert b"SUMMARY:Changed by organizer" in state.payload


@pytest.mark.parametrize(
    "mode", ["ignore", "verify_unavailable", "bad_verify", "partial_series", "missing_exception"]
)
def test_unverified_write_is_never_reported_as_success(caldav_http, mode):
    service, state, url = caldav_http
    state.mode = mode
    with pytest.raises(CalDAVPartstatUnconfirmedError):
        service.set_attendee_partstat(url, "ACCEPTED")
    assert state.puts == 1


@pytest.mark.parametrize(
    "mode,puts", [("unauthorized", 1), ("conflict_always", 2), ("bad_initial", 0)]
)
def test_definite_failures_are_bounded(caldav_http, mode, puts):
    service, state, url = caldav_http
    state.mode = mode
    with pytest.raises(CalDAVError):
        service.set_attendee_partstat(url, "ACCEPTED")
    assert state.puts == puts


def test_provider_keeps_unconfirmed_error_distinct(caldav_http, monkeypatch):
    service, state, url = caldav_http
    state.mode = "verify_unavailable"
    provider = MailruCalendarProvider()
    monkeypatch.setattr(provider, "_service_for_invitations", lambda credentials: service)
    context = UserCalendarContext(
        1, "mailru", ProviderCredentials(LOGIN, "test-password"), url, (), LOGIN
    )
    with pytest.raises(CalendarProviderError) as raised:
        provider.set_attendee_partstat(context, CalendarEventRef("series", url), "ACCEPTED")
    assert raised.value.error_code == "PARTSTAT_UPDATE_UNCONFIRMED"


def test_refresh_keeps_exception_status_separate_from_master(caldav_http):
    from satellite.calendar.events import user_partstat

    service, state, url = caldav_http
    calendar = Calendar.from_ical(state.payload)
    calendar.walk("VEVENT")[0]["ATTENDEE"][0].params["PARTSTAT"] = "ACCEPTED"
    calendar.walk("VEVENT")[1]["ATTENDEE"][0].params["PARTSTAT"] = "DECLINED"
    calendar.walk("VEVENT")[1].add("status", "CANCELLED")
    state.payload = calendar.to_ical()
    refreshed = service._refresh_attendees_via_get(url)
    master = {
        "uid": "series",
        "dtstart": "2026-10-07T10:00:00+00:00",
        "attendees": [],
        "status": "CONFIRMED",
    }
    moved = {
        "uid": "series",
        "dtstart": "2026-09-30T15:00:00+00:00",
        "recurrence_id": "2026-09-30T13:00:00+03:00",
        "attendees": [],
        "status": "CONFIRMED",
    }
    service._apply_partstat_refresh_to_event(master, refreshed)
    service._apply_partstat_refresh_to_event(moved, refreshed)
    assert user_partstat(master, LOGIN) == "ACCEPTED"
    assert master["status"] == "CONFIRMED"
    assert user_partstat(moved, LOGIN) == "DECLINED"
    assert moved["status"] == "CANCELLED"


def test_parser_keeps_original_occurrence_identity_when_event_moves():
    from satellite.calendar.ical_parser import parse_calendar_events

    exception = parse_calendar_events(series_ics(), "")[1]
    assert exception["recurrence_id"] == "2026-09-30T10:00:00+00:00"


def test_missing_get_etag_does_not_overwrite_edit_before_head(caldav_http):
    service, state, url = caldav_http
    state.mode = "head_race"
    service.set_attendee_partstat(url, "ACCEPTED")
    assert state.puts == 1
    assert b"SUMMARY:Changed before HEAD" in state.payload


def test_no_version_information_prevents_unguarded_write(caldav_http):
    service, state, url = caldav_http
    state.mode = "no_etag"
    with pytest.raises(CalDAVError):
        service.set_attendee_partstat(url, "ACCEPTED")
    assert state.puts == 0
