"""FSM создания события в календаре."""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta

from ...calendar.providers.base import CalendarEventPayload, CalendarProviderError
from ...calendar.time_utils import normalize_hhmm_input, parse_hhmm
from ...messages_ru import (
    CALENDAR_NOT_CONNECTED_HTML,
    CB_CREATE_CANCEL,
    CB_CREATE_CONFIRM,
    CB_CREATE_DATE_TODAY,
    CB_CREATE_DATE_TOMORROW,
    CB_CREATE_DURATION_PREFIX,
    CREATE_EVENT_ASK_DATE,
    CREATE_EVENT_ASK_DURATION,
    CREATE_EVENT_ASK_TIME,
    CREATE_EVENT_ASK_TITLE,
    CREATE_EVENT_CANCELLED_HTML,
    CREATE_EVENT_CONFIRM_HTML,
    CREATE_EVENT_CREATING_HTML,
    CREATE_EVENT_FAILED_HTML,
    CREATE_EVENT_INVALID_DATE,
    CREATE_EVENT_INVALID_DURATION,
    CREATE_EVENT_INVALID_TIME,
    CREATE_EVENT_SUCCESS_HTML,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    build_create_date_keyboard,
    build_create_duration_keyboard,
)
from ..calendar_state import (
    CalendarFlowState,
    CreateEventDraft,
    STATE_CREATE_CONFIRM,
    STATE_CREATE_SUBMITTING,
    STATE_CREATE_DATE,
    STATE_CREATE_DURATION,
    STATE_CREATE_TIME,
    STATE_CREATE_TITLE,
)
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingCallback, IncomingMessage
from ..visual import EFFECT_PARTY, private_message_effect, send_with_effect
from .delivery import edit_callback_message, safe_answer_callback, send

log = logging.getLogger(__name__)


def start_create_event(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None:
        return
    ctx.calendar_state.set(
        msg.chat_id,
        CalendarFlowState(state=STATE_CREATE_TITLE),
    )
    send(ctx, msg.chat_id, CREATE_EVENT_ASK_TITLE)


def handle_create_text_input(ctx: HandlerContext, msg: IncomingMessage) -> bool:
    if msg.chat_id is None or msg.user_id is None or msg.text is None:
        return False
    flow = ctx.calendar_state.get(msg.chat_id)
    if flow is None:
        return False
    if flow.state == STATE_CREATE_TITLE:
        title = msg.text.strip()
        if not title:
            send(ctx, msg.chat_id, CREATE_EVENT_ASK_TITLE)
            return True
        flow.draft.title = title
        flow.state = STATE_CREATE_DATE
        ctx.calendar_state.set(msg.chat_id, flow)
        _ask_date(ctx, msg.chat_id)
        return True
    if flow.state == STATE_CREATE_DATE:
        parsed = _parse_target_date(msg.text, ctx)
        if parsed is None:
            send(ctx, msg.chat_id, CREATE_EVENT_INVALID_DATE)
            return True
        flow.draft.event_date = parsed
        flow.state = STATE_CREATE_TIME
        ctx.calendar_state.set(msg.chat_id, flow)
        send(ctx, msg.chat_id, CREATE_EVENT_ASK_TIME)
        return True
    if flow.state == STATE_CREATE_TIME:
        normalized = normalize_hhmm_input(msg.text)
        if normalized is None:
            send(ctx, msg.chat_id, CREATE_EVENT_INVALID_TIME)
            return True
        flow.draft.start_time = normalized
        flow.state = STATE_CREATE_DURATION
        ctx.calendar_state.set(msg.chat_id, flow)
        _ask_duration(ctx, msg.chat_id)
        return True
    if flow.state == STATE_CREATE_DURATION:
        try:
            minutes = int(msg.text.strip())
        except ValueError:
            send(ctx, msg.chat_id, CREATE_EVENT_INVALID_DURATION)
            return True
        if minutes <= 0 or minutes > 24 * 60:
            send(ctx, msg.chat_id, CREATE_EVENT_INVALID_DURATION)
            return True
        flow.draft.duration_minutes = minutes
        flow.state = STATE_CREATE_CONFIRM
        ctx.calendar_state.set(msg.chat_id, flow)
        _send_confirm(ctx, msg.chat_id, flow.draft)
        return True
    return False


def route_create_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if data == CB_CREATE_CONFIRM:
        _confirm_create(ctx, cb)
        return True
    if data == CB_CREATE_CANCEL:
        if cb.chat_id is not None:
            ctx.calendar_state.clear(cb.chat_id)
            send(ctx, cb.chat_id, CREATE_EVENT_CANCELLED_HTML)
        safe_answer_callback(ctx, cb)
        return True
    if data in (CB_CREATE_DATE_TODAY, CB_CREATE_DATE_TOMORROW):
        _apply_date_preset(ctx, cb, data)
        return True
    if data.startswith(CB_CREATE_DURATION_PREFIX):
        _apply_duration_preset(ctx, cb, data)
        return True
    return False


def _ask_date(ctx: HandlerContext, chat_id: int) -> None:
    ctx.telegram.send_message(
        chat_id, CREATE_EVENT_ASK_DATE, reply_markup=build_create_date_keyboard()
    )


def _ask_duration(ctx: HandlerContext, chat_id: int) -> None:
    ctx.telegram.send_message(
        chat_id,
        CREATE_EVENT_ASK_DURATION,
        reply_markup=build_create_duration_keyboard(),
    )


def _apply_date_preset(
    ctx: HandlerContext, cb: IncomingCallback, data: str
) -> None:
    """Жмём «Сегодня»/«Завтра» — заполняем дату и переходим к шагу времени.

    State-проверка нужна, чтобы старая кнопка из давно отправленного сообщения
    не «оживила» закрытый сценарий и не отправила пользователю «Во сколько?»
    из ниоткуда.
    """
    if cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    flow = ctx.calendar_state.get(cb.chat_id)
    if flow is None or flow.state != STATE_CREATE_DATE:
        safe_answer_callback(ctx, cb)
        return
    today = datetime.now(tz=ctx.tz).date()
    flow.draft.event_date = (
        today if data == CB_CREATE_DATE_TODAY else today + timedelta(days=1)
    )
    flow.state = STATE_CREATE_TIME
    ctx.calendar_state.set(cb.chat_id, flow)
    send(ctx, cb.chat_id, CREATE_EVENT_ASK_TIME)
    safe_answer_callback(ctx, cb)


def _apply_duration_preset(
    ctx: HandlerContext, cb: IncomingCallback, data: str
) -> None:
    if cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    flow = ctx.calendar_state.get(cb.chat_id)
    if flow is None or flow.state != STATE_CREATE_DURATION:
        safe_answer_callback(ctx, cb)
        return
    try:
        minutes = int(data[len(CB_CREATE_DURATION_PREFIX):])
    except ValueError:
        safe_answer_callback(ctx, cb)
        return
    if minutes <= 0 or minutes > 24 * 60:
        safe_answer_callback(ctx, cb)
        return
    flow.draft.duration_minutes = minutes
    flow.state = STATE_CREATE_CONFIRM
    ctx.calendar_state.set(cb.chat_id, flow)
    _send_confirm(ctx, cb.chat_id, flow.draft)
    safe_answer_callback(ctx, cb)


def _send_confirm(ctx: HandlerContext, chat_id: int, draft: CreateEventDraft) -> None:
    assert draft.event_date and draft.start_time
    start_m = parse_hhmm(draft.start_time)
    end_m = start_m + draft.duration_minutes
    end_h, end_min = divmod(end_m, 60)
    end_time = f"{end_h:02d}:{end_min:02d}"
    text = CREATE_EVENT_CONFIRM_HTML.format(
        title=html.escape(draft.title),
        date=draft.event_date.strftime("%d.%m.%Y"),
        start=draft.start_time,
        end=end_time,
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Создать", "callback_data": CB_CREATE_CONFIRM},
                {"text": "❌ Отмена", "callback_data": CB_CREATE_CANCEL},
            ]
        ]
    }
    ctx.telegram.send_message(chat_id, text, reply_markup=keyboard)


def _confirm_create(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    flow = ctx.calendar_state.get(cb.chat_id)
    if flow is None or flow.state == STATE_CREATE_SUBMITTING:
        safe_answer_callback(ctx, cb, text="Уже создаём…")
        return
    if flow.state != STATE_CREATE_CONFIRM:
        safe_answer_callback(ctx, cb)
        return
    draft = flow.draft
    assert draft.event_date and draft.start_time
    start_m = parse_hhmm(draft.start_time)
    start_dt = datetime.combine(draft.event_date, datetime.min.time(), tzinfo=ctx.tz) + timedelta(
        minutes=start_m
    )
    end_dt = start_dt + timedelta(minutes=draft.duration_minutes)
    payload = CalendarEventPayload(title=draft.title, start=start_dt, end=end_dt)

    flow.state = STATE_CREATE_SUBMITTING
    ctx.calendar_state.set(cb.chat_id, flow)
    safe_answer_callback(ctx, cb, text="Создаю…")
    edit_callback_message(ctx, cb, CREATE_EVENT_CREATING_HTML, reply_markup=None)

    def do_create() -> None:
        ctx.calendar_service.create_event(cb.user_id, payload, tz=ctx.tz)

    try:
        do_create()
    except CalendarProviderError as exc:
        log.error("Create event failed user_id=%s code=%s", cb.user_id, exc.error_code)
        ctx.calendar_state.clear(cb.chat_id)
        edit_callback_message(ctx, cb, _create_failure_text(exc), reply_markup=None)
        safe_answer_callback(ctx, cb)
        return

    ctx.calendar_state.clear(cb.chat_id)
    edit_callback_message(ctx, cb, CREATE_EVENT_SUCCESS_HTML, reply_markup=None)
    if cb.chat_id is not None:
        send_with_effect(
            ctx.telegram,
            cb.chat_id,
            "✅ Готово.",
            message_effect_id=private_message_effect(EFFECT_PARTY, cb.chat_id),
        )
    safe_answer_callback(ctx, cb, text="Готово")


def _create_failure_text(exc: CalendarProviderError) -> str:
    if exc.error_code == "CREATE_FAILED":
        return CREATE_EVENT_FAILED_HTML
    if exc.error_code in {"NO_CALENDAR", "CALENDAR_NOT_CONNECTED"}:
        return CALENDAR_NOT_CONNECTED_HTML
    if exc.error_code == "CALDAV_UNAVAILABLE":
        return ERR_CALDAV_UNAVAILABLE_TEXT
    return ERR_CALDAV_UNAVAILABLE_TEXT


def _parse_target_date(text: str, ctx: HandlerContext) -> date | None:
    raw = (text or "").strip().lower()
    today = datetime.now(tz=ctx.tz).date()
    if raw in {"сегодня", "today"}:
        return today
    if raw in {"завтра", "tomorrow"}:
        return today + timedelta(days=1)
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
