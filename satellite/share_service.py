"""Сборка PNG для Web App «Поделиться» (план, ближайшие, аналитика)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from .analytics_service import build_week_analytics
from .calendar.events import build_upcoming_events_groups, filter_events_for_user
from .calendar.user_calendar_service import UserCalendarService
from .config import PlanConfig
from .digest_utils import resolve_target_date
from .seagull.digest import prepare_seagull_stats
from .seagull.rules import build_seagull_texts
from .share.cards import render_plan_share_card, render_upcoming_share_card
from .users import UserStore

SHARE_KIND_PLAN = "plan"
SHARE_KIND_UPCOMING = "upcoming"
SHARE_KIND_ANALYTICS = "analytics"

_VALID_PLAN_MODES = frozenset({"today", "tomorrow", "day_after_tomorrow"})
_DEFAULT_UPCOMING_DAYS = 7


def build_share_png(
    *,
    kind: str,
    telegram_user_id: int,
    tz: tzinfo,
    calendar_service: UserCalendarService,
    users: UserStore,
    plan_config: PlanConfig,
    mode: str | None = None,
    days: int | None = None,
    reference_date: date | None = None,
) -> bytes:
    """Возвращает PNG для ``kind`` (plan / upcoming / analytics)."""
    today = reference_date or datetime.now(tz=tz).date()
    if kind == SHARE_KIND_PLAN:
        plan_mode = mode if mode in _VALID_PLAN_MODES else "today"
        target = resolve_target_date(plan_mode, today)
        events, login = calendar_service.fetch_events_for_day(
            telegram_user_id, target, tz=tz
        )
        visible, _hidden = filter_events_for_user(
            events,
            target,
            tz=tz,
            login=login,
            hide_all_day=plan_config.hide_all_day_events,
            hide_lunch=plan_config.hide_lunch_events,
        )
        stats, _meal = prepare_seagull_stats(
            visible,
            target,
            tz=tz,
            reference_date=today,
            login=login,
        )
        texts = build_seagull_texts(stats)
        return render_plan_share_card(stats, texts)

    if kind == SHARE_KIND_UPCOMING:
        horizon = days if days and 1 <= days <= 31 else _DEFAULT_UPCOMING_DAYS
        end = today + timedelta(days=horizon)
        events = calendar_service.list_events(
            telegram_user_id,
            start_date=today,
            end_date=end,
            tz=tz,
        )
        groups = build_upcoming_events_groups(
            events, tz, today, days=horizon
        )
        return render_upcoming_share_card(
            groups, days=horizon, reference_date=today
        )

    if kind == SHARE_KIND_ANALYTICS:
        png, _caption = build_week_analytics(
            telegram_user_id=telegram_user_id,
            reference_date=today,
            tz=tz,
            calendar_service=calendar_service,
            users=users,
        )
        return png

    raise ValueError(f"unknown share kind: {kind}")
