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
        wait_for_typing_to_clear=False,
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
        wait_for_typing_to_clear=False,
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
        wait_for_typing_to_clear=False,
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
            wait_for_typing_to_clear=False,
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
            wait_for_typing_to_clear=False,
        )


def test_background_thread_stopped_after_fn() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    run_with_typing_action(
        telegram,
        1,
        lambda: None,
        interval_seconds=0.05,
        wait_for_typing_to_clear=False,
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
        wait_for_typing_to_clear=False,
    )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _typing_worker_threads():
        time.sleep(0.01)
    assert not _typing_worker_threads()


def test_waits_for_typing_indicator_to_clear_before_returning() -> None:
    """После fn() ждём остаток времени жизни typing, чтобы он не пережил итог."""
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    started = time.monotonic()
    run_with_typing_action(
        telegram,
        7,
        lambda: "done",
        interval_seconds=10.0,
        wait_for_typing_to_clear=True,
        typing_display_seconds=0.2,
    )
    elapsed = time.monotonic() - started

    # Первый typing уходит сразу, fn почти мгновенный — должны ждать ~ весь
    # typing_display_seconds. Допускаем небольшой запас в обе стороны.
    assert elapsed >= 0.18, f"expected wait for typing to clear, got {elapsed:.3f}s"
    assert elapsed < 1.0, f"wait should be bounded by typing_display_seconds, got {elapsed:.3f}s"


def test_wait_skipped_when_disabled() -> None:
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    started = time.monotonic()
    run_with_typing_action(
        telegram,
        7,
        lambda: "done",
        interval_seconds=10.0,
        wait_for_typing_to_clear=False,
        typing_display_seconds=0.5,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.2, f"expected no wait, got {elapsed:.3f}s"


def test_wait_skipped_when_typing_failed_to_send() -> None:
    """Если sendChatAction вообще не доехал до Telegram, ждать нечего."""
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(side_effect=RuntimeError("network"))

    started = time.monotonic()
    run_with_typing_action(
        telegram,
        7,
        lambda: "done",
        interval_seconds=10.0,
        wait_for_typing_to_clear=True,
        typing_display_seconds=0.5,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.2, f"no typing was sent, wait should be skipped, got {elapsed:.3f}s"


def test_wait_accounts_for_time_already_elapsed_since_last_typing() -> None:
    """Если fn() сам шёл достаточно долго, оставшегося ожидания должно быть мало."""
    telegram = MagicMock()
    telegram.send_chat_action = MagicMock(return_value=True)

    def slow() -> str:
        time.sleep(0.3)
        return "done"

    started = time.monotonic()
    run_with_typing_action(
        telegram,
        7,
        slow,
        interval_seconds=10.0,  # никаких повторных typing внутри fn
        wait_for_typing_to_clear=True,
        typing_display_seconds=0.2,
    )
    elapsed = time.monotonic() - started

    # fn идёт 0.3s, typing живёт 0.2s — он давно истёк к моменту возврата.
    # Ожидаем, что общий тайминг ≈ fn без заметной доплаты на typing.
    assert elapsed < 0.5, f"expected no extra wait, got {elapsed:.3f}s"


def test_no_typing_sent_after_stop_signal() -> None:
    """После fn() поток-обновлятор не должен успеть выстрелить ещё одним typing."""
    telegram = MagicMock()
    call_times: list[float] = []

    def record_typing(*_args, **_kwargs):
        call_times.append(time.monotonic())
        return True

    telegram.send_chat_action = MagicMock(side_effect=record_typing)

    def slow() -> str:
        # Достаточно долго, чтобы фоновый поток вышел из stop.wait по таймауту
        # и попытался отправить ещё один typing ровно на финише.
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
        wait_for_typing_to_clear=False,
    )

    # Любой typing, отправленный после возврата fn(), означает, что индикатор
    # «печатает» переживёт итоговое сообщение — этого допускать нельзя.
    after_fn = [t for t in call_times if t > stop_observed_at[0]]
    assert not after_fn, f"typing leaked after fn returned: {after_fn}"
