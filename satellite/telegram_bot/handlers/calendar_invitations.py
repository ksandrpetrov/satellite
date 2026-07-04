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
    CB_INV_BACK,
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
    open_streaming_reply,
    safe_answer_callback,
    send,
)
from .partstat_flow import (
    PartstatFlow,
    respond_partstat,
)
from .partstat_flow import (
    find_event_by_token as _find_event_by_token,
)

__all__ = [
    "handle_open_invitations",
    "open_invitations_from_settings",
    "route_invitations_callback",
    "_find_event_by_token",
]

log = logging.getLogger(__name__)

_INVITATIONS_OPEN_ACTION = "invitations:open"

# Двойной /invitations пока CalDAV ещё идёт — два одинаковых экрана.
_invitations_open_guard = ActionGuard(cooldown_sec=10.0)


def _load_screen(ctx: HandlerContext, user_id: int) -> tuple[str, str, dict]:
    screen = load_pending_invitations_screen(
        ctx.calendar_service,
        user_id,
        tz=ctx.tz,
    )
    return screen.rich_text, screen.text, screen.keyboard


def _fetch_all_for_token_lookup(ctx: HandlerContext, user_id: int) -> list:
    events, _login, _now = fetch_invitation_events(ctx.calendar_service, user_id, tz=ctx.tz)
    return events


def handle_open_invitations(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    if not _invitations_open_guard.try_acquire(msg.chat_id, _INVITATIONS_OPEN_ACTION):
        log.info("Invitations open skipped (duplicate within cooldown): user_id=%s", msg.user_id)
        send(ctx, msg.chat_id, INVITATIONS_BUSY_TEXT)
        return
    sent = False
    try:
        stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id, rich=True)
        stream.push_status(INVITATIONS_FETCH_STATUS)

        try:
            rich_text, fallback_text, keyboard = _load_screen(ctx, msg.user_id)
        except CalendarNotConnectedError:
            log.error("Invitations list failed user_id=%s: not connected", msg.user_id)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return
        except CalendarProviderError as exc:
            log.error("Invitations list failed user_id=%s: %s", msg.user_id, exc.error_code)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return
        stream.finish(
            rich_text,
            fallback_html=fallback_text,
            rich=True,
            reply_markup=keyboard,
            message_effect_id=pick_invitations_effect(fallback_text),
        )
        sent = True
        log.info("Opened invitations: user_id=%s", msg.user_id)
    finally:
        _invitations_open_guard.release(msg.chat_id, _INVITATIONS_OPEN_ACTION, sent=sent)


def _edit_invitations_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    toast: str | None = None,
    *,
    show_loading: bool = False,
    ack: bool = True,
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        if ack:
            safe_answer_callback(ctx, cb, text=toast)
        return
    if show_loading:
        ack_callback_with_loading(ctx, cb, status_html=INVITATIONS_FETCH_STATUS)
        ack = False
    try:
        rich_text, fallback_text, keyboard = _load_screen(ctx, cb.user_id)
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
    snapshot = get_event_token_cache().remove_invitations_pending(cb.user_id, token)
    if snapshot is not None:
        rich_text, fallback_text, keyboard = screen_from_pending(
            snapshot.pending,
            ctx.tz,
            reference_date=snapshot.moment.date(),
            truncated=snapshot.truncated,
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
        _edit_invitations_screen(ctx, cb, ack=False)
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
    )
    edit_callback_rich_or_html(
        ctx,
        cb,
        rich_html=rich_text,
        fallback_html=fallback_text,
        reply_markup=keyboard,
    )


def open_invitations_from_settings(ctx: HandlerContext, cb: IncomingCallback) -> None:
    _edit_invitations_screen(ctx, cb, show_loading=True)


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
    if data == CB_INV_BACK:
        from .settings_hub import show_settings_calendar_menu

        show_settings_calendar_menu(ctx, cb)
        return True
    if data == CB_INV_REFRESH:
        _edit_invitations_screen(ctx, cb, show_loading=True)
        return True
    if data.startswith(CB_INV_RESPOND_PREFIX):
        respond_partstat(ctx, cb, data, _FLOW)
        return True
    return False
