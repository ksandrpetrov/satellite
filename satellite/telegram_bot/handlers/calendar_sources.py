"""Выбор календарей, которые учитываются в плане и дайджесте."""

from __future__ import annotations

import logging

from ...calendar.selection import calendar_callback_token, find_calendar_entry_by_token
from ...messages_ru import (
    CALENDAR_NOT_CONNECTED_HTML,
    CALENDAR_SOURCES_CLOSED_TEXT,
    CALENDAR_SOURCES_FETCH_STATUS,
    CALENDAR_SOURCES_LAST_ENABLED_TEXT,
    CALENDAR_SOURCES_LOAD_FAIL_HTML,
    CALENDAR_SOURCES_SINGLE_HTML,
    CB_CAL_CLOSE,
    CB_CAL_TOGGLE_PREFIX,
    build_calendar_sources_keyboard,
)
from ..presenters.calendar_screens import calendar_sources_bundle
from .calendar_view import (
    CalendarSourcesScreenStatus,
    build_calendar_sources_screen,
    enabled_url_set,
    fetch_calendars,
    normalize_calendar_url,
)
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    ack_callback_with_loading,
    edit_callback_bundle,
    edit_callback_rich_or_html,
    safe_answer_callback,
    send,
    send_rich_or_html,
)

log = logging.getLogger(__name__)


def _sources_bundle(calendars: list, enabled_urls: set[str]) -> tuple:
    pairs = [(entry.name, entry.url) for entry in calendars]
    keyboard = build_calendar_sources_keyboard(
        calendars=pairs,
        enabled_urls=enabled_urls,
        url_tokens=[calendar_callback_token(url) for _name, url in pairs],
    )
    bundle = calendar_sources_bundle(
        calendars=calendars,
        enabled_urls=enabled_urls,
        reply_markup=keyboard,
    )
    return bundle, keyboard


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
    if screen.text is None or screen.keyboard is None:
        return
    record = ctx.users.get(msg.user_id)
    if record is None:
        return
    bundle, _keyboard = _sources_bundle(
        list(screen.calendars),
        enabled_url_set(record),
    )
    send_rich_or_html(
        ctx,
        msg.chat_id,
        rich_html=bundle.rich_html,
        fallback_html=bundle.fallback_html,
        reply_markup=bundle.reply_markup,
    )
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
    if cb.chat_id is not None and cb.message_id is not None:
        edit_callback_rich_or_html(
            ctx,
            cb,
            rich_html=CALENDAR_SOURCES_CLOSED_TEXT,
            fallback_html=CALENDAR_SOURCES_CLOSED_TEXT,
            reply_markup=None,
        )
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
    ack_callback_with_loading(ctx, cb, status_html=CALENDAR_SOURCES_FETCH_STATUS)
    result = fetch_calendars(ctx, cb.user_id, prefer_cache=True)
    if not result.ok:
        edit_callback_rich_or_html(
            ctx,
            cb,
            rich_html=CALENDAR_SOURCES_LOAD_FAIL_HTML,
            fallback_html=CALENDAR_SOURCES_LOAD_FAIL_HTML,
            reply_markup=None,
        )
        return
    calendars = list(result.calendars)
    target = find_calendar_entry_by_token(calendars, token)
    if target is None:
        return
    if len(calendars) <= 1:
        edit_callback_rich_or_html(
            ctx,
            cb,
            rich_html=CALENDAR_SOURCES_SINGLE_HTML,
            fallback_html=CALENDAR_SOURCES_SINGLE_HTML,
            reply_markup=None,
        )
        return
    target_url = normalize_calendar_url(target.url)
    current = set(enabled_url_set(record))
    if target_url in current:
        if len(current) <= 1:
            send(ctx, cb.chat_id, CALENDAR_SOURCES_LAST_ENABLED_TEXT)
            return
        current.remove(target_url)
        enabled_now = False
    else:
        current.add(target_url)
        enabled_now = True

    updated = ctx.users.set_enabled_calendar_urls(cb.user_id, calendar_urls=sorted(current))
    enabled_urls = enabled_url_set(updated)
    bundle, _keyboard = _sources_bundle(calendars, enabled_urls)
    edit_callback_bundle(ctx, cb, bundle)
    log.info(
        "Toggled calendar source: user_id=%s url=%s enabled=%s",
        cb.user_id,
        target_url[:48],
        enabled_now,
    )
