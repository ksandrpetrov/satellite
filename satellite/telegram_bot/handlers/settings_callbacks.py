"""Digest settings screens, callbacks, and routing."""

from __future__ import annotations

import logging

from ...calendar.time_utils import normalize_hhmm_input
from ...digest_utils import toggle_digest_days_bitmask
from ...messages_ru import (
    CB_DIGEST_WEATHER_TOGGLE,
    CB_PENDING_DIGEST_DAY_PREFIX,
    ERR_SETTINGS_SAVE_FAILED_TEXT,
    PENDING_DIGEST_LAST_DAY_TEXT,
    weather_in_plan_toggle_notice_text,
)
from ...subscriptions import (
    DIGEST_DAYS_ALL,
    DIGEST_DAYS_WEEKDAYS,
    DigestSettings,
    SubscriptionStorePersistenceError,
)
from ...users import UserStorePersistenceError
from .access import effective_username, effective_username_from_callback
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import (
    edit_callback_bundle,
    respond_callback_nav,
    respond_callback_rich_nav,
    safe_answer_callback,
    send,
)
from .digest_state import DIGEST_KIND_DAILY, DIGEST_KIND_PENDING, DigestKind
from .settings_actions import toggle_weather_in_plan
from .settings_bindings import (
    BINDINGS,
    DigestKindBindings,
    bindings_for,
    build_days_screen_bundle,
    build_settings_screen_bundle,
    build_time_screen_bundle,
    days_value,
    enabled_value,
    time_value,
    update_settings,
)

log = logging.getLogger(__name__)

# --- text/keyboard scenarios -----------------------------------------------


def handle_digest_time_input(ctx: HandlerContext, msg: IncomingMessage) -> None:
    """Принимает свободный текст пользователя как новое время (daily или pending)."""
    if msg.chat_id is None or msg.user_id is None:
        return
    waiting = ctx.digest_state.get(msg.chat_id)
    if waiting is None or waiting.state != "waiting_for_digest_time":
        return
    kind: DigestKind = waiting.digest_kind
    bindings = bindings_for(kind)
    username = effective_username(msg)
    normalized = normalize_hhmm_input(msg.text)
    if normalized is None:
        log.info("Invalid digest time input from %s: %r kind=%s", username, msg.text, kind)
        send(ctx, msg.chat_id, bindings.time_invalid_text)
        return

    try:
        updated = update_settings(
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
        time_value(updated, bindings),
    )
    send(ctx, msg.chat_id, bindings.time_applied_text(time_value(updated, bindings)))


# --- callback handlers -----------------------------------------------------


def handle_callback_toggle(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = bindings_for(kind)
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    new_enabled = not enabled_value(settings, bindings)
    updated = update_settings(
        ctx,
        cb.chat_id,
        username,
        telegram_user_id=cb.user_id,
        bindings=bindings,
        enabled=new_enabled,
    )
    notice = bindings.toggle_notice(enabled=enabled_value(updated, bindings))
    log.info(
        "Toggle %s: chat_id=%s username=%s -> %s",
        bindings.enabled_field,
        cb.chat_id,
        username,
        enabled_value(updated, bindings),
    )
    safe_answer_callback(ctx, cb, text=notice)
    render_digest_settings_screen(ctx, cb, updated, kind=kind)


def show_digest_settings_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    *,
    kind: DigestKind = DIGEST_KIND_DAILY,
) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    ctx.digest_state.clear(cb.chat_id)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    safe_answer_callback(ctx, cb)
    render_digest_settings_screen(ctx, cb, settings, kind=kind)


def show_pending_digest_settings_screen(ctx: HandlerContext, cb: IncomingCallback) -> None:
    show_digest_settings_screen(ctx, cb, kind=DIGEST_KIND_PENDING)


def show_digest_days_screen(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = bindings_for(kind)
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    keyboard = bindings.build_days_keyboard(digest_days=days_value(settings, bindings))
    bundle = build_days_screen_bundle(
        days_value(settings, bindings),
        bindings,
        kind=kind,
        keyboard=keyboard,
    )
    respond_callback_nav(ctx, cb, bundle)


def handle_callback_set_days(
    ctx: HandlerContext,
    cb: IncomingCallback,
    value: str,
    *,
    kind: DigestKind = DIGEST_KIND_DAILY,
) -> None:
    bindings = bindings_for(kind)
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    before = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    updated = update_settings(
        ctx,
        cb.chat_id,
        username,
        telegram_user_id=cb.user_id,
        bindings=bindings,
        days=value,
    )
    changed = days_value(before, bindings) != days_value(updated, bindings)
    log.info(
        "Set %s: chat_id=%s username=%s -> %s (changed=%s)",
        bindings.days_field,
        cb.chat_id,
        username,
        days_value(updated, bindings),
        changed,
    )
    safe_answer_callback(ctx, cb)
    render_digest_settings_screen(ctx, cb, updated, kind=kind)
    if changed:
        confirmation = (
            bindings.days_weekdays_applied
            if days_value(updated, bindings) == DIGEST_DAYS_WEEKDAYS
            else bindings.days_all_applied
        )
        send(ctx, cb.chat_id, confirmation)


def handle_pending_digest_day_toggle(
    ctx: HandlerContext,
    cb: IncomingCallback,
    weekday: int,
) -> None:
    bindings = bindings_for(DIGEST_KIND_PENDING)
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    current_days = days_value(settings, bindings)
    new_days = toggle_digest_days_bitmask(current_days, weekday)
    if new_days is None:
        safe_answer_callback(ctx, cb, text=PENDING_DIGEST_LAST_DAY_TEXT, show_alert=True)
        return
    if new_days == current_days:
        safe_answer_callback(ctx, cb)
        return
    updated = update_settings(
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
        days_value(updated, bindings),
    )
    keyboard = bindings.build_days_keyboard(digest_days=days_value(updated, bindings))
    bundle = build_days_screen_bundle(
        days_value(updated, bindings),
        bindings,
        kind=DIGEST_KIND_PENDING,
        keyboard=keyboard,
    )
    respond_callback_nav(ctx, cb, bundle)


def handle_callback_time(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = bindings_for(kind)
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    if cb.chat_id is not None:
        ctx.calendar_state.clear(cb.chat_id)
    ctx.digest_state.set_waiting_for_time(cb.chat_id, cb.message_id, digest_kind=kind)
    keyboard = bindings.build_time_keyboard()
    bundle = build_time_screen_bundle(time_value(settings, bindings), keyboard)
    respond_callback_nav(ctx, cb, bundle)


def handle_callback_close(
    ctx: HandlerContext, cb: IncomingCallback, *, kind: DigestKind = DIGEST_KIND_DAILY
) -> None:
    bindings = bindings_for(kind)
    if cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    ctx.digest_state.clear(cb.chat_id)
    respond_callback_rich_nav(
        ctx,
        cb,
        rich_html=bindings.settings_closed_text,
        fallback_html=bindings.settings_closed_text,
        reply_markup=None,
    )


def render_digest_settings_screen(
    ctx: HandlerContext,
    cb: IncomingCallback,
    settings: DigestSettings,
    *,
    kind: DigestKind = DIGEST_KIND_DAILY,
) -> None:
    bindings = bindings_for(kind)
    weather_in_plan_enabled = True
    if kind == DIGEST_KIND_DAILY and cb.user_id is not None:
        record = ctx.users.get(cb.user_id)
        if record is not None:
            weather_in_plan_enabled = record.weather_in_plan_enabled
    if kind == DIGEST_KIND_DAILY:
        keyboard = bindings.build_settings_keyboard(
            digest_enabled=enabled_value(settings, bindings),
            weather_in_plan_enabled=weather_in_plan_enabled,
        )
    else:
        keyboard = bindings.build_settings_keyboard(
            digest_enabled=enabled_value(settings, bindings)
        )
    bundle = build_settings_screen_bundle(
        settings,
        bindings,
        kind=kind,
        keyboard=keyboard,
        weather_in_plan_enabled=weather_in_plan_enabled,
    )
    edit_callback_bundle(ctx, cb, bundle)


def handle_daily_weather_toggle(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        new_enabled = toggle_weather_in_plan(ctx, cb.user_id)
    except UserStorePersistenceError:
        safe_answer_callback(ctx, cb, text=ERR_SETTINGS_SAVE_FAILED_TEXT)
        return
    if new_enabled is None:
        safe_answer_callback(ctx, cb)
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username, telegram_user_id=cb.user_id)
    safe_answer_callback(
        ctx,
        cb,
        text=weather_in_plan_toggle_notice_text(enabled=new_enabled),
    )
    render_digest_settings_screen(ctx, cb, settings, kind=DIGEST_KIND_DAILY)


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
        if _route_kind_callback(ctx, cb, BINDINGS[DIGEST_KIND_DAILY]):
            return True
        if _route_kind_callback(ctx, cb, BINDINGS[DIGEST_KIND_PENDING]):
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
