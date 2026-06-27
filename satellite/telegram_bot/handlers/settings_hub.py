"""Общий экран настроек: дайджест, аналитика, календарь.

Структура трёх уровней:

1. ``SETTINGS_HUB_TEXT`` (главный экран) — три раздела: Дайджест, Аналитика,
   Календарь. Управление подключением и календарями в плане спрятано в
   подэкран «Календарь», чтобы деструктивный «Отключить» не висел в одной
   строке с диагностической «Проверить» (была реальная ловушка по дрожанию
   пальца) и чтобы главный экран оставался коротким.
2. Подэкран ``settings_calendar_menu`` — четыре действия с календарём:
   выбор календарей в плане, проверка соединения, переподключение через
   Web App, отключение.
3. Подэкран ``settings_disconnect_confirm`` — двухшаговый disconnect:
   сначала «точно?», и только после явного подтверждения зовём
   ``calendar_service.disconnect``. Это снимает риск случайного нажатия
   и стилистически согласуется с остальным флоу Чайки («Чайка спрашивает
   подтверждение, а не отвязывает молча»).
"""

from __future__ import annotations

import logging

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    CALENDAR_CHECK_FAIL_HTML,
    CALENDAR_CHECK_OK_HTML,
    CALENDAR_DISCONNECT_TOAST,
    CALENDAR_DISCONNECTED_HTML,
    CALENDAR_NOT_CONNECTED_HTML,
    CALENDAR_SOURCES_LOAD_FAIL_HTML,
    CALENDAR_SOURCES_SINGLE_HTML,
    CALENDAR_SOURCES_UNAVAILABLE_TEXT,
    CB_PENDING_DIGEST_SETTINGS,
    CB_SETTINGS_ANALYTICS,
    CB_SETTINGS_BACK,
    CB_SETTINGS_CALENDAR_MENU,
    CB_SETTINGS_CALENDARS,
    CB_SETTINGS_CHECK,
    CB_SETTINGS_CLOSE,
    CB_SETTINGS_DIGEST,
    CB_SETTINGS_DISCONNECT,
    CB_SETTINGS_DISCONNECT_CONFIRM,
    CB_SETTINGS_WEATHER_TOGGLE,
    ERR_GENERIC_HANDLER_TEXT,
    ERR_SETTINGS_SAVE_FAILED_TEXT,
    SETTINGS_CALENDAR_MENU_TEXT,
    SETTINGS_DISCONNECT_CONFIRM_TEXT,
    SETTINGS_HUB_CLOSED_TEXT,
    build_settings_calendar_menu_keyboard,
    build_settings_disconnect_confirm_keyboard,
    build_settings_hub_keyboard,
    settings_hub_text,
    weather_in_plan_toggle_notice_text,
)
from ...subscriptions import SubscriptionStorePersistenceError
from ...users.store import UserStorePersistenceError
from ..api import TelegramError
from ..visual import set_default_menu_button_for_chat
from .analytics import CB_ANALYTICS_BACK, handle_open_analytics
from .calendar_view import (
    CalendarSourcesScreenStatus,
    build_calendar_sources_screen,
)
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    edit_callback_message,
    safe_answer_callback,
    send,
    webapp_connect_url,
)
from .settings import show_digest_settings_screen, show_pending_digest_settings_screen

log = logging.getLogger(__name__)

# Последнее inline-сообщение хаба настроек per chat (reply «⚙️ Настройки» сворачивает его).
_hub_message_by_chat: dict[int, int] = {}


def reset_settings_hub_message_tracker() -> None:
    """Сброс трекера между тестами."""
    _hub_message_by_chat.clear()


def _track_hub_message(chat_id: int, message_id: int | None) -> None:
    if message_id is not None:
        _hub_message_by_chat[chat_id] = message_id


def _untrack_hub_message(chat_id: int) -> None:
    _hub_message_by_chat.pop(chat_id, None)


def _close_tracked_hub_message(ctx: HandlerContext, chat_id: int) -> bool:
    """Свернуть хаб по reply-кнопке «Настройки». ``True`` — сообщение обновлено."""
    message_id = _hub_message_by_chat.get(chat_id)
    if message_id is None:
        return False
    try:
        ctx.telegram.edit_message_text(
            chat_id,
            message_id,
            SETTINGS_HUB_CLOSED_TEXT,
            reply_markup=None,
        )
        _untrack_hub_message(chat_id)
        return True
    except TelegramError as exc:
        log.info("Close settings hub via reply ignored: %s", exc)
        _untrack_hub_message(chat_id)
        return False


def _has_calendar(ctx: HandlerContext, user_id: int) -> bool:
    record = ctx.users.get(user_id)
    return bool(record and record.has_calendar)


def _subscription_username(record, user_id: int) -> str:
    uname = getattr(record, "username", None) if record else None
    if isinstance(uname, str) and uname.strip():
        return uname.strip()
    return str(user_id)


def _calendar_login(ctx: HandlerContext, user_id: int) -> str | None:
    svc = getattr(ctx, "calendar_service", None)
    if svc is None:
        return None
    try:
        connected = svc.require_connection(user_id)
        login = (connected.context.login or "").strip()
        return login or None
    except (CalendarNotConnectedError, CalendarProviderError):
        return None


def _hub_text_and_keyboard(ctx: HandlerContext, user_id: int, chat_id: int):
    record = ctx.users.get(user_id)
    has_cal = bool(record and record.has_calendar)
    digest_on = None
    pending_on = None
    weather_on = record.weather_in_plan_enabled if record else True
    if record:
        sub = ctx.subscriptions.get_or_create(
            chat_id,
            _subscription_username(record, user_id),
            telegram_user_id=user_id,
        )
        digest_on = sub.digest_enabled
        pending_on = sub.pending_digest_enabled
    else:
        pending_on = None
    text = settings_hub_text(
        digest_enabled=digest_on,
        pending_digest_enabled=pending_on,
        weather_in_plan_enabled=weather_on,
        has_calendar=has_cal,
    )
    keyboard = build_settings_hub_keyboard(
        webapp_url=webapp_connect_url(ctx, user_id),
        has_calendar=has_cal,
        weather_in_plan_enabled=weather_on,
        calendar_login=_calendar_login(ctx, user_id) if has_cal else None,
    )
    return text, keyboard


# --- главный экран --------------------------------------------------------


def handle_open_settings_hub(ctx: HandlerContext, msg: IncomingMessage) -> None:
    if msg.chat_id is None or msg.user_id is None:
        return
    ctx.digest_state.clear(msg.chat_id)
    if _close_tracked_hub_message(ctx, msg.chat_id):
        log.info("Closed settings hub via reply: chat_id=%s user_id=%s", msg.chat_id, msg.user_id)
        return
    try:
        text, keyboard = _hub_text_and_keyboard(ctx, msg.user_id, msg.chat_id)
    except SubscriptionStorePersistenceError:
        log.exception(
            "Failed to persist settings hub state: chat_id=%s user_id=%s",
            msg.chat_id,
            msg.user_id,
        )
        send(ctx, msg.chat_id, ERR_SETTINGS_SAVE_FAILED_TEXT)
        return
    sent = ctx.telegram.send_message(msg.chat_id, text, reply_markup=keyboard)
    message_id = sent.get("message_id") if isinstance(sent, dict) else None
    _track_hub_message(msg.chat_id, message_id)
    log.info("Opened settings hub: chat_id=%s user_id=%s", msg.chat_id, msg.user_id)


def show_settings_hub_screen(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    ctx.digest_state.clear(cb.chat_id)
    text, keyboard = _hub_text_and_keyboard(ctx, cb.user_id, cb.chat_id)
    edit_callback_message(ctx, cb, text, keyboard)
    if cb.message_id is not None:
        _track_hub_message(cb.chat_id, cb.message_id)


# --- подэкран «Календарь» -------------------------------------------------


def show_settings_calendar_menu(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not _has_calendar(ctx, cb.user_id):
        # подэкран не имеет смысла без подключения — возвращаем в хаб
        show_settings_hub_screen(ctx, cb)
        safe_answer_callback(ctx, cb)
        return
    keyboard = build_settings_calendar_menu_keyboard(webapp_url=webapp_connect_url(ctx, cb.user_id))
    edit_callback_message(ctx, cb, SETTINGS_CALENDAR_MENU_TEXT, keyboard)
    safe_answer_callback(ctx, cb)


def show_settings_disconnect_confirm(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not _has_calendar(ctx, cb.user_id):
        show_settings_hub_screen(ctx, cb)
        safe_answer_callback(ctx, cb)
        return
    edit_callback_message(
        ctx,
        cb,
        SETTINGS_DISCONNECT_CONFIRM_TEXT,
        build_settings_disconnect_confirm_keyboard(),
    )
    safe_answer_callback(ctx, cb)


# --- роутинг callback ------------------------------------------------------


def route_settings_hub_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    try:
        return _route_settings_hub_callback(ctx, cb)
    except SubscriptionStorePersistenceError:
        log.exception(
            "Failed to persist settings hub callback state: chat_id=%s user_id=%s data=%r",
            cb.chat_id,
            cb.user_id,
            cb.data,
        )
        safe_answer_callback(ctx, cb)
        send(ctx, cb.chat_id, ERR_SETTINGS_SAVE_FAILED_TEXT)
        return True


def _route_settings_hub_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if data == CB_SETTINGS_DIGEST:
        show_digest_settings_screen(ctx, cb)
        return True
    if data == CB_PENDING_DIGEST_SETTINGS:
        show_pending_digest_settings_screen(ctx, cb)
        return True
    if data == CB_SETTINGS_ANALYTICS:
        handle_open_analytics(ctx, cb)
        return True
    if data == CB_SETTINGS_WEATHER_TOGGLE:
        _toggle_weather_in_plan(ctx, cb)
        return True
    if data in (CB_SETTINGS_BACK, CB_ANALYTICS_BACK):
        show_settings_hub_screen(ctx, cb)
        return True
    if data == CB_SETTINGS_CALENDAR_MENU:
        show_settings_calendar_menu(ctx, cb)
        return True
    if data == CB_SETTINGS_CLOSE:
        if cb.chat_id is not None:
            ctx.digest_state.clear(cb.chat_id)
            _untrack_hub_message(cb.chat_id)
        edit_callback_message(ctx, cb, SETTINGS_HUB_CLOSED_TEXT, reply_markup=None)
        safe_answer_callback(ctx, cb)
        return True
    if data == CB_SETTINGS_CALENDARS:
        _open_calendar_sources_from_callback(ctx, cb)
        return True
    if data == CB_SETTINGS_CHECK:
        _check_calendar_from_callback(ctx, cb)
        return True
    if data == CB_SETTINGS_DISCONNECT:
        show_settings_disconnect_confirm(ctx, cb)
        return True
    if data == CB_SETTINGS_DISCONNECT_CONFIRM:
        _disconnect_calendar_from_callback(ctx, cb)
        return True
    return False


def _toggle_weather_in_plan(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    record = ctx.users.get(cb.user_id)
    if record is None:
        safe_answer_callback(ctx, cb)
        return
    new_enabled = not record.weather_in_plan_enabled
    try:
        ctx.users.set_weather_in_plan_enabled(cb.user_id, enabled=new_enabled)
    except KeyError:
        safe_answer_callback(ctx, cb)
        return
    except UserStorePersistenceError:
        log.exception("Failed to save weather_in_plan for user_id=%s", cb.user_id)
        safe_answer_callback(ctx, cb)
        send(ctx, cb.chat_id, ERR_GENERIC_HANDLER_TEXT)
        return
    show_settings_hub_screen(ctx, cb)
    safe_answer_callback(
        ctx,
        cb,
        text=weather_in_plan_toggle_notice_text(enabled=new_enabled),
    )


def _open_calendar_sources_from_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not _has_calendar(ctx, cb.user_id):
        safe_answer_callback(ctx, cb)
        return
    screen = build_calendar_sources_screen(ctx, cb.user_id)
    if screen.status is CalendarSourcesScreenStatus.NOT_CONNECTED:
        safe_answer_callback(ctx, cb)
        send(ctx, cb.chat_id, CALENDAR_NOT_CONNECTED_HTML)
        return
    if screen.status is CalendarSourcesScreenStatus.UNAVAILABLE:
        safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_UNAVAILABLE_TEXT)
        send(ctx, cb.chat_id, CALENDAR_SOURCES_LOAD_FAIL_HTML)
        return
    if screen.status is CalendarSourcesScreenStatus.SINGLE:
        safe_answer_callback(ctx, cb, text=CALENDAR_SOURCES_SINGLE_HTML)
        return
    if screen.status is not CalendarSourcesScreenStatus.SCREEN:
        safe_answer_callback(ctx, cb)
        return
    if screen.text is None or screen.keyboard is None:
        safe_answer_callback(ctx, cb)
        return
    edit_callback_message(ctx, cb, screen.text, screen.keyboard)
    safe_answer_callback(ctx, cb)
    log.info("Opened calendar sources from hub: user_id=%s", cb.user_id)


def _check_calendar_from_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        status = ctx.calendar_service.check_connection(cb.user_id)
        text = CALENDAR_CHECK_OK_HTML if status.connected else CALENDAR_CHECK_FAIL_HTML
    except (CalendarNotConnectedError, CalendarProviderError):
        text = CALENDAR_CHECK_FAIL_HTML
    send(ctx, cb.chat_id, text)
    safe_answer_callback(ctx, cb)


def _disconnect_calendar_from_callback(ctx: HandlerContext, cb: IncomingCallback) -> None:
    """Финальный шаг отключения — вызывается только после подтверждения.

    После disconnect возвращаем пользователя в главный хаб: подэкран
    «Календарь» без подключённого календаря недоступен, поэтому
    наглядно показать новое состояние можно только в хабе.
    """
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        ctx.calendar_service.disconnect(cb.user_id)
        if cb.chat_id is not None:
            set_default_menu_button_for_chat(ctx.telegram, cb.chat_id)
        send(ctx, cb.chat_id, CALENDAR_DISCONNECTED_HTML)
        show_settings_hub_screen(ctx, cb)
    except KeyError:
        safe_answer_callback(ctx, cb)
    else:
        safe_answer_callback(ctx, cb, text=CALENDAR_DISCONNECT_TOAST)
