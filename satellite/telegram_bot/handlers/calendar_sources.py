"""Выбор календарей, которые учитываются в плане и дайджесте."""

from __future__ import annotations

import logging

from ...calendar.providers.base import CalendarListEntry, CalendarProviderError
from ...calendar.selection import effective_enabled_calendar_urls
from ...messages_ru import (
    CALENDAR_SOURCES_LAST_ENABLED_TEXT,
    CALENDAR_SOURCES_LOAD_FAIL_HTML,
    CALENDAR_SOURCES_SINGLE_HTML,
    CB_CAL_CLOSE,
    CB_CAL_TOGGLE_PREFIX,
    build_calendar_sources_keyboard,
    calendar_sources_screen_text,
    calendar_sources_toggle_notice,
)
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, safe_answer_callback, send

log = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def _enabled_url_set(record) -> set[str]:
    return {_normalize_url(url) for url in effective_enabled_calendar_urls(record)}


def _screen_lines(
    calendars: list[CalendarListEntry], enabled_urls: set[str]
) -> list[str]:
    lines: list[str] = []
    for entry in calendars:
        mark = "✅" if _normalize_url(entry.url) in enabled_urls else "⬜️"
        lines.append(f"{mark} {entry.name}")
    return lines


def _fetch_calendars(ctx: HandlerContext, user_id: int) -> list[CalendarListEntry] | None:
    try:
        return ctx.calendar_service.list_calendars(user_id)
    except CalendarProviderError:
        log.warning("Failed to list calendars for user_id=%s", user_id)
        return None


def handle_open_calendar_sources(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    record = ctx.users.get(msg.user_id)
    if record is None or not record.has_calendar:
        return
    calendars = _fetch_calendars(ctx, msg.user_id)
    if calendars is None:
        send(ctx, msg.chat_id, CALENDAR_SOURCES_LOAD_FAIL_HTML)
        return
    if len(calendars) <= 1:
        send(ctx, msg.chat_id, CALENDAR_SOURCES_SINGLE_HTML)
        return
    enabled_urls = _enabled_url_set(record)
    text = calendar_sources_screen_text(lines=_screen_lines(calendars, enabled_urls))
    keyboard = build_calendar_sources_keyboard(
        calendars=[(entry.name, entry.url) for entry in calendars],
        enabled_urls=enabled_urls,
    )
    ctx.telegram.send_message(msg.chat_id, text, reply_markup=keyboard)
    log.info("Opened calendar sources: user_id=%s count=%d", msg.user_id, len(calendars))


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
        edit_callback_message(
            ctx,
            cb.chat_id,
            cb.message_id,
            CALENDAR_SOURCES_CLOSED_TEXT,
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
    try:
        idx = int(data[len(CB_CAL_TOGGLE_PREFIX) :])
    except ValueError:
        safe_answer_callback(ctx, cb)
        return
    calendars = _fetch_calendars(ctx, cb.user_id)
    if calendars is None:
        safe_answer_callback(ctx, cb, text="Не удалось обновить список")
        return
    if idx < 0 or idx >= len(calendars):
        safe_answer_callback(ctx, cb)
        return
    if len(calendars) <= 1:
        safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_SINGLE_HTML)
        return

    target = calendars[idx]
    target_url = _normalize_url(target.url)
    current = set(_enabled_url_set(record))
    if target_url in current:
        if len(current) <= 1:
            safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_LAST_ENABLED_TEXT)
            return
        current.remove(target_url)
        enabled_now = False
    else:
        current.add(target_url)
        enabled_now = True

    updated = ctx.users.set_enabled_calendar_urls(
        cb.user_id, calendar_urls=sorted(current)
    )
    enabled_urls = _enabled_url_set(updated)
    text = calendar_sources_screen_text(lines=_screen_lines(calendars, enabled_urls))
    keyboard = build_calendar_sources_keyboard(
        calendars=[(entry.name, entry.url) for entry in calendars],
        enabled_urls=enabled_urls,
    )
    edit_callback_message(
        ctx, cb.chat_id, cb.message_id, text, reply_markup=keyboard
    )
    notice = calendar_sources_toggle_notice(enabled=enabled_now, name=target.name)
    safe_answer_callback(ctx, cb, text=notice)
    log.info(
        "Toggled calendar source: user_id=%s url=%s enabled=%s",
        cb.user_id,
        target_url[:48],
        enabled_now,
    )
