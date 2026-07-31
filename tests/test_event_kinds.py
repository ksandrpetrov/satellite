"""Классификация системных vs рабочих событий."""

from __future__ import annotations

from datetime import UTC

from satellite.calendar.event_exclusions import EventExclusionPolicy, EventTitleOverride
from satellite.calendar.event_kinds import (
    classify_event_kind,
    filter_meetings_for_analytics,
    is_system_event_title,
)
from satellite.calendar.events import Event

TZ = UTC


def _ev(
    summary: str,
    *,
    start: str = "2026-05-12T10:00:00+00:00",
    end: str = "2026-05-12T11:00:00+00:00",
    attendees: list[str] | None = None,
    status: str | None = None,
) -> Event:
    payload: Event = {
        "summary": summary,
        "dtstart": start,
        "dtend": end,
    }
    if attendees is not None:
        payload["attendees"] = attendees
    if status is not None:
        payload["status"] = status
    return payload


def test_pizza_lunch_is_system():
    assert is_system_event_title("🍕 Обед")


def test_day_without_meetings_is_system():
    assert is_system_event_title("День без встреч")


def test_regular_meeting_is_not_system_title():
    assert not is_system_event_title("1:1 с Алексеем")


def test_cancelled_excluded():
    assert classify_event_kind(_ev("X", status="CANCELLED"), TZ, login="u@test") is None


def test_pending_excluded():
    ev = _ev(
        "Sync",
        attendees=["mailto:u@test;PARTSTAT=NEEDS-ACTION"],
    )
    assert classify_event_kind(ev, TZ, login="u@test") is None


def test_tentative_excluded():
    ev = _ev(
        "Sync",
        attendees=["mailto:u@test;PARTSTAT=TENTATIVE"],
    )
    assert classify_event_kind(ev, TZ, login="u@test") is None


def test_accepted_meeting_counted():
    ev = _ev(
        "Standup",
        attendees=["mailto:u@test;PARTSTAT=ACCEPTED"],
    )
    assert classify_event_kind(ev, TZ, login="u@test") == "meeting"


def test_filter_meetings_drops_system():
    events = [
        _ev("🍕 Обед", start="2026-05-12T13:00:00+00:00", end="2026-05-12T14:00:00+00:00"),
        _ev("Планирование"),
    ]
    out = filter_meetings_for_analytics(events, tz=TZ, login="u@test")
    assert len(out) == 1
    assert out[0]["summary"] == "Планирование"


def test_explicit_include_turns_builtin_system_title_into_meeting():
    event = _ev("Focus Time")
    policy = EventExclusionPolicy([EventTitleOverride("focus time", excluded=False)])

    assert (
        classify_event_kind(
            event,
            TZ,
            login="u@test",
            exclusion_policy=policy,
        )
        == "meeting"
    )


def test_disabled_meal_default_counts_meal_in_analytics():
    event = _ev("🍕 Обед")
    policy = EventExclusionPolicy(exclude_meals_by_default=False)

    assert (
        classify_event_kind(
            event,
            TZ,
            login="u@test",
            exclusion_policy=policy,
        )
        == "meeting"
    )


def test_explicit_exclusion_drops_regular_meeting_from_analytics():
    event = _ev("Weekly Sync")
    policy = EventExclusionPolicy([EventTitleOverride("weekly sync", excluded=True)])

    assert (
        classify_event_kind(
            event,
            TZ,
            login="u@test",
            exclusion_policy=policy,
        )
        is None
    )
