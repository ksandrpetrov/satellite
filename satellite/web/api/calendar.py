"""REST-хендлеры календаря: connect / disconnect / status / events CRUD."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from ...calendar.events import build_upcoming_events_groups
from ...calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ...calendar.providers.registry import (
    PROVIDER_IDS,
    PROVIDER_MAILRU,
    PROVIDER_YANDEX,
)
from ...security.token_vault import ProviderCredentials
from ...users import UserStorePersistenceError
from ..auth import validated_user
from ..parsing import (
    parse_date,
    parse_datetime,
    parse_positive_int,
    query_string,
    read_json,
    request_path,
    serialize_event,
)
from ..responses import AbortRequest, json_response
from ..routing import Deps

log = logging.getLogger(__name__)

_EVENTS_DEFAULT_DAYS = 14
_UPCOMING_VIEW_DAYS = 7


def handle_connect(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    body = read_json(handler)
    try:
        user_id = validated_user(
            handler, deps.users, deps.bot_token, deps.connect_tokens, body=body
        )
    except AbortRequest:
        return
    provider = str(body.get("provider") or PROVIDER_MAILRU).strip().lower()
    login = str(body.get("login") or "").strip()
    app_password = str(body.get("app_password") or body.get("token") or "").strip()
    if provider not in PROVIDER_IDS:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "unknown_provider"})
        return
    if provider == PROVIDER_YANDEX:
        json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": "PROVIDER_NOT_IMPLEMENTED"},
        )
        return
    if not login or not app_password:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_fields"})
        return
    caldav_url = str(body.get("caldav_url") or "").strip() or None
    try:
        deps.calendar.connect(
            user_id,
            provider_id=provider,
            credentials=ProviderCredentials(login=login, secret=app_password),
            caldav_url=caldav_url,
        )
    except CalendarProviderError as exc:
        json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    except UserStorePersistenceError as exc:
        log.error("Persistence error during connect: %s", exc)
        json_response(
            handler,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {"error": "storage_unavailable"},
        )
        return
    json_response(
        handler,
        HTTPStatus.OK,
        {"status": "connected", "provider": provider},
    )


def handle_disconnect(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    try:
        deps.calendar.disconnect(user_id)
    except KeyError:
        json_response(handler, HTTPStatus.OK, {"status": "disconnected"})
        return
    except UserStorePersistenceError as exc:
        log.error("Persistence error during disconnect: %s", exc)
        json_response(
            handler,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {"error": "storage_unavailable"},
        )
        return
    json_response(handler, HTTPStatus.OK, {"status": "disconnected"})


def handle_status(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    record = deps.users.get(user_id)
    if record is None or not record.has_calendar:
        json_response(
            handler,
            HTTPStatus.OK,
            {"connected": False, "status": "disconnected", "provider": None},
        )
        return
    try:
        status = deps.calendar.check_connection(user_id)
        json_response(
            handler,
            HTTPStatus.OK,
            {
                "provider": status.provider_id,
                "status": status.status,
                "connected": status.connected,
            },
        )
    except CalendarProviderError as exc:
        json_response(
            handler,
            HTTPStatus.OK,
            {
                "connected": False,
                "status": exc.error_code.lower(),
                "provider": record.calendar_provider,
            },
        )


def handle_list_events(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    qs = query_string(handler)
    today = datetime.now(tz=deps.tz).date()
    view = (qs.get("view", [None])[0] or "").strip().lower()
    if view == "upcoming":
        days = parse_positive_int(qs.get("days", [None])[0], default=_UPCOMING_VIEW_DAYS)
        if days is None or days > 31:
            json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_days"})
            return
        end_date = today + timedelta(days=days)
        try:
            events = deps.calendar.list_events(
                user_id, start_date=today, end_date=end_date, tz=deps.tz
            )
        except CalendarNotConnectedError:
            json_response(handler, HTTPStatus.CONFLICT, {"error": "not_connected"})
            return
        except CalendarProviderError as exc:
            json_response(
                handler,
                HTTPStatus.BAD_GATEWAY,
                {"error": exc.error_code, "message": str(exc)},
            )
            return
        groups = build_upcoming_events_groups(events, deps.tz, today, days=days)
        json_response(
            handler,
            HTTPStatus.OK,
            {
                "view": "upcoming",
                "reference_date": today.isoformat(),
                "days": days,
                "empty": not groups,
                "groups": groups,
            },
        )
        return

    start_date = parse_date(qs.get("from", [None])[0]) or today
    end_date = parse_date(qs.get("to", [None])[0]) or (today + timedelta(days=_EVENTS_DEFAULT_DAYS))
    if end_date < start_date:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_range"})
        return
    try:
        events = deps.calendar.list_events(
            user_id, start_date=start_date, end_date=end_date, tz=deps.tz
        )
    except CalendarNotConnectedError:
        json_response(handler, HTTPStatus.CONFLICT, {"error": "not_connected"})
        return
    except CalendarProviderError as exc:
        json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    serialized = [serialize_event(ev) for ev in events]
    json_response(
        handler,
        HTTPStatus.OK,
        {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "events": serialized,
        },
    )


def handle_create_event(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    body = read_json(handler)
    try:
        user_id = validated_user(
            handler, deps.users, deps.bot_token, deps.connect_tokens, body=body
        )
    except AbortRequest:
        return
    title = str(body.get("title") or "").strip()
    start_raw = str(body.get("start") or "").strip()
    end_raw = str(body.get("end") or "").strip()
    duration_raw = body.get("duration_minutes")
    location = body.get("location")
    description = body.get("description")
    if not title or not start_raw:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_fields"})
        return
    start = parse_datetime(start_raw, deps.tz)
    if start is None:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_dates"})
        return
    end = None
    if end_raw:
        end = parse_datetime(end_raw, deps.tz)
    elif duration_raw is not None:
        try:
            minutes = int(duration_raw)
        except (TypeError, ValueError):
            minutes = 0
        if minutes <= 0 or minutes > 24 * 60:
            json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_duration"})
            return
        end = start + timedelta(minutes=minutes)
    if end is None or end <= start:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_dates"})
        return
    payload = CalendarEventPayload(
        title=title,
        start=start,
        end=end,
        location=(
            str(location).strip() if isinstance(location, str) and location.strip() else None
        ),
        description=(
            str(description).strip()
            if isinstance(description, str) and description.strip()
            else None
        ),
    )
    try:
        ref = deps.calendar.create_event(user_id, payload, tz=deps.tz)
    except CalendarNotConnectedError:
        json_response(handler, HTTPStatus.CONFLICT, {"error": "not_connected"})
        return
    except CalendarProviderError as exc:
        json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    json_response(
        handler,
        HTTPStatus.CREATED,
        {"uid": ref.uid, "url": ref.url, "status": "created"},
    )


def handle_delete_event(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    path = request_path(handler)
    uid = path[len("/api/calendar/events/") :].strip("/")
    if not uid:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_uid"})
        return
    qs = query_string(handler)
    url = qs.get("url", [None])[0]
    ref = CalendarEventRef(uid=uid, url=url or None)
    try:
        deps.calendar.delete_event(user_id, ref)
    except CalendarNotConnectedError:
        json_response(handler, HTTPStatus.CONFLICT, {"error": "not_connected"})
        return
    except CalendarProviderError as exc:
        json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    json_response(handler, HTTPStatus.OK, {"status": "deleted"})
