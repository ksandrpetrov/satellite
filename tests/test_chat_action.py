"""Юнит-тесты ``run_with_typing_action`` (typing + долгая синхронная операция)."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from satellite.telegram_bot.chat_action import run_with_typing_action


def _typing_worker_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "satellite-typing-action"]


def test_returns_fn_result() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    out = run_with_typing_action(
        telegram,
        1,
        lambda: "digest",
        interval_seconds=10.0,
    )

    assert out == "digest"


def test_send_chat_action_called_immediately() -> None:
    telegram = MagicMock()
    events: list[str] = []

    def fn() -> str:
        events.append("fn")
        return "ok"

    telegram.send_chat_action = MagicMock(
        side_effect=lambda *_a, **_k: events.append("typing") or True
    )

    run_with_typing_action(
        telegram,
        42,
        fn,
        interval_seconds=60.0,
    )

    assert events[0] == "typing"
    assert events[1] == "fn"


def test_repeated_send_for_long_fn() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    def slow() -> int:
        time.sleep(0.18)
        return 7

    run_with_typing_action(
        telegram,
        9,
        slow,
        interval_seconds=0.05,
    )

    assert telegram.send_chat_action.call_count >= 3


def test_send_chat_action_failure_does_not_break_fn() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(side_effect=RuntimeError("network"))

    assert (
        run_with_typing_action(
            telegram,
            1,
            lambda: 123,
            interval_seconds=0.02,
        )
        == 123
    )
    assert telegram.send_chat_action.call_count >= 1


def test_fn_exception_propagates() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    def boom() -> None:
        raise ValueError("plan failed")

    with pytest.raises(ValueError, match="plan failed"):
        run_with_typing_action(
            telegram,
            1,
            boom,
            interval_seconds=0.05,
        )


def test_background_thread_stopped_after_fn() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    run_with_typing_action(
        telegram,
        1,
        lambda: None,
        interval_seconds=0.05,
    )

    time.sleep(0.06)
    assert not _typing_worker_threads()


def test_no_stale_typing_thread_after_slow_fn() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    def work() -> str:
        time.sleep(0.12)
        return "done"

    run_with_typing_action(
        telegram,
        3,
        work,
        interval_seconds=0.04,
    )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _typing_worker_threads():
        time.sleep(0.01)
    assert not _typing_worker_threads()


def test_returns_immediately_after_fn() -> None:
    """После fn() не должно быть никаких искусственных sleep — результат сразу."""
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    started = time.monotonic()
    run_with_typing_action(
        telegram,
        7,
        lambda: "done",
        interval_seconds=10.0,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.2, f"expected no artificial wait, got {elapsed:.3f}s"


def test_no_typing_sent_after_stop_signal() -> None:
    """После fn() поток-обновлятор не должен успеть выстрелить ещё одним typing."""
    telegram = MagicMock()
    call_times: list[float] = []

    def record_typing(*_args, **_kwargs):
        call_times.append(time.monotonic())
        return True

    telegram.send_chat_action = MagicMock(side_effect=record_typing)

    def slow() -> str:
        time.sleep(0.12)
        return "done"

    stop_observed_at = [0.0]

    def fn() -> str:
        result = slow()
        stop_observed_at[0] = time.monotonic()
        return result

    run_with_typing_action(
        telegram,
        9,
        fn,
        interval_seconds=0.05,
    )

    # Любой typing, отправленный после возврата fn(), означает, что индикатор
    # «печатает» переживёт итоговое сообщение дольше естественных ~5 с — этого
    # допускать нельзя.
    after_fn = [t for t in call_times if t > stop_observed_at[0]]
    assert not after_fn, f"typing leaked after fn returned: {after_fn}"
