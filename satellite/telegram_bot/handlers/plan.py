"""Сценарий «команда → план дня → ответ в чат».

Потоковая доставка (`sendMessageDraft` + финальный ``sendMessage``) или
fallback loading+edit — см. ``streaming_delivery``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...digest_utils import resolve_target_date
from ...messages_ru import (
    ERR_CALDAV_UNAVAILABLE_TEXT,
    ERR_DIGEST_BUILD_FAILED_TEXT,
    PLAN_BUSY_TEXT,
    PLAN_FETCH_STATUS_TEXT,
    PLAN_PROGRESS_COMPUTING,
)
from ...plan_service import PlanTextBundle
from ..visual import is_private_chat, pick_plan_message_effect
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingMessage, PlanMode
from .delivery import open_streaming_reply, send

log = logging.getLogger(__name__)

_plan_run_guard = ActionGuard(cooldown_sec=0.0)


def _plan_action_key(mode: PlanMode) -> str:
    return f"plan:{mode}"


def handle_plan(ctx: HandlerContext, msg: IncomingMessage, mode: PlanMode) -> None:
    """Сценарий: потоковый черновик → финальный ``sendMessage`` с дайджестом."""
    if msg.user_id is None or msg.chat_id is None:
        return

    action = _plan_action_key(mode)
    if not _plan_run_guard.try_acquire(msg.chat_id, action):
        log.info(
            "Plan run skipped (build in progress): user_id=%s mode=%s",
            msg.user_id,
            mode,
        )
        send(ctx, msg.chat_id, PLAN_BUSY_TEXT)
        return

    sent = False
    try:
        stream = open_streaming_reply(ctx, msg.chat_id, draft_id=msg.update_id, rich=True)
        stream.push_status(PLAN_FETCH_STATUS_TEXT[mode])

        try:
            plan_bundle = build_plan_bundle_for_user(
                ctx,
                telegram_user_id=msg.user_id,
                mode=mode,
                on_progress=lambda _: stream.push_status(PLAN_PROGRESS_COMPUTING),
            )
        except (CalendarNotConnectedError, CalendarProviderError) as exc:
            log.error("Calendar failure for user_id=%s: %s", msg.user_id, exc)
            stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT, rich=False)
            return
        except Exception:  # noqa: BLE001 - пользователю стек не показываем
            log.exception("Failed to build %s plan for user_id=%s", mode, msg.user_id)
            stream.finish(ERR_DIGEST_BUILD_FAILED_TEXT, rich=False)
            return

        effect = (
            pick_plan_message_effect(plan_bundle.fallback_html)
            if is_private_chat(msg.chat_id)
            else None
        )
        stream.finish(
            plan_bundle.rich_html,
            fallback_html=plan_bundle.fallback_html,
            rich=True,
            message_effect_id=effect,
        )
        sent = True
        log.info(
            "Sent %s plan to user_id=%s (update_id=%s)",
            mode,
            msg.user_id,
            msg.update_id,
        )
    finally:
        _plan_run_guard.release(msg.chat_id, action, sent=sent)


def build_plan_bundle_for_user(
    ctx: HandlerContext,
    *,
    telegram_user_id: int,
    mode: PlanMode,
    on_progress: Callable[[str], None] | None = None,
) -> PlanTextBundle:
    today_local = datetime.now(tz=ctx.tz).date()
    target_date = resolve_target_date(mode, today_local)
    record = ctx.users.get(telegram_user_id)
    weather_in_plan = record.weather_in_plan_enabled if record is not None else True
    exclusion_policy = ctx.meeting_exclusions.policy_for_user(telegram_user_id)
    return ctx.plan_builder().build_plan_bundle(
        telegram_user_id=telegram_user_id,
        target_date=target_date,
        reference_date=today_local,
        on_progress=on_progress,
        weather_in_plan_enabled=weather_in_plan,
        exclusion_policy=exclusion_policy,
    )


def build_plan_for_user(
    ctx: HandlerContext,
    *,
    telegram_user_id: int,
    mode: PlanMode,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    return build_plan_bundle_for_user(
        ctx,
        telegram_user_id=telegram_user_id,
        mode=mode,
        on_progress=on_progress,
    ).fallback_html
