"""Worker/executor orchestration for Telegram updates."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

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
    ) -> None:
        self._executor = executor
        self._chat_locks = chat_locks
        self._offset_tracker = offset_tracker
        self._stop_event = stop_event

    def dispatch_update(self, ctx: HandlerContext, update: dict) -> None:
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

    def _dispatch_message(self, ctx: HandlerContext, update: dict) -> None:
        msg = extract_message(update)
        try:
            future = self._executor.submit(self._run_message_handler, ctx, msg)
        except RuntimeError:
            log.info("Executor shut down; deferring update_id=%s", msg.update_id)
            return
        future.add_done_callback(lambda _fut: self._offset_tracker.mark_completed(msg.update_id))

    def _dispatch_callback(self, ctx: HandlerContext, update: dict, update_id: int) -> None:
        cb = extract_callback_query(update)
        if cb is None:
            self._offset_tracker.mark_completed(update_id)
            return
        try:
            future = self._executor.submit(self._run_callback_handler, ctx, cb)
        except RuntimeError:
            log.info("Executor shut down; deferring callback update_id=%s", cb.update_id)
            return
        future.add_done_callback(lambda _fut: self._offset_tracker.mark_completed(cb.update_id))

    def _run_message_handler(self, ctx: HandlerContext, msg: IncomingMessage) -> None:
        lock = self._chat_locks.acquire(msg.chat_id)
        with lock:
            handle_message(ctx, msg)

    def _run_callback_handler(self, ctx: HandlerContext, cb: IncomingCallback) -> None:
        lock = self._chat_locks.acquire(cb.chat_id)
        with lock:
            handle_callback_query(ctx, cb)
