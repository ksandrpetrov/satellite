"""Access gating: /start, заявки, статусы пользователя."""

from __future__ import annotations

from ...messages_ru import (
    ACCESS_APPROVED_HTML,
    ACCESS_BLOCKED_HTML,
    ACCESS_PENDING_HTML,
    ACCESS_REJECTED_HTML,
    ACCESS_REQUEST_SENT_HTML,
    BOT_HELP_HTML,
    BOT_WELCOME_HTML,
    CALENDAR_NOT_CONNECTED_HTML,
    ERR_USERS_SAVE_FAILED_TEXT,
    REPLY_KEYBOARD_REMOVE,
    build_approved_main_keyboard,
    build_webapp_connect_keyboard,
)
from ...users import (
    ACCESS_REQUEST_PENDING,
    USER_STATUS_APPROVED,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
    USER_STATUS_REJECTED,
    UserStorePersistenceError,
)
from ..visual import set_default_menu_button_for_chat
from .access_notifications import notify_admins_new_request
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import send, webapp_connect_url


def effective_username(msg: IncomingMessage) -> str:
    if msg.username:
        return msg.username
    if msg.user_id is not None:
        return str(msg.user_id)
    return "unknown"


def effective_username_from_callback(cb: IncomingCallback) -> str:
    if cb.username:
        return cb.username
    if cb.user_id is not None:
        return str(cb.user_id)
    return "unknown"


def handle_start_or_help(ctx: HandlerContext, msg: IncomingMessage, *, is_start: bool) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    default_status = (
        USER_STATUS_APPROVED if ctx.admin.is_admin(msg.user_id) else USER_STATUS_PENDING
    )
    try:
        record = ctx.users.upsert_from_telegram(
            telegram_user_id=msg.user_id,
            chat_id=msg.chat_id,
            username=msg.username,
            display_name=msg.display_name,
            default_status=default_status,
        )
        if ctx.admin.is_admin(msg.user_id) and record.status != USER_STATUS_APPROVED:
            record = ctx.users.approve(msg.user_id, admin_telegram_id=msg.user_id)
    except UserStorePersistenceError:
        send(ctx, msg.chat_id, ERR_USERS_SAVE_FAILED_TEXT)
        return

    if is_start:
        _handle_start_flow(ctx, msg, record.status)
    else:
        if (
            record.status == USER_STATUS_PENDING
            and record.access_request_status != ACCESS_REQUEST_PENDING
        ):
            _submit_access_request_if_needed(ctx, msg)
        ctx.telegram.send_message(
            msg.chat_id,
            BOT_HELP_HTML,
            reply_markup=REPLY_KEYBOARD_REMOVE,
        )


def _handle_start_flow(ctx: HandlerContext, msg: IncomingMessage, status: str) -> None:
    assert msg.chat_id is not None and msg.user_id is not None
    if status == USER_STATUS_BLOCKED:
        ctx.telegram.send_message(msg.chat_id, ACCESS_BLOCKED_HTML)
        return
    if status == USER_STATUS_REJECTED:
        ctx.telegram.send_message(msg.chat_id, ACCESS_REJECTED_HTML)
        return
    if status == USER_STATUS_PENDING:
        if _submit_access_request_if_needed(ctx, msg):
            ctx.telegram.send_message(msg.chat_id, ACCESS_REQUEST_SENT_HTML)
        else:
            ctx.telegram.send_message(msg.chat_id, ACCESS_PENDING_HTML)
        return
    # approved
    record = ctx.users.get(msg.user_id)
    has_calendar = bool(record and record.has_calendar)
    webapp_url = webapp_connect_url(ctx)
    markup = build_approved_main_keyboard() if webapp_url else REPLY_KEYBOARD_REMOVE
    if not has_calendar:
        ctx.telegram.send_message(msg.chat_id, ACCESS_APPROVED_HTML, reply_markup=markup)
    else:
        set_default_menu_button_for_chat(ctx.telegram, msg.chat_id)
        ctx.telegram.send_message(msg.chat_id, BOT_WELCOME_HTML, reply_markup=markup)


def _submit_access_request_if_needed(ctx: HandlerContext, msg: IncomingMessage) -> bool:
    """Открывает заявку и уведомляет админов. True — заявка создана впервые."""
    assert msg.user_id is not None
    _record, is_new = ctx.users.submit_access_request(msg.user_id)
    if is_new:
        notify_admins_new_request(ctx, msg)
    return is_new


def ensure_calendar_access(
    ctx: HandlerContext,
    msg: IncomingMessage | IncomingCallback | None = None,
    *,
    chat_id: int | None = None,
    user_id: int | None = None,
) -> bool:
    """True если пользователь approved и может выполнять календарные действия.

    Принимает либо ``msg`` (legacy: ``IncomingMessage`` / ``IncomingCallback``)
    с полями ``chat_id`` / ``user_id``, либо явные ``chat_id`` / ``user_id``.
    Второй вариант избавляет от фейковых ``IncomingMessage`` в callback-хендлерах.
    """
    resolved_chat_id, resolved_user_id = _resolve_chat_user(msg, chat_id, user_id)
    if resolved_user_id is None or resolved_chat_id is None:
        return False
    record = ctx.users.get(resolved_user_id)
    if record is None or record.status == USER_STATUS_BLOCKED:
        ctx.telegram.send_message(resolved_chat_id, ACCESS_BLOCKED_HTML)
        return False
    if record.status == USER_STATUS_REJECTED:
        ctx.telegram.send_message(resolved_chat_id, ACCESS_REJECTED_HTML)
        return False
    if record.status == USER_STATUS_PENDING:
        ctx.telegram.send_message(resolved_chat_id, ACCESS_PENDING_HTML)
        return False
    return True


def ensure_calendar_connected(
    ctx: HandlerContext,
    msg: IncomingMessage | IncomingCallback | None = None,
    *,
    chat_id: int | None = None,
    user_id: int | None = None,
) -> bool:
    resolved_chat_id, resolved_user_id = _resolve_chat_user(msg, chat_id, user_id)
    if not ensure_calendar_access(ctx, chat_id=resolved_chat_id, user_id=resolved_user_id):
        return False
    assert resolved_user_id is not None and resolved_chat_id is not None
    record = ctx.users.get(resolved_user_id)
    if record is None or not record.has_calendar:
        webapp_url = webapp_connect_url(ctx, resolved_user_id)
        markup = build_webapp_connect_keyboard(webapp_url) if webapp_url else REPLY_KEYBOARD_REMOVE
        ctx.telegram.send_message(
            resolved_chat_id, CALENDAR_NOT_CONNECTED_HTML, reply_markup=markup
        )
        return False
    return True


def _resolve_chat_user(
    msg: IncomingMessage | IncomingCallback | None,
    chat_id: int | None,
    user_id: int | None,
) -> tuple[int | None, int | None]:
    if msg is not None:
        return msg.chat_id, msg.user_id
    return chat_id, user_id
