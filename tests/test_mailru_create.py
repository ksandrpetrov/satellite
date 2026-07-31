"""Создание событий через Mail.ru provider."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from satellite.calendar.caldav_client import CalDAVError
from satellite.calendar.providers.base import (
    CalendarEventPayload,
    CalendarProviderError,
    UserCalendarContext,
)
from satellite.calendar.providers.mailru import MailruCalendarProvider
from satellite.messages_ru import CREATE_EVENT_FAILED_HTML, ERR_CALDAV_UNAVAILABLE_TEXT
from satellite.security.token_vault import ProviderCredentials
from satellite.telegram_bot.handlers.calendar_create import _create_failure_text


def _context(
    *, enabled: tuple[str, ...] = (), primary: str = "https://cal/a"
) -> UserCalendarContext:
    return UserCalendarContext(
        user_id=1,
        provider_id="mailru",
        credentials=ProviderCredentials(login="me@vk.team", secret="pw"),
        primary_calendar_url=primary,
        enabled_calendar_urls=enabled,
        login="me@vk.team",
    )


def test_mailru_create_tries_second_calendar_when_first_fails():
    provider = MailruCalendarProvider()
    tz = ZoneInfo("Europe/Moscow")
    payload = CalendarEventPayload(
        title="Meet",
        start=datetime(2026, 5, 20, 10, 0, tzinfo=tz),
        end=datetime(2026, 5, 20, 11, 0, tzinfo=tz),
    )
    context = _context(
        enabled=("https://cal/shared", "https://cal/writable"),
        primary="https://cal/shared",
    )
    mock_service = MagicMock()
    mock_service.create_event.side_effect = [
        CalDAVError("read-only"),
        ("uid-1", "https://cal/writable/uid-1.ics"),
    ]

    with patch.object(provider, "_service", return_value=mock_service):
        ref = provider.create_event(context, payload, tz=tz)

    assert ref.uid == "uid-1"
    assert mock_service.create_event.call_count == 2
    assert mock_service.create_event.call_args_list[0].kwargs["calendar_url"] == (
        "https://cal/shared"
    )
    assert mock_service.create_event.call_args_list[1].kwargs["calendar_url"] == (
        "https://cal/writable"
    )


def test_create_failure_text_maps_create_failed():
    exc = CalendarProviderError("x", error_code="CREATE_FAILED")
    assert _create_failure_text(exc) == CREATE_EVENT_FAILED_HTML


def test_create_failure_text_maps_caldav_unavailable():
    exc = CalendarProviderError("x", error_code="CALDAV_UNAVAILABLE")
    assert _create_failure_text(exc) == ERR_CALDAV_UNAVAILABLE_TEXT


def test_service_cache_is_threadsafe_and_credential_aware():
    provider = MailruCalendarProvider()
    credentials = ProviderCredentials(login="me@vk.team", secret="old-secret")
    barrier = threading.Barrier(12)

    with patch("satellite.calendar.providers.mailru.CalDAVService") as service_cls:
        service_cls.side_effect = lambda **_kwargs: MagicMock()

        def load_pair():
            barrier.wait(timeout=2.0)
            return provider._cached_services(credentials)

        with ThreadPoolExecutor(max_workers=12) as pool:
            pairs = list(pool.map(lambda _index: load_pair(), range(12)))

        first = pairs[0]
        assert all(pair is first for pair in pairs)
        assert service_cls.call_count == 2

        changed_secret = provider._cached_services(
            ProviderCredentials(login="me@vk.team", secret="new-secret")
        )
        assert changed_secret is not first
        first.plain.close.assert_called_once_with()
        first.invitations.close.assert_called_once_with()

        changed_url = provider._cached_services(
            ProviderCredentials(login="me@vk.team", secret="new-secret"),
            caldav_url="https://calendar.example/custom",
        )
        assert changed_url is not changed_secret
        changed_secret.plain.close.assert_called_once_with()
        changed_secret.invitations.close.assert_called_once_with()

        # Обычные операции после connect URL не передают: custom endpoint
        # должен сохраниться, а не замениться default Mail.ru endpoint'ом.
        without_explicit_url = provider._cached_services(
            ProviderCredentials(login="me@vk.team", secret="new-secret")
        )
        assert without_explicit_url is changed_url

        provider.close()
        provider.close()
        changed_url.plain.close.assert_called_once_with()
        changed_url.invitations.close.assert_called_once_with()
