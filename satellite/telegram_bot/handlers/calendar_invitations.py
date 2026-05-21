"""Список приглашений (NEEDS-ACTION) и ответы ACCEPTED / DECLINED / TENTATIVE.

Тонкий адаптер: фетчим события, рендерим экран, общий респонс PARTSTAT
делегируем :mod:`.partstat_flow`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from ...calendar.callback_tokens import event_callback_token
from ...calendar.events import (
    collect_pending_invitations,
    format_invitation_list_lines,
)
from ...calendar.providers.base import (
    CalendarNotConnectedError,
    CalendarProviderError,
)
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
from ..visual import EFFECT_SPARKLES, private_message_effect, send_with_effect
from .access import ensure_calendar_connected
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    edit_callback_message,
    open_streaming_reply,
    safe_answer_callback,
)
from .partstat_flow import (
    PartstatFlow,
    respond_partstat,
)
from .partstat_flow import (
    find_event_by_token as _find_event_by_token,
)
from .settings_hub import show_settings_calendar_menu

__all__ = [
    "handle_open_invitations",
    "route_invitations_callback",
    "_find_event_by_token",
]

log = logging.getLogger(__name__)

_INVITATION_HORIZON_DAYS = 60
_MAX_INVITATIONS = 12
_INVITATIONS_OPEN_ACTION = "invitations:open"

# Двойной /invitations пока CalDAV ещё идёт — два одинаковых экрана.
_invitations_open_guard = ActionGuard(cooldown_sec=10.0)


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
    return _screen_from_pending(pending, ctx.tz, reference_date=today, truncated=truncated)


def _fetch_invitation_events(ctx: HandlerContext, user_id: int) -> tuple[list, str, datetime]:
    """Все события на горизонте приглашений (до фильтра NEEDS-ACTION)."""
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
    return events, login, now


def _fetch_pending(ctx: HandlerContext, user_id: int) -> tuple[list, str, bool]:
    events, login, now = _fetch_invitation_events(ctx, user_id)
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


def _fetch_all_for_token_lookup(ctx: HandlerContext, user_id: int) -> list:
    events, _login, _now = _fetch_invitation_events(ctx, user_id)
    return events


def handle_open_invitations(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    if not _invitations_open_guard.try_acquire(msg.chat_id, _INVITATIONS_OPEN_ACTION):
        log.info("Invitations open skipped (duplicate within cooldown): user_id=%s", msg.user_id)
        return
    sent = False
    try:
        stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id)
        stream.push(INVITATIONS_FETCH_STATUS)

        try:
            text, keyboard = _load_screen(ctx, msg.user_id)
        except CalendarNotConnectedError:
            text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
        except CalendarProviderError as exc:
            log.error("Invitations list failed user_id=%s: %s", msg.user_id, exc.error_code)
            text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
        stream.finish(text, reply_markup=keyboard)
        sent = True
        log.info("Opened invitations: user_id=%s", msg.user_id)
    finally:
        _invitations_open_guard.release(msg.chat_id, _INVITATIONS_OPEN_ACTION, sent=sent)


def _edit_invitations_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
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


def _on_success(ctx: HandlerContext, cb: IncomingCallback, code: str, _toast: str) -> None:
    """Приглашения: эффект и фиксированный текст шлём только для ACCEPTED."""
    if code != "a" or cb.chat_id is None:
        return
    send_with_effect(
        ctx.telegram,
        cb.chat_id,
        INVITATIONS_RESPOND_ACCEPTED,
        message_effect_id=private_message_effect(EFFECT_SPARKLES, cb.chat_id),
    )


def _on_not_found(ctx: HandlerContext, cb: IncomingCallback) -> None:
    _edit_invitations_screen(ctx, cb, toast=INVITATIONS_RESPOND_FAIL_TEXT)


_FLOW = PartstatFlow(
    prefix=CB_INV_RESPOND_PREFIX,
    fail_text=INVITATIONS_RESPOND_FAIL_TEXT,
    toast_by_code={
        "a": INVITATIONS_RESPOND_ACCEPTED,
        "d": INVITATIONS_RESPOND_DECLINED,
        "t": INVITATIONS_RESPOND_TENTATIVE,
    },
    log_name="Invitation",
    fetch_events=_fetch_all_for_token_lookup,
    refresh_view=_edit_invitations_screen,
    on_not_found=_on_not_found,
    on_success=_on_success,
)


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
        respond_partstat(ctx, cb, data, _FLOW)
        return True
    return False
