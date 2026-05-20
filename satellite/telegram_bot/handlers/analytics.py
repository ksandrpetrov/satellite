"""Недельная аналитика календаря: PNG + подпись."""

from __future__ import annotations

import logging
from datetime import datetime

from ...analytics_service import build_week_analytics
from ...calendar.constants import ANALYTICS_WORKDAY_10_19, ANALYTICS_WORKDAY_9_18
from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    ANALYTICS_FETCH_STATUS,
    ANALYTICS_SAVED_TOAST,
    ANALYTICS_WORKDAY_APPLIED_TEXT,
    CB_ANALYTICS_BACK,
    CB_ANALYTICS_RUN,
    CB_ANALYTICS_WORKDAY_9,
    CB_ANALYTICS_WORKDAY_10,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    ERR_GENERIC_HANDLER_TEXT,
    analytics_options_screen_text,
    build_analytics_options_keyboard,
)
from ..chat_action import run_with_typing_action
from .access import ensure_calendar_connected
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    edit_callback_message,
    finalize_message,
    safe_answer_callback,
    try_send_return_message_id,
)

log = logging.getLogger(__name__)


def handle_open_analytics(ctx: HandlerContext, cb: IncomingCallback) -> None:
    """Экран выбора рабочего дня перед построением отчёта."""
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not ensure_calendar_connected(ctx, _msg_from_cb(cb)):
        safe_answer_callback(ctx, cb)
        return
    record = ctx.users.get(cb.user_id)
    preset = record.analytics_workday if record else ANALYTICS_WORKDAY_10_19
    edit_callback_message(
        ctx,
        cb,
        analytics_options_screen_text(workday_preset=preset),
        build_analytics_options_keyboard(workday_preset=preset),
    )
    safe_answer_callback(ctx, cb)


def handle_run_analytics(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not ensure_calendar_connected(ctx, _msg_from_cb(cb)):
        safe_answer_callback(ctx, cb)
        return

    loading_id = try_send_return_message_id(ctx, cb.chat_id, ANALYTICS_FETCH_STATUS)

    def build() -> tuple[bytes, str]:
        today = datetime.now(tz=ctx.tz).date()
        return build_week_analytics(
            telegram_user_id=cb.user_id,
            reference_date=today,
            tz=ctx.tz,
            calendar_service=ctx.calendar_service,
            users=ctx.users,
        )

    try:
        png, caption = run_with_typing_action(ctx.telegram, cb.chat_id, build)
    except CalendarNotConnectedError:
        finalize_message(ctx, cb.chat_id, loading_id, ERR_CALDAV_UNAVAILABLE_TEXT)
        safe_answer_callback(ctx, cb)
        return
    except CalendarProviderError as exc:
        log.error("Analytics failed user_id=%s: %s", cb.user_id, exc.error_code)
        finalize_message(ctx, cb.chat_id, loading_id, ERR_CALDAV_UNAVAILABLE_TEXT)
        safe_answer_callback(ctx, cb)
        return
    except Exception:  # noqa: BLE001 - не оставляем «сводит неделю…» висеть в чате
        log.exception("Analytics build failed user_id=%s", cb.user_id)
        finalize_message(ctx, cb.chat_id, loading_id, ERR_GENERIC_HANDLER_TEXT)
        safe_answer_callback(ctx, cb)
        return

    if loading_id is not None:
        try:
            ctx.telegram.delete_message(cb.chat_id, loading_id)
        except Exception:  # noqa: BLE001
            pass

    ctx.telegram.send_photo(cb.chat_id, png, caption=caption)
    safe_answer_callback(ctx, cb)
    log.info("Sent weekly analytics user_id=%s chat_id=%s", cb.user_id, cb.chat_id)


def handle_set_analytics_workday(ctx: HandlerContext, cb: IncomingCallback, preset: str) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        ctx.users.set_analytics_workday(cb.user_id, preset=preset)
    except (KeyError, ValueError):
        safe_answer_callback(ctx, cb)
        return
    edit_callback_message(
        ctx,
        cb,
        ANALYTICS_WORKDAY_APPLIED_TEXT,
        build_analytics_options_keyboard(workday_preset=preset),
    )
    safe_answer_callback(ctx, cb, text=ANALYTICS_SAVED_TOAST)


def route_analytics_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if data == CB_ANALYTICS_RUN:
        handle_run_analytics(ctx, cb)
        return True
    if data == CB_ANALYTICS_WORKDAY_9:
        handle_set_analytics_workday(ctx, cb, ANALYTICS_WORKDAY_9_18)
        return True
    if data == CB_ANALYTICS_WORKDAY_10:
        handle_set_analytics_workday(ctx, cb, ANALYTICS_WORKDAY_10_19)
        return True
    return False


def _msg_from_cb(cb: IncomingCallback) -> IncomingMessage:
    return IncomingMessage(
        update_id=cb.update_id,
        chat_id=cb.chat_id,
        user_id=cb.user_id,
        username=cb.username,
        display_name=None,
        text=None,
    )
