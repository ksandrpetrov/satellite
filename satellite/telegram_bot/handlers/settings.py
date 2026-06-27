"""UI настроек дайджестов: план на сегодня и непринятые встречи.

Все вью-функции, относящиеся к экранам настроек дайджеста и их callback'ам,
живут в одном модуле — общий контекст (state, store, edit/answer) удобно
держать рядом.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...calendar.time_utils import normalize_hhmm_input
from ...digest_utils import toggle_digest_days_bitmask
from ...messages_ru import (
    CB_DIGEST_BACK,
    CB_DIGEST_CLOSE,
    CB_DIGEST_DAYS,
    CB_DIGEST_DAYS_ALL,
    CB_DIGEST_DAYS_WEEKDAYS,
    CB_DIGEST_SETTINGS,
    CB_DIGEST_TIME,
    CB_DIGEST_TOGGLE,
    CB_DIGEST_WEATHER_TOGGLE,
    CB_PENDING_DIGEST_BACK,
    CB_PENDING_DIGEST_CLOSE,
    CB_PENDING_DIGEST_DAY_PREFIX,
    CB_PENDING_DIGEST_DAYS,
    CB_PENDING_DIGEST_DAYS_ALL,
    CB_PENDING_DIGEST_DAYS_WEEKDAYS,
    CB_PENDING_DIGEST_SETTINGS,
    CB_PENDING_DIGEST_TIME,
    CB_PENDING_DIGEST_TOGGLE,
    DIGEST_DAYS_ALL_APPLIED_TEXT,
    DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
    DIGEST_SETTINGS_CLOSED_TEXT,
    DIGEST_TIME_INVALID_TEXT,
    ERR_SETTINGS_SAVE_FAILED_TEXT,
    PENDING_DIGEST_DAYS_ALL_APPLIED_TEXT,
    PENDING_DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
    PENDING_DIGEST_LAST_DAY_TEXT,
    PENDING_DIGEST_SETTINGS_CLOSED_TEXT,
    PENDING_DIGEST_TIME_INVALID_TEXT,
    build_digest_days_keyboard,
    build_digest_settings_keyboard,
    build_digest_time_keyboard,
    build_pending_digest_days_keyboard,
    build_pending_digest_settings_keyboard,
    build_pending_digest_time_keyboard,
    digest_days_screen_text,
    digest_settings_screen_text,
    digest_time_applied_text,
    digest_time_screen_text,
    digest_toggle_notice_text,
    pending_digest_days_screen_text,
    pending_digest_settings_screen_text,
    pending_digest_time_applied_text,
    pending_digest_time_screen_text,
    pending_digest_toggle_notice_text,
    weather_in_plan_toggle_notice_text,
)
from ...subscriptions import (
    DIGEST_DAYS_ALL,
    DIGEST_DAYS_WEEKDAYS,
    DigestSettings,
    SubscriptionStorePersistenceError,
)
from ...users.store import UserStorePersistenceError
from .access import effective_username, effective_username_from_callback
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, safe_answer_callback, send
from .digest_state import DIGEST_KIND_DAILY, DIGEST_KIND_PENDING, DigestKind

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DigestKindBindings:
    kind: DigestKind
    enabled_field: str
    days_field: str
    time_field: str
    update_enabled_kw: str
    update_days_kw: str
    update_time_kw: str
    cb_settings: str
    cb_toggle: str
    cb_days: str
    cb_days_weekdays: str
    cb_days_all: str
    cb_time: str
    cb_back: str
    cb_close: str
    screen_text: Callable[..., str]
    days_screen_text: Callable[[str], str]
    time_screen_text: Callable[[str], str]
    time_applied_text: Callable[[str], str]
    time_invalid_text: str
    settings_closed_text: str
    days_weekdays_applied: str
    days_all_applied: str
    toggle_notice: Callable[..., str]
    build_settings_keyboard: Callable[..., dict]
    build_days_keyboard: Callable[..., dict]
    build_time_keyboard: Callable[[], dict]


def _enabled(settings: DigestSettings, bindings: DigestKindBindings) -> bool:
    return bool(getattr(settings, bindings.enabled_field))


def _days(settings: DigestSettings, bindings: DigestKindBindings) -> str:
    return str(getattr(settings, bindings.days_field))


def _time(settings: DigestSettings, bindings: DigestKindBindings) -> str:
    return str(getattr(settings, bindings.time_field))


_BINDINGS: dict[DigestKind, DigestKindBindings] = {
    DIGEST_KIND_DAILY: DigestKindBindings(
        kind=DIGEST_KIND_DAILY,
        enabled_field="digest_enabled",
        days_field="digest_days",
        time_field="digest_time",
        update_enabled_kw="digest_enabled",
        update_days_kw="digest_days",
        update_time_kw="digest_time",
        cb_settings=CB_DIGEST_SETTINGS,
        cb_toggle=CB_DIGEST_TOGGLE,
        cb_days=CB_DIGEST_DAYS,
        cb_days_weekdays=CB_DIGEST_DAYS_WEEKDAYS,
        cb_days_all=CB_DIGEST_DAYS_ALL,
        cb_time=CB_DIGEST_TIME,
        cb_back=CB_DIGEST_BACK,
        cb_close=CB_DIGEST_CLOSE,
        screen_text=digest_settings_screen_text,
        days_screen_text=digest_days_screen_text,
        time_screen_text=digest_time_screen_text,
        time_applied_text=digest_time_applied_text,
        time_invalid_text=DIGEST_TIME_INVALID_TEXT,
        settings_closed_text=DIGEST_SETTINGS_CLOSED_TEXT,
        days_weekdays_applied=DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
        days_all_applied=DIGEST_DAYS_ALL_APPLIED_TEXT,
        toggle_notice=digest_toggle_notice_text,
        build_settings_keyboard=build_digest_settings_keyboard,
        build_days_keyboard=build_digest_days_keyboard,
        build_time_keyboard=build_digest_time_keyboard,
    ),
    DIGEST_KIND_PENDING: DigestKindBindings(
        kind=DIGEST_KIND_PENDING,
        enabled_field="pending_digest_enabled",
        days_field="pending_digest_days",
        time_field="pending_digest_time",
        update_enabled_kw="pending_digest_enabled",
        update_days_kw="pending_digest_days",
        update_time_kw="pending_digest_time",
        cb_settings=CB_PENDING_DIGEST_SETTINGS,
        cb_toggle=CB_PENDING_DIGEST_TOGGLE,
        cb_days=CB_PENDING_DIGEST_DAYS,
        cb_days_weekdays=CB_PENDING_DIGEST_DAYS_WEEKDAYS,
        cb_days_all=CB_PENDING_DIGEST_DAYS_ALL,
        cb_time=CB_PENDING_DIGEST_TIME,
        cb_back=CB_PENDING_DIGEST_BACK,
        cb_close=CB_PENDING_DIGEST_CLOSE,
        screen_text=pending_digest_settings_screen_text,
        days_screen_text=pending_digest_days_screen_text,
        time_screen_text=pending_digest_time_screen_text,
        time_applied_text=pending_digest_time_applied_text,
        time_invalid_text=PENDING_DIGEST_TIME_INVALID_TEXT,
        settings_closed_text=PENDING_DIGEST_SETTINGS_CLOSED_TEXT,
        days_weekdays_applied=PENDING_DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
        days_all_applied=PENDING_DIGEST_DAYS_ALL_APPLIED_TEXT,
        toggle_notice=pending_digest_toggle_notice_text,
        build_settings_keyboard=build_pending_digest_settings_keyboard,
        build_days_keyboard=build_pending_digest_days_keyboard,
        build_time_keyboard=build_pending_digest_time_keyboard,
    ),
}


def _bindings(kind: DigestKind) -> DigestKindBindings:
    return _BINDINGS[kind]


def _update_settings(
    ctx: HandlerContext,
    chat_id: int,
    username: str,
    *,
    telegram_user_id: int,
    bindings: DigestKindBindings,
    **kwargs: Any,
) -> DigestSettings:
    patch: dict[str, Any] = {}
    if "enabled" in kwargs:
        patch[bindings.update_enabled_kw] = kwargs["enabled"]
    if "days" in kwargs:
        patch[bindings.update_days_kw] = kwargs["days"]
    if "time" in kwargs:
        patch[bindings.update_time_kw] = kwargs["time"]
    return ctx.subscriptions.update_settings(
        chat_id,
        username,
        telegram_user_id=telegram_user_id,
        **patch,
    )


# --- text/keyboard scenarios -----------------------------------------------


def handle_digest_time_input(ctx: HandlerContext, msg: IncomingMessage) -> None:
    """Принимает свободный текст пользователя как новое время (daily или pending)."""
    if msg.chat_id is None or msg.user_id is None:
        return
    waiting = ctx.digest_state.get(msg.chat_id)
    if waiting is None or waiting.state != "waiting_for_digest_time":
        return
    kind: DigestKind = waiting.digest_kind
    bindings = _bindings(kind)
    username = effective_username(msg)
    normalized = normalize_hhmm_input(msg.text)
    if normalized is None:
        log.info("Invalid digest time input from %s: %r kind=%s", username, msg.text, kind)
        send(ctx, msg.chat_id, bindings.time_invalid_text)
        return

    try:
        updated = _update_settings(
            ctx,
            msg.chat_id,
            username,
            telegram_user_id=msg.user_id,
            bindings=bindings,
            time=normalized,
        )
    except SubscriptionStorePersistenceError:
        log.exception(
            "Failed to persist %s from text input: chat_id=%s user_id=%s",
            bindings.time_field,
            msg.chat_id,
            msg.user_id,
        )
        send(ctx, msg.chat_id, ERR_SETTINGS_SAVE_FAILED_TEXT)
        return
    ctx.digest_state.clear(msg.chat_id)
    log.info(
        "Updated %s: chat_id=%s username=%s -> %s",
        bindings.time_field,
        msg.chat_id,
        username,
        _time(updated, bindings),
    )
    send(ctx, msg.chat_id, bindings.time_applied_text(_time(updated, bindings)))


# --- callback handlers -----------------------------------------------------


def handle_callback_toggle(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = _bindings(kind)
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    new_enabled = not _enabled(settings, bindings)
    updated = _update_settings(
        ctx,
        cb.chat_id,
        username,
        telegram_user_id=cb.user_id,
        bindings=bindings,
        enabled=new_enabled,
    )
    notice = bindings.toggle_notice(enabled=_enabled(updated, bindings))
    log.info(
        "Toggle %s: chat_id=%s username=%s -> %s",
        bindings.enabled_field,
        cb.chat_id,
        username,
        _enabled(updated, bindings),
    )
    render_digest_settings_screen(ctx, cb, updated, kind=kind)
    safe_answer_callback(ctx, cb, text=notice)


def show_digest_settings_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    *,
    kind: DigestKind = DIGEST_KIND_DAILY,
) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    ctx.digest_state.clear(cb.chat_id)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    render_digest_settings_screen(ctx, cb, settings, kind=kind)
    safe_answer_callback(ctx, cb)


def show_pending_digest_settings_screen(ctx: HandlerContext, cb: IncomingCallback) -> None:
    show_digest_settings_screen(ctx, cb, kind=DIGEST_KIND_PENDING)


def show_digest_days_screen(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = _bindings(kind)
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    edit_callback_message(
        ctx,
        cb,
        bindings.days_screen_text(_days(settings, bindings)),
        bindings.build_days_keyboard(digest_days=_days(settings, bindings)),
    )
    safe_answer_callback(ctx, cb)


def handle_callback_set_days(
    ctx: HandlerContext,
    cb: IncomingCallback,
    value: str,
    *,
    kind: DigestKind = DIGEST_KIND_DAILY,
) -> None:
    bindings = _bindings(kind)
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    before = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    updated = _update_settings(
        ctx,
        cb.chat_id,
        username,
        telegram_user_id=cb.user_id,
        bindings=bindings,
        days=value,
    )
    changed = _days(before, bindings) != _days(updated, bindings)
    log.info(
        "Set %s: chat_id=%s username=%s -> %s (changed=%s)",
        bindings.days_field,
        cb.chat_id,
        username,
        _days(updated, bindings),
        changed,
    )
    render_digest_settings_screen(ctx, cb, updated, kind=kind)
    if changed:
        confirmation = (
            bindings.days_weekdays_applied
            if _days(updated, bindings) == DIGEST_DAYS_WEEKDAYS
            else bindings.days_all_applied
        )
        send(ctx, cb.chat_id, confirmation)
    safe_answer_callback(ctx, cb)


def handle_pending_digest_day_toggle(
    ctx: HandlerContext,
    cb: IncomingCallback,
    weekday: int,
) -> None:
    bindings = _bindings(DIGEST_KIND_PENDING)
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    current_days = _days(settings, bindings)
    new_days = toggle_digest_days_bitmask(current_days, weekday)
    if new_days is None:
        safe_answer_callback(ctx, cb, text=PENDING_DIGEST_LAST_DAY_TEXT, show_alert=True)
        return
    if new_days == current_days:
        safe_answer_callback(ctx, cb)
        return
    updated = _update_settings(
        ctx,
        cb.chat_id,
        username,
        telegram_user_id=cb.user_id,
        bindings=bindings,
        days=new_days,
    )
    log.info(
        "Toggle %s weekday=%s: chat_id=%s username=%s -> %s",
        bindings.days_field,
        weekday,
        cb.chat_id,
        username,
        _days(updated, bindings),
    )
    edit_callback_message(
        ctx,
        cb,
        bindings.days_screen_text(_days(updated, bindings)),
        bindings.build_days_keyboard(digest_days=_days(updated, bindings)),
    )
    safe_answer_callback(ctx, cb)


def handle_callback_time(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = _bindings(kind)
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    ctx.digest_state.set_waiting_for_time(cb.chat_id, cb.message_id, digest_kind=kind)
    edit_callback_message(
        ctx,
        cb,
        bindings.time_screen_text(_time(settings, bindings)),
        bindings.build_time_keyboard(),
    )
    safe_answer_callback(ctx, cb)


def handle_callback_close(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = _bindings(kind)
    if cb.chat_id is None:
        return
    ctx.digest_state.clear(cb.chat_id)
    edit_callback_message(ctx, cb, bindings.settings_closed_text, reply_markup=None)
    safe_answer_callback(ctx, cb)


def render_digest_settings_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    settings: DigestSettings,
    *,
    kind: DigestKind = DIGEST_KIND_DAILY,
) -> None:
    bindings = _bindings(kind)
    weather_in_plan_enabled = True
    if kind == DIGEST_KIND_DAILY and cb.user_id is not None:
        record = ctx.users.get(cb.user_id)
        if record is not None:
            weather_in_plan_enabled = record.weather_in_plan_enabled
    if kind == DIGEST_KIND_DAILY:
        text = bindings.screen_text(
            digest_enabled=_enabled(settings, bindings),
            digest_days=_days(settings, bindings),
            digest_time=_time(settings, bindings),
            weather_in_plan_enabled=weather_in_plan_enabled,
        )
    else:
        text = bindings.screen_text(
            digest_enabled=_enabled(settings, bindings),
            digest_days=_days(settings, bindings),
            digest_time=_time(settings, bindings),
        )
    if kind == DIGEST_KIND_DAILY:
        keyboard = bindings.build_settings_keyboard(
            digest_enabled=_enabled(settings, bindings),
            weather_in_plan_enabled=weather_in_plan_enabled,
        )
    else:
        keyboard = bindings.build_settings_keyboard(digest_enabled=_enabled(settings, bindings))
    edit_callback_message(ctx, cb, text, keyboard)


def handle_daily_weather_toggle(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    record = ctx.users.get(cb.user_id)
    if record is None:
        safe_answer_callback(ctx, cb)
        return
    new_enabled = not record.weather_in_plan_enabled
    try:
        ctx.users.set_weather_in_plan_enabled(cb.user_id, enabled=new_enabled)
    except (KeyError, UserStorePersistenceError):
        log.exception("Failed to toggle weather_in_plan in digest settings: user_id=%s", cb.user_id)
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    render_digest_settings_screen(ctx, cb, settings, kind=DIGEST_KIND_DAILY)
    safe_answer_callback(
        ctx,
        cb,
        text=weather_in_plan_toggle_notice_text(enabled=new_enabled),
    )


# --- callback routing -------------------------------------------------------


def _route_kind_callback(
    ctx: HandlerContext, cb: IncomingCallback, bindings: DigestKindBindings
) -> bool:
    data = (cb.data or "").strip()
    if data in (bindings.cb_settings, bindings.cb_back):
        show_digest_settings_screen(ctx, cb, kind=bindings.kind)
        return True
    if data == bindings.cb_toggle:
        handle_callback_toggle(ctx, cb, kind=bindings.kind)
        return True
    if data == bindings.cb_days:
        show_digest_days_screen(ctx, cb, kind=bindings.kind)
        return True
    if data == bindings.cb_days_weekdays:
        handle_callback_set_days(ctx, cb, DIGEST_DAYS_WEEKDAYS, kind=bindings.kind)
        return True
    if data == bindings.cb_days_all:
        handle_callback_set_days(ctx, cb, DIGEST_DAYS_ALL, kind=bindings.kind)
        return True
    if data == bindings.cb_time:
        handle_callback_time(ctx, cb, kind=bindings.kind)
        return True
    if bindings.kind == DIGEST_KIND_DAILY and data == CB_DIGEST_WEATHER_TOGGLE:
        handle_daily_weather_toggle(ctx, cb)
        return True
    if data == bindings.cb_close:
        handle_callback_close(ctx, cb, kind=bindings.kind)
        return True
    return False


def _route_pending_digest_day_toggle(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    data = (cb.data or "").strip()
    if not data.startswith(CB_PENDING_DIGEST_DAY_PREFIX):
        return False
    suffix = data[len(CB_PENDING_DIGEST_DAY_PREFIX) :]
    if not suffix.isdigit():
        return False
    weekday = int(suffix)
    if not 0 <= weekday <= 6:
        return False
    handle_pending_digest_day_toggle(ctx, cb, weekday)
    return True


def route_settings_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    """Диспетчер callback_data для экранов настроек обоих дайджестов."""
    data = (cb.data or "").strip()
    if not data:
        return False
    try:
        if _route_pending_digest_day_toggle(ctx, cb):
            return True
        if _route_kind_callback(ctx, cb, _BINDINGS[DIGEST_KIND_DAILY]):
            return True
        if _route_kind_callback(ctx, cb, _BINDINGS[DIGEST_KIND_PENDING]):
            return True
    except SubscriptionStorePersistenceError:
        log.exception(
            "Failed to persist digest settings from callback: chat_id=%s user_id=%s data=%r",
            cb.chat_id,
            cb.user_id,
            data,
        )
        safe_answer_callback(ctx, cb)
        send(ctx, cb.chat_id, ERR_SETTINGS_SAVE_FAILED_TEXT)
        return True
    return False
