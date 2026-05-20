"""Сценарий «команда → план дня → ответ в чат».

Loading-сообщение + редактирование (`edit_or_send_message`) уменьшают
ощущение «бот завис»: пользователь сразу видит реакцию, итог приходит на то
же сообщение, без спама в чат.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from ...digest_utils import resolve_target_date
from ...messages_ru import (
    ERR_CALDAV_UNAVAILABLE_TEXT,
    ERR_DIGEST_BUILD_FAILED_TEXT,
    PLAN_FETCH_STATUS_TEXT,
)
from .context import HandlerContext, IncomingMessage, PlanMode
from .delivery import finalize_message, try_send_return_message_id

log = logging.getLogger(__name__)


def handle_plan(ctx: HandlerContext, msg: IncomingMessage, mode: PlanMode) -> None:
    """Сценарий: «loading-сообщение → результат редактированием того же сообщения»."""
    if msg.user_id is None or msg.chat_id is None:
        return

    loading_message_id = try_send_return_message_id(
        ctx, msg.chat_id, PLAN_FETCH_STATUS_TEXT[mode]
    )

    def build_plan() -> str:
        return build_plan_for_user(ctx, telegram_user_id=msg.user_id, mode=mode)

    try:
        plan_text = build_plan()
    except (CalendarNotConnectedError, CalendarProviderError) as exc:
        log.error("Calendar failure for user_id=%s: %s", msg.user_id, exc)
        finalize_message(
            ctx, msg.chat_id, loading_message_id, ERR_CALDAV_UNAVAILABLE_TEXT
        )
        return
    except Exception:  # noqa: BLE001 - пользователю стек не показываем
        log.exception("Failed to build %s plan for user_id=%s", mode, msg.user_id)
        finalize_message(
            ctx, msg.chat_id, loading_message_id, ERR_DIGEST_BUILD_FAILED_TEXT
        )
        return

    finalize_message(ctx, msg.chat_id, loading_message_id, plan_text)
    log.info(
        "Sent %s plan to user_id=%s (update_id=%s)",
        mode,
        msg.user_id,
        msg.update_id,
    )


def build_plan_for_user(
    ctx: HandlerContext, *, telegram_user_id: int, mode: PlanMode
) -> str:
    today_local = datetime.now(tz=ctx.tz).date()
    target_date = resolve_target_date(mode, today_local)
    return ctx.plan_builder().build_text(
        telegram_user_id=telegram_user_id,
        target_date=target_date,
        reference_date=today_local,
    )
