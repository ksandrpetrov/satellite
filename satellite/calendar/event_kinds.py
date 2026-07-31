"""Классификация событий: встреча vs системное (аналитика, без UI)."""

from __future__ import annotations

from datetime import tzinfo
from typing import Literal

from .constants import SYSTEM_EVENT_TITLE_PHRASES
from .event_exclusions import EventExclusionPolicy, default_is_excluded
from .events import (
    Event,
    is_all_day_event,
    is_cancelled_event,
    is_declined_event_for_user,
    is_lunch_event,
    user_partstat,
)

EventKind = Literal["meeting", "system"]


def _event_title(event: Event) -> str:
    return str(event.get("summary") or event.get("title") or "")


def is_system_event_title(title: str) -> bool:
    """True, если название похоже на служебный блок (обед 🍕, день без встреч, …)."""
    if is_lunch_event({"summary": title}):
        return True
    fold = title.casefold()
    return any(phrase in fold for phrase in SYSTEM_EVENT_TITLE_PHRASES)


def is_system_event(event: Event, tz: tzinfo) -> bool:
    """Системное событие: all-day, 🍕-приём пищи или служебные фразы в title."""
    if is_all_day_event(event, tz):
        return True
    return is_system_event_title(_event_title(event))


def is_unconfirmed_for_analytics(event: Event, login: str) -> bool:
    """Pending / tentative — не учитываем в аналитике (строже дайджеста)."""
    login_norm = (login or "").strip()
    if not login_norm:
        return False
    status = user_partstat(event, login_norm)
    if status in {"NEEDS-ACTION", "DELEGATED", "TENTATIVE"}:
        return True
    return False


def classify_event_kind(
    event: Event,
    tz: tzinfo,
    *,
    login: str,
    exclusion_policy: EventExclusionPolicy | None = None,
) -> EventKind | None:
    """Возвращает kind или None, если событие полностью исключается из аналитики."""
    if is_cancelled_event(event):
        return None
    if is_declined_event_for_user(event, login):
        return None
    if is_unconfirmed_for_analytics(event, login):
        return None
    if exclusion_policy is not None:
        title = _event_title(event)
        if exclusion_policy.is_excluded(title):
            return None
        if default_is_excluded(title) and not is_all_day_event(event, tz):
            # Явный include или выключенный default для встроенного title-правила.
            return "meeting"
    if is_system_event(event, tz):
        return "system"
    return "meeting"


def filter_meetings_for_analytics(
    events: list[Event],
    *,
    tz: tzinfo,
    login: str,
    exclusion_policy: EventExclusionPolicy | None = None,
) -> list[Event]:
    """Оставляет только подтверждённые timed-встречи (не системные)."""
    out: list[Event] = []
    for event in events:
        if (
            classify_event_kind(
                event,
                tz,
                login=login,
                exclusion_policy=exclusion_policy,
            )
            == "meeting"
        ):
            out.append(event)
    return out
