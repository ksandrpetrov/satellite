"""Bounded, ephemeral receipts for calendar writes, independent of Telegram delivery."""

from __future__ import annotations

import copy
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from threading import Lock

from ..presenters.bundle import ScreenBundle

ResultKey = tuple[int, int, int, str]  # user, chat, message, callback


@dataclass(frozen=True)
class PartstatReceipt:
    key: ResultKey
    bundle: ScreenBundle
    tokens: tuple[str, ...]
    allow_retry: bool
    created_at: float
    delivered: bool = False


class PartstatResultStore:
    def __init__(self, *, ttl_sec: float = 1800, max_results: int = 512) -> None:
        self._ttl = ttl_sec
        self._limit = max_results
        self._lock = Lock()
        self._items: OrderedDict[ResultKey, PartstatReceipt] = OrderedDict()

    def _prune(self) -> None:
        now = time.monotonic()
        for key, item in list(self._items.items()):
            if now - item.created_at >= self._ttl:
                del self._items[key]

    def save(
        self, key: ResultKey, bundle: ScreenBundle, tokens: tuple[str, ...], *, allow_retry: bool
    ) -> PartstatReceipt:
        with self._lock:
            self._prune()
            item = PartstatReceipt(
                key, copy.deepcopy(bundle), tokens, allow_retry, time.monotonic()
            )
            self._items[key] = item
            self._items.move_to_end(key)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
            return copy.deepcopy(item)

    def get(self, key: ResultKey) -> PartstatReceipt | None:
        with self._lock:
            self._prune()
            return copy.deepcopy(self._items.get(key))

    def undelivered(self, user_id: int, chat_id: int, message_id: int) -> PartstatReceipt | None:
        with self._lock:
            self._prune()
            for item in reversed(self._items.values()):
                if item.key[:3] == (user_id, chat_id, message_id):
                    return copy.deepcopy(item) if not item.delivered else None
            return None

    def mark_delivered(self, receipt: PartstatReceipt) -> None:
        with self._lock:
            current = self._items.get(receipt.key)
            if current is not None and current.created_at == receipt.created_at:
                self._items[receipt.key] = replace(current, delivered=True)

    def invalidate(self, user_id: int, token: str) -> None:
        """A new decision supersedes receipts about that resource on other screens."""
        with self._lock:
            for key, item in list(self._items.items()):
                if key[0] == user_id and token in item.tokens:
                    del self._items[key]
