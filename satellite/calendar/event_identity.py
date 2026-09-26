"""Shared occurrence identity for daily plans and period analytics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, tzinfo

from .events import Event, is_cancelled_event, parse_iso, user_partstat


def _stable_time_key(value: object, tz: tzinfo) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return str(value or "")
    if isinstance(parsed, datetime):
        localized = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
        return localized.isoformat()
    return parsed.isoformat()


def event_occurrence_key(event: Event, tz: tzinfo) -> tuple[str, ...] | None:
    """Cross-calendar identity for one expanded occurrence.

    A recurring series deliberately keeps separate occurrences because DTSTART
    and DTEND are part of the key. Missing UID is not guessed from title/time:
    collapsing unrelated meetings would be worse than retaining a duplicate.
    """
    uid = str(event.get("uid") or "").strip()
    if not uid:
        return None
    return (
        uid,
        _stable_time_key(event.get("dtstart"), tz),
        _stable_time_key(event.get("dtend"), tz),
    )


def _duplicate_information_score(event: Event, login: str | None) -> tuple[int, int, int, int]:
    status = user_partstat(event, login or "") if login else None
    status_priority = {
        "DECLINED": 5,
        "NEEDS-ACTION": 4,
        "DELEGATED": 4,
        "TENTATIVE": 3,
        "ACCEPTED": 2,
    }.get(status or "", 0)
    attendees = event.get("attendees") or []
    return (
        int(is_cancelled_event(event)),
        status_priority,
        len(attendees),
        int(bool(event.get("status"))),
    )


def deduplicate_event_occurrences(
    events: Sequence[Event], tz: tzinfo, *, login: str | None = None
) -> tuple[list[Event], int]:
    positions: dict[tuple[str, ...], int] = {}
    unique: list[Event] = []
    dropped = 0
    for event in events:
        key = event_occurrence_key(event, tz)
        if key is not None and key in positions:
            dropped += 1
            index = positions[key]
            if _duplicate_information_score(event, login) > _duplicate_information_score(
                unique[index], login
            ):
                unique[index] = event
            continue
        if key is not None:
            positions[key] = len(unique)
        unique.append(event)
    return unique, dropped
