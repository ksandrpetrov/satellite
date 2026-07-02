"""Application-layer use cases for Web calendar API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from http import HTTPStatus
from typing import Any

from ..calendar.events import build_upcoming_events_groups
from ..calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ..calendar.providers.registry import PROVIDER_IDS, PROVIDER_MAILRU, PROVIDER_YANDEX
from ..security.token_vault import ProviderCredentials
from ..users import UserStore, UserStorePersistenceError
from .errors import error_payload
from .parsing import parse_date, parse_datetime, parse_positive_int, serialize_event

_EVENTS_DEFAULT_DAYS = 14
_UPCOMING_VIEW_DAYS = 7


@dataclass(frozen=True)
class ApiResult:
    status: HTTPStatus
    payload: dict[str, Any]


class CalendarApiService:
    """Thin application service shared by Web handlers."""

    def __init__(self, *, calendar, users: UserStore, tz: tzinfo) -> None:
        self._calendar = calendar
        self._users = users
        self._tz = tz

    def connect(self, user_id: int, body: dict[str, Any]) -> ApiResult:
        provider = str(body.get("provider") or PROVIDER_MAILRU).strip().lower()
        login = str(body.get("login") or "").strip()
        app_password = str(body.get("app_password") or body.get("token") or "").strip()
        if provider not in PROVIDER_IDS:
            return self._error(HTTPStatus.BAD_REQUEST, "unknown_provider")
        if provider == PROVIDER_YANDEX:
            return self._error(HTTPStatus.BAD_REQUEST, "PROVIDER_NOT_IMPLEMENTED")
        if not login or not app_password:
            return self._error(HTTPStatus.BAD_REQUEST, "missing_fields")
        caldav_url = str(body.get("caldav_url") or "").strip() or None
        try:
            self._calendar.connect(
                user_id,
                provider_id=provider,
                credentials=ProviderCredentials(login=login, secret=app_password),
                caldav_url=caldav_url,
            )
        except CalendarProviderError as exc:
            return self._provider_error(exc, status=HTTPStatus.BAD_REQUEST)
        except UserStorePersistenceError:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "storage_unavailable")
        return ApiResult(HTTPStatus.OK, {"status": "connected", "provider": provider})

    def disconnect(self, user_id: int) -> ApiResult:
        try:
            self._calendar.disconnect(user_id)
        except KeyError:
            pass
        except UserStorePersistenceError:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "storage_unavailable")
        return ApiResult(HTTPStatus.OK, {"status": "disconnected"})

    def status(self, user_id: int) -> ApiResult:
        record = self._users.get(user_id)
        if record is None or not record.has_calendar:
            return ApiResult(
                HTTPStatus.OK,
                {"connected": False, "status": "disconnected", "provider": None},
            )
        try:
            status = self._calendar.check_connection(user_id)
        except CalendarProviderError as exc:
            return ApiResult(
                HTTPStatus.OK,
                {
                    "connected": False,
                    "status": exc.error_code.lower(),
                    "provider": record.calendar_provider,
                },
            )
        return ApiResult(
            HTTPStatus.OK,
            {
                "provider": status.provider_id,
                "status": status.status,
                "connected": status.connected,
            },
        )

    def list_events(self, user_id: int, query: dict[str, str | None]) -> ApiResult:
        today = datetime.now(tz=self._tz).date()
        view = (query.get("view") or "").strip().lower()
        if view == "upcoming":
            days = parse_positive_int(query.get("days"), default=_UPCOMING_VIEW_DAYS)
            if days is None or days > 31:
                return self._error(HTTPStatus.BAD_REQUEST, "invalid_days")
            end_date = today + timedelta(days=days)
            try:
                events = self._calendar.list_events(
                    user_id, start_date=today, end_date=end_date, tz=self._tz
                )
            except CalendarNotConnectedError:
                return self._error(HTTPStatus.CONFLICT, "not_connected")
            except CalendarProviderError as exc:
                return self._provider_error(exc)
            groups = build_upcoming_events_groups(events, self._tz, today, days=days)
            return ApiResult(
                HTTPStatus.OK,
                {
                    "view": "upcoming",
                    "reference_date": today.isoformat(),
                    "days": days,
                    "empty": not groups,
                    "groups": groups,
                },
            )

        start_date = parse_date(query.get("from")) or today
        end_date = parse_date(query.get("to")) or (today + timedelta(days=_EVENTS_DEFAULT_DAYS))
        if end_date < start_date:
            return self._error(HTTPStatus.BAD_REQUEST, "invalid_range")
        try:
            events = self._calendar.list_events(
                user_id, start_date=start_date, end_date=end_date, tz=self._tz
            )
        except CalendarNotConnectedError:
            return self._error(HTTPStatus.CONFLICT, "not_connected")
        except CalendarProviderError as exc:
            return self._provider_error(exc)
        return ApiResult(
            HTTPStatus.OK,
            {
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "events": [serialize_event(ev) for ev in events],
            },
        )

    def create_event(self, user_id: int, body: dict[str, Any]) -> ApiResult:
        title = str(body.get("title") or "").strip()
        start_raw = str(body.get("start") or "").strip()
        end_raw = str(body.get("end") or "").strip()
        duration_raw = body.get("duration_minutes")
        location = body.get("location")
        description = body.get("description")
        if not title or not start_raw:
            return self._error(HTTPStatus.BAD_REQUEST, "missing_fields")
        start = parse_datetime(start_raw, self._tz)
        if start is None:
            return self._error(HTTPStatus.BAD_REQUEST, "invalid_dates")

        end = None
        if end_raw:
            end = parse_datetime(end_raw, self._tz)
        elif duration_raw is not None:
            try:
                minutes = int(duration_raw)
            except (TypeError, ValueError):
                minutes = 0
            if minutes <= 0 or minutes > 24 * 60:
                return self._error(HTTPStatus.BAD_REQUEST, "invalid_duration")
            end = start + timedelta(minutes=minutes)
        if end is None or end <= start:
            return self._error(HTTPStatus.BAD_REQUEST, "invalid_dates")

        payload = CalendarEventPayload(
            title=title,
            start=start,
            end=end,
            location=str(location).strip()
            if isinstance(location, str) and location.strip()
            else None,
            description=(
                str(description).strip()
                if isinstance(description, str) and description.strip()
                else None
            ),
        )
        try:
            ref = self._calendar.create_event(user_id, payload, tz=self._tz)
        except CalendarNotConnectedError:
            return self._error(HTTPStatus.CONFLICT, "not_connected")
        except CalendarProviderError as exc:
            return self._provider_error(exc)
        return ApiResult(HTTPStatus.CREATED, {"uid": ref.uid, "url": ref.url, "status": "created"})

    def delete_event(self, user_id: int, uid: str, url: str | None) -> ApiResult:
        if not uid:
            return self._error(HTTPStatus.BAD_REQUEST, "missing_uid")
        ref = CalendarEventRef(uid=uid, url=url or None)
        try:
            self._calendar.delete_event(user_id, ref)
        except CalendarNotConnectedError:
            return self._error(HTTPStatus.CONFLICT, "not_connected")
        except CalendarProviderError as exc:
            return self._provider_error(exc)
        return ApiResult(HTTPStatus.OK, {"status": "deleted"})

    @staticmethod
    def _error(status: HTTPStatus, code: str) -> ApiResult:
        return ApiResult(status, error_payload(code))

    @staticmethod
    def _provider_error(
        exc: CalendarProviderError, *, status: HTTPStatus = HTTPStatus.BAD_GATEWAY
    ) -> ApiResult:
        return ApiResult(status, {"error": exc.error_code, "message": str(exc)})
