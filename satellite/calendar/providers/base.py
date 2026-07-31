"""Общий интерфейс calendar provider и DTO для CRUD."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any, Protocol, runtime_checkable

from ...security.token_vault import ProviderCredentials


class CalendarProviderError(RuntimeError):
    """Безопасная ошибка провайдера (без сырых stack trace для пользователя)."""

    def __init__(self, message: str, *, error_code: str = "CALENDAR_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


class ProviderNotImplementedError(CalendarProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(
            f"Провайдер {provider_id!r} пока не поддерживается.",
            error_code="PROVIDER_NOT_IMPLEMENTED",
        )


class CalendarNotConnectedError(CalendarProviderError):
    def __init__(self) -> None:
        super().__init__(
            "Календарь ещё не подключён. Нажмите «Подключить календарь», "
            "чтобы добавить свой сервисный токен.",
            error_code="CALENDAR_NOT_CONNECTED",
        )


@dataclass(frozen=True)
class CalendarListEntry:
    name: str
    url: str


@dataclass(frozen=True)
class UserCalendarContext:
    user_id: int
    provider_id: str
    credentials: ProviderCredentials
    primary_calendar_url: str | None
    enabled_calendar_urls: tuple[str, ...]
    login: str


@dataclass(frozen=True)
class CalendarConnectionStatus:
    connected: bool
    provider_id: str
    status: str  # connected | disconnected | invalid | error


@dataclass(frozen=True)
class CalendarEventRef:
    uid: str
    url: str | None = None


@dataclass(frozen=True)
class CalendarEventPayload:
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None


Event = dict[str, Any]


@runtime_checkable
class CalendarProvider(Protocol):
    provider_id: str

    def close(self) -> None:
        """Закрывает owned сетевые ресурсы. Повторный вызов безопасен."""
        ...

    def validate_credentials(
        self,
        credentials: ProviderCredentials,
        *,
        caldav_url: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """Проверяет credentials. Возвращает (ok, primary_calendar_url, error_code)."""

    def get_connection_status(self, context: UserCalendarContext) -> CalendarConnectionStatus: ...

    def list_calendars(self, context: UserCalendarContext) -> list[CalendarListEntry]: ...

    def list_events(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list[Event]: ...

    def create_event(
        self,
        context: UserCalendarContext,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef: ...

    def update_event(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef: ...

    def delete_event(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
    ) -> None: ...

    def list_events_for_invitations(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list[Event]: ...

    def set_attendee_partstat(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
        partstat: str,
    ) -> None: ...
