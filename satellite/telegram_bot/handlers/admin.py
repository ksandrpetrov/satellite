"""Admin approve/reject pending users."""

from __future__ import annotations

import logging

from ...messages_ru import (
    ADMIN_ACTION_FORBIDDEN_HTML,
    CB_ADMIN_APPROVE_PREFIX,
    CB_ADMIN_REJECT_PREFIX,
    admin_access_request_html,
    admin_pending_list_html,
    build_admin_access_keyboard,
)
from ..api import TelegramError
from .access import notify_user_access_decision
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import safe_answer_callback, send, webapp_connect_url

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


def handle_pending_command(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    if not ctx.admin.is_admin(msg.user_id):
        send(ctx, msg.chat_id, ADMIN_ACTION_FORBIDDEN_HTML)
        return
    pending = ctx.users.list_pending_requests()
    lines: list[str] = []
    for rec in pending:
        uname = f"@{rec.username}" if rec.username else "—"
        lines.append(f"{rec.display_name or '—'} ({uname}), id={rec.telegram_user_id}")
    send(ctx, msg.chat_id, admin_pending_list_html(lines))


def route_admin_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if data.startswith(CB_ADMIN_APPROVE_PREFIX):
        target_id = _parse_target_id(data, CB_ADMIN_APPROVE_PREFIX)
        if target_id is None:
            return False
        _handle_approve(ctx, cb, target_id)
        return True
    if data.startswith(CB_ADMIN_REJECT_PREFIX):
        target_id = _parse_target_id(data, CB_ADMIN_REJECT_PREFIX)
        if target_id is None:
            return False
        _handle_reject(ctx, cb, target_id)
        return True
    return False


def _parse_target_id(data: str, prefix: str) -> int | None:
    raw = data[len(prefix) :].strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _handle_approve(ctx: HandlerContext, cb: IncomingCallback, target_id: int) -> None:
    if cb.user_id is None or not ctx.admin.is_admin(cb.user_id):
        safe_answer_callback(ctx, cb, text="Недостаточно прав")
        return
    try:
        record = ctx.users.approve(target_id, admin_telegram_id=cb.user_id)
    except KeyError:
        safe_answer_callback(ctx, cb, text="Пользователь не найден")
        return
    webapp_url = webapp_connect_url(ctx)
    if record.chat_id is not None:
        notify_user_access_decision(
            ctx, chat_id=record.chat_id, approved=True, webapp_url=webapp_url
        )
    safe_answer_callback(ctx, cb, text="Доступ открыт")
    log.info("Admin %s approved user %s", cb.user_id, target_id)


def _handle_reject(ctx: HandlerContext, cb: IncomingCallback, target_id: int) -> None:
    if cb.user_id is None or not ctx.admin.is_admin(cb.user_id):
        safe_answer_callback(ctx, cb, text="Недостаточно прав")
        return
    try:
        record = ctx.users.reject(target_id, admin_telegram_id=cb.user_id)
    except KeyError:
        safe_answer_callback(ctx, cb, text="Пользователь не найден")
        return
    if record.chat_id is not None:
        notify_user_access_decision(
            ctx, chat_id=record.chat_id, approved=False, webapp_url=""
        )
    safe_answer_callback(ctx, cb, text="Отклонено")
    log.info("Admin %s rejected user %s", cb.user_id, target_id)
