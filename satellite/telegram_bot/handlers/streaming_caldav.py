"""Общий scaffold: ActionGuard → streaming reply → CalDAV fetch → finish."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import ERR_CALDAV_UNAVAILABLE_TEXT
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingMessage
from .delivery import open_streaming_reply, send

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamingCaldavResult:
    """Успешный fetch: rich + fallback HTML и опциональная клавиатура."""

    rich_html: str
    fallback_html: str
    reply_markup: dict | None = None
    message_effect_id: str | None = None
    rich: bool = True
    typewriter: bool = True


FetchFn = Callable[[HandlerContext, int], StreamingCaldavResult]


def run_streaming_caldav_message(
    ctx: HandlerContext,
    msg: IncomingMessage,
    *,
    guard: ActionGuard,
    action_key: str,
    busy_text: str,
    status_text: str,
    fetch_fn: FetchFn,
    log_label: str,
) -> bool:
    """Потоковый CalDAV-экран для message-команд. ``True`` — ответ доставлен."""
    if msg.chat_id is None or msg.user_id is None:
        return False
    if not guard.try_acquire(msg.chat_id, action_key):
        log.info("%s skipped (duplicate within cooldown): user_id=%s", log_label, msg.user_id)
        send(ctx, msg.chat_id, busy_text)
        return False

    sent = False
    try:
        stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id, rich=True)
        stream.push_status(status_text)
        try:
            result = fetch_fn(ctx, msg.user_id)
        except CalendarNotConnectedError:
            log.error("%s failed user_id=%s: not connected", log_label, msg.user_id)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return False
        except CalendarProviderError as exc:
            log.error("%s failed user_id=%s: %s", log_label, msg.user_id, exc.error_code)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return False

        stream.finish(
            result.rich_html,
            fallback_html=result.fallback_html,
            rich=result.rich,
            typewriter=result.typewriter,
            reply_markup=result.reply_markup,
            message_effect_id=result.message_effect_id,
        )
        sent = True
        log.info("%s delivered: user_id=%s", log_label, msg.user_id)
        return True
    finally:
        guard.release(msg.chat_id, action_key, sent=sent)
