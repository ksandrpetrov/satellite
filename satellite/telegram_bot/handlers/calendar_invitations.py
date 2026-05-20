"""Список приглашений (NEEDS-ACTION) и ответы ACCEPTED / DECLINED / TENTATIVE."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from ...calendar.events import (
    collect_pending_invitations,
    format_invitation_list_lines,
)
from ...calendar.providers.base import (
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ...calendar.callback_tokens import event_callback_token
from ...messages_ru import (
    CB_INV_BACK,
    CB_INV_CLOSE,
    CB_INV_REFRESH,
    CB_INV_RESPOND_PREFIX,
    CB_SETTINGS_INVITATIONS,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    INVITATIONS_CLOSED_TEXT,
    INVITATIONS_EMPTY_HTML,
    INVITATIONS_FETCH_STATUS,
    INVITATIONS_RESPOND_ACCEPTED,
    INVITATIONS_RESPOND_DECLINED,
    INVITATIONS_RESPOND_FAIL_TEXT,
    INVITATIONS_RESPOND_TENTATIVE,
    build_invitations_keyboard,
    invitations_list_html,
)
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingCallback, IncomingMessage
from ..message_editing import edit_or_send_message
from .delivery import (
    edit_callback_message,
    safe_answer_callback,
    try_send_return_message_id,
)
from .settings_hub import show_settings_calendar_menu

log = logging.getLogger(__name__)

_INVITATION_HORIZON_DAYS = 60
_MAX_INVITATIONS = 12

_PARTSTAT_BY_CODE = {
    "a": "ACCEPTED",
    "d": "DECLINED",
    "t": "TENTATIVE",
}

_TOAST_BY_CODE = {
    "a": INVITATIONS_RESPOND_ACCEPTED,
    "d": INVITATIONS_RESPOND_DECLINED,
    "t": INVITATIONS_RESPOND_TENTATIVE,
}


def _screen_from_pending(
    pending: list,
    tz,
    *,
    reference_date: date,
    truncated: bool,
) -> tuple[str, dict]:
    if not pending:
        return INVITATIONS_EMPTY_HTML, build_invitations_keyboard([])
    body = format_invitation_list_lines(pending, tz, reference_date)
    keyboard_rows = [
        (event_callback_token(str(ev.get("url") or "")), str(idx + 1))
        for idx, ev in enumerate(pending)
    ]
    text = invitations_list_html(body_lines=body, truncated=truncated)
    return text, build_invitations_keyboard(keyboard_rows)


def _load_screen(ctx: HandlerContext, user_id: int) -> tuple[str, dict]:
    pending, _login, truncated = _fetch_pending(ctx, user_id)
    today = datetime.now(tz=ctx.tz).date()
    return _screen_from_pending(
        pending, ctx.tz, reference_date=today, truncated=truncated
    )


def _fetch_pending(ctx: HandlerContext, user_id: int) -> tuple[list, str, bool]:
    now = datetime.now(tz=ctx.tz)
    today = now.date()
    end = today + timedelta(days=_INVITATION_HORIZON_DAYS)
    connected = ctx.calendar_service.require_connection(user_id)
    login = connected.context.login
    events = ctx.calendar_service.list_events_for_invitations(
        user_id,
        start_date=today,
        end_date=end,
        tz=ctx.tz,
    )
    pending = collect_pending_invitations(
        events,
        login,
        ctx.tz,
        now=now,
        max_events=_MAX_INVITATIONS + 1,
    )
    truncated = len(pending) > _MAX_INVITATIONS
    if truncated:
        pending = pending[:_MAX_INVITATIONS]
    return pending, login, truncated


def _find_pending_by_token(pending: list, token: str):
    needle = (token or "").strip()
    for ev in pending:
        if event_callback_token(str(ev.get("url") or "")) == needle:
            return ev
    return None


def handle_open_invitations(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    loading_id = try_send_return_message_id(ctx, msg.chat_id, INVITATIONS_FETCH_STATUS)

    def build() -> tuple[str, dict]:
        return _load_screen(ctx, msg.user_id)

    try:
        text, keyboard = build()
    except CalendarNotConnectedError:
        text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
    except CalendarProviderError as exc:
        log.error("Invitations list failed user_id=%s: %s", msg.user_id, exc.error_code)
        text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
    edit_or_send_message(
        ctx.telegram,
        msg.chat_id,
        loading_id,
        text,
        reply_markup=keyboard,
    )
    log.info("Opened invitations: user_id=%s", msg.user_id)


def _edit_invitations_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    *,
    toast: str | None = None,
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb, text=toast)
        return
    try:
        text, keyboard = _load_screen(ctx, cb.user_id)
    except (CalendarNotConnectedError, CalendarProviderError):
        text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
    edit_callback_message(ctx, cb, text, keyboard)
    safe_answer_callback(ctx, cb, text=toast)


def route_invitations_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data:
        return False
    if data == CB_SETTINGS_INVITATIONS:
        _edit_invitations_screen(ctx, cb)
        return True
    if not data.startswith("inv:"):
        return False
    if data == CB_INV_CLOSE:
        edit_callback_message(ctx, cb, INVITATIONS_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data == CB_INV_BACK:
        show_settings_calendar_menu(ctx, cb)
        return True
    if data == CB_INV_REFRESH:
        _edit_invitations_screen(ctx, cb)
        return True
    if data.startswith(CB_INV_RESPOND_PREFIX):
        _handle_respond(ctx, cb, data)
        return True
    return False


def _handle_respond(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    suffix = data[len(CB_INV_RESPOND_PREFIX) :]
    if ":" not in suffix:
        safe_answer_callback(ctx, cb)
        return
    token, code = suffix.rsplit(":", 1)
    partstat = _PARTSTAT_BY_CODE.get(code.strip().lower())
    if not partstat:
        safe_answer_callback(ctx, cb)
        return
    try:
        pending, _login, truncated = _fetch_pending(ctx, cb.user_id)
        event = _find_pending_by_token(pending, token)
        if event is None:
            _edit_invitations_screen(ctx, cb, toast=INVITATIONS_RESPOND_FAIL_TEXT)
            return
        event_url = str(event.get("url") or "")
        uid = str(event.get("uid") or "")
        ctx.calendar_service.set_attendee_partstat(
            cb.user_id,
            CalendarEventRef(uid=uid, url=event_url),
            partstat,
        )
    except (CalendarNotConnectedError, CalendarProviderError) as exc:
        log.error(
            "Invitation respond failed user_id=%s: %s",
            cb.user_id,
            getattr(exc, "error_code", exc.__class__.__name__),
        )
        safe_answer_callback(ctx, cb, text=INVITATIONS_RESPOND_FAIL_TEXT)
        return
    toast = _TOAST_BY_CODE.get(code.strip().lower(), INVITATIONS_RESPOND_ACCEPTED)
    _edit_invitations_screen(ctx, cb, toast=toast)
