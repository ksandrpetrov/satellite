"""Список ближайших событий."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    ERR_CALDAV_UNAVAILABLE_TEXT,
    UPCOMING_EMPTY_HTML,
    UPCOMING_FETCH_STATUS,
    upcoming_events_day_sections,
)
from ...messages_ru.rich_lists import upcoming_events_rich_html
from ..visual import is_private_chat, pick_upcoming_message_effect
from .access import ensure_calendar_connected
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingMessage
from .delivery import open_streaming_reply

log = logging.getLogger(__name__)

_UPCOMING_DAYS = 7
_UPCOMING_ACTION = "upcoming"

# Двойной /upcoming пока CalDAV ещё идёт даёт два одинаковых списка.
# Guard ограничивает повтор пока строим И ~15 с после успешной отправки.
_upcoming_guard = ActionGuard(cooldown_sec=15.0)


def handle_upcoming_events(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_connected(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    if not _upcoming_guard.try_acquire(msg.chat_id, _UPCOMING_ACTION):
        log.info("Upcoming skipped (duplicate within cooldown): user_id=%s", msg.user_id)
        return
    sent = False
    try:
        stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id, rich=True)
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
            day_sections = upcoming_events_day_sections(events, ctx.tz, today, days=_UPCOMING_DAYS)
            rich_html = upcoming_events_rich_html(events, ctx.tz, today, days=_UPCOMING_DAYS)
            if not day_sections:
                stream.finish(UPCOMING_EMPTY_HTML, rich=False)
                sent = True
                return
            parts = ["🗓 <b>Ближайшие события</b>"]
            for group_idx, section in enumerate(day_sections, start=1):
                parts.append(section)
                fallback_text = "\n\n".join(parts)
                rich_partial = upcoming_events_rich_html(
                    events,
                    ctx.tz,
                    today,
                    days=_UPCOMING_DAYS,
                    max_groups=group_idx,
                )
                stream.push(rich_partial or fallback_text, fallback_html=fallback_text)
            fallback_text = "\n\n".join(parts)
        except CalendarNotConnectedError:
            log.error("Upcoming list failed user_id=%s: not connected", msg.user_id)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False)
            return
        except CalendarProviderError as exc:
            log.error("Upcoming list failed user_id=%s: %s", msg.user_id, exc.error_code)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False)
            return
        effect = (
            pick_upcoming_message_effect(fallback_text) if is_private_chat(msg.chat_id) else None
        )
        stream.finish(
            rich_html,
            fallback_html=fallback_text,
            rich=True,
            message_effect_id=effect,
        )
        sent = True
    finally:
        _upcoming_guard.release(msg.chat_id, _UPCOMING_ACTION, sent=sent)
