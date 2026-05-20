"""Точки входа для апдейтов Telegram: routing → конкретный сценарий.

`handle_message` / `handle_callback_query` ловят любые исключения внутри
сценариев, чтобы один кривой апдейт не валил процесс бота. Все безопасные
текстовые реакции — в ``messages_ru``.
"""

from __future__ import annotations

import logging

from ...messages_ru import BOT_KEYBOARD_HINT
from ..api import TelegramError
from .access import (
    ensure_calendar_access,
    ensure_calendar_connected,
    handle_start_or_help,
)
from .admin import handle_pending_command, route_admin_callback
from .calendar_create import handle_create_text_input, route_create_callback, start_create_event
from .calendar_list import handle_upcoming_events
from .calendar_setup import (
    handle_check_calendar,
    handle_connect_calendar_button,
    handle_disconnect_calendar,
)
from .calendar_foreign import (
    handle_open_foreign_calendars,
    route_foreign_calendars_callback,
)
from .calendar_sources import (
    handle_open_calendar_sources,
    route_calendar_sources_callback,
)
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import notify_handler_failure, safe_answer_callback, send
from .plan import handle_plan
from .routing import (
    CalendarSourcesCommand,
    CheckCommand,
    ConnectCommand,
    CreateCommand,
    DisconnectCommand,
    ForeignCalendarsCommand,
    PendingCommand,
    PlanCommand,
    RecognizedCommand,
    SettingsCommand,
    StartOrHelpCommand,
    SubscriptionCommand,
    UpcomingCommand,
    recognize_message,
)
from .analytics import route_analytics_callback
from .settings import handle_digest_time_input, route_settings_callback
from .settings_hub import handle_open_settings_hub, route_settings_hub_callback
from .subscription import handle_subscription_action

log = logging.getLogger(__name__)


# --- диспетчер: сообщения --------------------------------------------------


def handle_message(ctx: HandlerContext, msg: IncomingMessage) -> None:
    """Точка входа для сообщений. Все исключения логируются и не пробрасываются."""
    if msg.chat_id is None:
        return

    cmd = recognize_message(msg.text)
    if isinstance(cmd, StartOrHelpCommand):
        try:
            handle_start_or_help(ctx, msg, is_start=cmd.is_start)
        except TelegramError as exc:
            log.error("Telegram error while handling user_id=%s: %s", msg.user_id, exc)
        except Exception:  # noqa: BLE001 - один апдейт не должен валить бота
            log.exception("Unexpected error while handling user_id=%s", msg.user_id)
            notify_handler_failure(ctx, msg.chat_id)
        return

    if isinstance(cmd, PendingCommand):
        try:
            handle_pending_command(ctx, msg)
        except TelegramError as exc:
            log.error("Telegram error in /pending user_id=%s: %s", msg.user_id, exc)
        except Exception:  # noqa: BLE001
            log.exception("Unexpected error in /pending user_id=%s", msg.user_id)
            notify_handler_failure(ctx, msg.chat_id)
        return

    try:
        _route_message(ctx, msg, cmd)
    except TelegramError as exc:
        log.error("Telegram error while handling user_id=%s: %s", msg.user_id, exc)
    except Exception:  # noqa: BLE001 - один апдейт не должен валить бота
        log.exception("Unexpected error while handling user_id=%s", msg.user_id)
        notify_handler_failure(ctx, msg.chat_id)


def _route_message(
    ctx: HandlerContext, msg: IncomingMessage, cmd: RecognizedCommand | None
) -> None:
    if cmd is None:
        if (
            msg.chat_id is not None
            and ctx.digest_state.is_waiting_for_time(msg.chat_id)
            and msg.text is not None
        ):
            if ensure_calendar_access(ctx, msg):
                handle_digest_time_input(ctx, msg)
            return
        if handle_create_text_input(ctx, msg):
            return
        if ensure_calendar_access(ctx, msg):
            _handle_unknown(ctx, msg)
        return

    if msg.chat_id is not None:
        ctx.digest_state.clear(msg.chat_id)
        ctx.calendar_state.clear(msg.chat_id)
    _dispatch_recognized(ctx, msg, cmd)


def _dispatch_recognized(
    ctx: HandlerContext, msg: IncomingMessage, cmd: RecognizedCommand
) -> None:
    if isinstance(cmd, ConnectCommand):
        handle_connect_calendar_button(ctx, msg)
        return
    if isinstance(cmd, CheckCommand):
        handle_check_calendar(ctx, msg)
        return
    if isinstance(cmd, DisconnectCommand):
        handle_disconnect_calendar(ctx, msg)
        return
    if isinstance(cmd, UpcomingCommand):
        handle_upcoming_events(ctx, msg)
        return
    if isinstance(cmd, CreateCommand):
        start_create_event(ctx, msg)
        return
    if isinstance(cmd, CalendarSourcesCommand):
        if ensure_calendar_connected(ctx, msg):
            handle_open_calendar_sources(ctx, msg)
        return
    if isinstance(cmd, ForeignCalendarsCommand):
        if ensure_calendar_connected(ctx, msg):
            handle_open_foreign_calendars(ctx, msg)
        return
    if isinstance(cmd, SettingsCommand):
        if ensure_calendar_access(ctx, msg):
            handle_open_settings_hub(ctx, msg)
        return
    if isinstance(cmd, SubscriptionCommand):
        if ensure_calendar_access(ctx, msg):
            handle_subscription_action(ctx, msg, cmd.action)
        return
    if isinstance(cmd, PlanCommand):
        if ensure_calendar_connected(ctx, msg):
            handle_plan(ctx, msg, cmd.mode)
        return


# --- диспетчер: callback_query ---------------------------------------------


def handle_callback_query(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return

    if not ctx.digest_state.claim_callback(cb.callback_query_id):
        log.info(
            "Drop duplicate callback_query id=%s chat=%s data=%r",
            cb.callback_query_id,
            cb.chat_id,
            cb.data,
        )
        safe_answer_callback(ctx, cb)
        return

    try:
        _route_callback(ctx, cb)
    except TelegramError as exc:
        log.error("Telegram error in callback user_id=%s: %s", cb.user_id, exc)
        safe_answer_callback(ctx, cb)
    except Exception:  # noqa: BLE001 - не валим бота
        log.exception("Unexpected error in callback user_id=%s", cb.user_id)
        safe_answer_callback(ctx, cb)
        notify_handler_failure(ctx, cb.chat_id)


def _route_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if route_admin_callback(ctx, cb):
        return
    if route_create_callback(ctx, cb):
        return
    if route_settings_hub_callback(ctx, cb):
        return
    if route_analytics_callback(ctx, cb):
        return
    if route_settings_callback(ctx, cb):
        return
    if route_calendar_sources_callback(ctx, cb):
        return
    if route_foreign_calendars_callback(ctx, cb):
        return
    log.info("Unknown callback_data: %r", cb.data)
    safe_answer_callback(ctx, cb)


# --- unknown ---------------------------------------------------------------


def _handle_unknown(ctx: HandlerContext, msg: IncomingMessage) -> None:
    send(ctx, msg.chat_id, BOT_KEYBOARD_HINT)
    log.info(
        "Sent unknown-command hint user_id=%s text=%r (update_id=%s)",
        msg.user_id,
        msg.text,
        msg.update_id,
    )
