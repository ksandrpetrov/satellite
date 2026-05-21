"""Mail.ru / Mailroom CalDAV provider."""

from __future__ import annotations

import logging
from datetime import date, tzinfo

from ...security.token_vault import ProviderCredentials
from ..caldav_client import CalDAVError, CalDAVService
from ..selection import effective_enabled_calendar_urls_from_parts
from .base import (
    CalendarConnectionStatus,
    CalendarEventPayload,
    CalendarEventRef,
    CalendarListEntry,
    CalendarProviderError,
    Event,
    UserCalendarContext,
)

log = logging.getLogger(__name__)

PROVIDER_ID = "mailru"
DEFAULT_CALDAV_URL = "https://calendar.mail.ru/"


class MailruCalendarProvider:
    provider_id = PROVIDER_ID

    def __init__(self, *, cache_ttl_sec: int = 300) -> None:
        self._cache_ttl_sec = cache_ttl_sec

    def validate_credentials(
        self,
        credentials: ProviderCredentials,
        *,
        caldav_url: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        if credentials.is_empty():
            return False, None, "INVALID_CREDENTIALS"
        seed = (caldav_url or "").strip() or None
        try:
            service = self._service(credentials, caldav_url=seed)
            primary = service.primary_calendar_url()
            if not primary:
                return False, None, "NO_CALENDAR"
            return True, primary, None
        except CalDAVError as exc:
            login_domain = credentials.login.split("@")[-1] if "@" in credentials.login else "?"
            log.info(
                "Mail.ru credential validation failed domain=%s detail=%s",
                login_domain,
                str(exc).splitlines()[-1][:200],
            )
            return False, None, "AUTH_FAILED"
        except Exception:  # noqa: BLE001
            log.exception("Unexpected Mail.ru validation error")
            return False, None, "CALENDAR_ERROR"

    def list_calendars(self, context: UserCalendarContext) -> list[CalendarListEntry]:
        service = self._service(context.credentials)
        try:
            handles, _endpoint = service.list_calendars()
        except CalDAVError as exc:
            raise CalendarProviderError(
                "Календарь временно недоступен. Попробуйте позже.",
                error_code="CALDAV_UNAVAILABLE",
            ) from exc
        return [CalendarListEntry(name=handle.name, url=handle.url) for handle in handles]

    def get_connection_status(self, context: UserCalendarContext) -> CalendarConnectionStatus:
        ok, _url, code = self.validate_credentials(context.credentials)
        status = "connected" if ok else "invalid"
        return CalendarConnectionStatus(
            connected=ok,
            provider_id=self.provider_id,
            status=status if ok else (code or "error").lower(),
        )

    def list_events(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list[Event]:
        service = self._service(context.credentials)
        calendar_urls = effective_enabled_calendar_urls_from_parts(
            enabled_calendar_urls=context.enabled_calendar_urls,
            primary_calendar_url=context.primary_calendar_url,
        )
        if not calendar_urls:
            raise CalendarProviderError("Календарь не настроен.", error_code="NO_CALENDAR")
        try:
            return service.fetch_events_in_range(
                start_date,
                end_date,
                tz=tz,
                calendar_urls=calendar_urls,
            )
        except CalDAVError as exc:
            raise CalendarProviderError(
                "Календарь временно недоступен. Попробуйте позже.",
                error_code="CALDAV_UNAVAILABLE",
            ) from exc

    def list_events_for_invitations(
        self,
        context: UserCalendarContext,
        *,
        start_date: date,
        end_date: date,
        tz: tzinfo,
    ) -> list[Event]:
        service = self._service_for_invitations(context.credentials)
        calendar_urls = effective_enabled_calendar_urls_from_parts(
            enabled_calendar_urls=context.enabled_calendar_urls,
            primary_calendar_url=context.primary_calendar_url,
        )
        if not calendar_urls:
            raise CalendarProviderError("Календарь не настроен.", error_code="NO_CALENDAR")
        try:
            return service.fetch_events_in_range(
                start_date,
                end_date,
                tz=tz,
                calendar_urls=calendar_urls,
                enrich_partstat=True,
                invitation_partstat_verify=True,
            )
        except CalDAVError as exc:
            raise CalendarProviderError(
                "Календарь временно недоступен. Попробуйте позже.",
                error_code="CALDAV_UNAVAILABLE",
            ) from exc

    def set_attendee_partstat(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
        partstat: str,
    ) -> None:
        if not event_ref.url:
            raise CalendarProviderError(
                "Не удалось определить событие.",
                error_code="MISSING_EVENT_URL",
            )
        service = self._service(context.credentials)
        try:
            service.set_attendee_partstat(event_ref.url, partstat)
        except CalDAVError as exc:
            log.warning(
                "Mail.ru set_attendee_partstat failed: %s",
                str(exc).splitlines()[-1][:200],
            )
            raise CalendarProviderError(
                "Не удалось обновить ответ на приглашение.",
                error_code="PARTSTAT_UPDATE_FAILED",
            ) from exc

    def create_event(
        self,
        context: UserCalendarContext,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef:
        service = self._service(context.credentials)
        calendar_urls = effective_enabled_calendar_urls_from_parts(
            enabled_calendar_urls=context.enabled_calendar_urls,
            primary_calendar_url=context.primary_calendar_url,
        )
        if not calendar_urls:
            raise CalendarProviderError("Календарь не настроен.", error_code="NO_CALENDAR")
        start = payload.start if payload.start.tzinfo else payload.start.replace(tzinfo=tz)
        end = payload.end if payload.end.tzinfo else payload.end.replace(tzinfo=tz)
        last_exc: CalDAVError | None = None
        for calendar_url in calendar_urls:
            try:
                uid, url = service.create_event(
                    calendar_url=calendar_url,
                    title=payload.title,
                    start=start,
                    end=end,
                    location=payload.location,
                    description=payload.description,
                )
            except CalDAVError as exc:
                last_exc = exc
                log.warning(
                    "Mail.ru create_event failed url=%s: %s",
                    calendar_url[:48],
                    str(exc).splitlines()[-1][:200],
                )
                continue
            return CalendarEventRef(uid=uid, url=url)
        assert last_exc is not None
        raise CalendarProviderError(
            "Не удалось создать событие. Проверьте права доступа.",
            error_code="CREATE_FAILED",
        ) from last_exc

    def update_event(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
        payload: CalendarEventPayload,
        *,
        tz: tzinfo,
    ) -> CalendarEventRef:
        if not event_ref.url:
            raise CalendarProviderError(
                "Не удалось определить событие для изменения.",
                error_code="MISSING_EVENT_URL",
            )
        service = self._service(context.credentials)
        start = payload.start if payload.start.tzinfo else payload.start.replace(tzinfo=tz)
        end = payload.end if payload.end.tzinfo else payload.end.replace(tzinfo=tz)
        try:
            service.update_event(
                event_ref.url,
                title=payload.title,
                start=start,
                end=end,
                location=payload.location,
                description=payload.description,
            )
        except CalDAVError as exc:
            log.warning(
                "Mail.ru update_event failed: %s",
                str(exc).splitlines()[-1][:200],
            )
            raise CalendarProviderError(
                "Не удалось изменить событие.",
                error_code="UPDATE_FAILED",
            ) from exc
        return CalendarEventRef(uid=event_ref.uid, url=event_ref.url)

    def delete_event(
        self,
        context: UserCalendarContext,
        event_ref: CalendarEventRef,
    ) -> None:
        if not event_ref.url:
            raise CalendarProviderError(
                "Не удалось определить событие для удаления.",
                error_code="MISSING_EVENT_URL",
            )
        service = self._service(context.credentials)
        try:
            service.delete_event(event_ref.url)
        except CalDAVError as exc:
            log.warning(
                "Mail.ru delete_event failed: %s",
                str(exc).splitlines()[-1][:200],
            )
            raise CalendarProviderError(
                "Не удалось удалить событие.",
                error_code="DELETE_FAILED",
            ) from exc

    def _service(
        self,
        credentials: ProviderCredentials,
        *,
        caldav_url: str | None = None,
    ) -> CalDAVService:
        return CalDAVService(
            caldav_url=(caldav_url or DEFAULT_CALDAV_URL).strip(),
            login=credentials.login.strip(),
            app_password=credentials.secret,
            cache_ttl_sec=self._cache_ttl_sec,
            partstat_refresh_limit=0,
        )

    def _service_for_invitations(
        self,
        credentials: ProviderCredentials,
        *,
        caldav_url: str | None = None,
    ) -> CalDAVService:
        return CalDAVService(
            caldav_url=(caldav_url or DEFAULT_CALDAV_URL).strip(),
            login=credentials.login.strip(),
            app_password=credentials.secret,
            cache_ttl_sec=self._cache_ttl_sec,
            partstat_refresh_limit=120,
            partstat_refresh_timeout_sec=3.0,
            partstat_refresh_budget_sec=25.0,
        )
