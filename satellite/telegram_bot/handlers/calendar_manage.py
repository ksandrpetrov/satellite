"""Удаление событий из списка ближайших (минимальный manage CRUD)."""

from __future__ import annotations

import html
import logging

from ...calendar.providers.base import CalendarEventRef, CalendarProviderError
from ...messages_ru import CB_MANAGE_DELETE_PREFIX
from .context import HandlerContext, IncomingCallback
from .delivery import safe_answer_callback, send

log = logging.getLogger(__name__)


def build_manage_keyboard(events: list[dict]) -> dict:
    rows = []
    for idx, ev in enumerate(events[:10]):
        title = str(ev.get("summary") or ev.get("title") or "—")[:40]
        rows.append(
            [
                {
                    "text": f"🗑 {title}",
                    "callback_data": f"{CB_MANAGE_DELETE_PREFIX}{idx}",
                }
            ]
        )
    return {"inline_keyboard": rows}


def route_manage_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data.startswith(CB_MANAGE_DELETE_PREFIX):
        return False
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return True
    flow = ctx.calendar_state.get(cb.chat_id)
    if flow is None or not flow.manage_events:
        safe_answer_callback(ctx, cb)
        return True
    try:
        idx = int(data[len(CB_MANAGE_DELETE_PREFIX) :])
    except ValueError:
        safe_answer_callback(ctx, cb)
        return True
    if idx < 0 or idx >= len(flow.manage_events):
        safe_answer_callback(ctx, cb)
        return True
    ev = flow.manage_events[idx]
    ref = CalendarEventRef(
        uid=str(ev.get("uid") or ""),
        url=str(ev.get("url") or "") or None,
    )
    try:
        ctx.calendar_service.delete_event(cb.user_id, ref)
        send(ctx, cb.chat_id, "Событие удалено из календаря.")
        safe_answer_callback(ctx, cb, text="Удалено")
    except CalendarProviderError as exc:
        log.error("Delete failed user_id=%s code=%s", cb.user_id, exc.error_code)
        safe_answer_callback(ctx, cb, text="Ошибка")
    return True
