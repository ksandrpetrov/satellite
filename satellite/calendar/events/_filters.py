"""Предикаты-фильтры событий: cancelled, all-day, lunch + index marker.

Все функции принимают «сырой» dict события (``Event``); пустой вход возвращает
безопасный default. Эти примитивы переиспользуются и в плане дня, и в
``/upcoming``, и в обзоре приглашений.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from ..constants import LUNCH_EMOJI_MARKER
from ._time import _to_local, parse_iso
from ._types import NUMBER_EMOJI, Event, PizzaMealKind


def event_index_marker(index: int) -> str:
    """Маркер порядкового номера встречи (как в дайджесте)."""
    if index < len(NUMBER_EMOJI):
        return NUMBER_EMOJI[index]
    return f"{index + 1}."


def is_cancelled_event(event: Event) -> bool:
    """True для событий с ``STATUS:CANCELLED`` (или булевым флагом из dict-API).

    Mail.ru CalDAV держит отменённые встречи в выдаче REPORT с обычными
    DTSTART/DTEND, помечая их только полем STATUS. Без этой проверки они
    попадают в план как полноценные встречи и пугают пользователя «фантомом».
    Дополнительно учитываем ключи ``isCancelled``/``is_cancelled`` для входов
    из не-CalDAV источников (тесты, ТЗ-совместимый словарь).
    """
    if event.get("isCancelled") or event.get("is_cancelled"):
        return True
    status = event.get("status")
    if not status:
        return False
    return str(status).strip().upper() == "CANCELLED"


def is_all_day_event(event: Event, tz: tzinfo) -> bool:
    start = parse_iso(event.get("dtstart"))
    end = parse_iso(event.get("dtend"))

    if isinstance(start, date) and not isinstance(start, datetime):
        return True

    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return False

    start_local = _to_local(start, tz)
    end_local = _to_local(end, tz)

    is_midnight_bounds = (
        start_local.hour == 0
        and start_local.minute == 0
        and end_local.hour == 0
        and end_local.minute == 0
    )
    if not is_midnight_bounds:
        return False

    duration = end_local - start_local
    if duration <= timedelta(0):
        return True
    return duration >= timedelta(days=1) and duration.total_seconds() % 86400 == 0


def pizza_meal_kind(summary: str) -> PizzaMealKind | None:
    """🍕 и одно из слов «завтрак» / «обед» / «ужин» (без учёта регистра)."""
    if LUNCH_EMOJI_MARKER not in summary:
        return None
    fold = summary.casefold()
    if "завтрак" in fold:
        return "breakfast"
    if "обед" in fold:
        return "lunch"
    if "ужин" in fold:
        return "dinner"
    return None


def is_lunch_event(event: Event) -> bool:
    """True для встреч, которые отфильтровывает ``HIDE_LUNCH_EVENTS``."""
    return pizza_meal_kind(str(event.get("summary") or "")) is not None
