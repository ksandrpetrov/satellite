"""Web App connect / disconnect / check from Telegram buttons."""

from __future__ import annotations

import logging

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    CALENDAR_CHECK_FAIL_HTML,
    CALENDAR_CHECK_OK_HTML,
    CALENDAR_CONNECTED_HTML,
    CALENDAR_DISCONNECTED_HTML,
    CALENDAR_NOT_CONNECTED_HTML,
    CALENDAR_RECONNECT_INTRO_HTML,
    build_webapp_connect_keyboard,
)
from .access import ensure_calendar_access
from .context import HandlerContext, IncomingMessage
from .delivery import send

log = logging.getLogger(__name__)


def handle_connect_calendar_button(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None:
        return
    webapp_url = _webapp_url(ctx)
    if not webapp_url:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)
        return
    reconnect = bool(
        msg.user_id and ctx.users.get(msg.user_id) and ctx.users.get(msg.user_id).has_calendar
    )
    intro = CALENDAR_RECONNECT_INTRO_HTML if reconnect else CALENDAR_NOT_CONNECTED_HTML
    send(
        ctx,
        msg.chat_id,
        intro,
        reply_markup=build_webapp_connect_keyboard(webapp_url, reconnect=reconnect),
    )


def handle_check_calendar(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    try:
        status = ctx.calendar_service.check_connection(msg.user_id)
        send(
            ctx,
            msg.chat_id,
            CALENDAR_CHECK_OK_HTML if status.connected else CALENDAR_CHECK_FAIL_HTML,
        )
    except (CalendarNotConnectedError, CalendarProviderError):
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)


def handle_disconnect_calendar(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    try:
        ctx.calendar_service.disconnect(msg.user_id)
        send(ctx, msg.chat_id, CALENDAR_DISCONNECTED_HTML)
    except KeyError:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)


def _webapp_url(ctx: HandlerContext) -> str:
    base = ctx.webapp.base_url.rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/connect") else f"{base}/connect"
