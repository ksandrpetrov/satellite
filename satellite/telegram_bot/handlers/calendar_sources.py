"""Выбор календарей, которые учитываются в плане и дайджесте."""

from __future__ import annotations

import logging

from ...calendar.selection import calendar_callback_token, find_calendar_entry_by_token
from ...messages_ru import (
    CALENDAR_NOT_CONNECTED_HTML,
    CALENDAR_SOURCES_LAST_ENABLED_TEXT,
    CALENDAR_SOURCES_LOAD_FAIL_HTML,
    CALENDAR_SOURCES_SINGLE_HTML,
    CALENDAR_SOURCES_UPDATE_FAIL_TEXT,
    CB_CAL_CLOSE,
    CB_CAL_TOGGLE_PREFIX,
    build_calendar_sources_keyboard,
    calendar_sources_screen_text,
    calendar_sources_toggle_notice,
)
from .calendar_view import (
    CalendarSourcesScreenStatus,
    build_calendar_sources_screen,
    enabled_url_set,
    fetch_calendars,
    normalize_calendar_url,
    screen_lines,
)
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, safe_answer_callback, send

log = logging.getLogger(__name__)


def handle_open_calendar_sources(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    record = ctx.users.get(msg.user_id)
    if record is None or not record.has_calendar:
        return
    screen = build_calendar_sources_screen(ctx, msg.user_id)
    if screen.status is CalendarSourcesScreenStatus.NOT_CONNECTED:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)
        return
    if screen.status is CalendarSourcesScreenStatus.UNAVAILABLE:
        send(ctx, msg.chat_id, CALENDAR_SOURCES_LOAD_FAIL_HTML)
        return
    if screen.status is CalendarSourcesScreenStatus.SINGLE:
        send(ctx, msg.chat_id, CALENDAR_SOURCES_SINGLE_HTML)
        return
    if screen.status is not CalendarSourcesScreenStatus.SCREEN:
        return
    ctx.telegram.send_message(msg.chat_id, screen.text, reply_markup=screen.keyboard)
    log.info("Opened calendar sources: user_id=%s", msg.user_id)


def route_calendar_sources_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data:
        return False
    if data == CB_CAL_CLOSE:
        _handle_close(ctx, cb)
        return True
    if data.startswith(CB_CAL_TOGGLE_PREFIX):
        _handle_toggle(ctx, cb, data)
        return True
    return False


def _handle_close(ctx: HandlerContext, cb: IncomingCallback) -> None:
    from ...messages_ru import CALENDAR_SOURCES_CLOSED_TEXT

    if cb.chat_id is not None and cb.message_id is not None:
        edit_callback_message(ctx, cb, CALENDAR_SOURCES_CLOSED_TEXT, reply_markup=None)
    safe_answer_callback(ctx, cb)
    log.info("Closed calendar sources: user_id=%s", cb.user_id)


def _handle_toggle(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None or cb.chat_id is None or cb.message_id is None:
        safe_answer_callback(ctx, cb)
        return
    record = ctx.users.get(cb.user_id)
    if record is None or not record.has_calendar:
        safe_answer_callback(ctx, cb)
        return
    token = data[len(CB_CAL_TOGGLE_PREFIX) :].strip()
    if not token:
        safe_answer_callback(ctx, cb)
        return
    result = fetch_calendars(ctx, cb.user_id)
    if not result.ok:
        safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_UPDATE_FAIL_TEXT)
        return
    calendars = list(result.calendars)
    target = find_calendar_entry_by_token(calendars, token)
    if target is None:
        safe_answer_callback(ctx, cb)
        return
    if len(calendars) <= 1:
        safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_SINGLE_HTML)
        return
    target_url = normalize_calendar_url(target.url)
    current = set(enabled_url_set(record))
    if target_url in current:
        if len(current) <= 1:
            safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_LAST_ENABLED_TEXT)
            return
        current.remove(target_url)
        enabled_now = False
    else:
        current.add(target_url)
        enabled_now = True

    updated = ctx.users.set_enabled_calendar_urls(cb.user_id, calendar_urls=sorted(current))
    enabled_urls = enabled_url_set(updated)
    text = calendar_sources_screen_text(lines=screen_lines(calendars, enabled_urls))
    pairs = [(entry.name, entry.url) for entry in calendars]
    keyboard = build_calendar_sources_keyboard(
        calendars=pairs,
        enabled_urls=enabled_urls,
        url_tokens=[calendar_callback_token(url) for _name, url in pairs],
    )
    edit_callback_message(ctx, cb, text, reply_markup=keyboard)
    notice = calendar_sources_toggle_notice(enabled=enabled_now, name=target.name)
    safe_answer_callback(ctx, cb, text=notice)
    log.info(
        "Toggled calendar source: user_id=%s url=%s enabled=%s",
        cb.user_id,
        target_url[:48],
        enabled_now,
    )
