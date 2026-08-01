"""Недельная аналитика календаря: PNG + подпись."""

from __future__ import annotations

import logging
from datetime import datetime

from ...analytics.service import build_week_analytics
from ...calendar.constants import ANALYTICS_WORKDAY_10_19
from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...messages_ru import (
    ANALYTICS_BUSY_TOAST,
    ANALYTICS_SAVED_TOAST,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    ERR_GENERIC_HANDLER_TEXT,
    ERR_SETTINGS_SAVE_FAILED_TEXT,
    build_analytics_options_keyboard,
)
from ...presentation.delivery import deliver_rich_or_html
from ...users import UserStorePersistenceError
from ..api import TelegramError
from ..presenters.settings_screens import analytics_options_bundle, analytics_workday_applied_bundle
from ..visual import pick_analytics_effect, private_message_effect
from .access import ensure_calendar_connected
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingCallback
from .delivery import (
    open_streaming_reply,
    respond_callback_nav,
    safe_answer_callback,
)

log = logging.getLogger(__name__)

# Повтор «Построить отчёт» пока идёт сборка или сразу после отправки: второй
# callback ждёт chat lock и стартует только когда первый уже закончил — без
# debounce пользователь получает два PNG подряд (см. prod log 2026-05-21
# 12:49:50/57 UTC). 45 c — заметно длиннее средней сборки PNG (~10 c).
_ANALYTICS_ACTION = "analytics:run"
_analytics_run_guard = ActionGuard(cooldown_sec=45.0)


def handle_open_analytics(ctx: HandlerContext, cb: IncomingCallback) -> None:
    """Экран выбора рабочего дня перед построением отчёта."""
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not ensure_calendar_connected(ctx, chat_id=cb.chat_id, user_id=cb.user_id):
        safe_answer_callback(ctx, cb)
        return
    record = ctx.users.get(cb.user_id)
    preset = record.analytics_workday if record else ANALYTICS_WORKDAY_10_19
    keyboard = build_analytics_options_keyboard(workday_preset=preset)
    bundle = analytics_options_bundle(workday_preset=preset, reply_markup=keyboard)
    respond_callback_nav(ctx, cb, bundle)


def handle_run_analytics(ctx: HandlerContext, cb: IncomingCallback) -> None:
    user_id = cb.user_id
    if user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    if not ensure_calendar_connected(ctx, chat_id=cb.chat_id, user_id=user_id):
        safe_answer_callback(ctx, cb)
        return
    if not _analytics_run_guard.try_acquire(cb.chat_id, _ANALYTICS_ACTION):
        safe_answer_callback(ctx, cb, text=ANALYTICS_BUSY_TOAST)
        return

    safe_answer_callback(ctx, cb)
    sent = False
    try:
        stream = open_streaming_reply(
            ctx,
            cb.chat_id,
            chat_action="upload_photo",
            use_draft=False,
        )

        def build() -> tuple[bytes, str, str]:
            today = datetime.now(tz=ctx.tz).date()
            exclusion_policy = ctx.meeting_exclusions.policy_for_user(user_id)
            return build_week_analytics(
                telegram_user_id=user_id,
                reference_date=today,
                tz=ctx.tz,
                calendar_service=ctx.calendar_service,
                users=ctx.users,
                exclusion_policy=exclusion_policy,
            )

        try:
            png, caption, rich_caption = build()
        except CalendarNotConnectedError:
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return
        except CalendarProviderError as exc:
            log.error("Analytics failed user_id=%s: %s", cb.user_id, exc.error_code)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False, typewriter=False)
            return
        except Exception:  # noqa: BLE001 - не оставляем upload_photo без финального ответа
            log.exception("Analytics build failed user_id=%s", cb.user_id)
            stream.finish(ERR_GENERIC_HANDLER_TEXT, rich=False, typewriter=False)
            return

        effect = private_message_effect(pick_analytics_effect(), cb.chat_id)
        try:
            ctx.telegram.send_photo(
                cb.chat_id,
                png,
                message_effect_id=effect,
            )
        except TelegramError as exc:
            log.error(
                "Analytics sendPhoto failed user_id=%s chat_id=%s: %s",
                cb.user_id,
                cb.chat_id,
                exc,
            )
            stream.finish(ERR_GENERIC_HANDLER_TEXT, rich=False, typewriter=False)
            return
        stream.dismiss()
        deliver_rich_or_html(
            ctx.telegram,
            cb.chat_id,
            rich_html=rich_caption,
            fallback_html=caption,
        )
        sent = True
        log.info("Sent weekly analytics user_id=%s chat_id=%s", cb.user_id, cb.chat_id)
    finally:
        _analytics_run_guard.release(cb.chat_id, _ANALYTICS_ACTION, sent=sent)


def handle_set_analytics_workday(ctx: HandlerContext, cb: IncomingCallback, preset: str) -> None:
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    try:
        ctx.users.set_analytics_workday(cb.user_id, preset=preset)
    except (KeyError, ValueError):
        safe_answer_callback(ctx, cb)
        return
    except UserStorePersistenceError:
        log.exception("Failed to persist analytics workday user_id=%s", cb.user_id)
        safe_answer_callback(ctx, cb, text=ERR_SETTINGS_SAVE_FAILED_TEXT)
        return
    keyboard = build_analytics_options_keyboard(workday_preset=preset)
    bundle = analytics_workday_applied_bundle(workday_preset=preset, reply_markup=keyboard)
    respond_callback_nav(ctx, cb, bundle, toast=ANALYTICS_SAVED_TOAST)
