"""Unit-тесты in-memory кэша token→URL для PARTSTAT respond."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from satellite.calendar.callback_tokens import event_callback_token
from satellite.calendar.event_token_cache import (
    EventTokenCache,
    apply_user_partstat_to_event,
    reset_event_token_cache,
)

TZ = ZoneInfo("Europe/Moscow")
LOGIN = "me@mail.ru"
USER_ID = 42


def _ev(*, url: str = "https://cal/e/1.ics", partstat: str = "NEEDS-ACTION") -> dict:
    return {
        "uid": "uid-1",
        "url": url,
        "summary": "Meet",
        "dtstart": "2026-05-22T14:00:00+03:00",
        "dtend": "2026-05-22T15:00:00+03:00",
        "attendees": [f"mailto:{LOGIN};PARTSTAT={partstat}"],
    }


def setup_function() -> None:
    reset_event_token_cache()


def test_register_and_lookup_invitations_token() -> None:
    cache = EventTokenCache()
    ev = _ev()
    token = event_callback_token(ev["url"])
    moment = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    cache.register_invitations_screen(
        USER_ID,
        pending=[ev],
        all_events=[ev],
        login=LOGIN,
        moment=moment,
        truncated=False,
    )
    ref = cache.lookup(USER_ID, token)
    assert ref is not None
    assert ref.url == ev["url"]
    assert ref.uid == "uid-1"


def test_lookup_miss_returns_none() -> None:
    cache = EventTokenCache()
    assert cache.lookup(USER_ID, "missing") is None


def test_remove_invitations_pending_updates_snapshot() -> None:
    cache = EventTokenCache()
    ev1 = _ev(url="https://cal/e/1.ics")
    ev2 = _ev(url="https://cal/e/2.ics")
    token1 = event_callback_token(ev1["url"])
    moment = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    cache.register_invitations_screen(
        USER_ID,
        pending=[ev1, ev2],
        all_events=[ev1, ev2],
        login=LOGIN,
        moment=moment,
        truncated=False,
    )
    snapshot = cache.remove_invitations_pending(USER_ID, token1)
    assert snapshot is not None
    assert len(snapshot.pending) == 1
    assert snapshot.pending[0]["url"] == ev2["url"]


def test_update_manage_partstat_changes_attendee() -> None:
    cache = EventTokenCache()
    ev = _ev(partstat="TENTATIVE")
    token = event_callback_token(ev["url"])
    moment = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    cache.register_manage_screen(
        USER_ID,
        events=[ev],
        login=LOGIN,
        moment=moment,
        truncated=False,
    )
    snapshot = cache.update_manage_partstat(USER_ID, token, LOGIN, "ACCEPTED")
    assert snapshot is not None
    assert "PARTSTAT=ACCEPTED" in snapshot.events[0]["attendees"][0]


def test_apply_user_partstat_to_event_updates_matching_login() -> None:
    ev = _ev(partstat="NEEDS-ACTION")
    updated = apply_user_partstat_to_event(ev, LOGIN, "DECLINED")
    assert "PARTSTAT=DECLINED" in updated["attendees"][0]
    assert "PARTSTAT=NEEDS-ACTION" in ev["attendees"][0]


def test_token_expires_after_ttl() -> None:
    cache = EventTokenCache(ttl_sec=0.0)
    ev = _ev()
    token = event_callback_token(ev["url"])
    moment = datetime(2026, 5, 22, 10, 0, tzinfo=TZ)
    cache.register_invitations_screen(
        USER_ID,
        pending=[ev],
        all_events=[ev],
        login=LOGIN,
        moment=moment,
        truncated=False,
    )
    assert cache.lookup(USER_ID, token) is None
