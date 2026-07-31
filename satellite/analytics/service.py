"""Сборка недельной аналитики: CalDAV → отчёт → PNG + подпись."""

from __future__ import annotations

import logging
from datetime import date, timedelta, tzinfo

from ..calendar.event_exclusions import EventExclusionPolicy
from ..calendar.period_stats import (
    QUARTER_WEEKS,
    build_analytics_report,
    week_bounds,
    workday_options_from_preset,
)
from ..calendar.user_calendar_service import UserCalendarService
from ..users import UserStore
from .caption import build_analytics_caption
from .render_card import render_analytics_card
from .rich_caption import build_analytics_rich_caption

log = logging.getLogger(__name__)


def build_week_analytics(
    *,
    telegram_user_id: int,
    reference_date: date,
    tz: tzinfo,
    calendar_service: UserCalendarService,
    users: UserStore,
    exclusion_policy: EventExclusionPolicy | None = None,
) -> tuple[bytes, str, str]:
    connected = calendar_service.require_connection(telegram_user_id)
    login = connected.context.login
    record = connected.record
    preset = record.analytics_workday
    options = workday_options_from_preset(preset)

    current_start, current_end = week_bounds(reference_date)
    quarter_start = current_start - timedelta(days=7 * (QUARTER_WEEKS - 1))

    events = calendar_service.list_events_for_analytics(
        telegram_user_id,
        start_date=quarter_start,
        end_date=current_end,
        tz=tz,
    )
    report = build_analytics_report(
        events,
        reference_date,
        tz=tz,
        login=login,
        options=options,
        exclusion_policy=exclusion_policy,
    )
    log.info(
        "Analytics input quality user_id=%s events=%d duplicates_dropped=%d unverified_partstat=%d",
        telegram_user_id,
        len(events),
        report.quality.duplicate_occurrences_dropped,
        report.quality.unverified_partstat_events,
    )
    png = render_analytics_card(report)
    caption = build_analytics_caption(report)
    rich_caption = build_analytics_rich_caption(report)
    return png, caption, rich_caption
