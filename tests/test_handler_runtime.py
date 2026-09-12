"""Runtime state belongs to an application, not imported handler modules."""

from __future__ import annotations

from datetime import UTC, datetime

from satellite.calendar.callback_tokens import event_callback_token
from satellite.telegram_bot.handlers.runtime import HandlerRuntime, UserCache


def test_runtime_isolation_and_shared_context_state() -> None:
    first, second = HandlerRuntime(), HandlerRuntime()
    assert first.plan.try_acquire(1, "plan:today")
    assert not first.plan.try_acquire(1, "plan:today")
    assert second.plan.try_acquire(1, "plan:today")
    first.hub_messages[1] = 50
    assert second.hub_messages == {}
    event = {"url": "https://cal/1.ics", "uid": "one"}
    first.event_tokens.register_manage_screen(
        1, events=[event], login="user@example.com", moment=datetime.now(UTC), truncated=False
    )
    token = event_callback_token(event["url"])
    assert first.event_tokens.lookup(1, token).uid == "one"
    assert second.event_tokens.lookup(1, token) is None


def test_cache_ttl_does_not_slide_on_read(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr("satellite.telegram_bot.handlers.runtime.time.monotonic", lambda: now[0])
    cache = UserCache[str](60.0)
    cache.put(1, "first")
    now[0] = 59.0
    assert cache.get(1) == "first"
    now[0] = 60.0
    assert cache.get(1) is None
    cache.put(1, "replacement")
    assert cache.get(1) == "replacement"
    cache.clear(1)
    assert cache.get(1) is None


def test_bounded_cache_evicts_least_recently_used_user() -> None:
    cache = UserCache[str](60.0, max_users=2)
    cache.put(1, "one")
    cache.put(2, "two")
    assert cache.get(1) == "one"
    cache.put(3, "three")
    assert cache.get(2) is None
    assert cache.get(1) == "one"
    assert cache.get(3) == "three"
