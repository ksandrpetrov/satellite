"""Раздел «Изменить статус встречи»: список встреч на неделе и смена PARTSTAT.

Это «второй слой» поверх ``/invitations``:

- ``/invitations`` — inbox с NEEDS-ACTION, по ним нужно решить впервые.
- ``/manage``      — все встречи на ближайшую неделю, где пользователь
  числится как ATTENDEE (любой PARTSTAT), и решение можно поменять.

Список → детальный экран по встрече → ответ. После ответа возвращаемся в
список с тостом — чтобы можно было обработать несколько встреч подряд.
Удаление встречи здесь сознательно не делаем: DECLINE и так убирает её из
плана и дайджеста, а необратимый DELETE в массовом UX опасен.

Общий поток PARTSTAT-ответа делегирован :mod:`.partstat_flow`.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta

from ...calendar.callback_tokens import event_callback_token
from ...calendar.event_token_cache import apply_user_partstat_to_event, get_event_token_cache
from ...calendar.events import (
    collect_manageable_events,
    event_index_marker,
    event_local_start_date,
    format_time_range,
    format_upcoming_day_header,
    user_partstat,
)
from ...calendar.providers.base import (
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
    MANAGE_BUSY_TEXT,
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
from ..presenters.calendar_lists import (
    manage_detail_rich_html,
    manage_list_body_lines,
    manage_list_rich_html,
)
from .access import ensure_calendar_connected
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    ack_callback_with_loading,
    edit_callback_message,
    edit_callback_rich_or_html,
    open_streaming_reply,
    safe_answer_callback,
    send,
)
from .partstat_flow import PartstatFlow, find_event_by_token, respond_partstat

log = logging.getLogger(__name__)

_HORIZON_DAYS = 7
_MAX_EVENTS = 12
_MANAGE_OPEN_ACTION = "manage:open"

# Двойной /manage пока CalDAV ещё идёт — два одинаковых экрана.
_manage_open_guard = ActionGuard(cooldown_sec=10.0)


def _fetch_manageable(ctx: HandlerContext, user_id: int) -> tuple[list, str, bool]:
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
    get_event_token_cache().register_manage_screen(
        user_id,
        events=manageable,
        login=login,
        moment=now,
        truncated=truncated,
    )
    return manageable, login, truncated


def _fetch_manageable_events_only(ctx: HandlerContext, user_id: int) -> list:
    events, _login, _ = _fetch_manageable(ctx, user_id)
    return events


def _build_list_screen(
    events: list, *, tz, reference_date: date, truncated: bool
) -> tuple[str, str, dict]:
    if not events:
        empty = MANAGE_EMPTY_HTML
        return empty, empty, build_manage_list_keyboard([])
    body = manage_list_body_lines(events, tz, reference_date)
    rows: list[tuple[str, str]] = []
    for idx, ev in enumerate(events):
        token = event_callback_token(str(ev.get("url") or ""))
        marker = event_index_marker(idx)
        title = str(ev.get("summary") or "—")
        when = format_time_range(ev, tz)
        rows.append((token, f"{marker} {when} · {title}"))
    fallback = manage_list_html(body_lines=body, truncated=truncated)
    rich = manage_list_rich_html(
        body_events=events,
        tz=tz,
        reference_date=reference_date,
        truncated=truncated,
    )
    return rich, fallback, build_manage_list_keyboard(rows)


def _load_list_screen(ctx: HandlerContext, user_id: int) -> tuple[str, str, dict]:
    events, _login, truncated = _fetch_manageable(ctx, user_id)
    today = datetime.now(tz=ctx.tz).date()
    return _build_list_screen(events, tz=ctx.tz, reference_date=today, truncated=truncated)


def _detail_screen_for(ctx: HandlerContext, event, login: str) -> tuple[str, str, dict]:
    token = event_callback_token(str(event.get("url") or ""))
    title_raw = str(event.get("summary") or "—")
    title = html.escape(title_raw)
    day = event_local_start_date(event, ctx.tz)
    today = datetime.now(tz=ctx.tz).date()
    day_header = format_upcoming_day_header(day, today) if day is not None else "—"
    when = f"{day_header} · {format_time_range(event, ctx.tz)}"
    partstat = user_partstat(event, login)
    fallback = manage_detail_html(title=title, when=when, partstat=partstat)
    rich = manage_detail_rich_html(title=title_raw, when=when, partstat=partstat)
    keyboard = build_manage_detail_keyboard(token, partstat=partstat)
    return rich, fallback, keyboard


# --- entry points ----------------------------------------------------------


def handle_open_manage_events(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    if not _manage_open_guard.try_acquire(msg.chat_id, _MANAGE_OPEN_ACTION):
        log.info("Manage open skipped (duplicate within cooldown): user_id=%s", msg.user_id)
        send(ctx, msg.chat_id, MANAGE_BUSY_TEXT)
        return
    sent = False
    try:
        stream = open_streaming_reply(
            ctx,
            msg.chat_id,
            initial_text=MANAGE_FETCH_STATUS,
            draft_id=msg.update_id,
            rich=True,
        )

        try:
            rich_text, fallback_text, keyboard = _load_list_screen(ctx, msg.user_id)
        except CalendarNotConnectedError:
            log.error("Manage list failed user_id=%s: not connected", msg.user_id)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return
        except CalendarProviderError as exc:
            log.error("Manage list failed user_id=%s: %s", msg.user_id, exc.error_code)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return
        stream.finish(
            rich_text,
            fallback_html=fallback_text,
            rich=True,
            reply_markup=keyboard,
        )
        sent = True
        log.info("Opened manage events: user_id=%s", msg.user_id)
    finally:
        _manage_open_guard.release(msg.chat_id, _MANAGE_OPEN_ACTION, sent=sent)


def _refresh_list(
    ctx: HandlerContext,
    cb: IncomingCallback,
    toast: str | None = None,
    *,
    show_loading: bool = False,
    ack: bool = True,
) -> None:
    if cb.user_id is None:
        if ack:
            safe_answer_callback(ctx, cb, text=toast)
        return
    if show_loading:
        ack_callback_with_loading(ctx, cb, status_html=MANAGE_FETCH_STATUS)
        ack = False
    try:
        rich_text, fallback_text, keyboard = _load_list_screen(ctx, cb.user_id)
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


def _open_detail(ctx: HandlerContext, cb: IncomingCallback, token: str) -> None:
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    ack_callback_with_loading(ctx, cb, status_html=MANAGE_FETCH_STATUS)
    cache = get_event_token_cache()
    snapshot = cache.get_manage_snapshot(cb.user_id)
    if snapshot is not None:
        event = find_event_by_token(snapshot.events, token)
        if event is not None:
            rich_text, fallback_text, keyboard = _detail_screen_for(ctx, event, snapshot.login)
            edit_callback_rich_or_html(
                ctx,
                cb,
                rich_html=rich_text,
                fallback_html=fallback_text,
                reply_markup=keyboard,
            )
            return
    try:
        events, login, _ = _fetch_manageable(ctx, cb.user_id)
    except (CalendarNotConnectedError, CalendarProviderError):
        edit_callback_message(ctx, cb, ERR_CALDAV_UNAVAILABLE_TEXT, reply_markup=None)
        return
    event = find_event_by_token(events, token)
    if event is None:
        _refresh_list(ctx, cb, toast=MANAGE_NOT_FOUND_TEXT, ack=False)
        return
    rich_text, fallback_text, keyboard = _detail_screen_for(ctx, event, login)
    edit_callback_rich_or_html(
        ctx,
        cb,
        rich_html=rich_text,
        fallback_html=fallback_text,
        reply_markup=keyboard,
    )


def _optimistic_refresh_list(
    ctx: HandlerContext,
    cb: IncomingCallback,
    token: str,
    partstat: str,
    fallback_events: list | None,
) -> None:
    if cb.user_id is None or cb.chat_id is None:
        return
    cache = get_event_token_cache()
    existing = cache.get_manage_snapshot(cb.user_id)
    if existing is not None:
        snapshot = cache.update_manage_partstat(
            cb.user_id,
            token,
            existing.login,
            partstat,
        )
        if snapshot is not None:
            rich_text, fallback_text, keyboard = _build_list_screen(
                snapshot.events,
                tz=ctx.tz,
                reference_date=snapshot.moment.date(),
                truncated=snapshot.truncated,
            )
            edit_callback_rich_or_html(
                ctx,
                cb,
                rich_html=rich_text,
                fallback_html=fallback_text,
                reply_markup=keyboard,
            )
            return
    if fallback_events is not None:
        connected = ctx.calendar_service.require_connection(cb.user_id)
        login = connected.context.login
        moment = datetime.now(tz=ctx.tz)
        manageable = collect_manageable_events(
            fallback_events,
            login,
            ctx.tz,
            now=moment,
            max_events=_MAX_EVENTS + 1,
        )
        truncated = len(manageable) > _MAX_EVENTS
        if truncated:
            manageable = manageable[:_MAX_EVENTS]
        events = [
            apply_user_partstat_to_event(ev, login, partstat)
            if event_callback_token(str(ev.get("url") or "")) == token
            else ev
            for ev in manageable
        ]
        rich_text, fallback_text, keyboard = _build_list_screen(
            events,
            tz=ctx.tz,
            reference_date=moment.date(),
            truncated=truncated,
        )
        edit_callback_rich_or_html(
            ctx,
            cb,
            rich_html=rich_text,
            fallback_html=fallback_text,
            reply_markup=keyboard,
        )
        return
    _refresh_list(ctx, cb, ack=False)


def _on_fail(ctx: HandlerContext, cb: IncomingCallback) -> None:
    edit_callback_rich_or_html(
        ctx,
        cb,
        rich_html=MANAGE_RESPOND_FAIL_TEXT,
        fallback_html=MANAGE_RESPOND_FAIL_TEXT,
        reply_markup=None,
    )


def _on_not_found(ctx: HandlerContext, cb: IncomingCallback) -> None:
    _refresh_list(ctx, cb, toast=MANAGE_NOT_FOUND_TEXT, ack=False)


_FLOW = PartstatFlow(
    prefix=CB_MANAGE_RESPOND_PREFIX,
    fail_text=MANAGE_RESPOND_FAIL_TEXT,
    toast_by_code={
        "a": MANAGE_RESPOND_ACCEPTED,
        "d": MANAGE_RESPOND_DECLINED,
        "t": MANAGE_RESPOND_TENTATIVE,
    },
    log_name="Manage",
    loading_status_html=MANAGE_FETCH_STATUS,
    fetch_events=_fetch_manageable_events_only,
    optimistic_refresh_view=_optimistic_refresh_list,
    on_not_found=_on_not_found,
    on_fail=_on_fail,
)


def route_manage_events_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data or not data.startswith("mng:"):
        return False
    if data == CB_MANAGE_CLOSE:
        edit_callback_message(ctx, cb, MANAGE_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data in (CB_MANAGE_BACK, CB_MANAGE_REFRESH):
        _refresh_list(ctx, cb, show_loading=True)
        return True
    if data.startswith(CB_MANAGE_PICK_PREFIX):
        token = data[len(CB_MANAGE_PICK_PREFIX) :]
        _open_detail(ctx, cb, token)
        return True
    if data.startswith(CB_MANAGE_RESPOND_PREFIX):
        respond_partstat(ctx, cb, data, _FLOW)
        return True
    return False
