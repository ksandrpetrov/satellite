"""Фасад per-user календарных операций с audit log и шифрованием."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, tzinfo
from typing import TypeVar

from ..security.token_vault import ProviderCredentials, TokenVault
from ..users import CALENDAR_CONNECTED, UserRecord, UserStore
from .operation_log import CalendarOperationLog
from .providers.base import (
    CalendarConnectionStatus,
    CalendarEventPayload,
    CalendarEventRef,
    CalendarListEntry,
    CalendarNotConnectedError,
    CalendarProvider,
    CalendarProviderError,
    UserCalendarContext,
)
from .providers.registry import get_provider

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class ConnectedCalendar:
    record: UserRecord
    context: UserCalendarContext
    provider: CalendarProvider


class UserCalendarService:
    """Единственная точка доступа handlers/plan/scheduler к календарю."""

    def __init__(
        self,
        *,
        users: UserStore,
        token_vault: TokenVault,
        operation_log: CalendarOperationLog,
        cache_ttl_sec: int = 300,
    ) -> None:
        self._users = users
        self._vault = token_vault
        self._log = operation_log
        self._cache_ttl_sec = cache_ttl_sec
        self._lock = threading.Lock()
        self._provider_cache: dict[str, CalendarProvider] = {}

    def close(self) -> None:
        """Закрывает кэшированные провайдеры после остановки всех callers."""
        with self._lock:
            providers = tuple(self._provider_cache.values())
            self._provider_cache.clear()
        for provider in providers:
            try:
                provider.close()
            except Exception:  # noqa: BLE001 - один provider не мешает закрыть остальные
                log.exception("Failed to close calendar provider %s", provider.provider_id)

    def require_connection(self, telegram_user_id: int) -> ConnectedCalendar:
        record = self._users.get(telegram_user_id)
        if record is None or not record.has_calendar:
            raise CalendarNotConnectedError()
        credentials = self._vault.decrypt(record.encrypted_credentials or "")
        provider = self._provider_for(record.calendar_provider or "")
        context = UserCalendarContext(
            user_id=telegram_user_id,
            provider_id=record.calendar_provider or "",
            credentials=credentials,
            primary_calendar_url=record.primary_calendar_url,
            enabled_calendar_urls=record.enabled_calendar_urls,
            login=credentials.login,
        )
        return ConnectedCalendar(record=record, context=context, provider=provider)

    def connect(
        self,
        telegram_user_id: int,
        *,
        provider_id: str,
        credentials: ProviderCredentials,
        caldav_url: str | None = None,
    ) -> UserRecord:
        provider = self._provider_for(provider_id)
        ok, primary_url, error_code = provider.validate_credentials(
            credentials, caldav_url=caldav_url
        )
        if not ok or not primary_url:
            self._log.record(
                user_id=telegram_user_id,
                provider=provider_id,
                operation="auth_check",
                status="fail",
                error_code=error_code or "AUTH_FAILED",
            )
            raise CalendarProviderError(
                "Токен не подошёл. Проверьте, что он создан для календаря и не отозван.",
                error_code=error_code or "AUTH_FAILED",
            )
        encrypted = self._vault.encrypt(credentials)
        record = self._users.set_calendar_connection(
            telegram_user_id,
            provider=provider_id,
            encrypted_credentials=encrypted,
            primary_calendar_url=primary_url,
        )
        self._log.record(
            user_id=telegram_user_id,
            provider=provider_id,
            operation="auth_check",
            status="ok",
        )
        return record

    def disconnect(self, telegram_user_id: int) -> UserRecord:
        record = self._users.clear_calendar_connection(telegram_user_id)
        self._log.record(
            user_id=telegram_user_id,
            provider=record.calendar_provider or "none",
            operation="disconnect",
            status="ok",
        )
        return record

    def check_connection(self, telegram_user_id: int) -> CalendarConnectionStatus:
        connected = self.require_connection(telegram_user_id)
        status = connected.provider.get_connection_status(connected.context)
        self._users.mark_calendar_status(
            telegram_user_id,
            status=CALENDAR_CONNECTED if status.connected else "invalid",
        )
        self._log.record(
            user_id=telegram_user_id,
            provider=connected.context.provider_id,
            operation="auth_check",
            status="ok" if status.connected else "fail",
            error_code=None if status.connected else status.status,
        )
        return status

    def list_calendars(self, telegram_user_id: int) -> list[CalendarListEntry]:
        return self._run(
            telegram_user_id,
            operation="list",
            fn=lambda cc: cc.provider.list_calendars(cc.context),
        )

    def list_events(
        self,
        telegram_user_id: int,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
        calendar_urls: tuple[str, ...] | None = None,
    ) -> list:
        def _list(cc: ConnectedCalendar) -> list:
            context = cc.context
            if calendar_urls:
                context = replace(context, enabled_calendar_urls=calendar_urls)
            return cc.provider.list_events(context, start_date=start_date, end_date=end_date, tz=tz)

        return self._run(telegram_user_id, operation="list", fn=_list)

    def create_event(
        self,
        telegram_user_id: int,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef:
        return self._run(
            telegram_user_id,
            operation="create",
            fn=lambda cc: cc.provider.create_event(cc.context, payload, tz=tz),
        )

    def update_event(
        self,
        telegram_user_id: int,
        event_ref: CalendarEventRef,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef:
        return self._run(
            telegram_user_id,
            operation="update",
            fn=lambda cc: cc.provider.update_event(cc.context, event_ref, payload, tz=tz),
        )

    def delete_event(
        self,
        telegram_user_id: int,
        event_ref: CalendarEventRef,
    ) -> None:
        self._run(
            telegram_user_id,
            operation="delete",
            fn=lambda cc: cc.provider.delete_event(cc.context, event_ref),
        )

    def list_events_for_invitations(
        self,
        telegram_user_id: int,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list:
        return self._run(
            telegram_user_id,
            operation="list",
            fn=lambda cc: cc.provider.list_events_for_invitations(
                cc.context,
                start_date=start_date,
                end_date=end_date,
                tz=tz,
            ),
        )

    def set_attendee_partstat(
        self,
        telegram_user_id: int,
        event_ref: CalendarEventRef,
        partstat: str,
    ) -> None:
        self._run(
            telegram_user_id,
            operation="update",
            fn=lambda cc: cc.provider.set_attendee_partstat(cc.context, event_ref, partstat),
        )

    def fetch_events_for_day(
        self,
        telegram_user_id: int,
        target_date: date,
        *,
        tz: tzinfo,
    ) -> tuple[list, str]:
        connected = self.require_connection(telegram_user_id)
        events = self._run(
            telegram_user_id,
            operation="list",
            fn=lambda cc: cc.provider.list_events(
                cc.context,
                start_date=target_date,
                end_date=target_date,
                tz=tz,
            ),
            connected=connected,
        )
        return events, connected.context.login

    def _run(
        self,
        telegram_user_id: int,
        *,
        operation: str,
        fn: Callable[[ConnectedCalendar], T],
        connected: ConnectedCalendar | None = None,
    ) -> T:
        if connected is None:
            connected = self.require_connection(telegram_user_id)
        try:
            result = fn(connected)
        except CalendarProviderError as exc:
            self._log.record(
                user_id=telegram_user_id,
                provider=connected.context.provider_id,
                operation=operation,
                status="fail",
                error_code=exc.error_code,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "Calendar operation failed user_id=%s operation=%s",
                telegram_user_id,
                operation,
            )
            self._log.record(
                user_id=telegram_user_id,
                provider=connected.context.provider_id,
                operation=operation,
                status="fail",
                error_code=exc.__class__.__name__,
            )
            raise CalendarProviderError(
                "Календарь временно недоступен. Попробуйте позже.",
                error_code="CALENDAR_ERROR",
            ) from exc
        self._log.record(
            user_id=telegram_user_id,
            provider=connected.context.provider_id,
            operation=operation,
            status="ok",
        )
        return result

    def _provider_for(self, provider_id: str) -> CalendarProvider:
        normalized = (provider_id or "").strip().lower()
        with self._lock:
            cached = self._provider_cache.get(normalized)
            if cached is not None:
                return cached
            provider = get_provider(normalized, cache_ttl_sec=self._cache_ttl_sec)
            self._provider_cache[normalized] = provider
            return provider
