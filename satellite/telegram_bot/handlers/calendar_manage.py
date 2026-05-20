"""Раздел «Изменить статус встречи»: список встреч на неделе и смена PARTSTAT.

Это «второй слой» поверх ``/invitations``:

- ``/invitations`` — inbox с NEEDS-ACTION, по ним нужно решить впервые.
- ``/manage``      — все встречи на ближайшую неделю, где пользователь
  числится как ATTENDEE (любой PARTSTAT), и решение можно поменять.

Список → детальный экран по встрече → ответ. После ответа возвращаемся в
список с тостом — чтобы можно было обработать несколько встреч подряд.
Удаление встречи здесь сознательно не делаем: DECLINE и так убирает её из
плана и дайджеста, а необратимый DELETE в массовом UX опасен.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta

from ...calendar.events import (
    collect_manageable_events,
    event_index_marker,
    event_local_start_date,
    format_time_range,
    format_upcoming_day_header,
    user_partstat,
)
from ...calendar.callback_tokens import event_callback_token
from ...calendar.providers.base import (
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ...messages_ru import (
    CB_MANAGE_BACK,
    CB_MANAGE_CLOSE,
    CB_MANAGE_PICK_PREFIX,
    CB_MANAGE_REFRESH,
    CB_MANAGE_RESPOND_PREFIX,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    MANAGE_CLOSED_TEXT,
    MANAGE_EMPTY_HTML,
    MANAGE_FETCH_STATUS,
    MANAGE_NOT_FOUND_TEXT,
    MANAGE_RESPOND_ACCEPTED,
    MANAGE_RESPOND_DECLINED,
    MANAGE_RESPOND_FAIL_TEXT,
    MANAGE_RESPOND_TENTATIVE,
    build_manage_detail_keyboard,
    build_manage_list_keyboard,
    manage_detail_html,
    manage_list_html,
)
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, open_streaming_reply, safe_answer_callback

log = logging.getLogger(__name__)

_HORIZON_DAYS = 7
_MAX_EVENTS = 12

_PARTSTAT_BY_CODE = {
    "a": "ACCEPTED",
    "d": "DECLINED",
    "t": "TENTATIVE",
}

_TOAST_BY_CODE = {
    "a": MANAGE_RESPOND_ACCEPTED,
    "d": MANAGE_RESPOND_DECLINED,
    "t": MANAGE_RESPOND_TENTATIVE,
}


def _fetch_manageable(
    ctx: HandlerContext, user_id: int
) -> tuple[list, str, bool]:
    now = datetime.now(tz=ctx.tz)
    today = now.date()
    end = today + timedelta(days=_HORIZON_DAYS)
    connected = ctx.calendar_service.require_connection(user_id)
    login = connected.context.login
    events = ctx.calendar_service.list_events_for_invitations(
        user_id,
        start_date=today,
        end_date=end,
        tz=ctx.tz,
    )
    manageable = collect_manageable_events(
        events,
        login,
        ctx.tz,
        now=now,
        max_events=_MAX_EVENTS + 1,
    )
    truncated = len(manageable) > _MAX_EVENTS
    if truncated:
        manageable = manageable[:_MAX_EVENTS]
    return manageable, login, truncated


def _format_list_lines(
    events: list, tz, reference_date: date
) -> list[str]:
    """Строки тела списка: заголовок дня + пронумерованные встречи со статусом.

    Отличие от ``format_invitation_list_lines``: тут показываем ещё и текущий
    PARTSTAT, чтобы пользователь видел, что именно нужно править.
    """
    if not events:
        return []
    lines: list[str] = []
    last_day: date | None = None
    for idx, ev in enumerate(events):
        day = event_local_start_date(ev, tz)
        if day is not None and day != last_day:
            if lines:
                lines.append("")
            lines.append(
                f"<b>{format_upcoming_day_header(day, reference_date)}</b>"
            )
            last_day = day
        marker = event_index_marker(idx)
        title = html.escape(str(ev.get("summary") or "—"))
        when = format_time_range(ev, tz)
        lines.append(f"{marker} {when} — {title}")
    return lines


def _build_list_screen(
    events: list, *, tz, reference_date: date, truncated: bool
) -> tuple[str, dict]:
    if not events:
        return MANAGE_EMPTY_HTML, build_manage_list_keyboard([])
    body = _format_list_lines(events, tz, reference_date)
    rows: list[tuple[str, str]] = []
    for idx, ev in enumerate(events):
        token = event_callback_token(str(ev.get("url") or ""))
        marker = event_index_marker(idx)
        title = str(ev.get("summary") or "—")
        when = format_time_range(ev, tz)
        rows.append((token, f"{marker} {when} · {title}"))
    text = manage_list_html(body_lines=body, truncated=truncated)
    return text, build_manage_list_keyboard(rows)


def _load_list_screen(ctx: HandlerContext, user_id: int) -> tuple[str, dict]:
    events, _login, truncated = _fetch_manageable(ctx, user_id)
    today = datetime.now(tz=ctx.tz).date()
    return _build_list_screen(
        events, tz=ctx.tz, reference_date=today, truncated=truncated
    )


def _find_event_by_token(events: list, token: str):
    needle = (token or "").strip()
    if not needle:
        return None
    for ev in events:
        if event_callback_token(str(ev.get("url") or "")) == needle:
            return ev
    return None


def _detail_screen_for(
    ctx: HandlerContext, event, login: str
) -> tuple[str, dict]:
    token = event_callback_token(str(event.get("url") or ""))
    title = html.escape(str(event.get("summary") or "—"))
    day = event_local_start_date(event, ctx.tz)
    today = datetime.now(tz=ctx.tz).date()
    day_header = (
        format_upcoming_day_header(day, today) if day is not None else "—"
    )
    when = f"{day_header} · {format_time_range(event, ctx.tz)}"
    partstat = user_partstat(event, login)
    text = manage_detail_html(title=title, when=when, partstat=partstat)
    keyboard = build_manage_detail_keyboard(token, partstat=partstat)
    return text, keyboard


# --- entry points ----------------------------------------------------------


def handle_open_manage_events(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if (
        not ensure_calendar_connected(ctx, msg)
        or msg.chat_id is None
        or msg.user_id is None
    ):
        return
    stream = open_streaming_reply(
        ctx, msg.chat_id, MANAGE_FETCH_STATUS, draft_id=msg.update_id
    )

    try:
        text, keyboard = _load_list_screen(ctx, msg.user_id)
    except CalendarNotConnectedError:
        text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
    except CalendarProviderError as exc:
        log.error("Manage list failed user_id=%s: %s", msg.user_id, exc.error_code)
        text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
    stream.finish(text, reply_markup=keyboard)
    log.info("Opened manage events: user_id=%s", msg.user_id)


def _refresh_list(
    ctx: HandlerContext, cb: IncomingCallback, *, toast: str | None = None
) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb, text=toast)
        return
    try:
        text, keyboard = _load_list_screen(ctx, cb.user_id)
    except (CalendarNotConnectedError, CalendarProviderError):
        text, keyboard = ERR_CALDAV_UNAVAILABLE_TEXT, None
    edit_callback_message(ctx, cb, text, keyboard)
    safe_answer_callback(ctx, cb, text=toast)


def _open_detail(ctx: HandlerContext, cb: IncomingCallback, token: str) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        events, login, _ = _fetch_manageable(ctx, cb.user_id)
    except (CalendarNotConnectedError, CalendarProviderError):
        edit_callback_message(ctx, cb, ERR_CALDAV_UNAVAILABLE_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return
    event = _find_event_by_token(events, token)
    if event is None:
        _refresh_list(ctx, cb, toast=MANAGE_NOT_FOUND_TEXT)
        return
    text, keyboard = _detail_screen_for(ctx, event, login)
    edit_callback_message(ctx, cb, text, keyboard)
    safe_answer_callback(ctx, cb)


def _handle_respond(ctx: HandlerContext, cb: IncomingCallback, data: str) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    suffix = data[len(CB_MANAGE_RESPOND_PREFIX) :]
    if ":" not in suffix:
        safe_answer_callback(ctx, cb)
        return
    token, code = suffix.rsplit(":", 1)
    partstat = _PARTSTAT_BY_CODE.get(code.strip().lower())
    if not partstat:
        safe_answer_callback(ctx, cb)
        return
    try:
        events, _login, _ = _fetch_manageable(ctx, cb.user_id)
        event = _find_event_by_token(events, token)
        if event is None:
            _refresh_list(ctx, cb, toast=MANAGE_NOT_FOUND_TEXT)
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
            "Manage respond failed user_id=%s: %s",
            cb.user_id,
            getattr(exc, "error_code", exc.__class__.__name__),
        )
        safe_answer_callback(ctx, cb, text=MANAGE_RESPOND_FAIL_TEXT)
        return
    toast = _TOAST_BY_CODE.get(code.strip().lower(), MANAGE_RESPOND_ACCEPTED)
    _refresh_list(ctx, cb, toast=toast)


def route_manage_events_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data or not data.startswith("mng:"):
        return False
    if data == CB_MANAGE_CLOSE:
        edit_callback_message(ctx, cb, MANAGE_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data in (CB_MANAGE_BACK, CB_MANAGE_REFRESH):
        _refresh_list(ctx, cb)
        return True
    if data.startswith(CB_MANAGE_PICK_PREFIX):
        token = data[len(CB_MANAGE_PICK_PREFIX) :]
        _open_detail(ctx, cb, token)
        return True
    if data.startswith(CB_MANAGE_RESPOND_PREFIX):
        _handle_respond(ctx, cb, data)
        return True
    return False
