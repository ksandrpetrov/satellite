"""Настройка персональных исключений встреч из дайджестов."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as datetime_time
from threading import Lock

from ...calendar.event_exclusions import normalize_event_title
from ...calendar.events import (
    Event,
    event_datetime_bounds,
    is_all_day_event,
    is_cancelled_event,
    is_declined_event_for_user,
    sort_key,
)
from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...calendar.selection import effective_enabled_calendar_urls
from ...meeting_exclusions import MeetingExclusionLimitError
from ...messages_ru import (
    CB_MEX_PREFIX,
    MEETING_EXCLUSIONS_CALENDAR_ERROR_TEXT,
    MEETING_EXCLUSIONS_CLEARED_TOAST,
    MEETING_EXCLUSIONS_LIMIT_TEXT,
    MEETING_EXCLUSIONS_LOADING_HTML,
    MEETING_EXCLUSIONS_REFRESH_TOAST,
    MEETING_EXCLUSIONS_RESET_TOAST,
    MEETING_EXCLUSIONS_SAVE_ERROR_TEXT,
    MEETING_EXCLUSIONS_SAVED_TOAST,
    MEETING_EXCLUSIONS_SETTINGS_ERROR_TEXT,
    MEETING_EXCLUSIONS_STALE_TEXT,
    MEX_CALLBACK_CLEAR,
    MEX_CALLBACK_PAGE_PREFIX,
    MEX_CALLBACK_REFRESH,
    MEX_CALLBACK_RESET_PREFIX,
    MEX_CALLBACK_TOGGLE_PREFIX,
    build_meeting_exclusions_error_keyboard,
    build_meeting_exclusions_keyboard,
)
from ...security import TokenDecryptError
from ...users import UserStorePersistenceError
from ..presenters.settings_screens import (
    meeting_exclusions_bundle,
    meeting_exclusions_error_bundle,
)
from .context import HandlerContext, IncomingCallback
from .delivery import (
    ack_callback_with_loading,
    edit_callback_bundle,
    safe_answer_callback,
    send,
)

log = logging.getLogger(__name__)

_WINDOW_DAYS = 7
_PAGE_SIZE = 8
_MAX_WEEK_TITLES = 200
_SNAPSHOT_TTL_SEC = 600.0
_MAX_CACHED_USERS = 128


@dataclass(frozen=True)
class _ScreenRow:
    title: str
    token: str
    excluded: bool
    reset_only: bool


@dataclass(frozen=True)
class _MeetingExclusionSnapshot:
    candidates: tuple[str, ...]
    rows: tuple[_ScreenRow, ...]
    token_to_title: dict[str, str]
    saved_outside_week_count: int
    has_overrides: bool
    truncated: bool
    cached_at: float


_snapshot_cache: OrderedDict[int, _MeetingExclusionSnapshot] = OrderedDict()
_snapshot_lock = Lock()


def reset_meeting_exclusion_cache(user_id: int | None = None) -> None:
    """Сбросить ephemeral token→title cache (production/tests)."""
    with _snapshot_lock:
        if user_id is None:
            _snapshot_cache.clear()
        else:
            _snapshot_cache.pop(user_id, None)


def _put_snapshot(user_id: int, snapshot: _MeetingExclusionSnapshot) -> None:
    with _snapshot_lock:
        _snapshot_cache.pop(user_id, None)
        _snapshot_cache[user_id] = snapshot
        while len(_snapshot_cache) > _MAX_CACHED_USERS:
            _snapshot_cache.popitem(last=False)


def _get_snapshot(user_id: int) -> _MeetingExclusionSnapshot | None:
    with _snapshot_lock:
        snapshot = _snapshot_cache.get(user_id)
        if snapshot is None:
            return None
        if time.monotonic() - snapshot.cached_at >= _SNAPSHOT_TTL_SEC:
            _snapshot_cache.pop(user_id, None)
            return None
        _snapshot_cache.move_to_end(user_id)
        return snapshot


def _normalized_title(title: str) -> str:
    return normalize_event_title(title)


def _display_title(event: Event) -> str:
    raw = str(event.get("summary") or event.get("title") or "")
    return " ".join(raw.split())


def _title_token(title: str) -> str:
    normalized = _normalized_title(title).encode("utf-8")
    return hashlib.blake2s(normalized, digest_size=16).hexdigest()


def _load_week_titles(ctx: HandlerContext, user_id: int) -> tuple[tuple[str, ...], bool]:
    connected = ctx.calendar_service.require_connection(user_id)
    login_value = getattr(connected.context, "login", "")
    login = login_value.strip() if isinstance(login_value, str) else ""
    enabled_urls = effective_enabled_calendar_urls(connected.record)
    today = datetime.now(tz=ctx.tz).date()
    window_start = datetime.combine(today, datetime_time.min, tzinfo=ctx.tz)
    window_end = datetime.combine(
        today + timedelta(days=_WINDOW_DAYS),
        datetime_time.min,
        tzinfo=ctx.tz,
    )
    events = ctx.calendar_service.list_events(
        user_id,
        start_date=today,
        end_date=today + timedelta(days=_WINDOW_DAYS),
        tz=ctx.tz,
        calendar_urls=enabled_urls or None,
    )

    unique: dict[str, str] = {}
    for event in sorted(events, key=lambda item: sort_key(item, ctx.tz)):
        if is_cancelled_event(event) or is_all_day_event(event, ctx.tz):
            continue
        if is_declined_event_for_user(event, login):
            continue
        start, end = event_datetime_bounds(event, ctx.tz)
        if start is None or end is None or end <= start:
            continue
        if end <= window_start or start >= window_end:
            continue
        title = _display_title(event)
        key = _normalized_title(title)
        if not key or key in unique:
            continue
        unique[key] = title

    all_titles = tuple(unique.values())
    truncated = len(all_titles) > _MAX_WEEK_TITLES
    return all_titles[:_MAX_WEEK_TITLES], truncated


def _build_snapshot(
    ctx: HandlerContext,
    user_id: int,
    *,
    candidates: tuple[str, ...],
    truncated: bool,
) -> _MeetingExclusionSnapshot:
    policy = ctx.meeting_exclusions.policy_for_user(user_id)
    overrides = tuple(ctx.meeting_exclusions.list_overrides(user_id))
    candidate_keys = {_normalized_title(title) for title in candidates}
    rows: list[_ScreenRow] = []
    token_to_title: dict[str, str] = {}

    for title in candidates:
        token = _title_token(title)
        token_to_title[token] = title
        rows.append(
            _ScreenRow(
                title=title,
                token=token,
                excluded=policy.is_excluded(title),
                reset_only=False,
            )
        )

    outside_count = 0
    for override in overrides:
        title = " ".join(str(override.title or "").split())
        key = _normalized_title(title)
        if not key or key in candidate_keys:
            continue
        outside_count += 1
        token = _title_token(title)
        token_to_title[token] = title
        rows.append(
            _ScreenRow(
                title=title,
                token=token,
                excluded=policy.is_excluded(title),
                reset_only=True,
            )
        )

    snapshot = _MeetingExclusionSnapshot(
        candidates=candidates,
        rows=tuple(rows),
        token_to_title=token_to_title,
        saved_outside_week_count=outside_count,
        has_overrides=bool(overrides),
        truncated=truncated,
        cached_at=time.monotonic(),
    )
    _put_snapshot(user_id, snapshot)
    return snapshot


def _fetch_snapshot(ctx: HandlerContext, user_id: int) -> _MeetingExclusionSnapshot:
    candidates, truncated = _load_week_titles(ctx, user_id)
    return _build_snapshot(
        ctx,
        user_id,
        candidates=candidates,
        truncated=truncated,
    )


def _rebuild_snapshot(
    ctx: HandlerContext,
    user_id: int,
    snapshot: _MeetingExclusionSnapshot,
) -> _MeetingExclusionSnapshot:
    return _build_snapshot(
        ctx,
        user_id,
        candidates=snapshot.candidates,
        truncated=snapshot.truncated,
    )


def _render_snapshot(
    ctx: HandlerContext,
    cb: IncomingCallback,
    snapshot: _MeetingExclusionSnapshot,
    *,
    page: int = 0,
) -> None:
    page_count = max(1, (len(snapshot.rows) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    safe_page = min(max(page, 0), page_count - 1)
    start = safe_page * _PAGE_SIZE
    visible_rows = snapshot.rows[start : start + _PAGE_SIZE]
    keyboard = build_meeting_exclusions_keyboard(
        rows=[(row.title, row.token, row.excluded, row.reset_only) for row in visible_rows],
        page=safe_page,
        page_count=page_count,
        has_overrides=snapshot.has_overrides,
    )
    bundle = meeting_exclusions_bundle(
        week_count=len(snapshot.candidates),
        saved_outside_week_count=snapshot.saved_outside_week_count,
        page=safe_page,
        page_count=page_count,
        truncated=snapshot.truncated,
        reply_markup=keyboard,
    )
    edit_callback_bundle(ctx, cb, bundle)


def _render_error(ctx: HandlerContext, cb: IncomingCallback, text: str) -> None:
    edit_callback_bundle(
        ctx,
        cb,
        meeting_exclusions_error_bundle(
            text,
            reply_markup=build_meeting_exclusions_error_keyboard(),
        ),
    )


def open_meeting_exclusions_from_settings(
    ctx: HandlerContext,
    cb: IncomingCallback,
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    ack_callback_with_loading(ctx, cb, status_html=MEETING_EXCLUSIONS_LOADING_HTML)
    try:
        snapshot = _fetch_snapshot(ctx, cb.user_id)
    except (CalendarNotConnectedError, CalendarProviderError) as exc:
        log.warning(
            "Meeting exclusions calendar fetch failed user_id=%s error=%s",
            cb.user_id,
            exc.__class__.__name__,
        )
        _render_error(ctx, cb, MEETING_EXCLUSIONS_CALENDAR_ERROR_TEXT)
        return
    except TokenDecryptError:
        log.exception("Meeting exclusions decrypt failed user_id=%s", cb.user_id)
        _render_error(ctx, cb, MEETING_EXCLUSIONS_SETTINGS_ERROR_TEXT)
        return
    _render_snapshot(ctx, cb, snapshot)


def _parse_token_action(data: str, prefix: str) -> tuple[str, int] | None:
    payload = data.removeprefix(prefix)
    token, separator, raw_page = payload.rpartition(":")
    if not separator or not token:
        return None
    try:
        page = int(raw_page)
    except ValueError:
        return None
    return token, page


def _snapshot_for_action(
    ctx: HandlerContext,
    cb: IncomingCallback,
    *,
    token: str,
) -> tuple[_MeetingExclusionSnapshot | None, str | None, bool]:
    if cb.user_id is None:
        return None, None, False
    snapshot = _get_snapshot(cb.user_id)
    if snapshot is not None:
        title = snapshot.token_to_title.get(token)
        if title is not None:
            return snapshot, title, False

    ack_callback_with_loading(
        ctx,
        cb,
        status_html=MEETING_EXCLUSIONS_LOADING_HTML,
        toast=MEETING_EXCLUSIONS_REFRESH_TOAST,
    )
    snapshot = _fetch_snapshot(ctx, cb.user_id)
    title = snapshot.token_to_title.get(token)
    if title is None:
        _render_snapshot(ctx, cb, snapshot)
        send(ctx, cb.chat_id, MEETING_EXCLUSIONS_STALE_TEXT)
        return None, None, True
    return snapshot, title, True


def _handle_page(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        page = int(data.removeprefix(MEX_CALLBACK_PAGE_PREFIX))
    except ValueError:
        page = 0
    snapshot = _get_snapshot(cb.user_id)
    if snapshot is None:
        ack_callback_with_loading(
            ctx,
            cb,
            status_html=MEETING_EXCLUSIONS_LOADING_HTML,
            toast=MEETING_EXCLUSIONS_REFRESH_TOAST,
        )
        snapshot = _fetch_snapshot(ctx, cb.user_id)
    else:
        safe_answer_callback(ctx, cb)
    _render_snapshot(ctx, cb, snapshot, page=page)


def _handle_refresh(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    ack_callback_with_loading(
        ctx,
        cb,
        status_html=MEETING_EXCLUSIONS_LOADING_HTML,
        toast=MEETING_EXCLUSIONS_REFRESH_TOAST,
    )
    snapshot = _fetch_snapshot(ctx, cb.user_id)
    _render_snapshot(ctx, cb, snapshot)


def _handle_clear(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    ctx.meeting_exclusions.clear(cb.user_id)
    safe_answer_callback(ctx, cb, text=MEETING_EXCLUSIONS_CLEARED_TOAST)
    snapshot = _get_snapshot(cb.user_id)
    if snapshot is None:
        snapshot = _fetch_snapshot(ctx, cb.user_id)
    else:
        snapshot = _rebuild_snapshot(ctx, cb.user_id, snapshot)
    _render_snapshot(ctx, cb, snapshot)


def _handle_title_action(
    ctx: HandlerContext,
    cb: IncomingCallback,
    data: str,
    *,
    reset: bool,
) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    prefix = MEX_CALLBACK_RESET_PREFIX if reset else MEX_CALLBACK_TOGGLE_PREFIX
    parsed = _parse_token_action(data, prefix)
    if parsed is None:
        safe_answer_callback(ctx, cb, text=MEETING_EXCLUSIONS_STALE_TEXT)
        return
    token, page = parsed
    snapshot, title, already_acked = _snapshot_for_action(ctx, cb, token=token)
    if snapshot is None or title is None:
        return
    try:
        if reset:
            ctx.meeting_exclusions.reset_title(cb.user_id, title)
            toast = MEETING_EXCLUSIONS_RESET_TOAST
        else:
            ctx.meeting_exclusions.toggle_title(cb.user_id, title)
            toast = MEETING_EXCLUSIONS_SAVED_TOAST
    except MeetingExclusionLimitError:
        if not already_acked:
            raise
        _render_error(ctx, cb, MEETING_EXCLUSIONS_LIMIT_TEXT)
        return
    except UserStorePersistenceError:
        if not already_acked:
            raise
        log.exception("Meeting exclusions callback save failed user_id=%s", cb.user_id)
        _render_error(ctx, cb, MEETING_EXCLUSIONS_SAVE_ERROR_TEXT)
        return
    if not already_acked:
        safe_answer_callback(ctx, cb, text=toast)
    refreshed = _rebuild_snapshot(ctx, cb.user_id, snapshot)
    _render_snapshot(ctx, cb, refreshed, page=page)


def route_meeting_exclusions_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data.startswith(CB_MEX_PREFIX):
        return False
    try:
        if data == MEX_CALLBACK_REFRESH:
            _handle_refresh(ctx, cb)
        elif data == MEX_CALLBACK_CLEAR:
            _handle_clear(ctx, cb)
        elif data.startswith(MEX_CALLBACK_PAGE_PREFIX):
            _handle_page(ctx, cb, data)
        elif data.startswith(MEX_CALLBACK_TOGGLE_PREFIX):
            _handle_title_action(ctx, cb, data, reset=False)
        elif data.startswith(MEX_CALLBACK_RESET_PREFIX):
            _handle_title_action(ctx, cb, data, reset=True)
        else:
            safe_answer_callback(ctx, cb, text=MEETING_EXCLUSIONS_STALE_TEXT)
    except (CalendarNotConnectedError, CalendarProviderError) as exc:
        log.warning(
            "Meeting exclusions callback calendar failed user_id=%s error=%s",
            cb.user_id,
            exc.__class__.__name__,
        )
        _render_error(ctx, cb, MEETING_EXCLUSIONS_CALENDAR_ERROR_TEXT)
    except TokenDecryptError:
        log.exception("Meeting exclusions callback decrypt failed user_id=%s", cb.user_id)
        _render_error(ctx, cb, MEETING_EXCLUSIONS_SETTINGS_ERROR_TEXT)
    except MeetingExclusionLimitError:
        safe_answer_callback(ctx, cb, text=MEETING_EXCLUSIONS_LIMIT_TEXT, show_alert=True)
    except UserStorePersistenceError:
        log.exception("Meeting exclusions callback save failed user_id=%s", cb.user_id)
        safe_answer_callback(ctx, cb, text=MEETING_EXCLUSIONS_SAVE_ERROR_TEXT, show_alert=True)
    return True
