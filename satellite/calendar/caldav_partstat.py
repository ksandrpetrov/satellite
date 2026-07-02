"""Pure helpers for ATTENDEE/PARTSTAT mutation in ICS components."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .ical_parser import _attendee_to_str


def attendee_matches_login_variants(attendee: Any, login_variants: Sequence[str]) -> bool:
    blob = _attendee_to_str(attendee).casefold()
    if not blob:
        return False
    for variant in login_variants:
        needle = (variant or "").strip().casefold()
        if needle and needle in blob:
            return True
    return False


def bump_vevent_dtstamp(component: Any) -> None:
    for prop in ("dtstamp", "DTSTAMP"):
        if prop in component:
            del component[prop]
    component.add("dtstamp", datetime.now(tz=timezone.utc))


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


def update_vevent_pending_attendee_partstat(component: Any, partstat: str) -> bool:
    raw_attendees = component.get("ATTENDEE")
    if raw_attendees is None:
        return False
    items = raw_attendees if isinstance(raw_attendees, list) else [raw_attendees]
    for attendee in items:
        blob = _attendee_to_str(attendee).casefold()
        if "partstat=needs-action" in blob or "partstat=delegated" in blob:
            attendee.params["PARTSTAT"] = partstat
            return True
    return False


def add_vevent_attendee(component: Any, login: str, partstat: str) -> None:
    mailto = (login or "").strip()
    if not mailto:
        raise ValueError("Login is required to add ATTENDEE")
    component.add(
        "attendee",
        f"mailto:{mailto}",
        parameters={
            "PARTSTAT": partstat,
            "RSVP": "TRUE",
            "ROLE": "REQ-PARTICIPANT",
        },
    )
