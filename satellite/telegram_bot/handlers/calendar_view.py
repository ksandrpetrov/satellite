"""Общие хелперы UI для списка календарей (sources / foreign / settings hub).

`fetch_calendars` — единая точка получения списка CalDAV-календарей в UI.
Возвращает структурированный `CalendarListResult`, чтобы callers могли
разделять «не подключён» и «сеть/пароль не отвечает», не дублируя
обработку `CalendarProviderError`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock

from ...calendar.providers.base import (
    CalendarListEntry,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ...calendar.selection import (
    calendar_callback_token,
    effective_enabled_calendar_urls,
    normalize_calendar_url,
    sort_calendar_entries,
)
from ...messages_ru import (
    build_calendar_sources_keyboard,
    calendar_sources_screen_text,
)
from ...users import UserRecord
from ..presenters.calendar_screens import calendar_source_toggle_lines
from .context import HandlerContext

log = logging.getLogger(__name__)

_CALENDAR_LIST_TTL_SEC = 60.0
_calendar_list_cache: dict[int, tuple[CalendarListResult, float]] = {}
_calendar_list_lock = Lock()


def _put_calendar_list_cache(user_id: int, result: CalendarListResult) -> None:
    if not result.ok:
        return
    with _calendar_list_lock:
        _calendar_list_cache[user_id] = (result, time.monotonic())


def get_calendar_list_cache(user_id: int) -> CalendarListResult | None:
    with _calendar_list_lock:
        stored = _calendar_list_cache.get(user_id)
    if stored is None:
        return None
    result, cached_at = stored
    if (time.monotonic() - cached_at) >= _CALENDAR_LIST_TTL_SEC:
        with _calendar_list_lock:
            _calendar_list_cache.pop(user_id, None)
        return None
    return result


def clear_calendar_list_cache(user_id: int | None = None) -> None:
    with _calendar_list_lock:
        if user_id is None:
            _calendar_list_cache.clear()
        else:
            _calendar_list_cache.pop(user_id, None)


class CalendarListStatus(StrEnum):
    """Исход попытки получить список календарей пользователя."""

    OK = "ok"
    NOT_CONNECTED = "not_connected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CalendarListResult:
    status: CalendarListStatus
    calendars: tuple[CalendarListEntry, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status is CalendarListStatus.OK


def enabled_url_set(record: UserRecord) -> set[str]:
    return {normalize_calendar_url(url) for url in effective_enabled_calendar_urls(record)}


def screen_lines(calendars: list[CalendarListEntry], enabled_urls: set[str]) -> list[str]:
    return calendar_source_toggle_lines(calendars, enabled_urls)


def fetch_calendars(
    ctx: HandlerContext,
    user_id: int,
    *,
    prefer_cache: bool = False,
) -> CalendarListResult:
    if prefer_cache:
        cached = get_calendar_list_cache(user_id)
        if cached is not None:
            return cached
    try:
        calendars = ctx.calendar_service.list_calendars(user_id)
    except CalendarNotConnectedError:
        log.info("List calendars: user_id=%s not connected", user_id)
        return CalendarListResult(status=CalendarListStatus.NOT_CONNECTED)
    except CalendarProviderError as exc:
        log.warning("List calendars failed user_id=%s code=%s", user_id, exc.error_code)
        return CalendarListResult(status=CalendarListStatus.UNAVAILABLE)
    result = CalendarListResult(
        status=CalendarListStatus.OK,
        calendars=tuple(sort_calendar_entries(calendars)),
    )
    _put_calendar_list_cache(user_id, result)
    return result


class CalendarSourcesScreenStatus(StrEnum):
    """Готовый экран «Календари в плане» либо причина, почему его нет."""

    SCREEN = "screen"
    SINGLE = "single"
    NOT_CONNECTED = "not_connected"
    UNAVAILABLE = "unavailable"
    NO_RECORD = "no_record"


@dataclass(frozen=True)
class CalendarSourcesScreen:
    status: CalendarSourcesScreenStatus
    text: str | None = None
    keyboard: dict | None = None
    calendars: tuple[CalendarListEntry, ...] = field(default_factory=tuple)


def build_calendar_sources_screen(ctx: HandlerContext, user_id: int) -> CalendarSourcesScreen:
    """Единый builder экрана «Календари в плане».

    Возвращает либо готовые ``text`` + ``keyboard`` (``SCREEN``), либо
    причину отсутствия экрана (``SINGLE`` / ``NOT_CONNECTED`` / ``UNAVAILABLE``
    / ``NO_RECORD``) — конкретное UI-поведение (send / edit, toast / message)
    выбирает caller.
    """
    record = ctx.users.get(user_id)
    if record is None:
        return CalendarSourcesScreen(status=CalendarSourcesScreenStatus.NO_RECORD)
    result = fetch_calendars(ctx, user_id)
    if result.status is CalendarListStatus.NOT_CONNECTED:
        return CalendarSourcesScreen(status=CalendarSourcesScreenStatus.NOT_CONNECTED)
    if not result.ok:
        return CalendarSourcesScreen(status=CalendarSourcesScreenStatus.UNAVAILABLE)
    calendars = list(result.calendars)
    if len(calendars) <= 1:
        return CalendarSourcesScreen(status=CalendarSourcesScreenStatus.SINGLE)
    enabled_urls = enabled_url_set(record)
    text = calendar_sources_screen_text(lines=screen_lines(calendars, enabled_urls))
    pairs = [(entry.name, entry.url) for entry in calendars]
    keyboard = build_calendar_sources_keyboard(
        calendars=pairs,
        enabled_urls=enabled_urls,
        url_tokens=[calendar_callback_token(url) for _name, url in pairs],
    )
    return CalendarSourcesScreen(
        status=CalendarSourcesScreenStatus.SCREEN,
        text=text,
        keyboard=keyboard,
        calendars=tuple(calendars),
    )
