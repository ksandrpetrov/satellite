"""In-memory кэш token→URL и снимков экранов для быстрого PARTSTAT respond.

Заполняется при open/refresh ``/invitations`` и ``/manage``. Позволяет отвечать
на приглашение без повторного тяжёлого ``list_events_for_invitations``.
"""

from __future__ import annotations

import copy
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .callback_tokens import event_callback_token
from .events._partstat import _attendee_line_matches_login

_TOKEN_TTL_SEC = 30 * 60

Event = Mapping[str, Any]


@dataclass(frozen=True)
class CachedEventRef:
    url: str
    uid: str


@dataclass(frozen=True)
class InvitationsScreenSnapshot:
    pending: list[dict[str, Any]]
    login: str
    moment: datetime
    truncated: bool
    from_settings_hub: bool = False


@dataclass(frozen=True)
class ManageScreenSnapshot:
    events: list[dict[str, Any]]
    login: str
    moment: datetime
    truncated: bool


@dataclass
class _TokenEntry:
    ref: CachedEventRef
    cached_at: float


def apply_user_partstat_to_event(event: Event, login: str, partstat: str) -> dict[str, Any]:
    """Копия события с обновлённым PARTSTAT пользователя (для optimistic UI)."""
    ev: dict[str, Any] = copy.deepcopy(dict(event))
    partstat_upper = partstat.strip().upper()
    attendees: list[str] = []
    updated = False
    for line in ev.get("attendees", []):
        line_str = str(line)
        if _attendee_line_matches_login(line_str, login):
            attendees.append(_replace_partstat_in_line(line_str, partstat_upper))
            updated = True
        else:
            attendees.append(line_str)
    if not updated:
        for line in ev.get("attendees", []):
            line_str = str(line)
            if "partstat=needs-action" in line_str.casefold():
                attendees = [
                    _replace_partstat_in_line(str(a), partstat_upper)
                    if str(a) == line_str
                    else str(a)
                    for a in ev.get("attendees", [])
                ]
                updated = True
                break
    if updated:
        ev["attendees"] = attendees
    return ev


def _replace_partstat_in_line(line: str, partstat: str) -> str:
    if "partstat=" in line.casefold():
        return re.sub(
            r"(?i)partstat=[^;,\s:]+",
            f"PARTSTAT={partstat}",
            line,
            count=1,
        )
    return f"{line.rstrip()};PARTSTAT={partstat}"


class EventTokenCache:
    def __init__(self, *, ttl_sec: float = _TOKEN_TTL_SEC) -> None:
        self._ttl_sec = ttl_sec
        self._tokens: dict[tuple[int, str], _TokenEntry] = {}
        self._invitations: dict[int, tuple[InvitationsScreenSnapshot, float]] = {}
        self._manage: dict[int, tuple[ManageScreenSnapshot, float]] = {}

    def reset(self) -> None:
        self._tokens.clear()
        self._invitations.clear()
        self._manage.clear()

    def register_invitations_screen(
        self,
        user_id: int,
        *,
        pending: Sequence[Event],
        all_events: Sequence[Event],
        login: str,
        moment: datetime,
        truncated: bool,
        from_settings_hub: bool = False,
    ) -> None:
        now = time.monotonic()
        self._invitations[user_id] = (
            InvitationsScreenSnapshot(
                pending=[copy.deepcopy(dict(ev)) for ev in pending],
                login=login,
                moment=moment,
                truncated=truncated,
                from_settings_hub=from_settings_hub,
            ),
            now,
        )
        for ev in all_events:
            self._register_event(user_id, ev, cached_at=now)

    def register_manage_screen(
        self,
        user_id: int,
        *,
        events: Sequence[Event],
        login: str,
        moment: datetime,
        truncated: bool,
    ) -> None:
        now = time.monotonic()
        self._manage[user_id] = (
            ManageScreenSnapshot(
                events=[copy.deepcopy(dict(ev)) for ev in events],
                login=login,
                moment=moment,
                truncated=truncated,
            ),
            now,
        )
        for ev in events:
            self._register_event(user_id, ev, cached_at=now)

    def lookup(self, user_id: int, token: str) -> CachedEventRef | None:
        needle = (token or "").strip()
        if not needle:
            return None
        entry = self._tokens.get((user_id, needle))
        if entry is None:
            return None
        if (time.monotonic() - entry.cached_at) >= self._ttl_sec:
            self._tokens.pop((user_id, needle), None)
            return None
        return entry.ref

    def get_invitations_snapshot(self, user_id: int) -> InvitationsScreenSnapshot | None:
        stored = self._invitations.get(user_id)
        if stored is None:
            return None
        snapshot, cached_at = stored
        if (time.monotonic() - cached_at) >= self._ttl_sec:
            self._invitations.pop(user_id, None)
            return None
        return snapshot

    def get_manage_snapshot(self, user_id: int) -> ManageScreenSnapshot | None:
        stored = self._manage.get(user_id)
        if stored is None:
            return None
        snapshot, cached_at = stored
        if (time.monotonic() - cached_at) >= self._ttl_sec:
            self._manage.pop(user_id, None)
            return None
        return snapshot

    def remove_invitations_pending(
        self, user_id: int, token: str
    ) -> InvitationsScreenSnapshot | None:
        stored = self._invitations.get(user_id)
        if stored is None:
            return None
        snapshot, cached_at = stored
        if (time.monotonic() - cached_at) >= self._ttl_sec:
            self._invitations.pop(user_id, None)
            return None
        pending = [
            ev for ev in snapshot.pending if event_callback_token(str(ev.get("url") or "")) != token
        ]
        updated = InvitationsScreenSnapshot(
            pending=pending,
            login=snapshot.login,
            moment=snapshot.moment,
            truncated=snapshot.truncated and len(pending) >= len(snapshot.pending),
            from_settings_hub=snapshot.from_settings_hub,
        )
        self._invitations[user_id] = (updated, cached_at)
        return updated

    def update_manage_partstat(
        self,
        user_id: int,
        token: str,
        login: str,
        partstat: str,
    ) -> ManageScreenSnapshot | None:
        stored = self._manage.get(user_id)
        if stored is None:
            return None
        snapshot, cached_at = stored
        if (time.monotonic() - cached_at) >= self._ttl_sec:
            self._manage.pop(user_id, None)
            return None
        events: list[dict[str, Any]] = []
        for ev in snapshot.events:
            if event_callback_token(str(ev.get("url") or "")) == token:
                events.append(apply_user_partstat_to_event(ev, login, partstat))
            else:
                events.append(copy.deepcopy(ev))
        updated = ManageScreenSnapshot(
            events=events,
            login=snapshot.login,
            moment=snapshot.moment,
            truncated=snapshot.truncated,
        )
        self._manage[user_id] = (updated, cached_at)
        return updated

    def _register_event(self, user_id: int, event: Event, *, cached_at: float) -> None:
        url = str(event.get("url") or "").strip()
        if not url:
            return
        token = event_callback_token(url)
        self._tokens[(user_id, token)] = _TokenEntry(
            ref=CachedEventRef(url=url, uid=str(event.get("uid") or "")),
            cached_at=cached_at,
        )


_cache = EventTokenCache()


def get_event_token_cache() -> EventTokenCache:
    return _cache


def reset_event_token_cache() -> None:
    _cache.reset()
