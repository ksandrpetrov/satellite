"""Yandex Calendar provider — skeleton for future implementation."""

from __future__ import annotations

from datetime import date, tzinfo

from ...security.token_vault import ProviderCredentials
from .base import (
    CalendarConnectionStatus,
    CalendarEventPayload,
    CalendarEventRef,
    CalendarListEntry,
    ProviderNotImplementedError,
    UserCalendarContext,
)

PROVIDER_ID = "yandex"


class YandexCalendarProvider:
    provider_id = PROVIDER_ID

    def close(self) -> None:
        return

    def validate_credentials(
        self,
        credentials: ProviderCredentials,
        *,
        caldav_url: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        raise ProviderNotImplementedError(self.provider_id)

    def get_connection_status(self, context: UserCalendarContext) -> CalendarConnectionStatus:
        raise ProviderNotImplementedError(self.provider_id)

    def list_calendars(self, context: UserCalendarContext) -> list[CalendarListEntry]:
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

    def list_events_for_invitations(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list:
        raise ProviderNotImplementedError(self.provider_id)

    def list_events_for_analytics(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list:
        raise ProviderNotImplementedError(self.provider_id)

    def set_attendee_partstat(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
        partstat: str,
    ) -> None:
        raise ProviderNotImplementedError(self.provider_id)
