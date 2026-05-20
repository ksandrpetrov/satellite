"""Список ближайших событий."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta

from ...calendar.events import format_time_range, is_cancelled_event, sort_key
from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import ERR_CALDAV_UNAVAILABLE_TEXT, UPCOMING_EMPTY_HTML, UPCOMING_FETCH_STATUS
from ..chat_action import run_with_typing_action
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingMessage
from .delivery import finalize_message, try_send_return_message_id

log = logging.getLogger(__name__)

_UPCOMING_DAYS = 7


def handle_upcoming_events(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    loading_id = try_send_return_message_id(ctx, msg.chat_id, UPCOMING_FETCH_STATUS)

    def build() -> str:
        today = datetime.now(tz=ctx.tz).date()
        end = today + timedelta(days=_UPCOMING_DAYS)
        events = ctx.calendar_service.list_events(
            msg.user_id,
            start_date=today,
            end_date=end,
            tz=ctx.tz,
        )
        visible = [
            ev
            for ev in events
            if not is_cancelled_event(ev)
        ]
        if not visible:
            return UPCOMING_EMPTY_HTML
        visible.sort(key=lambda ev: sort_key(ev, ctx.tz))
        lines = ["🗓 <b>Ближайшие события</b>", ""]
        for ev in visible[:30]:
            title = html.escape(str(ev.get("summary") or ev.get("title") or "—"))
            when = format_time_range(ev, ctx.tz)
            lines.append(f"• {when} — {title}")
        return "\n".join(lines)

    try:
        text = run_with_typing_action(ctx.telegram, msg.chat_id, build)
    except CalendarNotConnectedError:
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    except CalendarProviderError as exc:
        log.error("Upcoming list failed user_id=%s: %s", msg.user_id, exc.error_code)
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    finalize_message(ctx, msg.chat_id, loading_id, text)
