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
        self.close_calls = 0
        self.validate_calls = 0
        self.list_calendars_calls = 0
        self.list_events_calls = 0
        self.list_analytics_calls = 0
        self.next_status = CalendarConnectionStatus(
            connected=True, provider_id=PROVIDER_MAILRU, status="connected"
        )
        self.raise_on_list_events: Exception | None = None

    def close(self) -> None:
        self.close_calls += 1

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

    def get_connection_status(self, context: UserCalendarContext) -> CalendarConnectionStatus:
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

    def list_events_for_analytics(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list[dict[str, Any]]:
        self.list_analytics_calls += 1
        return [{"summary": "Verified", "start": start_date.isoformat()}]

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


def test_close_closes_cached_providers_once(
    service: UserCalendarService, fake_provider: FakeProvider
) -> None:
    service._provider_cache[PROVIDER_MAILRU] = fake_provider

    service.close()
    service.close()

    assert fake_provider.close_calls == 1


def test_list_events_for_analytics_uses_dedicated_provider_path(
    service: UserCalendarService, fake_provider: FakeProvider
) -> None:
    _connect(service)

    events = service.list_events_for_analytics(
        USER_ID,
        start_date=date(2026, 2, 16),
        end_date=date(2026, 5, 17),
        tz=datetime.now().astimezone().tzinfo,
    )

    assert [(ev["summary"], ev["start"]) for ev in events] == [("Verified", "2026-02-16")]
    assert events[0]["_calendar_connection_id"] == service.connection_id(USER_ID)
    assert fake_provider.list_analytics_calls == 1
    assert fake_provider.list_events_calls == 0


def test_partstat_uses_only_callers_connected_account(service, users, fake_provider):
    from unittest.mock import MagicMock

    from satellite.calendar.providers.base import CalendarEventRef

    second_id = USER_ID + 1
    users.upsert_from_telegram(
        telegram_user_id=second_id,
        chat_id=second_id,
        username="other",
        display_name="Other",
        default_status=USER_STATUS_APPROVED,
    )
    _connect(service)
    service.connect(
        second_id,
        provider_id=PROVIDER_MAILRU,
        credentials=ProviderCredentials("other@mail.ru", "other-pw"),
    )
    fake_provider.set_attendee_partstat = MagicMock()
    ref = CalendarEventRef("meeting", "https://caldav.example/primary/event.ics")
    for user_id, address, secret in [
        (USER_ID, LOGIN, PASSWORD),
        (second_id, "other@mail.ru", "other-pw"),
    ]:
        service.set_attendee_partstat(user_id, ref, "ACCEPTED")
        context, actual_ref, status = fake_provider.set_attendee_partstat.call_args.args
        assert context.user_id == user_id
        assert context.login == address
        assert context.credentials == ProviderCredentials(address, secret)
        assert context.primary_calendar_url == "https://caldav.example/primary/"
        assert actual_ref == ref
        assert status == "ACCEPTED"
    fake_provider.set_attendee_partstat.reset_mock()
    with pytest.raises(CalendarNotConnectedError):
        service.set_attendee_partstat(second_id + 1, ref, "ACCEPTED")
    fake_provider.set_attendee_partstat.assert_not_called()


@pytest.mark.parametrize("replacement", ["disconnect", "new_connect"])
def test_late_connect_cannot_overwrite_newer_intent(service, users, fake_provider, replacement):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    original = fake_provider.validate_credentials

    def blocked(credentials, **kwargs):
        if credentials.secret == "slow":
            entered.set()
            assert release.wait(5)
        return original(credentials, **kwargs)

    fake_provider.validate_credentials = blocked
    with ThreadPoolExecutor() as pool:
        old = pool.submit(_connect, service, password="slow")
        try:
            assert entered.wait(5)
            if replacement == "disconnect":
                service.disconnect(USER_ID)
            else:
                _connect(service, password="new")
        finally:
            release.set()
        with pytest.raises(CalendarProviderError) as exc:
            old.result(timeout=5)
        assert exc.value.error_code == "CALENDAR_CONNECTION_CHANGED"
    record = users.get(USER_ID)
    if replacement == "disconnect":
        assert not record.has_calendar
    else:
        assert service.require_connection(USER_ID).context.credentials.secret == "new"


def test_failed_reconnect_keeps_previous_connection(service, users):
    _connect(service)
    previous = users.get(USER_ID)
    with pytest.raises(CalendarProviderError):
        _connect(service, password="bad")
    assert users.get(USER_ID) == previous


def test_custom_endpoint_survives_vault_roundtrip(service, users, vault):
    service.connect(
        USER_ID,
        provider_id=PROVIDER_MAILRU,
        credentials=ProviderCredentials(LOGIN, PASSWORD),
        caldav_url="https://custom.example/dav/",
    )
    stored = vault.decrypt(users.get(USER_ID).encrypted_credentials)
    assert stored.caldav_url == "https://custom.example/dav/"


def test_old_event_reference_cannot_write_to_reconnected_account(service, fake_provider):
    from unittest.mock import Mock

    from satellite.calendar.providers.base import CalendarEventRef

    _connect(service)
    old_events = service.list_events(
        USER_ID,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        tz=datetime.now().astimezone().tzinfo,
    )
    old_id = old_events[0]["_calendar_connection_id"]
    _connect(service, password="new")
    fake_provider.set_attendee_partstat = Mock()
    with pytest.raises(CalendarProviderError) as exc:
        service.set_attendee_partstat(
            USER_ID,
            CalendarEventRef(
                "meeting", "https://caldav.example/primary/event.ics", connection_id=old_id
            ),
            "ACCEPTED",
        )
    assert exc.value.error_code == "CALENDAR_CONNECTION_CHANGED"
    fake_provider.set_attendee_partstat.assert_not_called()


@pytest.mark.parametrize("action", ["check", "list"])
def test_old_read_cannot_report_success_after_reconnect(service, fake_provider, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    _connect(service)
    entered, release = Event(), Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return fake_provider.next_status if action == "check" else []

    if action == "check":
        fake_provider.get_connection_status = blocked

        def call():
            return service.check_connection(USER_ID)
    else:
        fake_provider.list_events = blocked

        def call():
            return service.list_events(
                USER_ID,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 1),
                tz=datetime.now().astimezone().tzinfo,
            )

    with ThreadPoolExecutor() as pool:
        future = pool.submit(call)
        try:
            assert entered.wait(5)
            _connect(service, password="new")
        finally:
            release.set()
        with pytest.raises(CalendarProviderError) as exc:
            future.result(timeout=5)
        assert exc.value.error_code == "CALENDAR_CONNECTION_CHANGED"
    assert service.require_connection(USER_ID).context.credentials.secret == "new"


def test_failed_probe_does_not_disable_future_recovery(service, fake_provider, users):
    _connect(service)
    fake_provider.next_status = CalendarConnectionStatus(False, PROVIDER_MAILRU, "calendar_error")
    assert not service.check_connection(USER_ID).connected
    assert users.get(USER_ID).has_calendar
    fake_provider.next_status = CalendarConnectionStatus(True, PROVIDER_MAILRU, "connected")
    assert service.check_connection(USER_ID).connected


def test_disconnect_waits_for_started_write_without_blocking_other_users(
    service, users, fake_provider
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from satellite.calendar.providers.base import CalendarEventRef

    _connect(service)
    other = USER_ID + 1
    users.upsert_from_telegram(
        telegram_user_id=other,
        chat_id=other,
        username="other",
        display_name="Other",
        default_status=USER_STATUS_APPROVED,
    )
    service.connect(
        other,
        provider_id=PROVIDER_MAILRU,
        credentials=ProviderCredentials("other@example.com", "pw"),
    )
    entered, release, disconnect_started = Event(), Event(), Event()
    order = []

    def write(*args):
        order.append("write_started")
        entered.set()
        assert release.wait(5)
        order.append("write_finished")

    fake_provider.set_attendee_partstat = write

    def disconnect():
        disconnect_started.set()
        service.disconnect(USER_ID)
        order.append("disconnected")

    with ThreadPoolExecutor() as pool:
        writing = pool.submit(
            service.set_attendee_partstat,
            USER_ID,
            CalendarEventRef("meeting", "https://cal/e"),
            "ACCEPTED",
        )
        try:
            assert entered.wait(5)
            removing = pool.submit(disconnect)
            assert disconnect_started.wait(5)
            assert service.list_calendars(other)
            assert users.get(USER_ID).has_calendar
        finally:
            release.set()
        writing.result(timeout=5)
        removing.result(timeout=5)
    assert order == ["write_started", "write_finished", "disconnected"]
    assert not users.get(USER_ID).has_calendar


def test_persisted_endpoint_used_by_fresh_provider_after_restart(service, users, vault):
    from satellite.calendar.providers.mailru import MailruCalendarProvider

    service.connect(
        USER_ID,
        provider_id=PROVIDER_MAILRU,
        credentials=ProviderCredentials(LOGIN, PASSWORD),
        caldav_url="https://custom.example/dav/",
    )
    credentials = vault.decrypt(users.get(USER_ID).encrypted_credentials)
    provider = MailruCalendarProvider()
    try:
        assert provider._service(credentials)._caldav_url == "https://custom.example/dav/"
        assert (
            provider._service_for_invitations(credentials)._caldav_url
            == "https://custom.example/dav/"
        )
    finally:
        provider.close()


def test_legacy_encrypted_credentials_remain_readable(vault):
    import json

    blob = vault._fernet.encrypt(json.dumps({"login": LOGIN, "secret": PASSWORD}).encode()).decode()
    assert vault.decrypt(blob) == ProviderCredentials(LOGIN, PASSWORD)
