"""Общая сборка экрана «непринятые приглашения» для /invitations и scheduler."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, cast

from .calendar.callback_tokens import event_callback_token
from .calendar.events import (
    collect_pending_invitations,
    format_invitation_list_lines,
)
from .calendar.user_calendar_service import UserCalendarService
from .messages_ru import (
    INVITATIONS_EMPTY_HTML,
    build_invitations_keyboard,
    invitations_list_html,
)

INVITATION_HORIZON_DAYS = 60
INVITATION_LOOKBACK_DAYS = 14
MAX_INVITATIONS = 12

Event = dict[str, Any]


@dataclass(frozen=True)
class InvitationsScreen:
    """Результат загрузки pending-приглашений: текст, клавиатура, метаданные."""

    pending: list[Event]
    text: str
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
) -> tuple[str, dict]:
    if not pending:
        return INVITATIONS_EMPTY_HTML, build_invitations_keyboard([])
    body = format_invitation_list_lines(pending, tz, reference_date)
    keyboard_rows = [
        (event_callback_token(str(ev.get("url") or "")), str(idx + 1))
        for idx, ev in enumerate(pending)
    ]
    text = invitations_list_html(body_lines=body, truncated=truncated)
    return text, build_invitations_keyboard(keyboard_rows)


def load_pending_invitations_screen(
    calendar_service: UserCalendarService,
    user_id: int,
    *,
    tz: tzinfo,
    now: datetime | None = None,
) -> InvitationsScreen:
    """Загружает CalDAV, фильтрует pending и собирает текст + inline-клавиатуру."""
    events, login, moment = fetch_invitation_events(
        calendar_service,
        user_id,
        tz=tz,
        now=now,
    )
    pending, truncated = collect_pending_from_events(events, login, tz, now=moment)
    # #region agent log
    try:
        summaries = [str(e.get("summary") or "")[:40] for e in pending[:5]]
        with open(
            "/Users/aleksandr/Developer/satellite/.cursor/debug-2d45ee.log",
            "a",
            encoding="utf-8",
        ) as _df:
            _df.write(
                json.dumps(
                    {
                        "sessionId": "2d45ee",
                        "hypothesisId": "H1-H4",
                        "location": "invitations_view.py:load_pending",
                        "message": "pending_invitations_screen",
                        "data": {
                            "user_id": user_id,
                            "events_fetched": len(events),
                            "pending_count": len(pending),
                            "truncated": truncated,
                            "first_pending": summaries,
                            "login_domain": login.split("@")[-1] if "@" in login else "",
                        },
                        "timestamp": int(time.time() * 1000),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass
    # #endregion
    today = moment.date()
    text, keyboard = screen_from_pending(
        pending,
        tz,
        reference_date=today,
        truncated=truncated,
    )
    return InvitationsScreen(
        pending=pending,
        text=text,
        keyboard=keyboard,
        truncated=truncated,
        login=login,
    )
