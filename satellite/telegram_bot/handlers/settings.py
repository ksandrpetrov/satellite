"""UI настроек дайджеста: открытие экрана, ввод времени, inline-кнопки.

Все вью-функции, относящиеся к экрану ``/settings`` и его callback'ам, живут
в одном модуле — общий контекст (state, store, edit/answer) удобно держать
рядом.
"""

from __future__ import annotations

import logging

from ...calendar.time_utils import normalize_hhmm_input
from ...messages_ru import (
    CB_DIGEST_BACK,
    CB_DIGEST_CLOSE,
    CB_SETTINGS_BACK,
    CB_DIGEST_DAYS,
    CB_DIGEST_DAYS_ALL,
    CB_DIGEST_DAYS_WEEKDAYS,
    CB_DIGEST_SETTINGS,
    CB_DIGEST_TIME,
    CB_DIGEST_TOGGLE,
    DIGEST_DAYS_ALL_APPLIED_TEXT,
    DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
    DIGEST_SETTINGS_CLOSED_TEXT,
    DIGEST_TIME_INVALID_TEXT,
    build_digest_days_keyboard,
    build_digest_settings_keyboard,
    build_digest_time_keyboard,
    digest_days_screen_text,
    digest_settings_screen_text,
    digest_time_applied_text,
    digest_time_screen_text,
    digest_toggle_notice_text,
)
from ...subscriptions import DIGEST_DAYS_ALL, DIGEST_DAYS_WEEKDAYS, DigestSettings
from .access import effective_username, effective_username_from_callback
from .context import HandlerContext, IncomingCallback, IncomingMessage
from .delivery import edit_callback_message, safe_answer_callback, send

log = logging.getLogger(__name__)


# --- text/keyboard scenarios -----------------------------------------------


def handle_open_digest_settings(
    ctx: HandlerContext, msg: IncomingMessage
) -> None:
    """Открывает экран настроек по кнопке reply-клавиатуры / команде."""
    if msg.chat_id is None or msg.user_id is None:
        return
    username = effective_username(msg)
    # Выход из state ожидания времени, если он был.
    ctx.digest_state.clear(msg.chat_id)
    settings = ctx.subscriptions.get_or_create(msg.chat_id, username)
    text = digest_settings_screen_text(
        digest_enabled=settings.digest_enabled,
        digest_days=settings.digest_days,
        digest_time=settings.digest_time,
    )
    keyboard = build_digest_settings_keyboard(digest_enabled=settings.digest_enabled)
    ctx.telegram.send_message(msg.chat_id, text, reply_markup=keyboard)
    log.info(
        "Opened digest settings: chat_id=%s username=%s", msg.chat_id, username
    )


def handle_digest_time_input(ctx: HandlerContext, msg: IncomingMessage) -> None:
    """Принимает свободный текст пользователя как новое время."""
    if msg.chat_id is None or msg.user_id is None:
        return
    username = effective_username(msg)
    normalized = normalize_hhmm_input(msg.text)
    if normalized is None:
        log.info(
            "Invalid digest time input from %s: %r", username, msg.text
        )
        # State НЕ очищаем — спека требует, чтобы при невалидном вводе
        # пользователь оставался в режиме ожидания времени.
        send(ctx, msg.chat_id, DIGEST_TIME_INVALID_TEXT)
        return

    updated = ctx.subscriptions.update_settings(
        msg.chat_id,
        username,
        digest_time=normalized,
    )
    ctx.digest_state.clear(msg.chat_id)
    log.info(
        "Updated digest_time: chat_id=%s username=%s -> %s",
        msg.chat_id,
        username,
        updated.digest_time,
    )
    send(ctx, msg.chat_id, digest_time_applied_text(updated.digest_time))


# --- callback handlers -----------------------------------------------------


def handle_callback_toggle(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username)
    new_enabled = not settings.digest_enabled
    updated = ctx.subscriptions.update_settings(
        cb.chat_id, username, digest_enabled=new_enabled
    )
    notice = digest_toggle_notice_text(enabled=updated.digest_enabled)
    log.info(
        "Toggle digest: chat_id=%s username=%s -> %s",
        cb.chat_id,
        username,
        updated.digest_enabled,
    )
    render_digest_settings_screen(ctx, cb, updated)
    safe_answer_callback(ctx, cb, text=notice)


def show_digest_settings_screen(
    ctx: HandlerContext, cb: IncomingCallback
) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    ctx.digest_state.clear(cb.chat_id)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username)
    render_digest_settings_screen(ctx, cb, settings)
    safe_answer_callback(ctx, cb)


def show_digest_days_screen(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username)
    edit_callback_message(
        ctx,
        cb,
        digest_days_screen_text(settings.digest_days),
        build_digest_days_keyboard(digest_days=settings.digest_days),
    )
    safe_answer_callback(ctx, cb)


def handle_callback_set_days(
    ctx: HandlerContext, cb: IncomingCallback, value: str
) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    before = ctx.subscriptions.get_or_create(cb.chat_id, username)
    updated = ctx.subscriptions.update_settings(
        cb.chat_id, username, digest_days=value
    )
    changed = before.digest_days != updated.digest_days
    log.info(
        "Set digest_days: chat_id=%s username=%s -> %s (changed=%s)",
        cb.chat_id,
        username,
        updated.digest_days,
        changed,
    )
    render_digest_settings_screen(ctx, cb, updated)
    # Подтверждение отдельным сообщением — только если значение реально
    # поменялось. Иначе повторный тап по уже-активной кнопке не должен
    # засорять чат «Готово.»-сообщениями.
    if changed:
        confirmation = (
            DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT
            if updated.digest_days == DIGEST_DAYS_WEEKDAYS
            else DIGEST_DAYS_ALL_APPLIED_TEXT
        )
        send(ctx, cb.chat_id, confirmation)
    safe_answer_callback(ctx, cb)


def handle_callback_time(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None or cb.user_id is None:
        return
    username = effective_username_from_callback(cb)
    settings = ctx.subscriptions.get_or_create(cb.chat_id, username)
    ctx.digest_state.set_waiting_for_time(cb.chat_id, cb.message_id)
    edit_callback_message(
        ctx,
        cb,
        digest_time_screen_text(settings.digest_time),
        build_digest_time_keyboard(),
    )
    safe_answer_callback(ctx, cb)


def handle_callback_close(ctx: HandlerContext, cb: IncomingCallback) -> None:
    if cb.chat_id is None:
        return
    ctx.digest_state.clear(cb.chat_id)
    edit_callback_message(ctx, cb, DIGEST_SETTINGS_CLOSED_TEXT, reply_markup=None)
    safe_answer_callback(ctx, cb)


def render_digest_settings_screen(
    ctx: HandlerContext, cb: IncomingCallback, settings: DigestSettings
) -> None:
    text = digest_settings_screen_text(
        digest_enabled=settings.digest_enabled,
        digest_days=settings.digest_days,
        digest_time=settings.digest_time,
    )
    keyboard = build_digest_settings_keyboard(digest_enabled=settings.digest_enabled)
    edit_callback_message(ctx, cb, text, keyboard)


# --- callback routing -------------------------------------------------------


def route_settings_callback(ctx: HandlerContext, cb: IncomingCallback) -> bool:
    """Диспетчер callback_data для всех экранов настроек дайджеста.

    Возвращает ``True``, если callback относится к настройкам и обработан.
    ``False`` — если callback_data не из этого экрана (диспетчер выше делает
    fallback на ``safe_answer_callback`` + лог). Когда добавляешь новую кнопку
    настроек — расширяй именно эту таблицу: один модуль на сценарий.
    """
    data = (cb.data or "").strip()
    if data in (CB_DIGEST_SETTINGS, CB_DIGEST_BACK):
        show_digest_settings_screen(ctx, cb)
        return True
    if data == CB_DIGEST_TOGGLE:
        handle_callback_toggle(ctx, cb)
        return True
    if data == CB_DIGEST_DAYS:
        show_digest_days_screen(ctx, cb)
        return True
    if data == CB_DIGEST_DAYS_WEEKDAYS:
        handle_callback_set_days(ctx, cb, DIGEST_DAYS_WEEKDAYS)
        return True
    if data == CB_DIGEST_DAYS_ALL:
        handle_callback_set_days(ctx, cb, DIGEST_DAYS_ALL)
        return True
    if data == CB_DIGEST_TIME:
        handle_callback_time(ctx, cb)
        return True
    if data == CB_DIGEST_CLOSE:
        handle_callback_close(ctx, cb)
        return True
    if data == CB_SETTINGS_BACK:
        from .settings_hub import show_settings_hub_screen

        show_settings_hub_screen(ctx, cb)
        return True
    return False
