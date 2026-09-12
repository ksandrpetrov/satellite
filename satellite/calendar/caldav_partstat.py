"""Pure helpers for ATTENDEE/PARTSTAT mutation in ICS components."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .attendee_identity import attendee_matches_account


def attendee_matches_login_variants(attendee: Any, login_variants: Sequence[str]) -> bool:
    return any(attendee_matches_account(str(attendee), login) for login in login_variants)


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
