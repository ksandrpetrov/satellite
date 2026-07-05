"""Политика «пора ли стрелять» для per-user дайджестов."""

from __future__ import annotations

import logging
from datetime import datetime

from .calendar.time_utils import parse_hhmm
from .digest_utils import is_digest_day_allowed
from .subscriptions import DigestSettings

log = logging.getLogger(__name__)


def should_fire_at(
    *,
    enabled: bool,
    days: str,
    time_str: str,
    last_sent_iso: str | None,
    now_in_user_tz: datetime,
    chat_id: int | None = None,
    log_label: str = "digest_time",
) -> bool:
    """Чистый решатель «пора ли стрелять» для одного вида дайджеста."""
    if not enabled:
        return False
    if not is_digest_day_allowed(days, now_in_user_tz.weekday()):
        return False
    try:
        scheduled_minutes = parse_hhmm(time_str)
    except ValueError:
        if chat_id is not None:
            log.warning(
                "Invalid %s for chat_id=%s: %r",
                log_label,
                chat_id,
                time_str,
            )
        return False
    current_minutes = now_in_user_tz.hour * 60 + now_in_user_tz.minute
    if current_minutes < scheduled_minutes:
        return False
    today_iso = now_in_user_tz.date().isoformat()
    if last_sent_iso == today_iso:
        return False
    return True


def should_fire_for_user(
    *,
    settings: DigestSettings,
    now_in_user_tz: datetime,
) -> bool:
    """Дайджест на сегодня (план дня)."""
    return should_fire_at(
        enabled=settings.digest_enabled,
        days=settings.digest_days,
        time_str=settings.digest_time,
        last_sent_iso=settings.last_digest_sent_date,
        now_in_user_tz=now_in_user_tz,
        chat_id=settings.chat_id,
        log_label="digest_time",
    )


def should_fire_pending_for_user(
    *,
    settings: DigestSettings,
    now_in_user_tz: datetime,
) -> bool:
    """Дайджест непринятых встреч (экран /invitations)."""
    return should_fire_at(
        enabled=settings.pending_digest_enabled,
        days=settings.pending_digest_days,
        time_str=settings.pending_digest_time,
        last_sent_iso=settings.last_pending_digest_sent_date,
        now_in_user_tz=now_in_user_tz,
        chat_id=settings.chat_id,
        log_label="pending_digest_time",
    )
