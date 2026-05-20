"""FSM для создания/редактирования событий и dedup callback (отдельно от digest)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date

STATE_CREATE_TITLE = "create_title"
STATE_CREATE_DATE = "create_date"
STATE_CREATE_TIME = "create_time"
STATE_CREATE_DURATION = "create_duration"
STATE_CREATE_CONFIRM = "create_confirm"

_DEDUP_CAPACITY = 1024


@dataclass
class CreateEventDraft:
    title: str = ""
    event_date: date | None = None
    start_time: str | None = None
    duration_minutes: int = 60


@dataclass
class CalendarFlowState:
    state: str
    draft: CreateEventDraft = field(default_factory=CreateEventDraft)
    manage_events: list[dict] = field(default_factory=list)


class CalendarStateStore:
    def __init__(self, dedup_capacity: int = _DEDUP_CAPACITY) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, CalendarFlowState] = {}
        self._seen_callbacks: OrderedDict[str, None] = OrderedDict()
        self._dedup_capacity = max(1, int(dedup_capacity))

    def get(self, chat_id: int) -> CalendarFlowState | None:
        with self._lock:
            return self._items.get(chat_id)

    def set(self, chat_id: int, flow: CalendarFlowState) -> None:
        with self._lock:
            self._items[chat_id] = flow

    def clear(self, chat_id: int) -> None:
        with self._lock:
            self._items.pop(chat_id, None)

    def is_busy(self, chat_id: int) -> bool:
        with self._lock:
            return chat_id in self._items

    def claim_callback(self, callback_id: str) -> bool:
        if not callback_id:
            return True
        with self._lock:
            if callback_id in self._seen_callbacks:
                self._seen_callbacks.move_to_end(callback_id)
                return False
            self._seen_callbacks[callback_id] = None
            while len(self._seen_callbacks) > self._dedup_capacity:
                self._seen_callbacks.popitem(last=False)
            return True
