"""Reproducible schedule metrics and independently simulated recommendations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..calendar.availability import find_free_slots
from ..calendar.event_identity import deduplicate_event_occurrences
from ..calendar.events import (
    Event,
    event_datetime_bounds,
    is_all_day_event,
    is_cancelled_event,
    is_declined_event_for_user,
)
from ..calendar.stats import WorkdayOptions, normalize_caldav_event
from ..calendar.time_utils import count_overlap_pairs, merge_intervals, sum_minutes


@dataclass(frozen=True)
class Preferences:
    workday: WorkdayOptions = WorkdayOptions()
    focus_minutes: int = 90
    break_minutes: int = 10

    def __post_init__(self) -> None:
        if not 15 <= self.focus_minutes <= 240 or not 0 <= self.break_minutes <= 60:
            raise ValueError("Invalid optimization preferences")


@dataclass(frozen=True)
class OptimizationReport:
    from_date: str
    to_date: str
    timezone: str
    preferences: dict[str, Any]
    metrics: dict[str, Any]
    candidates: list[dict[str, Any]]
    limitations: tuple[str, ...]


def event_id(event: Event) -> str:
    identity = "|".join(str(event.get(k) or "") for k in ("uid", "url", "recurrence_id", "dtstart"))
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def owned(event: Event, login: str) -> bool:
    organizer = str(event.get("organizer") or "").casefold().removeprefix("mailto:")
    return organizer == login.casefold() if organizer else not event.get("attendees")


def active_events(events: Sequence[Event], tz: ZoneInfo, login: str) -> list[Event]:
    result = [
        e for e in events if not is_cancelled_event(e) and not is_declined_event_for_user(e, login)
    ]
    for event in result:
        start, end = event_datetime_bounds(event, tz)
        if not start or not end or end <= start:
            raise ValueError("Incomplete calendar times")
    return deduplicate_event_occurrences(result, tz, login=login)[0]


def free_slots(
    events: Sequence[Event],
    start: date,
    end: date,
    tz: ZoneInfo,
    login: str,
    preferences: Preferences,
    duration: int,
    *,
    now: datetime,
) -> list[tuple[datetime, datetime]]:
    # Availability always uses every selected calendar, including analytics exclusions,
    # pending invitations and all-day blocks. Lunch and transition buffers are busy too.
    blocked: list[Event] = list(events)
    for event in events:
        begin, finish = event_datetime_bounds(event, tz)
        if (
            begin
            and finish
            and not is_all_day_event(event, tz)
            and not is_cancelled_event(event)
            and not is_declined_event_for_user(event, login)
        ):
            blocked.append(
                {
                    "dtstart": (begin - timedelta(minutes=preferences.break_minutes)).isoformat(),
                    "dtend": (finish + timedelta(minutes=preferences.break_minutes)).isoformat(),
                }
            )
    options = preferences.workday.to_minutes()
    day = start
    while day < end:
        midnight = datetime.combine(day, time.min, tzinfo=tz)
        if options.lunch_end > options.lunch_start:
            blocked.append(
                {
                    "dtstart": (midnight + timedelta(minutes=options.lunch_start)).isoformat(),
                    "dtend": (midnight + timedelta(minutes=options.lunch_end)).isoformat(),
                }
            )
        day += timedelta(days=1)
    slots = find_free_slots(
        blocked,
        start_date=start,
        end_date=end,
        tz=tz,
        login=login,
        duration_minutes=duration,
        work_start=preferences.workday.workday_start,
        work_end=preferences.workday.workday_end,
    )
    return [
        (max(begin, now), finish)
        for begin, finish in slots
        if (start == end - timedelta(days=1) or begin.weekday() < 5)
        and (finish.astimezone(UTC) - max(begin, now).astimezone(UTC)).total_seconds()
        >= duration * 60
    ]


def metrics(
    events: Sequence[Event],
    start: date,
    end: date,
    tz: ZoneInfo,
    login: str,
    preferences: Preferences,
    now: datetime,
) -> dict[str, Any]:
    options = preferences.workday.to_minutes()
    days: list[dict[str, Any]] = []
    day = start
    slots = free_slots(
        events, start, end, tz, login, preferences, preferences.focus_minutes, now=now
    )
    while day < end:
        normalized = [n for e in events if (n := normalize_caldav_event(e, day, tz, login=login))]
        intervals = [n.interval for n in normalized]
        inside = [
            (max(a, options.workday_start), min(b, options.workday_end))
            for a, b in intervals
            if min(b, options.workday_end) > max(a, options.workday_start)
        ]
        busy = sum_minutes(merge_intervals(inside))
        outside = sum_minutes(merge_intervals(intervals)) - busy
        short_gaps = sum(
            0 <= b[0] - a[1] < preferences.break_minutes
            for a, b in zip(sorted(intervals), sorted(intervals)[1:], strict=False)
        )
        days.append(
            {
                "date": day.isoformat(),
                "busy_minutes": busy,
                "overlaps": count_overlap_pairs(intervals),
                "outside_minutes": outside,
                "short_breaks": short_gaps,
                "focus_windows": sum(begin.date() == day for begin, _ in slots),
            }
        )
        day += timedelta(days=1)
    loads = [d["busy_minutes"] for d in days if date.fromisoformat(d["date"]).weekday() < 5]
    return {
        "days": days,
        "overlaps": sum(d["overlaps"] for d in days),
        "outside_minutes": sum(d["outside_minutes"] for d in days),
        "short_breaks": sum(d["short_breaks"] for d in days),
        "focus_windows": len(slots),
        "load_spread_minutes": max(loads) - min(loads) if loads else 0,
    }


def _score(m: dict[str, Any]) -> int:
    return (
        m["overlaps"] * 10_000
        + m["outside_minutes"] * 20
        + m["short_breaks"] * 100
        + m["load_spread_minutes"]
        - m["focus_windows"] * 30
    )


def build_optimization(
    events: Sequence[Event],
    *,
    start: date,
    end: date,
    tz: ZoneInfo,
    login: str,
    preferences: Preferences,
    now: datetime,
    check_deadline: Callable[[], object] | None = None,
) -> OptimizationReport:
    if not 1 <= (end - start).days <= 31 or len(events) > 1000:
        raise ValueError("Optimization range too large")
    active = active_events(events, tz, login)
    before = metrics(active, start, end, tz, login, preferences, now)
    candidates: list[dict[str, Any]] = []
    # Evaluate each proposal independently; do not imply several individually free
    # alternatives can be applied together without another fresh calendar read.
    for event in active[:200]:
        if check_deadline:
            check_deadline()
        begin, finish = event_datetime_bounds(event, tz)
        if (
            not begin
            or not finish
            or begin < now
            or is_all_day_event(event, tz)
            or event.get("_partstat_unverified")
            or not owned(event, login)
        ):
            continue
        duration = int((finish.astimezone(UTC) - begin.astimezone(UTC)).total_seconds() // 60)
        if not 1 <= duration <= 480:
            continue
        others = [e for e in active if event_id(e) != event_id(event)]
        alternatives = free_slots(others, start, end, tz, login, preferences, duration, now=now)
        best: dict[str, Any] | None = None
        for proposed, _ in alternatives[:20]:
            if check_deadline:
                check_deadline()
            if proposed == begin:
                continue
            proposed_end = proposed + timedelta(minutes=duration)
            moved = dict(event, dtstart=proposed.isoformat(), dtend=proposed_end.isoformat())
            after = metrics([*others, moved], start, end, tz, login, preferences, now)
            benefit = _score(before) - _score(after)
            # Never trade a new conflict or an outside-work interval for a cosmetic gain.
            if (
                benefit <= 0
                or after["overlaps"] > before["overlaps"]
                or after["outside_minutes"] > before["outside_minutes"]
            ):
                continue
            candidate: dict[str, Any] = {
                "kind": "reschedule",
                "event_id": event_id(event),
                "title": str(event.get("summary") or ""),
                "original_start": begin.isoformat(),
                "start": proposed.isoformat(),
                "end": proposed_end.isoformat(),
                "before": before,
                "after": after,
                "benefit": benefit,
            }
            if best is None or benefit > best["benefit"]:
                best = candidate
        if best:
            candidates.append(best)
    candidates.sort(key=lambda c: (-c["benefit"], c["start"]))
    candidates = candidates[:5]
    if len(candidates) < 5:
        windows = free_slots(
            active, start, end, tz, login, preferences, preferences.focus_minutes, now=now
        )
        if windows:
            begin, _ = windows[0]
            candidates.append(
                {
                    "kind": "focus",
                    "start": begin.isoformat(),
                    "end": (begin + timedelta(minutes=preferences.focus_minutes)).isoformat(),
                    "before": {"reserved_focus_minutes": 0},
                    "after": {"reserved_focus_minutes": preferences.focus_minutes},
                }
            )
    for i, candidate in enumerate(candidates, 1):
        candidate["option"] = i
    limitations = ["other_participants_availability_unknown", "suggestions_are_independent"]
    if any(e.get("_partstat_unverified") for e in events):
        limitations.append("some_invitation_statuses_unverified_time_remains_blocked")
    if len(active) > 200:
        limitations.append("all_events_counted_only_first_200_checked_for_moves")
    return OptimizationReport(
        start.isoformat(),
        end.isoformat(),
        str(tz),
        asdict(preferences),
        before,
        candidates,
        tuple(limitations),
    )
