"""Only the connected account may receive invitation status changes."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from icalendar import Calendar, Event

from satellite.calendar.caldav_client import CalDAVError, CalDAVService
from satellite.calendar.event_token_cache import apply_user_partstat_to_event
from satellite.calendar.events import is_pending_invitation_for_user, user_partstat
from satellite.calendar.providers.base import CalendarEventRef
from satellite.calendar.providers.mailru import MailruCalendarProvider
from satellite.security.token_vault import ProviderCredentials

from .test_mailru_create import _context


@pytest.mark.parametrize("address", ["other@example.com", "ann@other.com", "joann@example.com"])
def test_name_and_partial_address_never_match_account(address):
    event = {"attendees": [f"mailto:{address};CN=ann@example.com;PARTSTAT=NEEDS-ACTION"]}
    assert not is_pending_invitation_for_user(event, "ann@example.com")
    assert user_partstat(event, "ann@example.com") is None
    assert apply_user_partstat_to_event(event, "ann@example.com", "ACCEPTED") == event


@pytest.mark.parametrize("login", ["ann@example.com", " ANN@EXAMPLE.COM "])
def test_exact_account_match_accepts_case_and_whitespace(login):
    assert is_pending_invitation_for_user(
        {"attendees": ["mailto:ann@example.com;PARTSTAT=NEEDS-ACTION"]}, login
    )


def test_two_accounts_update_only_their_own_attendee_and_clear_invitation_cache(monkeypatch):
    provider = MailruCalendarProvider()
    contexts = [
        replace(
            _context(), user_id=i, login=login, credentials=ProviderCredentials(login, f"pw{i}")
        )
        for i, login in enumerate(["ann@example.com", "bob@example.com"], 1)
    ]
    calendar = Calendar()
    event = Event()
    event.add("uid", "meeting")
    for context in contexts:
        event.add("attendee", f"mailto:{context.login}", parameters={"PARTSTAT": "NEEDS-ACTION"})
    calendar.add_component(event)
    stored = {context.login: calendar.to_ical() for context in contexts}
    url = "https://cal/meeting.ics"
    for context in contexts:
        service = provider._service_for_invitations(context.credentials)
        service._partstat_cache[url] = (["stale"], None)
        monkeypatch.setattr(
            service,
            "_get_event_ics_via_http",
            lambda _, login=context.login: (stored[login], '"etag"'),
        )

        def put(_, payload, *, etag, login=context.login):
            assert etag == '"etag"'
            stored[login] = payload

        monkeypatch.setattr(service, "_put_event_ics_via_http", put)
        monkeypatch.setattr(
            provider._service(context.credentials),
            "set_attendee_partstat",
            MagicMock(side_effect=AssertionError("wrong client")),
        )
    for context in contexts:
        before_other = stored[next(c.login for c in contexts if c != context)]
        provider.set_attendee_partstat(context, CalendarEventRef("meeting", url), "ACCEPTED")
        statuses = {
            str(a): str(a.params["PARTSTAT"])
            for a in Calendar.from_ical(stored[context.login]).walk("VEVENT")[0].get("ATTENDEE")
        }
        assert statuses[f"mailto:{context.login}"] == "ACCEPTED"
        other = next(c for c in contexts if c != context)
        assert statuses[f"mailto:{other.login}"] == "NEEDS-ACTION"
        assert stored[other.login] == before_other
        assert url not in provider._service_for_invitations(context.credentials)._partstat_cache
    provider.close()


def test_write_does_not_match_connected_address_in_cn(monkeypatch):
    service = CalDAVService(caldav_url="https://cal/", login="ann@example.com", app_password="pw")
    calendar = Calendar()
    event = Event()
    event.add("uid", "meeting")
    event.add(
        "attendee",
        "mailto:other@example.com",
        parameters={"CN": "ann@example.com", "PARTSTAT": "NEEDS-ACTION"},
    )
    calendar.add_component(event)
    monkeypatch.setattr(
        service, "_get_event_ics_via_http", MagicMock(return_value=(calendar.to_ical(), None))
    )
    put = MagicMock()
    monkeypatch.setattr(service, "_put_event_ics_via_http", put)
    with pytest.raises(CalDAVError, match="not an attendee"):
        service.set_attendee_partstat("https://cal/meeting.ics", "ACCEPTED")
    put.assert_not_called()
    service.close()
