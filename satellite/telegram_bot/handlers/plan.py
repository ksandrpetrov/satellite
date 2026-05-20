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
    PLAN_FETCH_STATUS_TEXT,
)
from .context import HandlerContext, IncomingMessage, PlanMode
from .delivery import open_streaming_reply

log = logging.getLogger(__name__)


def handle_plan(ctx: HandlerContext, msg: IncomingMessage, mode: PlanMode) -> None:
    """Сценарий: потоковый черновик → финальный ``sendMessage`` с дайджестом."""
    if msg.user_id is None or msg.chat_id is None:
        return

    stream = open_streaming_reply(
        ctx,
        msg.chat_id,
        PLAN_FETCH_STATUS_TEXT[mode],
        draft_id=msg.update_id,
    )

    try:
        plan_text = build_plan_for_user(
            ctx,
            telegram_user_id=msg.user_id,
            mode=mode,
            on_progress=stream.push,
        )
    except (CalendarNotConnectedError, CalendarProviderError) as exc:
        log.error("Calendar failure for user_id=%s: %s", msg.user_id, exc)
        stream.finish(ERR_CALDAV_UNAVAILABLE_TEXT)
        return
    except Exception:  # noqa: BLE001 - пользователю стек не показываем
        log.exception("Failed to build %s plan for user_id=%s", mode, msg.user_id)
        stream.finish(ERR_DIGEST_BUILD_FAILED_TEXT)
        return

    stream.finish(plan_text)
    log.info(
        "Sent %s plan to user_id=%s (update_id=%s)",
        mode,
        msg.user_id,
        msg.update_id,
    )


def build_plan_for_user(
    ctx: HandlerContext,
    *,
    telegram_user_id: int,
    mode: PlanMode,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    today_local = datetime.now(tz=ctx.tz).date()
    target_date = resolve_target_date(mode, today_local)
    return ctx.plan_builder().build_text(
        telegram_user_id=telegram_user_id,
        target_date=target_date,
        reference_date=today_local,
        on_progress=on_progress,
    )
