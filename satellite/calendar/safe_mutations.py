"""Conditional, verified writes. A recurring move changes exactly one occurrence."""

from __future__ import annotations

import copy
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import requests
from dateutil.rrule import rruleset, rrulestr
from icalendar import Calendar, Event

from .caldav_shared import CalDAVError, CalDAVPartstatUnconfirmedError
from .providers.base import CalendarEventRef, CalendarMutation, CalendarProviderError

if TYPE_CHECKING:
    from .caldav_client import CalDAVService


def _fail(code: str) -> CalendarProviderError:
    return CalendarProviderError(code, error_code=code)


def _dt(event: Any, key: str) -> datetime | None:
    value = getattr(event.get(key), "dt", None)
    return value if isinstance(value, datetime) and value.tzinfo else None


def _end(event: Any) -> datetime | None:
    end = _dt(event, "dtend")
    if end:
        return end
    duration = getattr(event.get("duration"), "dt", None)
    start = _dt(event, "dtstart")
    return start + duration if start and isinstance(duration, timedelta) else None


def _owned(event: Any, login: str) -> bool:
    organizer = str(event.get("organizer", "")).casefold().removeprefix("mailto:")
    return organizer == login.casefold() if organizer else not event.get("attendee")


def _occurs(master: Any, moment: datetime) -> bool:
    start = _dt(master, "dtstart")
    if start is None:
        return False
    rules = rruleset()
    rules.rdate(start)
    rule = master.get("rrule")
    if rule:
        rules.rrule(rrulestr(rule.to_ical().decode(), dtstart=start))
    for key, add in (("rdate", rules.rdate), ("exdate", rules.exdate)):
        values = master.get(key, [])
        for group in values if isinstance(values, list) else [values]:
            for item in group.dts:
                if not isinstance(item.dt, datetime) or not item.dt.tzinfo:
                    raise _fail("UNSUPPORTED_RECURRENCE")
                add(item.dt)
    return rules.before(moment, inc=True) == moment


def move_occurrence(calendar: Any, mutation: CalendarMutation, login: str) -> tuple[Any, bool]:
    """Return changed component and whether readback already matches the request."""
    ref, expected = mutation.event_ref, mutation.original_start
    if ref is None or expected is None or mutation.original_end is None:
        raise _fail("INVALID_EVENT_IDENTITY")
    events = calendar.walk("vevent")
    if not events or any(str(e.get("uid", "")) != ref.uid for e in events):
        raise _fail("EVENT_CHANGED")
    if any(e.get("recurrence-id") and e["recurrence-id"].params.get("RANGE") for e in events):
        raise _fail("UNSUPPORTED_RECURRENCE")
    masters = [e for e in events if not e.get("recurrence-id")]
    recurrence = mutation.recurrence_id or expected
    selected = [e for e in events if _dt(e, "recurrence-id") == recurrence]
    if len(selected) > 1 or len(masters) > 1:
        raise _fail("EVENT_CHANGED")
    master = masters[0] if masters else None
    needs_exception = (
        not selected and master is not None and bool(master.get("rrule") or master.get("rdate"))
    )
    component = selected[0] if selected else master
    if component is None or not _owned(component, login):
        raise _fail("NOT_ORGANIZER")
    if str(component.get("summary", "")) != mutation.payload.title:
        raise _fail("EVENT_CHANGED")
    start, end = _dt(component, "dtstart"), _end(component)
    if start is None or end is None:
        raise _fail("TIMED_EVENTS_ONLY")
    if not needs_exception and start == mutation.payload.start and end == mutation.payload.end:
        return component, True
    if needs_exception:
        assert master is not None
        if (
            not _occurs(master, recurrence)
            or expected != recurrence
            or end - start != mutation.original_end - expected
        ):
            raise _fail("EVENT_CHANGED")
        component = copy.deepcopy(master)
        for key in ("rrule", "rdate", "exdate", "recurrence-id"):
            component.pop(key, None)
        component.add("recurrence-id", recurrence.astimezone(UTC))
        calendar.add_component(component)
    elif start != expected or end != mutation.original_end:
        raise _fail("EVENT_CHANGED")
    sequence = int(component.get("sequence", 0))
    for key in ("dtstart", "dtend", "duration", "dtstamp", "sequence"):
        component.pop(key, None)
    component.add("dtstart", mutation.payload.start.astimezone(UTC))
    component.add("dtend", mutation.payload.end.astimezone(UTC))
    component.add("dtstamp", datetime.now(UTC))
    component.add("sequence", sequence + 1)
    return component, False


def _resource_is_in_calendar(resource: str, calendar_url: str) -> bool:
    parsed, parent = urlsplit(resource), urlsplit(calendar_url)
    return (parsed.scheme, parsed.netloc) == (
        parent.scheme,
        parent.netloc,
    ) and parsed.path.startswith(parent.path.rstrip("/") + "/")


def apply_mutation(
    service: CalDAVService,
    mutation: CalendarMutation,
    *,
    reconcile_only: bool,
    deadline: float | None = None,
) -> CalendarEventRef:
    def timeout() -> float:
        remaining = deadline - time.monotonic() if deadline is not None else 20.0
        if remaining <= 0:
            raise _fail("AI_DEADLINE")
        return min(service._partstat_update_timeout_sec, remaining)

    timeout()
    payload = mutation.payload
    if (
        not payload.start.tzinfo
        or not payload.end.tzinfo
        or payload.end <= payload.start
        or payload.end - payload.start > timedelta(days=1)
    ):
        raise _fail("INVALID_INTERVAL")
    if not re.fullmatch(r"[a-f0-9]{32,64}", mutation.operation_id):
        raise _fail("INVALID_OPERATION_ID")
    # Discovery verifies calendar scope before any authenticated request to a URL.
    handle = service._require_handle(mutation.calendar_url)
    if mutation.kind == "create":
        uid = f"satellite-ai-{mutation.operation_id}@satellite.local"
        url = f"{handle.url.rstrip('/')}/{uid}.ics"
        component = Event()
        for name, value in (
            ("uid", uid),
            ("summary", payload.title),
            ("dtstart", payload.start.astimezone(UTC)),
            ("dtend", payload.end.astimezone(UTC)),
            ("dtstamp", datetime.now(UTC)),
            ("organizer", f"mailto:{service._login}"),
        ):
            component.add(name, value)
        if payload.location:
            component.add("location", payload.location)
        if payload.description:
            component.add("description", payload.description)
        calendar = Calendar()
        calendar.add("version", "2.0")
        calendar.add("prodid", "-//Satellite AI//RU")
        calendar.add_component(component)
        if not reconcile_only:
            try:
                response = service._http_put(
                    url,
                    data=calendar.to_ical(),
                    auth=(service._auth_username(), service._app_password),
                    timeout=timeout(),
                    headers={"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
                )
                if response.status_code in (401, 403):
                    raise _fail("WRITE_FORBIDDEN")
                if response.status_code not in (200, 201, 204, 412) and response.status_code < 500:
                    raise _fail("CREATE_FAILED")
            except (requests.RequestException, OSError):
                pass  # GET determines the outcome; never replay the PUT.
        if not service._created_event_is_saved(url, component, timeout_sec=timeout()):
            raise _fail("WRITE_UNCONFIRMED")
        return CalendarEventRef(uid, url, mutation.connection_id)
    ref = mutation.event_ref
    if (
        mutation.kind != "reschedule"
        or ref is None
        or not ref.url
        or not _resource_is_in_calendar(ref.url, handle.url)
    ):
        raise _fail("INVALID_EVENT_IDENTITY")
    original, etag = service._get_event_ics_via_http(ref.url, timeout_sec=timeout())
    calendar = Calendar.from_ical(original)
    changed, already_saved = move_occurrence(calendar, mutation, service._login)
    if already_saved:
        return ref
    if reconcile_only:
        raise _fail("WRITE_UNCONFIRMED")
    if not etag:
        raise _fail("MISSING_ETAG")
    try:
        service._put_event_ics_via_http(
            ref.url, calendar.to_ical(), etag=etag, timeout_sec=timeout()
        )
    except (requests.RequestException, OSError, CalDAVPartstatUnconfirmedError):
        pass
    try:
        saved, _ = service._get_event_ics_via_http(ref.url, timeout_sec=timeout())
        verified = Calendar.from_ical(saved)
        saved_component, confirmed = move_occurrence(verified, mutation, service._login)
        # Readback must preserve all other components, including master and alarms.
        rid = _dt(changed, "recurrence-id")
        untouched = [e.to_ical() for e in calendar.walk("vevent") if e is not changed]
        observed = [e.to_ical() for e in verified.walk("vevent") if _dt(e, "recurrence-id") != rid]
        critical = ("description", "attendee", "location", "organizer")
        properties_preserved = all(
            str(saved_component.get(k, "")) == str(changed.get(k, "")) for k in critical
        )
        alarms_preserved = [a.to_ical() for a in changed.walk("valarm")] == [
            a.to_ical() for a in saved_component.walk("valarm")
        ]
        if (
            not confirmed
            or sorted(untouched) != sorted(observed)
            or not properties_preserved
            or not alarms_preserved
        ):
            raise _fail("WRITE_UNCONFIRMED")
    except (CalDAVError, ValueError, requests.RequestException, OSError) as exc:
        raise _fail("WRITE_UNCONFIRMED") from exc
    finally:
        service._invalidate_partstat_cache()
    return ref
