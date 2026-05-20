"""Список ближайших событий."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ...calendar.events import format_upcoming_events_lines
from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import ERR_CALDAV_UNAVAILABLE_TEXT, UPCOMING_EMPTY_HTML, UPCOMING_FETCH_STATUS
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingMessage
from ..html_format import expandable_blockquote
from ..visual import (
    SCENARIO_UPCOMING,
    is_private_chat,
    pick_upcoming_message_effect,
    react_to_command,
)
from .delivery import open_streaming_reply

log = logging.getLogger(__name__)

_UPCOMING_DAYS = 7


def handle_upcoming_events(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    react_to_command(ctx, msg, SCENARIO_UPCOMING)

    stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id)
    stream.push(UPCOMING_FETCH_STATUS)

    try:
        today = datetime.now(tz=ctx.tz).date()
        end = today + timedelta(days=_UPCOMING_DAYS)
        events = ctx.calendar_service.list_events(
            msg.user_id,
            start_date=today,
            end_date=end,
            tz=ctx.tz,
        )
        body = format_upcoming_events_lines(events, ctx.tz, today, days=_UPCOMING_DAYS)
        if not body:
            stream.finish(UPCOMING_EMPTY_HTML)
            return
        header = "🗓 <b>Ближайшие события</b>"
        parts = [header, ""]
        for line in body:
            parts.append(line)
            stream.push("\n".join(parts))
        raw_body = "\n".join(parts[2:]) if len(parts) > 2 else ""
        if raw_body.count("\n") >= 6:
            text = "\n".join(parts[:2]) + "\n" + expandable_blockquote(raw_body, threshold=6)
        else:
            text = "\n".join(parts)
    except CalendarNotConnectedError:
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    except CalendarProviderError as exc:
        log.error("Upcoming list failed user_id=%s: %s", msg.user_id, exc.error_code)
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    effect = pick_upcoming_message_effect(text) if is_private_chat(msg.chat_id) else None
    stream.finish(text, message_effect_id=effect)
