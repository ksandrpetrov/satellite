"""Просмотр событий в календарях, пошаренных на аккаунт пользователя."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ...calendar.events import format_single_day_events_lines
from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...calendar.selection import foreign_calendar_entries
from ...messages_ru import (
    CALENDAR_NOT_CONNECTED_HTML,
    CB_FOREIGN_BACK,
    CB_FOREIGN_CLOSE,
    CB_FOREIGN_DAY_PREFIX,
    CB_FOREIGN_PICK_PREFIX,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    FOREIGN_CALENDARS_CLOSED_TEXT,
    FOREIGN_CALENDARS_DAY_EMPTY_HTML,
    FOREIGN_CALENDARS_EMPTY_HTML,
    FOREIGN_CALENDARS_FETCH_STATUS,
    FOREIGN_CALENDARS_INTRO_HTML,
    FOREIGN_CALENDARS_LOAD_FAIL_HTML,
    FOREIGN_CALENDARS_LOADING_TOAST,
    FOREIGN_CALENDARS_REFRESH_FAIL_TEXT,
    build_foreign_calendars_keyboard,
    build_foreign_day_keyboard,
    foreign_calendars_day_result_text,
    foreign_calendars_pick_day_text,
)
from ..chat_action import run_with_typing_action
from .access import ensure_calendar_connected
from .calendar_view import CalendarListStatus, fetch_calendars, normalize_calendar_url
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, safe_answer_callback, send

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ForeignResult:
    status: CalendarListStatus
    entries: tuple = ()

    @property
    def ok(self) -> bool:
        return self.status is CalendarListStatus.OK


def _foreign_calendars(ctx: HandlerContext, user_id: int) -> _ForeignResult:
    record = ctx.users.get(user_id)
    if record is None:
        return _ForeignResult(status=CalendarListStatus.NOT_CONNECTED)
    result = fetch_calendars(ctx, user_id)
    if not result.ok:
        return _ForeignResult(status=result.status)
    foreign = foreign_calendar_entries(
        list(result.calendars),
        primary_calendar_url=record.primary_calendar_url,
    )
    return _ForeignResult(status=CalendarListStatus.OK, entries=tuple(foreign))


def handle_open_foreign_calendars(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    result = _foreign_calendars(ctx, msg.user_id)
    if result.status is CalendarListStatus.NOT_CONNECTED:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)
        return
    if not result.ok:
        send(ctx, msg.chat_id, FOREIGN_CALENDARS_LOAD_FAIL_HTML)
        return
    foreign = list(result.entries)
    if not foreign:
        send(ctx, msg.chat_id, FOREIGN_CALENDARS_EMPTY_HTML)
        return
    keyboard = build_foreign_calendars_keyboard(
        calendars=[(entry.name, entry.url) for entry in foreign],
    )
    ctx.telegram.send_message(
        msg.chat_id,
        FOREIGN_CALENDARS_INTRO_HTML,
        reply_markup=keyboard,
    )
    log.info("Opened foreign calendars: user_id=%s count=%d", msg.user_id, len(foreign))


def route_foreign_calendars_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data:
        return False
    if data == CB_FOREIGN_CLOSE:
        _handle_close(ctx, cb)
        return True
    if data == CB_FOREIGN_BACK:
        _handle_back(ctx, cb)
        return True
    if data.startswith(CB_FOREIGN_PICK_PREFIX):
        _handle_pick(ctx, cb, data)
        return True
    if data.startswith(CB_FOREIGN_DAY_PREFIX):
        _handle_day(ctx, cb, data)
        return True
    return False


def _handle_close(ctx: HandlerContext, cb: IncomingCallback) -> None:
    edit_callback_message(ctx, cb, FOREIGN_CALENDARS_CLOSED_TEXT, reply_markup=None)
    safe_answer_callback(ctx, cb)
    log.info("Closed foreign calendars: user_id=%s", cb.user_id)


def _handle_back(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    result = _foreign_calendars(ctx, cb.user_id)
    if not result.ok:
        safe_answer_callback(ctx, cb, text=FOREIGN_CALENDARS_REFRESH_FAIL_TEXT)
        return
    foreign = list(result.entries)
    if not foreign:
        edit_callback_message(ctx, cb, FOREIGN_CALENDARS_EMPTY_HTML, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return
    keyboard = build_foreign_calendars_keyboard(
        calendars=[(entry.name, entry.url) for entry in foreign],
    )
    edit_callback_message(ctx, cb, FOREIGN_CALENDARS_INTRO_HTML, reply_markup=keyboard)
    safe_answer_callback(ctx, cb)


def _handle_pick(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    result = _foreign_calendars(ctx, cb.user_id)
    if not result.ok:
        safe_answer_callback(ctx, cb, text=FOREIGN_CALENDARS_REFRESH_FAIL_TEXT)
        return
    foreign = list(result.entries)
    try:
        idx = int(data[len(CB_FOREIGN_PICK_PREFIX) :])
    except ValueError:
        safe_answer_callback(ctx, cb)
        return
    if idx < 0 or idx >= len(foreign):
        safe_answer_callback(ctx, cb)
        return
    entry = foreign[idx]
    text = foreign_calendars_pick_day_text(calendar_name=entry.name)
    keyboard = build_foreign_day_keyboard(calendar_idx=idx)
    edit_callback_message(ctx, cb, text, reply_markup=keyboard)
    safe_answer_callback(ctx, cb)


def _handle_day(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    result = _foreign_calendars(ctx, cb.user_id)
    if not result.ok:
        safe_answer_callback(ctx, cb, text=FOREIGN_CALENDARS_REFRESH_FAIL_TEXT)
        return
    foreign = list(result.entries)
    payload = data[len(CB_FOREIGN_DAY_PREFIX) :]
    try:
        idx_str, day_offset_str = payload.split(":", 1)
        idx = int(idx_str)
        day_offset = int(day_offset_str)
    except ValueError:
        safe_answer_callback(ctx, cb)
        return
    if idx < 0 or idx >= len(foreign) or day_offset not in (0, 1, 2):
        safe_answer_callback(ctx, cb)
        return
    entry = foreign[idx]
    calendar_url = normalize_calendar_url(entry.url)
    today = datetime.now(tz=ctx.tz).date()
    target_date = today + timedelta(days=day_offset)
    edit_callback_message(ctx, cb, FOREIGN_CALENDARS_FETCH_STATUS, reply_markup=None)
    safe_answer_callback(ctx, cb, text=FOREIGN_CALENDARS_LOADING_TOAST)

    def build() -> str:
        events = ctx.calendar_service.list_events(
            cb.user_id,
            start_date=target_date,
            end_date=target_date,
            tz=ctx.tz,
            calendar_urls=(calendar_url,),
        )
        lines = format_single_day_events_lines(
            events, ctx.tz, target_date, reference_date=today
        )
        if not lines:
            return FOREIGN_CALENDARS_DAY_EMPTY_HTML
        return foreign_calendars_day_result_text(
            calendar_name=entry.name,
            body_lines=lines,
        )

    try:
        text = run_with_typing_action(ctx.telegram, cb.chat_id, build)
    except CalendarNotConnectedError:
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    except CalendarProviderError as exc:
        log.error(
            "Foreign calendar day failed user_id=%s calendar=%s: %s",
            cb.user_id,
            calendar_url[:48],
            exc.error_code,
        )
        text = ERR_CALDAV_UNAVAILABLE_TEXT

    edit_callback_message(ctx, cb, text, reply_markup=None)
    log.info(
        "Foreign calendar day: user_id=%s idx=%d offset=%d",
        cb.user_id,
        idx,
        day_offset,
    )
