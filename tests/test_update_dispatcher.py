"""Unit tests for UpdateDispatcher orchestration."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from satellite.telegram_bot.concurrency import ChatLockManager
from satellite.telegram_bot.handlers.context import HandlerContext
from satellite.telegram_bot.offset_store import OffsetStore
from satellite.telegram_bot.offset_tracker import OffsetTracker
from satellite.telegram_bot.update_dispatcher import UpdateDispatcher


@pytest.fixture
def dispatcher_ctx(tmp_path) -> tuple[UpdateDispatcher, OffsetTracker, MagicMock, MagicMock]:
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)
    stop_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-dispatch")
    chat_locks = ChatLockManager()
    disp = UpdateDispatcher(
        executor=executor,
        chat_locks=chat_locks,
        offset_tracker=tracker,
        stop_event=stop_event,
    )
    ctx = MagicMock(spec=HandlerContext)
    yield disp, tracker, ctx, stop_event
    stop_event.set()
    executor.shutdown(wait=True)


def test_duplicate_update_id_is_ignored(dispatcher_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    disp, tracker, ctx, _ = dispatcher_ctx
    calls: list[int] = []

    def _handle_message(_ctx: HandlerContext, msg) -> None:
        calls.append(msg.update_id)

    monkeypatch.setattr(
        "satellite.telegram_bot.update_dispatcher.handle_message",
        _handle_message,
    )

    update = {
        "update_id": 10,
        "message": {"message_id": 1, "chat": {"id": 1}, "text": "hi"},
    }
    disp.dispatch_update(ctx, update)
    disp.dispatch_update(ctx, update)

    assert tracker.polling_offset == 11
    assert calls == [10]


def test_message_path_marks_completed_after_handler(
    dispatcher_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    disp, tracker, ctx, _ = dispatcher_ctx
    done = threading.Event()

    def _handle_message(_ctx: HandlerContext, msg) -> None:
        done.set()

    monkeypatch.setattr(
        "satellite.telegram_bot.update_dispatcher.handle_message",
        _handle_message,
    )

    disp.dispatch_update(
        ctx,
        {
            "update_id": 5,
            "message": {"message_id": 1, "chat": {"id": 42}, "text": "x"},
        },
    )
    assert done.wait(timeout=2.0)
    assert tracker.offset == 6


def test_callback_without_payload_completes_immediately(
    dispatcher_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    disp, tracker, ctx, _ = dispatcher_ctx
    called = False

    def _handle_callback(_ctx: HandlerContext, _cb) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "satellite.telegram_bot.update_dispatcher.handle_callback_query",
        _handle_callback,
    )

    disp.dispatch_update(
        ctx,
        {
            "update_id": 7,
            "callback_query": {"id": ""},
        },
    )

    assert called is False
    assert tracker.offset == 8


def test_executor_shutdown_defers_without_advancing_persisted_offset(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)
    stop_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-shutdown")
    disp = UpdateDispatcher(
        executor=executor,
        chat_locks=ChatLockManager(),
        offset_tracker=tracker,
        stop_event=stop_event,
    )
    ctx = MagicMock(spec=HandlerContext)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("Executor shut down")

    monkeypatch.setattr(executor, "submit", _boom)

    disp.dispatch_update(
        ctx,
        {
            "update_id": 3,
            "message": {"message_id": 1, "chat": {"id": 1}, "text": "y"},
        },
    )

    assert tracker.polling_offset == 4
    assert tracker.offset == 0
    executor.shutdown(wait=False)


def test_same_chat_messages_are_serialized(dispatcher_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    disp, _, ctx, _ = dispatcher_ctx
    order: list[int] = []
    first_started = threading.Event()
    allow_first_finish = threading.Event()
    both_done = threading.Event()

    def _handle_message(_ctx: HandlerContext, msg) -> None:
        order.append(msg.update_id)
        if msg.update_id == 20:
            first_started.set()
            assert allow_first_finish.wait(timeout=2.0)
        elif msg.update_id == 21:
            both_done.set()

    monkeypatch.setattr(
        "satellite.telegram_bot.update_dispatcher.handle_message",
        _handle_message,
    )

    disp.dispatch_update(
        ctx,
        {
            "update_id": 20,
            "message": {"message_id": 1, "chat": {"id": 99}, "text": "a"},
        },
    )
    assert first_started.wait(timeout=2.0)
    disp.dispatch_update(
        ctx,
        {
            "update_id": 21,
            "message": {"message_id": 2, "chat": {"id": 99}, "text": "b"},
        },
    )
    allow_first_finish.set()
    assert both_done.wait(timeout=2.0)
    assert order == [20, 21]
