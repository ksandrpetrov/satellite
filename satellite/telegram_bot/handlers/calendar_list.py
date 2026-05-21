"""Список ближайших событий."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    ERR_CALDAV_UNAVAILABLE_TEXT,
    SHARE_KIND_UPCOMING,
    UPCOMING_EMPTY_HTML,
    UPCOMING_FETCH_STATUS,
    upcoming_events_day_sections,
)
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingMessage
from ..visual import is_private_chat, pick_upcoming_message_effect
from .delivery import open_streaming_reply, share_reply_markup

log = logging.getLogger(__name__)

_UPCOMING_DAYS = 7


def handle_upcoming_events(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id)
    stream.push(UPCOMING_FETCH_STATUS)
    day_sections: list[str] = []

    try:
        today = datetime.now(tz=ctx.tz).date()
        end = today + timedelta(days=_UPCOMING_DAYS)
        events = ctx.calendar_service.list_events(
            msg.user_id,
            start_date=today,
            end_date=end,
            tz=ctx.tz,
        )
        day_sections = upcoming_events_day_sections(
            events, ctx.tz, today, days=_UPCOMING_DAYS
        )
        if not day_sections:
            stream.finish(UPCOMING_EMPTY_HTML)
            return
        parts = ["🗓 <b>Ближайшие события</b>", ""]
        for section in day_sections:
            parts.append(section)
            stream.push("\n\n".join(parts))
        text = "\n\n".join(parts)
    except CalendarNotConnectedError:
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    except CalendarProviderError as exc:
        log.error("Upcoming list failed user_id=%s: %s", msg.user_id, exc.error_code)
        text = ERR_CALDAV_UNAVAILABLE_TEXT
    effect = pick_upcoming_message_effect(text) if is_private_chat(msg.chat_id) else None
    markup = None
    if day_sections:
        markup = share_reply_markup(
            ctx,
            msg.user_id,
            kind=SHARE_KIND_UPCOMING,
            days=_UPCOMING_DAYS,
        )
    stream.finish(text, message_effect_id=effect, reply_markup=markup)
