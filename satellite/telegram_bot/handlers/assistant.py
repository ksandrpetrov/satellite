"""Telegram adapter; established commands/FSMs take precedence over free text."""

from dataclasses import replace
from datetime import datetime

from ...messages_ru import (
    AI_DISABLED,
    AI_HELP,
    AI_NO_ACCESS,
    AI_OPTIMIZE_REQUEST,
    AI_PRIVATE,
    AI_RESET,
    ai_usage_text,
    build_approved_main_keyboard,
)
from ...presentation.assistant import assistant_message_chunks, assistant_message_html
from ...users import USER_STATUS_APPROVED
from ..visual import TypingIndicator
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingMessage
from .delivery import send, send_rich_or_html


def _private(ctx: HandlerContext, msg: IncomingMessage) -> bool:
    if msg.chat_type not in (None, "private") or msg.chat_id != msg.user_id:
        send(ctx, msg.chat_id, AI_PRIVATE)
        return False
    return True


def _send_text(ctx: HandlerContext, msg: IncomingMessage, text: str) -> None:
    # Escape generated content; Telegram must never interpret calendar titles as HTML.
    user = ctx.users.get(msg.user_id) if msg.user_id is not None else None
    keyboard = (
        build_approved_main_keyboard()
        if user and user.status == USER_STATUS_APPROVED and user.has_calendar
        else None
    )
    for i, chunk in enumerate(assistant_message_chunks(text)):
        rich, legacy = assistant_message_html(chunk)
        send_rich_or_html(
            ctx,
            msg.chat_id,
            rich_html=rich,
            fallback_html=legacy,
            reply_markup=keyboard if i == 0 else None,
        )


def handle_ai_help(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if _private(ctx, msg):
        _send_text(ctx, msg, AI_HELP if ctx.assistant else AI_DISABLED)


def handle_ai_reset(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not _private(ctx, msg):
        return
    if ctx.assistant and msg.user_id is not None:
        ctx.assistant.reset(msg.user_id)
        send(ctx, msg.chat_id, AI_RESET)
    else:
        send(ctx, msg.chat_id, AI_DISABLED)


def handle_ai_usage(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not _private(ctx, msg):
        return
    if not ctx.admin.is_admin(msg.user_id):
        send(ctx, msg.chat_id, AI_NO_ACCESS)
        return
    if ctx.assistant:
        month = datetime.now(ctx.assistant.provider.tz).strftime("%Y-%m")
        _send_text(
            ctx,
            msg,
            ai_usage_text(ctx.assistant.store.usage(month), ctx.assistant.config.monthly_limit_usd),
        )
    else:
        send(ctx, msg.chat_id, AI_DISABLED)


def handle_optimize(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ctx.assistant:
        send(ctx, msg.chat_id, AI_DISABLED)
        return
    handle_ai_text(ctx, replace(msg, text=AI_OPTIMIZE_REQUEST))


def handle_ai_text(ctx: HandlerContext, msg: IncomingMessage) -> bool:
    if not ctx.assistant or not msg.text or msg.text.lstrip().startswith("/"):
        return False
    if not _private(ctx, msg) or not ensure_calendar_connected(ctx, msg):
        return True
    assert msg.user_id is not None and msg.chat_id is not None
    settings = ctx.subscriptions.get(msg.user_id)
    tz_name = settings.digest_timezone if settings else ctx.plan_config.tz_name
    typing = TypingIndicator(ctx.telegram, msg.chat_id)
    typing.start()
    try:
        text = ctx.assistant.respond(msg.user_id, msg.update_id, msg.text, tz_name)
    finally:
        typing.stop()
    _send_text(ctx, msg, text)
    return True
