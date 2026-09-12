"""Список приглашений (NEEDS-ACTION) и ответы ACCEPTED / DECLINED / TENTATIVE.

Тонкий адаптер: фетчим события, рендерим экран, общий респонс PARTSTAT
делегируем :mod:`.partstat_flow`.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...calendar.callback_tokens import event_callback_token
from ...calendar.events import event_local_start_date, format_time_range, format_upcoming_day_header
from ...calendar.providers.base import (
    CalendarEventRef,
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
    CB_INV_ACCEPT_ALL_PREFIX,
    CB_INV_BACK,
    CB_INV_CLOSE,
    CB_INV_PICK_PREFIX,
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
    build_invitation_detail_keyboard,
    invitation_accept_all_callback,
    invitation_detail_html,
    invitations_accept_all_result,
)
from ...presentation.rich import join_blocks, paragraph
from ..visual import pick_invitations_effect
from .access import ensure_calendar_connected
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


def _invitations_from_settings_hub(
    ctx: HandlerContext, user_id: int, *, explicit: bool | None = None
) -> bool:
    if explicit is not None:
        return explicit
    snapshot = ctx.runtime.event_tokens.get_invitations_snapshot(user_id)
    return bool(snapshot and snapshot.from_settings_hub)


def _load_screen(
    ctx: HandlerContext,
    user_id: int,
    *,
    from_settings_hub: bool | None = None,
) -> tuple[str, str, dict]:
    hub = _invitations_from_settings_hub(ctx, user_id, explicit=from_settings_hub)
    screen = load_pending_invitations_screen(
        ctx.calendar_service,
        user_id,
        tz=ctx.tz,
        from_settings_hub=hub,
        event_tokens=ctx.runtime.event_tokens,
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
        guard=ctx.runtime.invitations_open,
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
    from_hub = _invitations_from_settings_hub(ctx, cb.user_id)
    snapshot = ctx.runtime.event_tokens.remove_invitations_pending(cb.user_id, token)
    if snapshot is not None:
        fallback_text, rich_text, keyboard = screen_from_pending(
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
    fallback_text, rich_text, keyboard = screen_from_pending(
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
    token = (cb.data or "")[len(CB_INV_RESPOND_PREFIX) :].rsplit(":", 1)[0]
    _show_cached_invitation(ctx, cb, token, error=True)


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


def _show_cached_invitation(
    ctx: HandlerContext, cb: IncomingCallback, token: str | None, *, error: bool = False
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    snapshot = ctx.runtime.event_tokens.get_invitations_snapshot(cb.user_id)
    if snapshot is None:
        # An expired screen must be refreshed before choosing an event again.
        _edit_invitations_screen(ctx, cb, show_loading=True)
        return
    if token is not None:
        event = _find_event_by_token(snapshot.pending, token)
        if event is not None:
            day = event_local_start_date(event, ctx.tz)
            when = format_time_range(event, ctx.tz)
            if day is not None:
                when = f"{format_upcoming_day_header(day, snapshot.moment.date())} · {when}"
            text = invitation_detail_html(
                title=str(event.get("summary") or "—"),
                when=when,
                series=bool(event.get("invitation_series")),
            )
            if error:
                text += f"\n\n{INVITATIONS_RESPOND_FAIL_TEXT}"
            edit_callback_rich_or_html(
                ctx,
                cb,
                rich_html=join_blocks([paragraph(part) for part in text.split("\n\n")]),
                fallback_html=text,
                reply_markup=build_invitation_detail_keyboard(token),
            )
            safe_answer_callback(ctx, cb)
            return
    text, rich_text, keyboard = screen_from_pending(
        snapshot.pending,
        ctx.tz,
        reference_date=snapshot.moment.date(),
        truncated=snapshot.truncated,
        from_settings_hub=snapshot.from_settings_hub,
    )
    edit_callback_rich_or_html(
        ctx, cb, rich_html=rich_text, fallback_html=text, reply_markup=keyboard
    )
    safe_answer_callback(ctx, cb)


def _accept_all_invitations(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    cache = ctx.runtime.event_tokens
    snapshot = cache.get_invitations_snapshot(cb.user_id)
    if snapshot is None or data != invitation_accept_all_callback(
        [event_callback_token(str(ev.get("url") or "")) for ev in snapshot.pending]
    ):
        # A button from an older list must never accept a newly loaded selection.
        _edit_invitations_screen(ctx, cb, show_loading=True)
        return
    guard = ctx.runtime.partstat_respond
    if not guard.try_acquire(cb.chat_id, data):
        safe_answer_callback(ctx, cb)
        return
    safe_answer_callback(ctx, cb)
    accepted = 0
    try:
        for event in snapshot.pending:
            url = str(event.get("url") or "")
            token = event_callback_token(url)
            action = f"{CB_INV_RESPOND_PREFIX}{token}"
            if not guard.try_acquire(cb.chat_id, action):
                continue
            sent = False
            try:
                ctx.calendar_service.set_attendee_partstat(
                    cb.user_id,
                    CalendarEventRef(uid=str(event.get("uid") or ""), url=url),
                    "ACCEPTED",
                )
                cache.remove_invitations_pending(cb.user_id, token)
                accepted += 1
                sent = True
            except (CalendarNotConnectedError, CalendarProviderError):
                log.warning("Bulk invitation response failed user_id=%s", cb.user_id)
            finally:
                guard.release(cb.chat_id, action, sent=sent)
        remaining = cache.get_invitations_snapshot(cb.user_id)
        pending = remaining.pending if remaining is not None else snapshot.pending
        text, rich, keyboard = screen_from_pending(
            pending,
            ctx.tz,
            reference_date=snapshot.moment.date(),
            truncated=snapshot.truncated,
            from_settings_hub=snapshot.from_settings_hub,
        )
        result = invitations_accept_all_result(accepted, len(pending), snapshot.truncated)
        if not pending and snapshot.truncated:
            text, rich = result, paragraph(result)
        else:
            text = f"{result}\n\n{text}"
            rich = join_blocks([paragraph(result), rich])
        edit_callback_rich_or_html(
            ctx, cb, rich_html=rich, fallback_html=text, reply_markup=keyboard
        )
    finally:
        guard.release(cb.chat_id, data, sent=accepted > 0)


def route_invitations_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data:
        return False
    if not data.startswith("inv:"):
        return False
    if data.startswith(CB_INV_ACCEPT_ALL_PREFIX):
        _accept_all_invitations(ctx, cb, data)
        return True
    if data == CB_INV_BACK or data.startswith(CB_INV_PICK_PREFIX):
        _show_cached_invitation(
            ctx, cb, None if data == CB_INV_BACK else data[len(CB_INV_PICK_PREFIX) :]
        )
        return True
    if data == CB_INV_CLOSE:
        edit_callback_message(ctx, cb, INVITATIONS_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data == CB_INV_REFRESH:
        if cb.chat_id is None:
            return True
        if not ctx.runtime.invitations_refresh.try_acquire(cb.chat_id, _INVITATIONS_REFRESH_ACTION):
            safe_answer_callback(ctx, cb, text=INVITATIONS_BUSY_TEXT)
            return True
        sent = False
        try:
            _edit_invitations_screen(ctx, cb, show_loading=True)
            sent = True
        finally:
            ctx.runtime.invitations_refresh.release(
                cb.chat_id, _INVITATIONS_REFRESH_ACTION, sent=sent
            )
        return True
    if data.startswith(CB_INV_RESPOND_PREFIX):
        respond_partstat(ctx, cb, data, _FLOW)
        return True
    return False
