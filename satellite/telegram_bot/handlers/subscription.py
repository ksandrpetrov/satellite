"""Сценарии включения/выключения дайджеста по кнопке/команде."""

from __future__ import annotations

import logging

from ...messages_ru import (
    SUBSCRIBE_ALREADY_TEXT,
    UNSUBSCRIBE_CONFIRMATION_TEXT,
    UNSUBSCRIBE_NOT_SUBSCRIBED_TEXT,
    subscribe_confirmation_text,
)
from ...subscriptions import DIGEST_DAYS_WEEKDAYS
from .access import effective_username
from .context import HandlerContext, IncomingMessage, SubscriptionAction
from .delivery import send

log = logging.getLogger(__name__)


def handle_subscription_action(
    ctx: HandlerContext, msg: IncomingMessage, action: SubscriptionAction
) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    username = effective_username(msg)
    if action == "subscribe":
        text = _do_subscribe(ctx, msg.chat_id, username, msg.user_id)
    else:
        text = _do_unsubscribe(ctx, msg.chat_id, username)
    send(ctx, msg.chat_id, text)


def _do_subscribe(
    ctx: HandlerContext, chat_id: int, username: str, telegram_user_id: int
) -> str:
    settings = ctx.subscriptions.get_or_create(
        chat_id, username, telegram_user_id=telegram_user_id
    )
    if settings.digest_enabled:
        log.info("Already subscribed: chat_id=%s username=%s", chat_id, username)
        return SUBSCRIBE_ALREADY_TEXT
    updated = ctx.subscriptions.update_settings(
        chat_id,
        username,
        telegram_user_id=telegram_user_id,
        digest_enabled=True,
    )
    log.info(
        "Subscribed: chat_id=%s username=%s time=%s days=%s",
        chat_id,
        username,
        updated.digest_time,
        updated.digest_days,
    )
    return subscribe_confirmation_text(
        updated.digest_time,
        weekdays_only=(updated.digest_days == DIGEST_DAYS_WEEKDAYS),
    )


def _do_unsubscribe(ctx: HandlerContext, chat_id: int, username: str) -> str:
    removed = ctx.subscriptions.unsubscribe(chat_id)
    log.info(
        "Unsubscribed: chat_id=%s username=%s removed=%s",
        chat_id,
        username,
        removed,
    )
    return UNSUBSCRIBE_CONFIRMATION_TEXT if removed else UNSUBSCRIBE_NOT_SUBSCRIBED_TEXT
