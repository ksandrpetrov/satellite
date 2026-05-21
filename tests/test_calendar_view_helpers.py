"""Тесты единого mapping ошибок CalDAV в UI и builder экрана календарей."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from satellite.calendar.providers.base import (
    CalendarListEntry,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from satellite.calendar.providers.registry import PROVIDER_MAILRU
from satellite.telegram_bot.handlers.calendar_view import (
    CalendarListStatus,
    CalendarSourcesScreenStatus,
    build_calendar_sources_screen,
    fetch_calendars,
)
from satellite.users import (
    USER_STATUS_APPROVED,
    UserStore,
)

USER_ID = 3001


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    store = UserStore(tmp_path / "users.json")
    record = store.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=USER_ID,
        username="u",
        display_name="U",
        default_status=USER_STATUS_APPROVED,
    )
    store.set_calendar_connection(
        USER_ID,
        provider=PROVIDER_MAILRU,
        encrypted_credentials="encrypted",
        primary_calendar_url="https://caldav.example/primary/",
    )
    return store


def _ctx(users: UserStore, calendar_service: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.users = users
    ctx.calendar_service = calendar_service
    return ctx


def test_fetch_calendars_ok_returns_entries(users: UserStore) -> None:
    service = MagicMock()
    service.list_calendars.return_value = [
        CalendarListEntry(name="Primary", url="https://caldav.example/primary/")
    ]
    result = fetch_calendars(_ctx(users, service), USER_ID)
    assert result.status is CalendarListStatus.OK
    assert len(result.calendars) == 1


def test_fetch_calendars_not_connected(users: UserStore) -> None:
    service = MagicMock()
    service.list_calendars.side_effect = CalendarNotConnectedError()
    result = fetch_calendars(_ctx(users, service), USER_ID)
    assert result.status is CalendarListStatus.NOT_CONNECTED
    assert result.calendars == ()


def test_fetch_calendars_unavailable(users: UserStore) -> None:
    service = MagicMock()
    service.list_calendars.side_effect = CalendarProviderError(
        "timeout", error_code="CALENDAR_ERROR"
    )
    result = fetch_calendars(_ctx(users, service), USER_ID)
    assert result.status is CalendarListStatus.UNAVAILABLE


def test_build_calendar_sources_screen_returns_screen_for_multiple(
    users: UserStore,
) -> None:
    service = MagicMock()
    service.list_calendars.return_value = [
        CalendarListEntry(name="Primary", url="https://caldav.example/primary/"),
        CalendarListEntry(name="Work", url="https://caldav.example/work/"),
    ]
    screen = build_calendar_sources_screen(_ctx(users, service), USER_ID)
    assert screen.status is CalendarSourcesScreenStatus.SCREEN
    assert screen.text and "Календари" in screen.text
    assert screen.keyboard and "inline_keyboard" in screen.keyboard


def test_build_calendar_sources_screen_single_calendar(users: UserStore) -> None:
    service = MagicMock()
    service.list_calendars.return_value = [
        CalendarListEntry(name="Primary", url="https://caldav.example/primary/")
    ]
    screen = build_calendar_sources_screen(_ctx(users, service), USER_ID)
    assert screen.status is CalendarSourcesScreenStatus.SINGLE


def test_build_calendar_sources_screen_unavailable(users: UserStore) -> None:
    service = MagicMock()
    service.list_calendars.side_effect = CalendarProviderError("boom", error_code="CALENDAR_ERROR")
    screen = build_calendar_sources_screen(_ctx(users, service), USER_ID)
    assert screen.status is CalendarSourcesScreenStatus.UNAVAILABLE


def test_build_calendar_sources_screen_no_record(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "users.json")
    service = MagicMock()
    screen = build_calendar_sources_screen(_ctx(store, service), USER_ID)
    assert screen.status is CalendarSourcesScreenStatus.NO_RECORD
