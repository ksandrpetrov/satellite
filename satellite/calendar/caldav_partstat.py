"""Pure helpers for ATTENDEE/PARTSTAT mutation in ICS components."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .attendee_identity import attendee_matches_account


def attendee_matches_login_variants(attendee: Any, login_variants: Sequence[str]) -> bool:
    return any(attendee_matches_account(str(attendee), login) for login in login_variants)


def calendar_attendee_partstats(
    calendar: Any, login_variants: Sequence[str]
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Keep master and exception states separate when verifying a series response."""
    states = {}
    for component in calendar.walk("vevent"):
        raw = component.get("ATTENDEE")
        attendees = raw if isinstance(raw, list) else [raw] if raw is not None else []
        matching = [a for a in attendees if attendee_matches_login_variants(a, login_variants)]
        if not matching:
            continue
        recurrence = component.get("RECURRENCE-ID")
        recurrence_key = recurrence.to_ical().decode() if recurrence is not None else ""
        key = (str(component.get("UID") or ""), recurrence_key)
        if key in states:
            raise ValueError("Duplicate event component identity")
        states[key] = tuple(str(a.params.get("PARTSTAT", "")).upper() for a in matching)
    return states


def bump_vevent_dtstamp(component: Any) -> None:
    for prop in ("dtstamp", "DTSTAMP"):
        if prop in component:
            del component[prop]
    component.add("dtstamp", datetime.now(tz=UTC))


def bump_vevent_sequence(component: Any) -> None:
    seq = component.get("SEQUENCE")
    try:
        next_seq = int(seq) + 1 if seq is not None else 0
    except (TypeError, ValueError):
        next_seq = 1
    for prop in ("sequence", "SEQUENCE"):
        if prop in component:
            del component[prop]
    component.add("sequence", next_seq)


def update_vevent_attendee_partstat(
    component: Any, login_variants: Sequence[str], partstat: str
) -> bool:
    raw_attendees = component.get("ATTENDEE")
    if raw_attendees is None:
        return False
    items = raw_attendees if isinstance(raw_attendees, list) else [raw_attendees]
    updated = False
    for attendee in items:
        if not attendee_matches_login_variants(attendee, login_variants):
            continue
        attendee.params["PARTSTAT"] = partstat
        updated = True
    return updated
