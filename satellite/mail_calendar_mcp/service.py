"""Calendar use cases, account scoping and opaque resource identifiers."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken

from ..calendar.availability import find_free_slots
from ..calendar.conference_url import extract_conference_url
from ..calendar.event_identity import deduplicate_event_occurrences
from ..calendar.events import (
    collect_pending_invitations,
    is_all_day_event,
    is_cancelled_event,
    sort_key,
    user_partstat,
)
from ..calendar.providers.base import CalendarEventPayload, CalendarEventRef, UserCalendarContext
from ..calendar.providers.mailru import MailruCalendarProvider
from ..messages_ru import MCP_CONFIRMATION_REQUIRED
from ..security.token_vault import ProviderCredentials
from .accounts import CalendarAccount, CalendarAccountStore
from .settings import McpSettings


class MailCalendarService:
    def __init__(
        self,
        settings: McpSettings,
        accounts: CalendarAccountStore,
        provider: MailruCalendarProvider | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.provider = provider or MailruCalendarProvider()
        self.tz = ZoneInfo(settings.timezone)
        self._fernet = Fernet(settings.encryption_key.encode())

    def close(self) -> None:
        self.provider.close()

    def connect(self, login: str, secret: str) -> CalendarAccount:
        login = login.strip().casefold()
        if login not in self.settings.allowed_logins or not secret or len(secret) > 1024:
            raise ValueError("Account is not permitted")
        credentials = ProviderCredentials(login=login, secret=secret)
        ok, primary, _error = self.provider.validate_credentials(credentials)
        if not ok or not primary:
            raise ValueError("Calendar credentials were not accepted")
        context = UserCalendarContext(1, "mailru", credentials, primary, (primary,), login)
        calendars = self.provider.list_calendars(context)
        urls = tuple(item.url for item in calendars)
        if primary not in urls:
            raise ValueError("Primary calendar is unavailable")
        return self.accounts.connect(credentials, primary, urls)

    def context(self, account_id: int) -> UserCalendarContext:
        account = self.accounts.get(account_id)
        credentials = self.accounts.vault.decrypt(account.credentials_blob)
        if credentials.login not in self.settings.allowed_logins:
            raise ValueError("Account is no longer permitted")
        return UserCalendarContext(
            account_id,
            "mailru",
            credentials,
            account.primary_calendar_url,
            account.calendar_urls,
            credentials.login,
        )

    def _encode(self, account_id: int, kind: str, **payload: Any) -> str:
        account = self.accounts.get(account_id)
        data = {
            "account_id": account_id,
            "connection": account.connection_id,
            "kind": kind,
            **payload,
        }
        return self._fernet.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()

    def _decode(self, account_id: int, token: str, kind: str) -> dict[str, Any]:
        try:
            data = json.loads(self._fernet.decrypt(token.encode(), ttl=86400))
        except (InvalidToken, ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("Refresh the calendar list to obtain a current identifier") from exc
        if (
            not isinstance(data, dict)
            or data.get("account_id") != account_id
            or data.get("kind") != kind
            or data.get("connection") != self.accounts.get(account_id).connection_id
        ):
            raise ValueError("Resource does not belong to this calendar connection")
        return data

    def profile(self, account_id: int) -> dict[str, Any]:
        context = self.context(account_id)
        return {
            "id": str(account_id),
            "name": context.login,
            "email": context.login,
            "timezone": self.settings.timezone,
            "current_time": datetime.now(self.tz).isoformat(),
        }

    def calendars(self, account_id: int) -> dict[str, Any]:
        context = self.context(account_id)
        calendars = self.provider.list_calendars(context)
        return {
            "calendars": [
                {
                    "calendar_id": self._encode(account_id, "calendar", url=item.url),
                    "name": item.name,
                    "primary": item.url == context.primary_calendar_url,
                }
                for item in calendars
                if item.url in context.enabled_calendar_urls
            ]
        }

    def _selected_context(self, account_id: int, calendar_id: str | None) -> UserCalendarContext:
        context = self.context(account_id)
        if calendar_id:
            url = self._decode(account_id, calendar_id, "calendar")["url"]
            if url not in context.enabled_calendar_urls:
                raise ValueError("Calendar is not in this connection")
            context = replace(context, primary_calendar_url=url, enabled_calendar_urls=(url,))
        return context

    def _events(
        self,
        account_id: int,
        start: date,
        end: date,
        *,
        calendar_id: str | None = None,
        invitations: bool = False,
    ) -> tuple[UserCalendarContext, list[dict[str, Any]]]:
        if not 1 <= (end - start).days <= 90:
            raise ValueError("Date range must contain 1 to 90 days; end date is exclusive")
        context = self._selected_context(account_id, calendar_id)
        fetch = (
            self.provider.list_events_for_invitations if invitations else self.provider.list_events
        )
        events = fetch(context, start_date=start, end_date=end, tz=self.tz)
        unique, _dropped = deduplicate_event_occurrences(events, self.tz, login=context.login)
        return context, sorted((dict(ev) for ev in unique), key=lambda ev: sort_key(ev, self.tz))

    def _serialize(self, context: UserCalendarContext, event: dict[str, Any]) -> dict[str, Any]:
        url = str(event.get("url") or "")
        uid = str(event.get("uid") or "")
        recurring = bool(event.get("rrule") or event.get("recurrence_id"))
        return {
            "event_id": self._encode(
                context.user_id, "event", url=url, uid=uid, recurring=recurring
            ),
            "title": str(event.get("summary") or event.get("title") or ""),
            "start": _iso(event.get("dtstart")),
            "end": _iso(event.get("dtend")),
            "all_day": is_all_day_event(event, self.tz),
            "calendar": str(event.get("calendar") or ""),
            "location": str(event.get("location") or ""),
            "description": str(event.get("description") or "")[:8000],
            "conference_url": extract_conference_url(event),
            "status": str(event.get("status") or ""),
            "response": user_partstat(event, context.login),
            "recurring": recurring,
        }

    def events(
        self,
        account_id: int,
        start: date,
        end: date,
        *,
        query: str = "",
        calendar_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        invitations: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100 or offset < 0 or len(query) > 200:
            raise ValueError("Invalid pagination or search")
        context, events = self._events(
            account_id, start, end, calendar_id=calendar_id, invitations=invitations
        )
        if invitations:
            events = [
                dict(ev)
                for ev in collect_pending_invitations(
                    events,
                    context.login,
                    self.tz,
                    now=datetime.now(self.tz),
                    max_events=len(events),
                    lookback_days=14,
                )
            ]
        else:
            events = [ev for ev in events if not is_cancelled_event(ev)]
        if query.strip():
            needle = query.strip().casefold()
            events = [
                ev
                for ev in events
                if needle
                in " ".join(
                    str(ev.get(field) or "") for field in ("summary", "description", "location")
                ).casefold()
            ]
        next_offset = offset + limit if offset + limit < len(events) else None
        return {
            "timezone": self.settings.timezone,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "events": [self._serialize(context, ev) for ev in events[offset : offset + limit]],
            "total": len(events),
            "has_more": next_offset is not None,
            "next_offset": next_offset,
        }

    def availability(
        self,
        account_id: int,
        start: date,
        end: date,
        *,
        duration_minutes: int,
        work_start: str,
        work_end: str,
    ) -> dict[str, Any]:
        if not 1 <= (end - start).days <= 31:
            raise ValueError("Availability is limited to 31 days")
        # Refresh participant states before deciding that a declined event is free.
        context, events = self._events(account_id, start, end, invitations=True)
        slots = find_free_slots(
            events,
            start_date=start,
            end_date=end,
            tz=self.tz,
            login=context.login,
            duration_minutes=duration_minutes,
            work_start=work_start,
            work_end=work_end,
        )
        return {
            "timezone": self.settings.timezone,
            "slots": [
                {"start": begin.isoformat(), "end": finish.isoformat()} for begin, finish in slots
            ],
        }

    def create(
        self,
        account_id: int,
        title: str,
        start: datetime,
        end: datetime,
        *,
        calendar_id: str | None,
        location: str | None,
        description: str | None,
        confirm: bool,
    ) -> dict[str, Any]:
        title = title.strip()
        if (
            not title
            or len(title) > 500
            or start.tzinfo is None
            or end.tzinfo is None
            or end <= start
        ):
            raise ValueError("Provide a title and timezone-aware start/end times")
        if (
            end - start > timedelta(days=7)
            or len(location or "") > 1000
            or len(description or "") > 8000
        ):
            raise ValueError("Event exceeds the supported bounds")
        context = self._selected_context(account_id, calendar_id)
        # Creation always targets one explicit calendar; never try other calendars
        # after an uncertain write to the primary calendar.
        context = replace(context, enabled_calendar_urls=(context.primary_calendar_url or "",))
        preview = {
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "location": location,
            "description": description,
        }
        if not confirm:
            return {"status": "preview", "event": preview, "message": MCP_CONFIRMATION_REQUIRED}
        ref = self.provider.create_event(
            context, CalendarEventPayload(title, start, end, location, description), tz=self.tz
        )
        return {
            "status": "created",
            "event": preview,
            "event_id": self._encode(
                account_id, "event", url=ref.url, uid=ref.uid, recurring=False
            ),
        }

    def respond(
        self,
        account_id: int,
        event_id: str,
        response: str,
        *,
        confirm: bool,
        confirm_series: bool,
    ) -> dict[str, Any]:
        if response not in {"ACCEPTED", "DECLINED", "TENTATIVE"}:
            raise ValueError("Unsupported invitation response")
        data = self._decode(account_id, event_id, "event")
        context = self.context(account_id)
        url = str(data.get("url") or "")
        if not data.get("uid") or not _url_in_calendars(url, context.enabled_calendar_urls):
            raise ValueError("Invitation identifier does not reference a connected calendar")
        result = {"response": response, "affects_entire_series": bool(data.get("recurring"))}
        if not confirm or (data.get("recurring") and not confirm_series):
            return {"status": "preview", **result, "message": MCP_CONFIRMATION_REQUIRED}
        self.provider.set_attendee_partstat(
            context, CalendarEventRef(uid=data["uid"], url=url), response
        )
        return {"status": "updated", **result}


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if value is not None else None


def _url_in_calendars(url: str, calendars: tuple[str, ...]) -> bool:
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or target.username
        or target.password
        or target.query
        or target.fragment
    ):
        return False
    return any(
        target.netloc == urlsplit(calendar).netloc
        and target.path.startswith(urlsplit(calendar).path.rstrip("/") + "/")
        for calendar in calendars
    )
