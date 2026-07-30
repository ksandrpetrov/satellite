"""Общая сборка экрана «непринятые приглашения» для /invitations и scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, cast

from .calendar.callback_tokens import event_callback_token
from .calendar.event_token_cache import get_event_token_cache
from .calendar.events import (
    collect_pending_invitations,
    event_local_start_date,
    format_invitation_list_lines,
    format_time_range,
    format_upcoming_day_header,
)
from .calendar.user_calendar_service import UserCalendarService
from .messages_ru import (
    INVITATIONS_EMPTY_HTML,
    build_invitations_keyboard,
    invitations_list_html,
)
from .presentation.calendar_lists import invitations_list_rich_html

INVITATION_HORIZON_DAYS = 60
INVITATION_LOOKBACK_DAYS = 14
MAX_INVITATIONS = 12

Event = dict[str, Any]


@dataclass(frozen=True)
class InvitationsScreen:
    """Результат загрузки pending-приглашений: текст, клавиатура, метаданные."""

    pending: list[Event]
    text: str
    rich_text: str
    keyboard: dict
    truncated: bool
    login: str


def fetch_invitation_events(
    calendar_service: UserCalendarService,
    user_id: int,
    *,
    tz: tzinfo,
    now: datetime | None = None,
) -> tuple[list[Event], str, datetime]:
    """Все события на горизонте приглашений (до фильтра NEEDS-ACTION)."""
    moment = now or datetime.now(tz=tz)
    today = moment.date()
    start = today - timedelta(days=INVITATION_LOOKBACK_DAYS)
    end = today + timedelta(days=INVITATION_HORIZON_DAYS)
    connected = calendar_service.require_connection(user_id)
    login = connected.context.login
    events = calendar_service.list_events_for_invitations(
        user_id,
        start_date=start,
        end_date=end,
        tz=tz,
    )
    return events, login, moment


def collect_pending_from_events(
    events: list[Event],
    login: str,
    tz: tzinfo,
    *,
    now: datetime,
) -> tuple[list[Event], bool]:
    """Pending NEEDS-ACTION с тем же лимитом, что экран /invitations."""
    pending = collect_pending_invitations(
        events,
        login,
        tz,
        now=now,
        max_events=MAX_INVITATIONS + 1,
        lookback_days=INVITATION_LOOKBACK_DAYS,
    )
    truncated = len(pending) > MAX_INVITATIONS
    if truncated:
        pending = pending[:MAX_INVITATIONS]
    return cast(list[Event], pending), truncated


def screen_from_pending(
    pending: list[Event],
    tz: tzinfo,
    *,
    reference_date: date,
    truncated: bool,
    from_settings_hub: bool = False,
) -> tuple[str, str, dict]:
    if not pending:
        empty = INVITATIONS_EMPTY_HTML
        return empty, empty, build_invitations_keyboard([], from_settings_hub=from_settings_hub)
    preview_event = pending[0]
    preview_title = str(preview_event.get("summary") or "—")
    preview_day = event_local_start_date(preview_event, tz)
    preview_when_parts = []
    if preview_day is not None:
        preview_when_parts.append(format_upcoming_day_header(preview_day, reference_date))
    preview_when_parts.append(format_time_range(preview_event, tz))
    preview_when = " · ".join(preview_when_parts)
    body = format_invitation_list_lines(pending, tz, reference_date)
    keyboard_rows = [
        (event_callback_token(str(ev.get("url") or "")), str(idx + 1))
        for idx, ev in enumerate(pending)
    ]
    text = invitations_list_html(
        body_lines=body,
        preview_title=preview_title,
        preview_when=preview_when,
        truncated=truncated,
    )
    rich_text = invitations_list_rich_html(
        body_events=pending,
        tz=tz,
        reference_date=reference_date,
        preview_title=preview_title,
        preview_when=preview_when,
        truncated=truncated,
    )
    return (
        text,
        rich_text,
        build_invitations_keyboard(
            keyboard_rows,
            from_settings_hub=from_settings_hub,
        ),
    )


def load_pending_invitations_screen(
    calendar_service: UserCalendarService,
    user_id: int,
    *,
    tz: tzinfo,
    now: datetime | None = None,
    from_settings_hub: bool = False,
) -> InvitationsScreen:
    """Загружает CalDAV, фильтрует pending и собирает текст + inline-клавиатуру."""
    events, login, moment = fetch_invitation_events(
        calendar_service,
        user_id,
        tz=tz,
        now=now,
    )
    pending, truncated = collect_pending_from_events(events, login, tz, now=moment)
    today = moment.date()
    text, rich_text, keyboard = screen_from_pending(
        pending,
        tz,
        reference_date=today,
        truncated=truncated,
        from_settings_hub=from_settings_hub,
    )
    get_event_token_cache().register_invitations_screen(
        user_id,
        pending=pending,
        all_events=events,
        login=login,
        moment=moment,
        truncated=truncated,
        from_settings_hub=from_settings_hub,
    )
    return InvitationsScreen(
        pending=pending,
        text=text,
        rich_text=rich_text,
        keyboard=keyboard,
        truncated=truncated,
        login=login,
    )
