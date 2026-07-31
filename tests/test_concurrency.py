"""Юнит-тесты на потокобезопасные примитивы из telegram_bot/concurrency.py."""

from __future__ import annotations

import threading

import pytest

from satellite.telegram_bot.concurrency import ChatLockManager


class _InflightTracker:
    """Legacy dedup helper — kept only to document prior behaviour in tests."""

    def __init__(self) -> None:
        self._items: set[int] = set()
        self._lock = threading.Lock()

    def add_if_absent(self, chat_id: int | None) -> bool:
        if chat_id is None:
            return True
        with self._lock:
            if chat_id in self._items:
                return False
            self._items.add(chat_id)
            return True

    def discard(self, chat_id: int | None) -> None:
        if chat_id is None:
            return
        with self._lock:
            self._items.discard(chat_id)


def test_chat_lock_manager_returns_same_lock_for_same_chat():
    mgr = ChatLockManager()
    a = mgr.acquire(42)
    b = mgr.acquire(42)
    assert a is b


def test_chat_lock_manager_returns_distinct_locks_per_chat():
    mgr = ChatLockManager()
    a = mgr.acquire(1)
    b = mgr.acquire(2)
    assert a is not b


def test_chat_lock_manager_handles_none_chat_with_throwaway_lock():
    mgr = ChatLockManager()
    a = mgr.acquire(None)
    b = mgr.acquire(None)
    assert isinstance(a, type(threading.Lock()))
    assert a is not b


def test_chat_lock_manager_is_threadsafe():
    mgr = ChatLockManager()
    locks_per_thread: list[object] = []
    lock_for_lock = threading.Lock()

    def worker():
        lk = mgr.acquire(7)
        with lock_for_lock:
            locks_per_thread.append(lk)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(lk) for lk in locks_per_thread}) == 1


def test_chat_lock_manager_uses_bounded_stripes():
    mgr = ChatLockManager(stripes=4)

    for chat_id in range(10_000):
        mgr.acquire(chat_id)

    assert len(mgr._locks) == 4
    assert mgr.acquire(1) is mgr.acquire(5)


def test_chat_lock_manager_rejects_non_positive_stripes():
    with pytest.raises(ValueError, match="positive"):
        ChatLockManager(stripes=0)


def test_inflight_tracker_add_if_absent_returns_true_first_time():
    tracker = _InflightTracker()
    assert tracker.add_if_absent(1) is True
    assert tracker.add_if_absent(1) is False
    tracker.discard(1)
    assert tracker.add_if_absent(1) is True


def test_inflight_tracker_handles_none_as_always_admit():
    tracker = _InflightTracker()
    assert tracker.add_if_absent(None) is True
    assert tracker.add_if_absent(None) is True


def test_inflight_tracker_discard_noop_for_missing():
    tracker = _InflightTracker()
    tracker.discard(99)
    tracker.discard(None)
    assert tracker.add_if_absent(99) is True
