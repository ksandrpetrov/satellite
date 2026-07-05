"""Список приглашений (NEEDS-ACTION) и ответы ACCEPTED / DECLINED / TENTATIVE.

Тонкий адаптер: фетчим события, рендерим экран, общий респонс PARTSTAT
делегируем :mod:`.partstat_flow`.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...calendar.callback_tokens import event_callback_token
from ...calendar.event_token_cache import get_event_token_cache
from ...calendar.providers.base import (
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ...invitations_view import (
    collect_pending_from_events,
    fetch_invitation_events,
    load_pending_invitations_screen,
    screen_from_pending,
)
from ...messages_ru import (
    CB_INV_CLOSE,
    CB_INV_REFRESH,
    CB_INV_RESPOND_PREFIX,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    INVITATIONS_BUSY_TEXT,
    INVITATIONS_CLOSED_TEXT,
    INVITATIONS_FETCH_STATUS,
    INVITATIONS_RESPOND_ACCEPTED,
    INVITATIONS_RESPOND_DECLINED,
    INVITATIONS_RESPOND_FAIL_TEXT,
    INVITATIONS_RESPOND_TENTATIVE,
)
from ..visual import pick_invitations_effect
from .access import ensure_calendar_connected
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    ack_callback_with_loading,
    edit_callback_message,
    edit_callback_rich_or_html,
    safe_answer_callback,
)
from .partstat_flow import (
    PartstatFlow,
    respond_partstat,
)
from .partstat_flow import (
    find_event_by_token as _find_event_by_token,
)
from .streaming_caldav import StreamingCaldavResult, run_streaming_caldav_message

__all__ = [
    "handle_open_invitations",
    "open_invitations_from_settings",
    "route_invitations_callback",
    "_find_event_by_token",
]

log = logging.getLogger(__name__)

_INVITATIONS_OPEN_ACTION = "invitations:open"
_INVITATIONS_REFRESH_ACTION = "invitations:refresh"

# Двойной /invitations или refresh пока CalDAV ещё идёт — два одинаковых экрана.
_invitations_open_guard = ActionGuard(cooldown_sec=10.0)
_invitations_refresh_guard = ActionGuard(cooldown_sec=10.0)


def _invitations_from_settings_hub(user_id: int, *, explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    snapshot = get_event_token_cache().get_invitations_snapshot(user_id)
    return bool(snapshot and snapshot.from_settings_hub)


def _load_screen(
    ctx: HandlerContext,
    user_id: int,
    *,
    from_settings_hub: bool | None = None,
) -> tuple[str, str, dict]:
    hub = _invitations_from_settings_hub(user_id, explicit=from_settings_hub)
    screen = load_pending_invitations_screen(
        ctx.calendar_service,
        user_id,
        tz=ctx.tz,
        from_settings_hub=hub,
    )
    return screen.rich_text, screen.text, screen.keyboard


def _fetch_all_for_token_lookup(ctx: HandlerContext, user_id: int) -> list:
    events, _login, _now = fetch_invitation_events(ctx.calendar_service, user_id, tz=ctx.tz)
    return events


def handle_open_invitations(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg):
        return

    def fetch(_ctx: HandlerContext, user_id: int) -> StreamingCaldavResult:
        rich_text, fallback_text, keyboard = _load_screen(_ctx, user_id, from_settings_hub=False)
        return StreamingCaldavResult(
            rich_html=rich_text,
            fallback_html=fallback_text,
            reply_markup=keyboard,
            message_effect_id=pick_invitations_effect(fallback_text),
        )

    run_streaming_caldav_message(
        ctx,
        msg,
        guard=_invitations_open_guard,
        action_key=_INVITATIONS_OPEN_ACTION,
        busy_text=INVITATIONS_BUSY_TEXT,
        status_text=INVITATIONS_FETCH_STATUS,
        fetch_fn=fetch,
        log_label="Invitations",
    )


def _edit_invitations_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    toast: str | None = None,
    *,
    show_loading: bool = False,
    ack: bool = True,
    from_settings_hub: bool | None = None,
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        if ack:
            safe_answer_callback(ctx, cb, text=toast)
        return
    if show_loading:
        ack_callback_with_loading(ctx, cb, status_html=INVITATIONS_FETCH_STATUS)
        ack = False
    try:
        rich_text, fallback_text, keyboard = _load_screen(
            ctx,
            cb.user_id,
            from_settings_hub=from_settings_hub,
        )
    except (CalendarNotConnectedError, CalendarProviderError):
        rich_text = fallback_text = ERR_CALDAV_UNAVAILABLE_TEXT
        keyboard = None
    edit_callback_rich_or_html(
        ctx,
        cb,
        rich_html=rich_text,
        fallback_html=fallback_text,
        reply_markup=keyboard,
    )
    if ack:
        safe_answer_callback(ctx, cb, text=toast)


def _optimistic_refresh_invitations(
    ctx: HandlerContext,
    cb: IncomingCallback,
    token: str,
    _partstat: str,
    fallback_events: list | None,
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        return
    from_hub = _invitations_from_settings_hub(cb.user_id)
    snapshot = get_event_token_cache().remove_invitations_pending(cb.user_id, token)
    if snapshot is not None:
        rich_text, fallback_text, keyboard = screen_from_pending(
            snapshot.pending,
            ctx.tz,
            reference_date=snapshot.moment.date(),
            truncated=snapshot.truncated,
            from_settings_hub=snapshot.from_settings_hub,
        )
        edit_callback_rich_or_html(
            ctx,
            cb,
            rich_html=rich_text,
            fallback_html=fallback_text,
            reply_markup=keyboard,
        )
        return
    if fallback_events is None:
        _edit_invitations_screen(ctx, cb, ack=False, from_settings_hub=from_hub)
        return
    connected = ctx.calendar_service.require_connection(cb.user_id)
    login = connected.context.login
    moment = datetime.now(tz=ctx.tz)
    pending, truncated = collect_pending_from_events(
        fallback_events,
        login,
        ctx.tz,
        now=moment,
    )
    pending = [ev for ev in pending if event_callback_token(str(ev.get("url") or "")) != token]
    rich_text, fallback_text, keyboard = screen_from_pending(
        pending,
        ctx.tz,
        reference_date=moment.date(),
        truncated=truncated,
        from_settings_hub=from_hub,
    )
    edit_callback_rich_or_html(
        ctx,
        cb,
        rich_html=rich_text,
        fallback_html=fallback_text,
        reply_markup=keyboard,
    )


def open_invitations_from_settings(ctx: HandlerContext, cb: IncomingCallback) -> None:
    _edit_invitations_screen(ctx, cb, show_loading=True, from_settings_hub=True)


def _on_not_found(ctx: HandlerContext, cb: IncomingCallback) -> None:
    _edit_invitations_screen(ctx, cb, toast=INVITATIONS_RESPOND_FAIL_TEXT, ack=False)


def _on_fail(ctx: HandlerContext, cb: IncomingCallback) -> None:
    edit_callback_rich_or_html(
        ctx,
        cb,
        rich_html=INVITATIONS_RESPOND_FAIL_TEXT,
        fallback_html=INVITATIONS_RESPOND_FAIL_TEXT,
        reply_markup=None,
    )


_FLOW = PartstatFlow(
    prefix=CB_INV_RESPOND_PREFIX,
    fail_text=INVITATIONS_RESPOND_FAIL_TEXT,
    toast_by_code={
        "a": INVITATIONS_RESPOND_ACCEPTED,
        "d": INVITATIONS_RESPOND_DECLINED,
        "t": INVITATIONS_RESPOND_TENTATIVE,
    },
    log_name="Invitation",
    loading_status_html=INVITATIONS_FETCH_STATUS,
    fetch_events=_fetch_all_for_token_lookup,
    optimistic_refresh_view=_optimistic_refresh_invitations,
    on_not_found=_on_not_found,
    on_fail=_on_fail,
)


def route_invitations_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data:
        return False
    if not data.startswith("inv:"):
        return False
    if data == CB_INV_CLOSE:
        edit_callback_message(ctx, cb, INVITATIONS_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data == CB_INV_REFRESH:
        if cb.chat_id is None:
            return True
        if not _invitations_refresh_guard.try_acquire(cb.chat_id, _INVITATIONS_REFRESH_ACTION):
            safe_answer_callback(ctx, cb, text=INVITATIONS_BUSY_TEXT)
            return True
        sent = False
        try:
            _edit_invitations_screen(ctx, cb, show_loading=True)
            sent = True
        finally:
            _invitations_refresh_guard.release(cb.chat_id, _INVITATIONS_REFRESH_ACTION, sent=sent)
        return True
    if data.startswith(CB_INV_RESPOND_PREFIX):
        respond_partstat(ctx, cb, data, _FLOW)
        return True
    return False
