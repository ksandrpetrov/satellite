"""Worker/executor orchestration for Telegram updates."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from .concurrency import ChatLockManager
from .handlers import (
    HandlerContext,
    IncomingCallback,
    IncomingMessage,
    extract_callback_query,
    extract_message,
    handle_callback_query,
    handle_message,
    is_update_callback,
    is_update_message,
)
from .offset_tracker import OffsetTracker

log = logging.getLogger(__name__)


class UpdateDispatcher:
    """Owns update fan-out into executor workers."""

    def __init__(
        self,
        *,
        executor: ThreadPoolExecutor,
        chat_locks: ChatLockManager,
        offset_tracker: OffsetTracker,
        stop_event: threading.Event,
        max_pending_updates: int,
    ) -> None:
        if max_pending_updates <= 0:
            raise ValueError("max_pending_updates must be positive")
        self._executor = executor
        self._chat_locks = chat_locks
        self._offset_tracker = offset_tracker
        self._stop_event = stop_event
        self._pending_slots = threading.BoundedSemaphore(max_pending_updates)

    def dispatch_update(self, ctx: HandlerContext, update: dict[str, Any]) -> None:
        update_id = int(update.get("update_id") or 0)
        if update_id <= 0:
            return
        if not self._offset_tracker.mark_dispatched(update_id):
            return
        if is_update_callback(update):
            self._dispatch_callback(ctx, update, update_id)
            return
        if is_update_message(update):
            self._dispatch_message(ctx, update)
            return
        self._offset_tracker.mark_completed(update_id)

    def _dispatch_message(self, ctx: HandlerContext, update: dict[str, Any]) -> None:
        msg = extract_message(update)
        if not self._acquire_pending_slot(msg.update_id):
            return
        try:
            future = self._executor.submit(self._run_message_handler, ctx, msg)
        except RuntimeError:
            self._pending_slots.release()
            log.info("Executor shut down; deferring update_id=%s", msg.update_id)
            return
        future.add_done_callback(
            lambda completed: self._complete_and_release(completed, msg.update_id)
        )

    def _dispatch_callback(
        self,
        ctx: HandlerContext,
        update: dict[str, Any],
        update_id: int,
    ) -> None:
        cb = extract_callback_query(update)
        if cb is None:
            self._offset_tracker.mark_completed(update_id)
            return
        if not self._acquire_pending_slot(cb.update_id):
            return
        try:
            future = self._executor.submit(self._run_callback_handler, ctx, cb)
        except RuntimeError:
            self._pending_slots.release()
            log.info("Executor shut down; deferring callback update_id=%s", cb.update_id)
            return
        future.add_done_callback(
            lambda completed: self._complete_and_release(completed, cb.update_id)
        )

    def _acquire_pending_slot(self, update_id: int) -> bool:
        while not self._stop_event.is_set():
            if self._pending_slots.acquire(timeout=0.1):
                return True
        log.info("Stopping while waiting for update capacity; deferring update_id=%s", update_id)
        return False

    def _complete_and_release(self, _future: Future[None], update_id: int) -> None:
        try:
            self._offset_tracker.mark_completed(update_id)
        finally:
            self._pending_slots.release()

    def _run_message_handler(self, ctx: HandlerContext, msg: IncomingMessage) -> None:
        lock = self._chat_locks.acquire(msg.chat_id)
        with lock:
            handle_message(ctx, msg)

    def _run_callback_handler(self, ctx: HandlerContext, cb: IncomingCallback) -> None:
        lock = self._chat_locks.acquire(cb.chat_id)
        with lock:
            handle_callback_query(ctx, cb)
