"""Yandex Calendar provider — skeleton for future implementation."""

from __future__ import annotations

from datetime import date, tzinfo

from ...security.token_vault import ProviderCredentials
from .base import (
    CalendarConnectionStatus,
    CalendarEventPayload,
    CalendarEventRef,
    ProviderNotImplementedError,
    UserCalendarContext,
)

PROVIDER_ID = "yandex"


class YandexCalendarProvider:
    provider_id = PROVIDER_ID

    def validate_credentials(
        self, credentials: ProviderCredentials
    ) -> tuple[bool, str | None, str | None]:
        raise ProviderNotImplementedError(self.provider_id)

    def get_connection_status(
        self, context: UserCalendarContext
    ) -> CalendarConnectionStatus:
        raise ProviderNotImplementedError(self.provider_id)

    def list_events(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list:
        raise ProviderNotImplementedError(self.provider_id)

    def create_event(
        self,
        context: UserCalendarContext,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef:
        raise ProviderNotImplementedError(self.provider_id)

    def update_event(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef:
        raise ProviderNotImplementedError(self.provider_id)

    def delete_event(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
    ) -> None:
        raise ProviderNotImplementedError(self.provider_id)
