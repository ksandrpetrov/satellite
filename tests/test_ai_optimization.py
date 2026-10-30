"""All proposed intervals and benefits are computed, including conservative busy time."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from satellite.assistant.optimization import (
    Preferences,
    active_events,
    build_optimization,
    event_id,
    free_slots,
    metrics,
)

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 2, 9, tzinfo=TZ)
START, END = NOW.date(), NOW.date() + timedelta(days=7)


def event(uid, hour, minutes=60, day=0, **extra):
    start = NOW.replace(hour=hour) + timedelta(days=day)
    return {
        "uid": uid,
        "url": f"https://cal/own/{uid}.ics",
        "summary": uid,
        "dtstart": start.isoformat(),
        "dtend": (start + timedelta(minutes=minutes)).isoformat(),
        "organizer": "mailto:me@example.com",
        **extra,
    }


def test_optimization_candidates_are_free_and_benefits_recompute():
    events = [event("a", 10), event("b", 10), event("c", 11), event("late", 20)]
    preferences = Preferences()
    report = build_optimization(
        events,
        start=START,
        end=END,
        tz=TZ,
        login="me@example.com",
        preferences=preferences,
        now=NOW,
    )
    assert report.metrics["overlaps"] == 1
    assert report.metrics["outside_minutes"] == 60
    assert 1 <= len(report.candidates) <= 5
    for candidate in report.candidates:
        if candidate["kind"] != "reschedule":
            continue
        others = [e for e in events if event_id(e) != candidate["event_id"]]
        moved = next(e for e in events if event_id(e) == candidate["event_id"])
        moved = dict(moved, dtstart=candidate["start"], dtend=candidate["end"])
        actual = metrics([*others, moved], START, END, TZ, "me@example.com", preferences, NOW)
        assert actual == candidate["after"]
        assert candidate["before"] == report.metrics
        start, end = (
            datetime.fromisoformat(candidate["start"]),
            datetime.fromisoformat(candidate["end"]),
        )
        assert any(
            a <= start and b >= end
            for a, b in free_slots(
                others, START, END, TZ, "me@example.com", preferences, 1, now=NOW
            )
        )


def test_pending_all_day_and_analytics_exclusions_never_free_busy_time():
    events = [
        event("excluded", 10, excluded=True),
        event("pending", 11, attendees=["mailto:me@example.com;PARTSTAT=NEEDS-ACTION"]),
        {"uid": "all", "dtstart": "2026-11-03", "dtend": "2026-11-04"},
    ]
    slots = free_slots(events, START, END, TZ, "me@example.com", Preferences(), 30, now=NOW)
    assert not any(a.date().isoformat() == "2026-11-03" for a, _ in slots)
    assert not any(a.date() == START and a.hour < 12 for a, _ in slots)
    assert not any(a.hour < 14 and b.hour > 13 for a, b in slots)


def test_cancelled_declined_duplicates_and_invalid_times():
    events = [
        event("a", 10),
        event("a", 10),
        event("b", 11, status="CANCELLED"),
        event("c", 12, attendees=["mailto:me@example.com;PARTSTAT=DECLINED"]),
    ]
    assert len(active_events(events, TZ, "me@example.com")) == 1
    with pytest.raises(ValueError):
        active_events([{"uid": "bad", "dtstart": "unparseable"}], TZ, "me@example.com")


def test_advice_does_not_offer_moves_for_other_organizers_and_explains_unverified():
    events = [
        event("a", 10, organizer="mailto:other@example.com"),
        event("b", 10, _partstat_unverified=True),
    ]
    report = build_optimization(
        events,
        start=START,
        end=END,
        tz=TZ,
        login="me@example.com",
        preferences=Preferences(),
        now=NOW,
    )
    assert all(c["kind"] != "reschedule" for c in report.candidates)
    assert "some_invitation_statuses_unverified_time_remains_blocked" in report.limitations


def test_free_slots_exclude_past_and_midnight_overlap():
    events = [
        dict(
            event("night", 10),
            dtstart="2026-11-01T23:30:00+03:00",
            dtend="2026-11-02T10:30:00+03:00",
        )
    ]
    slots = free_slots(
        events,
        START,
        START + timedelta(days=1),
        TZ,
        "me@example.com",
        Preferences(),
        30,
        now=NOW.replace(hour=11),
    )
    assert all(a >= NOW.replace(hour=11) for a, _ in slots)
    assert slots[0][0].hour == 11
