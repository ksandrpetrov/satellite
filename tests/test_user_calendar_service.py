"""Юнит-тесты ``UserCalendarService``: фасад per-user CalDAV.

Подменяем provider на фейк, чтобы не ходить в сеть. Покрываем:

- ``connect`` сохраняет credentials через ``UserStore`` и пишет audit;
- ``require_connection`` бросает ``CalendarNotConnectedError``, когда нет связи;
- ``_run`` мапит произвольное исключение на ``CalendarProviderError``;
- ``fetch_events_for_day`` решает connection один раз (а не дважды).
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from satellite.calendar.operation_log import CalendarOperationLog
from satellite.calendar.providers.base import (
    CalendarConnectionStatus,
    CalendarListEntry,
    CalendarNotConnectedError,
    CalendarProvider,
    CalendarProviderError,
    UserCalendarContext,
)
from satellite.calendar.providers.registry import PROVIDER_MAILRU
from satellite.calendar.user_calendar_service import UserCalendarService
from satellite.security.token_vault import ProviderCredentials, TokenVault
from satellite.users import USER_STATUS_APPROVED, UserStore


USER_ID = 7777
LOGIN = "tester@mail.ru"
PASSWORD = "app-pwd"


class FakeProvider:
    provider_id = PROVIDER_MAILRU

    def __init__(self) -> None:
        self.validate_calls = 0
        self.list_calendars_calls = 0
        self.list_events_calls = 0
        self.next_status = CalendarConnectionStatus(
            connected=True, provider_id=PROVIDER_MAILRU, status="connected"
        )
        self.raise_on_list_events: Exception | None = None

    def validate_credentials(
        self,
        credentials: ProviderCredentials,
        *,
        caldav_url: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        self.validate_calls += 1
        if credentials.secret == "bad":
            return False, None, "AUTH_FAILED"
        return True, "https://caldav.example/primary/", None

    def get_connection_status(
        self, context: UserCalendarContext
    ) -> CalendarConnectionStatus:
        return self.next_status

    def list_calendars(self, context: UserCalendarContext) -> list[CalendarListEntry]:
        self.list_calendars_calls += 1
        return [CalendarListEntry(name="Primary", url="https://caldav.example/primary/")]

    def list_events(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list[dict[str, Any]]:
        self.list_events_calls += 1
        if self.raise_on_list_events is not None:
            raise self.raise_on_list_events
        return [{"summary": "Standup", "start": start_date.isoformat()}]

    def create_event(self, *args, **kwargs):  # pragma: no cover - не вызывается
        raise NotImplementedError

    def update_event(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def delete_event(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def vault() -> TokenVault:
    from cryptography.fernet import Fernet

    return TokenVault(Fernet.generate_key().decode("ascii"))


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    store = UserStore(tmp_path / "users.json")
    store.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=USER_ID,
        username="tester",
        display_name="Tester",
        default_status=USER_STATUS_APPROVED,
    )
    return store


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def service(
    users: UserStore,
    vault: TokenVault,
    fake_provider: FakeProvider,
    tmp_path: Path,
) -> UserCalendarService:
    op_log = CalendarOperationLog(tmp_path / "calendar_ops.jsonl")
    svc = UserCalendarService(users=users, token_vault=vault, operation_log=op_log)
    # Подменяем provider lookup на фейк, чтобы не дёргать реальный mailru/yandex.
    with patch.object(svc, "_provider_for", return_value=fake_provider):
        yield svc


def _connect(service: UserCalendarService, *, password: str = PASSWORD) -> None:
    service.connect(
        USER_ID,
        provider_id=PROVIDER_MAILRU,
        credentials=ProviderCredentials(login=LOGIN, secret=password),
    )


def test_require_connection_raises_when_not_connected(
    service: UserCalendarService,
) -> None:
    with pytest.raises(CalendarNotConnectedError):
        service.require_connection(USER_ID)


def test_connect_persists_credentials_and_marks_connected(
    service: UserCalendarService, users: UserStore, fake_provider: FakeProvider
) -> None:
    _connect(service)
    record = users.get(USER_ID)
    assert record is not None
    assert record.calendar_provider == PROVIDER_MAILRU
    assert record.encrypted_credentials  # зашифровано, не пусто
    assert record.has_calendar is True
    assert fake_provider.validate_calls == 1


def test_connect_with_bad_credentials_raises(
    service: UserCalendarService, users: UserStore
) -> None:
    with pytest.raises(CalendarProviderError) as exc:
        _connect(service, password="bad")
    assert exc.value.error_code == "AUTH_FAILED"
    assert users.get(USER_ID).has_calendar is False


def test_run_wraps_unexpected_exception(
    service: UserCalendarService, fake_provider: FakeProvider
) -> None:
    _connect(service)
    fake_provider.raise_on_list_events = RuntimeError("network blip")
    with pytest.raises(CalendarProviderError) as exc:
        service.list_events(
            USER_ID,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            tz=datetime.now().astimezone().tzinfo,
        )
    assert exc.value.error_code == "CALENDAR_ERROR"


def test_run_propagates_calendar_provider_error(
    service: UserCalendarService, fake_provider: FakeProvider
) -> None:
    _connect(service)
    fake_provider.raise_on_list_events = CalendarProviderError(
        "auth lost", error_code="AUTH_FAILED"
    )
    with pytest.raises(CalendarProviderError) as exc:
        service.list_events(
            USER_ID,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            tz=datetime.now().astimezone().tzinfo,
        )
    assert exc.value.error_code == "AUTH_FAILED"


def test_fetch_events_for_day_resolves_connection_once(
    service: UserCalendarService, fake_provider: FakeProvider
) -> None:
    _connect(service)
    calls: list[int] = []

    original = service.require_connection

    def counting(uid: int):
        calls.append(uid)
        return original(uid)

    with patch.object(service, "require_connection", side_effect=counting):
        events, login = service.fetch_events_for_day(
            USER_ID,
            date(2025, 1, 1),
            tz=datetime.now().astimezone().tzinfo,
        )

    assert len(events) == 1
    assert login == LOGIN
    assert calls == [USER_ID]  # ровно один require_connection
    assert fake_provider.list_events_calls == 1
