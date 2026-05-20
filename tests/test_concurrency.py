"""Юнит-тесты на потокобезопасные примитивы из telegram_bot/concurrency.py."""

from __future__ import annotations

import threading

from satellite.telegram_bot.concurrency import ChatLockManager, InflightTracker


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


def test_inflight_tracker_add_if_absent_returns_true_first_time():
    tracker = InflightTracker()
    assert tracker.add_if_absent(1) is True
    assert tracker.add_if_absent(1) is False
    tracker.discard(1)
    assert tracker.add_if_absent(1) is True


def test_inflight_tracker_handles_none_as_always_admit():
    tracker = InflightTracker()
    # None — это «нет чата»; обработка не должна сериализоваться, всегда True.
    assert tracker.add_if_absent(None) is True
    assert tracker.add_if_absent(None) is True


def test_inflight_tracker_discard_noop_for_missing():
    tracker = InflightTracker()
    tracker.discard(99)  # не должно крашиться
    tracker.discard(None)
    assert tracker.add_if_absent(99) is True
