"""Ephemeral state owned by one bot, shared by its handler contexts."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Generic, TypeVar

from ...calendar.event_token_cache import EventTokenCache
from ...calendar.providers.base import CalendarListEntry
from .action_guard import ActionGuard
from .partstat_results import PartstatResultStore

if TYPE_CHECKING:
    from .calendar_view import CalendarListResult
    from .meeting_exclusions import _MeetingExclusionSnapshot

T = TypeVar("T")


class UserCache(Generic[T]):
    """A per-user TTL cache; lookup and expiry are atomic with writes."""

    def __init__(self, ttl_sec: float, *, max_users: int | None = None) -> None:
        self._ttl_sec = ttl_sec
        self._max_users = max_users
        self._items: OrderedDict[int, tuple[T, float]] = OrderedDict()
        self._lock = Lock()

    def put(self, user_id: int, value: T) -> None:
        with self._lock:
            self._items[user_id] = (value, time.monotonic())
            self._items.move_to_end(user_id)
            if self._max_users is not None:
                while len(self._items) > self._max_users:
                    self._items.popitem(last=False)

    def clear(self, user_id: int) -> None:
        with self._lock:
            self._items.pop(user_id, None)

    def get(self, user_id: int) -> T | None:
        with self._lock:
            stored = self._items.get(user_id)
            if stored is None:
                return None
            value, cached_at = stored
            if time.monotonic() - cached_at >= self._ttl_sec:
                self._items.pop(user_id)
                return None
            self._items.move_to_end(user_id)
            return value


@dataclass
class HandlerRuntime:
    event_tokens: EventTokenCache = field(default_factory=EventTokenCache)
    partstat_results: PartstatResultStore = field(default_factory=PartstatResultStore)
    calendar_lists: UserCache[CalendarListResult] = field(default_factory=lambda: UserCache(60.0))
    foreign_lists: UserCache[tuple[CalendarListEntry, ...]] = field(
        default_factory=lambda: UserCache(60.0)
    )
    meeting_snapshots: UserCache[_MeetingExclusionSnapshot] = field(
        default_factory=lambda: UserCache(600.0, max_users=128)
    )
    hub_messages: dict[int, int] = field(default_factory=dict)
    plan: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=0.0))
    upcoming: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=15.0))
    analytics: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=45.0))
    invitations_open: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=10.0))
    invitations_refresh: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=10.0))
    manage_open: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=10.0))
    manage_refresh: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=10.0))
    partstat_respond: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=5.0))
    partstat_write: ActionGuard = field(default_factory=lambda: ActionGuard(cooldown_sec=0.0))
