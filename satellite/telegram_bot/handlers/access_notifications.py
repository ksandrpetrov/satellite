"""Уведомления access/admin без связи access.py <-> admin.py."""

from __future__ import annotations

import logging

from ...messages_ru import (
    ACCESS_APPROVED_HTML,
    ACCESS_APPROVED_KEYBOARD_HINT,
    ACCESS_REJECTED_HTML,
    admin_access_request_html,
    build_admin_access_keyboard,
    build_approved_main_keyboard,
    build_webapp_connect_keyboard,
)
from ..api import TelegramError
from ..visual import EFFECT_HEART, private_message_effect, send_with_effect
from .context import HandlerContext, IncomingMessage

log = logging.getLogger(__name__)


def notify_admins_new_request(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if msg.user_id is None:
        return
    text = admin_access_request_html(
        display_name=msg.display_name,
        username=msg.username,
        telegram_user_id=msg.user_id,
    )
    keyboard = build_admin_access_keyboard(telegram_user_id=msg.user_id)
    for admin_id in ctx.admin.telegram_ids:
        try:
            ctx.telegram.send_message(admin_id, text, reply_markup=keyboard)
        except TelegramError as exc:
            log.warning("Failed to notify admin %s: %s", admin_id, exc)


def notify_user_access_decision(
    ctx: HandlerContext, *, chat_id: int, approved: bool, webapp_url: str
) -> None:
    if approved:
        try:
            if webapp_url:
                send_with_effect(
                    ctx.telegram,
                    chat_id,
                    ACCESS_APPROVED_HTML,
                    reply_markup=build_webapp_connect_keyboard(webapp_url),
                    message_effect_id=private_message_effect(EFFECT_HEART, chat_id),
                )
                ctx.telegram.send_message(
                    chat_id,
                    ACCESS_APPROVED_KEYBOARD_HINT,
                    reply_markup=build_approved_main_keyboard(),
                )
            else:
                send_with_effect(
                    ctx.telegram,
                    chat_id,
                    ACCESS_APPROVED_HTML,
                    message_effect_id=private_message_effect(EFFECT_HEART, chat_id),
                )
        except TelegramError as exc:
            log.warning("Failed to notify user %s about approval: %s", chat_id, exc)
    else:
        try:
            ctx.telegram.send_message(chat_id, ACCESS_REJECTED_HTML)
        except TelegramError as exc:
            log.warning("Failed to notify user %s about rejection: %s", chat_id, exc)
