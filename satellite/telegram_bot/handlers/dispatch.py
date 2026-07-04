"""Точки входа для апдейтов Telegram: routing → конкретный сценарий.

`handle_message` / `handle_callback_query` ловят любые исключения внутри
сценариев, чтобы один кривой апдейт не валил процесс бота. Все безопасные
текстовые реакции — в ``messages_ru``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ...messages_ru import (
    BOT_KEYBOARD_HINT,
    CB_ANALYTICS_BACK,
    CB_ANALYTICS_RUN,
    CB_ANALYTICS_WORKDAY_9,
    CB_ANALYTICS_WORKDAY_10,
    CB_INV_BACK,
    CB_SETTINGS_ANALYTICS,
    CB_SETTINGS_BACK,
    CB_SETTINGS_CALENDAR_MENU,
    CB_SETTINGS_CALENDARS,
    CB_SETTINGS_CHECK,
    CB_SETTINGS_CLOSE,
    CB_SETTINGS_DIGEST,
    CB_SETTINGS_DISCONNECT,
    CB_SETTINGS_DISCONNECT_CONFIRM,
    CB_SETTINGS_INVITATIONS,
    CB_SETTINGS_RECONNECT,
    CB_SETTINGS_WEATHER_TOGGLE,
)
from ..api import TelegramError
from .access import (
    ensure_calendar_access,
    ensure_calendar_connected,
    handle_start_or_help,
)
from .admin import handle_pending_command, route_admin_callback
from .calendar_create import handle_create_text_input, route_create_callback, start_create_event
from .calendar_foreign import (
    handle_open_foreign_calendars,
    route_foreign_calendars_callback,
)
from .calendar_invitations import handle_open_invitations, route_invitations_callback
from .calendar_list import handle_upcoming_events
from .calendar_manage import handle_open_manage_events, route_manage_events_callback
from .calendar_setup import (
    handle_check_calendar,
    handle_connect_calendar_button,
    handle_disconnect_calendar,
    handle_web_app_connect,
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
    InvitationsCommand,
    ManageEventsCommand,
    PendingCommand,
    PlanCommand,
    RecognizedCommand,
    SettingsCommand,
    StartOrHelpCommand,
    SubscriptionCommand,
    UpcomingCommand,
    recognize_message,
)
from .settings import handle_digest_time_input, route_settings_callback
from .settings_hub import handle_open_settings_hub, route_settings_hub_callback
from .subscription import handle_subscription_action

log = logging.getLogger(__name__)


def _safe_message_run(
    ctx: HandlerContext,
    msg: IncomingMessage,
    fn: Callable[[], None],
    *,
    log_context: str,
) -> None:
    """Единая обёртка: TelegramError и прочие исключения не валят процесс бота."""
    try:
        fn()
    except TelegramError as exc:
        log.error("Telegram error %s user_id=%s: %s", log_context, msg.user_id, exc)
    except Exception:  # noqa: BLE001 - один апдейт не должен валить бота
        log.exception("Unexpected error %s user_id=%s", log_context, msg.user_id)
        if msg.chat_id is not None:
            notify_handler_failure(ctx, msg.chat_id)


# --- диспетчер: сообщения --------------------------------------------------


def handle_message(ctx: HandlerContext, msg: IncomingMessage) -> None:
    """Точка входа для сообщений. Все исключения логируются и не пробрасываются."""
    if msg.chat_id is None:
        return

    if msg.web_app_data:
        _safe_message_run(
            ctx,
            msg,
            lambda: handle_web_app_connect(ctx, msg),
            log_context="on web_app_data",
        )
        return

    cmd = recognize_message(msg.text)
    _safe_message_run(
        ctx,
        msg,
        lambda: _route_message(ctx, msg, cmd),
        log_context="while handling message",
    )


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


HandlerFn = Callable[[HandlerContext, IncomingMessage, "RecognizedCommand"], None]


@dataclass(frozen=True)
class _MessageRoute:
    """Один маршрут команды → handler + опциональный access-guard.

    Добавление новой команды: одна строка в :data:`_MESSAGE_ROUTES`.
    """

    handler: HandlerFn
    access_guard: Callable[[HandlerContext, IncomingMessage], bool] | None = None


def _run_simple(handler):
    """Адаптер для handler, который не смотрит на конкретный класс команды."""

    def _call(ctx, msg, _cmd):
        handler(ctx, msg)

    return _call


def _plan(ctx, msg, cmd):
    handle_plan(ctx, msg, cmd.mode)


def _subscription(ctx, msg, cmd):
    handle_subscription_action(ctx, msg, cmd.action)


def _start_or_help(ctx, msg, cmd):
    handle_start_or_help(ctx, msg, is_start=cmd.is_start)


def _pending(ctx, msg, cmd):
    handle_pending_command(ctx, msg)


_MESSAGE_ROUTES: dict[type, _MessageRoute] = {
    StartOrHelpCommand: _MessageRoute(handler=_start_or_help),
    PendingCommand: _MessageRoute(handler=_pending),
    ConnectCommand: _MessageRoute(handler=_run_simple(handle_connect_calendar_button)),
    CheckCommand: _MessageRoute(handler=_run_simple(handle_check_calendar)),
    DisconnectCommand: _MessageRoute(handler=_run_simple(handle_disconnect_calendar)),
    UpcomingCommand: _MessageRoute(handler=_run_simple(handle_upcoming_events)),
    InvitationsCommand: _MessageRoute(
        handler=_run_simple(handle_open_invitations),
        access_guard=ensure_calendar_connected,
    ),
    ManageEventsCommand: _MessageRoute(
        handler=_run_simple(handle_open_manage_events),
        access_guard=ensure_calendar_connected,
    ),
    CreateCommand: _MessageRoute(handler=_run_simple(start_create_event)),
    CalendarSourcesCommand: _MessageRoute(
        handler=_run_simple(handle_open_calendar_sources),
        access_guard=ensure_calendar_connected,
    ),
    ForeignCalendarsCommand: _MessageRoute(
        handler=_run_simple(handle_open_foreign_calendars),
        access_guard=ensure_calendar_connected,
    ),
    SettingsCommand: _MessageRoute(
        handler=_run_simple(handle_open_settings_hub),
        access_guard=ensure_calendar_access,
    ),
    SubscriptionCommand: _MessageRoute(
        handler=_subscription,
        access_guard=ensure_calendar_access,
    ),
    PlanCommand: _MessageRoute(
        handler=_plan,
        access_guard=ensure_calendar_connected,
    ),
}


def _dispatch_recognized(ctx: HandlerContext, msg: IncomingMessage, cmd: RecognizedCommand) -> None:
    route = _MESSAGE_ROUTES.get(type(cmd))
    if route is None:
        raise LookupError(f"Recognized command is not routed: {type(cmd).__name__}")
    if route.access_guard is not None and not route.access_guard(ctx, msg):
        return
    route.handler(ctx, msg, cmd)


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


CallbackRouter = Callable[[HandlerContext, IncomingCallback], bool]


# Порядок важен: первый router, вернувший True, забирает callback.
# Добавление нового раздела — одна строка в этом списке.
_CALLBACK_ROUTERS: list[CallbackRouter] = [
    route_admin_callback,
    route_create_callback,
    route_manage_events_callback,
    route_settings_hub_callback,
    route_invitations_callback,
    route_settings_callback,
    route_calendar_sources_callback,
    route_foreign_calendars_callback,
]

_SETTINGS_CALLBACK_OWNERS: dict[str, str] = {
    CB_SETTINGS_DIGEST: "settings_hub",
    CB_SETTINGS_ANALYTICS: "settings_hub",
    CB_SETTINGS_CALENDAR_MENU: "settings_hub",
    CB_SETTINGS_CALENDARS: "settings_hub",
    CB_SETTINGS_INVITATIONS: "settings_hub",
    CB_SETTINGS_CHECK: "settings_hub",
    CB_SETTINGS_RECONNECT: "web_app",
    CB_SETTINGS_DISCONNECT: "settings_hub",
    CB_SETTINGS_DISCONNECT_CONFIRM: "settings_hub",
    CB_SETTINGS_BACK: "settings_hub",
    CB_SETTINGS_CLOSE: "settings_hub",
    CB_SETTINGS_WEATHER_TOGGLE: "settings_hub",
    CB_ANALYTICS_RUN: "settings_hub",
    CB_ANALYTICS_WORKDAY_9: "settings_hub",
    CB_ANALYTICS_WORKDAY_10: "settings_hub",
    CB_ANALYTICS_BACK: "settings_hub",
    CB_INV_BACK: "settings_hub",
}


def _route_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    for router in _CALLBACK_ROUTERS:
        if router(ctx, cb):
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
