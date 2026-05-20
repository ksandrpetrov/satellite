"""Общий экран настроек: дайджест, календари, подключение."""

from __future__ import annotations

import logging

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    CALENDAR_CHECK_FAIL_HTML,
    CALENDAR_CHECK_OK_HTML,
    CALENDAR_DISCONNECTED_HTML,
    CALENDAR_SOURCES_LOAD_FAIL_HTML,
    CALENDAR_SOURCES_SINGLE_HTML,
    CB_SETTINGS_BACK,
    CB_SETTINGS_CALENDARS,
    CB_SETTINGS_CHECK,
    CB_SETTINGS_CLOSE,
    CB_SETTINGS_DIGEST,
    CB_SETTINGS_DISCONNECT,
    SETTINGS_HUB_CLOSED_TEXT,
    SETTINGS_HUB_TEXT,
    build_settings_hub_keyboard,
)
from .calendar_view import enabled_url_set, fetch_calendars, screen_lines
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, safe_answer_callback, send
from .settings import show_digest_settings_screen

log = logging.getLogger(__name__)


def _webapp_url(ctx: HandlerContext) -> str:
    base = ctx.webapp.base_url.rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/connect") else f"{base}/connect"


def _has_calendar(ctx: HandlerContext, user_id: int) -> bool:
    record = ctx.users.get(user_id)
    return bool(record and record.has_calendar)


def handle_open_settings_hub(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    ctx.digest_state.clear(msg.chat_id)
    webapp_url = _webapp_url(ctx)
    keyboard = build_settings_hub_keyboard(
        webapp_url=webapp_url,
        has_calendar=_has_calendar(ctx, msg.user_id),
    )
    ctx.telegram.send_message(msg.chat_id, SETTINGS_HUB_TEXT, reply_markup=keyboard)
    log.info("Opened settings hub: chat_id=%s user_id=%s", msg.chat_id, msg.user_id)


def show_settings_hub_screen(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    ctx.digest_state.clear(cb.chat_id)
    webapp_url = _webapp_url(ctx)
    keyboard = build_settings_hub_keyboard(
        webapp_url=webapp_url,
        has_calendar=_has_calendar(ctx, cb.user_id),
    )
    edit_callback_message(ctx, cb, SETTINGS_HUB_TEXT, keyboard)


def route_settings_hub_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if data == CB_SETTINGS_DIGEST:
        show_digest_settings_screen(ctx, cb)
        return True
    if data == CB_SETTINGS_BACK:
        show_settings_hub_screen(ctx, cb)
        return True
    if data == CB_SETTINGS_CLOSE:
        if cb.chat_id is not None:
            ctx.digest_state.clear(cb.chat_id)
        edit_callback_message(ctx, cb, SETTINGS_HUB_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data == CB_SETTINGS_CALENDARS:
        _open_calendar_sources_from_callback(ctx, cb)
        return True
    if data == CB_SETTINGS_CHECK:
        _check_calendar_from_callback(ctx, cb)
        return True
    if data == CB_SETTINGS_DISCONNECT:
        _disconnect_calendar_from_callback(ctx, cb)
        return True
    return False


def _open_calendar_sources_from_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not _has_calendar(ctx, cb.user_id):
        safe_answer_callback(ctx, cb)
        return
    calendars = fetch_calendars(ctx, cb.user_id)
    if calendars is None:
        safe_answer_callback(ctx, cb, text="Не удалось загрузить календари")
        send(ctx, cb.chat_id, CALENDAR_SOURCES_LOAD_FAIL_HTML)
        return
    if len(calendars) <= 1:
        safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_SINGLE_HTML)
        return
    record = ctx.users.get(cb.user_id)
    if record is None:
        safe_answer_callback(ctx, cb)
        return
    from ...messages_ru import (
        build_calendar_sources_keyboard,
        calendar_sources_screen_text,
    )

    enabled_urls = enabled_url_set(record)
    text = calendar_sources_screen_text(lines=screen_lines(calendars, enabled_urls))
    keyboard = build_calendar_sources_keyboard(
        calendars=[(entry.name, entry.url) for entry in calendars],
        enabled_urls=enabled_urls,
    )
    edit_callback_message(ctx, cb, text, keyboard)
    safe_answer_callback(ctx, cb)
    log.info("Opened calendar sources from hub: user_id=%s", cb.user_id)


def _check_calendar_from_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        status = ctx.calendar_service.check_connection(cb.user_id)
        text = CALENDAR_CHECK_OK_HTML if status.connected else CALENDAR_CHECK_FAIL_HTML
    except (CalendarNotConnectedError, CalendarProviderError):
        text = CALENDAR_CHECK_FAIL_HTML
    send(ctx, cb.chat_id, text)
    safe_answer_callback(ctx, cb)


def _disconnect_calendar_from_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        ctx.calendar_service.disconnect(cb.user_id)
        send(ctx, cb.chat_id, CALENDAR_DISCONNECTED_HTML)
        show_settings_hub_screen(ctx, cb)
    except KeyError:
        safe_answer_callback(ctx, cb)
    else:
        safe_answer_callback(ctx, cb)
