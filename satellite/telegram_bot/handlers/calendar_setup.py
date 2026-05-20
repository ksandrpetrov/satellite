"""Web App connect / disconnect / check from Telegram buttons."""

from __future__ import annotations

import json
import logging

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...calendar.providers.registry import PROVIDER_IDS, PROVIDER_MAILRU, PROVIDER_YANDEX
from ...messages_ru import (
    CALENDAR_CHECK_FAIL_HTML,
    CALENDAR_CHECK_OK_HTML,
    CALENDAR_CONNECTED_HTML,
    CALENDAR_DISCONNECTED_HTML,
    CALENDAR_NOT_CONNECTED_HTML,
    CALENDAR_RECONNECT_INTRO_HTML,
    build_webapp_connect_keyboard,
)
from ...security.token_vault import ProviderCredentials
from ...users import UserStorePersistenceError
from ..html_format import build_copy_text_button as _copy_btn
from ..visual import (
    EFFECT_HEART,
    private_message_effect,
    send_with_effect,
    set_default_menu_button_for_chat,
)
from .access import ensure_calendar_access
from .context import HandlerContext, IncomingMessage
from .delivery import send, webapp_connect_url

log = logging.getLogger(__name__)


def _check_ok_keyboard(ctx: HandlerContext, user_id: int) -> dict | None:
    try:
        connected = ctx.calendar_service.require_connection(user_id)
        login = (connected.context.login or "").strip()
    except (CalendarNotConnectedError, CalendarProviderError):
        return None
    if not login:
        return None
    return {"inline_keyboard": [[_copy_btn("📋 Скопировать e-mail", login)]]}


def handle_web_app_connect(ctx: HandlerContext, msg: IncomingMessage) -> None:
    """Подключение календаря через ``Telegram.WebApp.sendData`` (без initData)."""
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    if not msg.web_app_data:
        return
    try:
        payload = json.loads(msg.web_app_data)
    except json.JSONDecodeError:
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)
        return
    if not isinstance(payload, dict) or payload.get("action") != "connect":
        return
    provider = str(payload.get("provider") or PROVIDER_MAILRU).strip().lower()
    login = str(payload.get("login") or "").strip()
    app_password = str(
        payload.get("app_password") or payload.get("token") or ""
    ).strip()
    if provider not in PROVIDER_IDS:
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)
        return
    if provider == PROVIDER_YANDEX:
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)
        return
    if not login or not app_password:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)
        return
    caldav_url = str(payload.get("caldav_url") or "").strip() or None
    try:
        ctx.calendar_service.connect(
            msg.user_id,
            provider_id=provider,
            credentials=ProviderCredentials(login=login, secret=app_password),
            caldav_url=caldav_url,
        )
        set_default_menu_button_for_chat(ctx.telegram, msg.chat_id)
        send_with_effect(
            ctx.telegram,
            msg.chat_id,
            CALENDAR_CONNECTED_HTML,
            message_effect_id=private_message_effect(EFFECT_HEART, msg.chat_id),
            reply_markup=_check_ok_keyboard(ctx, msg.user_id),
        )
    except CalendarProviderError:
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)
    except UserStorePersistenceError:
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)


def handle_connect_calendar_button(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None:
        return
    webapp_url = webapp_connect_url(ctx, msg.user_id)
    if not webapp_url:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)
        return
    reconnect = bool(
        msg.user_id and ctx.users.get(msg.user_id) and ctx.users.get(msg.user_id).has_calendar
    )
    intro = CALENDAR_RECONNECT_INTRO_HTML if reconnect else CALENDAR_NOT_CONNECTED_HTML
    ctx.telegram.send_message(
        msg.chat_id,
        intro,
        reply_markup=build_webapp_connect_keyboard(webapp_url, reconnect=reconnect),
    )


def handle_check_calendar(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    try:
        status = ctx.calendar_service.check_connection(msg.user_id)
        text = CALENDAR_CHECK_OK_HTML if status.connected else CALENDAR_CHECK_FAIL_HTML
        markup = _check_ok_keyboard(ctx, msg.user_id) if status.connected else None
        if status.connected and markup:
            ctx.telegram.send_message(msg.chat_id, text, reply_markup=markup)
        else:
            send(ctx, msg.chat_id, text)
    except (CalendarNotConnectedError, CalendarProviderError):
        send(ctx, msg.chat_id, CALENDAR_CHECK_FAIL_HTML)


def handle_disconnect_calendar(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if not ensure_calendar_access(ctx, msg) or msg.chat_id is None or msg.user_id is None:
        return
    try:
        ctx.calendar_service.disconnect(msg.user_id)
        set_default_menu_button_for_chat(ctx.telegram, msg.chat_id)
        send(ctx, msg.chat_id, CALENDAR_DISCONNECTED_HTML)
    except KeyError:
        send(ctx, msg.chat_id, CALENDAR_NOT_CONNECTED_HTML)
