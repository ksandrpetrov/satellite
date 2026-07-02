"""Reusable calendar actions shared across handlers."""

from __future__ import annotations

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...formatters.html import build_copy_text_button
from ...messages_ru import (
    BUTTON_COPY_EMAIL,
    CALENDAR_CHECK_FAIL_HTML,
    CALENDAR_CHECK_OK_HTML,
    CALENDAR_DISCONNECTED_HTML,
    CALENDAR_NOT_CONNECTED_HTML,
)
from ..visual import set_default_menu_button_for_chat
from .context import HandlerContext


def build_connected_login_keyboard(ctx: HandlerContext, user_id: int) -> dict | None:
    try:
        connected = ctx.calendar_service.require_connection(user_id)
        login = (connected.context.login or "").strip()
    except (CalendarNotConnectedError, CalendarProviderError):
        return None
    if not login:
        return None
    return {"inline_keyboard": [[build_copy_text_button(BUTTON_COPY_EMAIL, login)]]}


def calendar_check_result(ctx: HandlerContext, user_id: int) -> tuple[str, dict | None]:
    try:
        status = ctx.calendar_service.check_connection(user_id)
    except (CalendarNotConnectedError, CalendarProviderError):
        return CALENDAR_CHECK_FAIL_HTML, None
    if not status.connected:
        return CALENDAR_CHECK_FAIL_HTML, None
    return CALENDAR_CHECK_OK_HTML, build_connected_login_keyboard(ctx, user_id)


def disconnect_calendar_action(ctx: HandlerContext, *, user_id: int, chat_id: int) -> str:
    try:
        ctx.calendar_service.disconnect(user_id)
    except KeyError:
        return CALENDAR_NOT_CONNECTED_HTML
    set_default_menu_button_for_chat(ctx.telegram, chat_id)
    return CALENDAR_DISCONNECTED_HTML
