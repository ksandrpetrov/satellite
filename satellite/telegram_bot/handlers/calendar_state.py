"""FSM для создания/редактирования событий и dedup callback (отдельно от digest)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date

STATE_CREATE_TITLE = "create_title"
STATE_CREATE_DATE = "create_date"
STATE_CREATE_TIME = "create_time"
STATE_CREATE_DURATION = "create_duration"
STATE_CREATE_CONFIRM = "create_confirm"
STATE_CREATE_SUBMITTING = "create_submitting"


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


class CalendarStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, CalendarFlowState] = {}

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
