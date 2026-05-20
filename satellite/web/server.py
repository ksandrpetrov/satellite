"""Embedded HTTP server for Telegram Web App.

Поднимает локальный ThreadingHTTPServer, отдающий статическую SPA-страницу
``/connect`` и REST API ``/api/calendar/*`` для подключения календаря и
управления событиями. Все запросы к API авторизуются по Telegram
``initData`` (HMAC по bot token) и дополнительно фильтруются по
``UserStore`` (статус ``approved``).

HTTPS делегируется внешнему reverse proxy (Traefik с Let's Encrypt в
production-compose). Локально сервер слушает на ``WEBAPP_HOST:WEBAPP_PORT``.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from ..calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ..calendar.providers.registry import PROVIDER_IDS, PROVIDER_MAILRU, PROVIDER_YANDEX
from ..calendar.user_calendar_service import UserCalendarService
from ..security.token_vault import ProviderCredentials
from ..users import USER_STATUS_APPROVED, UserStore
from .init_data import InitDataError, validate_init_data

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_FILE = _STATIC_DIR / "connect.html"
_MAX_BODY_BYTES = 64 * 1024
_EVENTS_DEFAULT_DAYS = 14


@dataclass(frozen=True)
class WebAppServerConfig:
    host: str
    port: int
    bot_token: str
    tz_name: str = "Europe/Moscow"


class WebAppServer:
    """Управляет жизненным циклом HTTP-сервера в фоновом потоке."""

    def __init__(
        self,
        *,
        config: WebAppServerConfig,
        calendar_service: UserCalendarService,
        users: UserStore,
    ) -> None:
        self._config = config
        self._calendar = calendar_service
        self._users = users
        self._tz: tzinfo = _safe_zone(config.tz_name)
        self._thread: threading.Thread | None = None
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(
            (self._config.host, self._config.port), handler
        )
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="satellite-webapp",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "WebApp server started on http://%s:%s",
            self._config.host,
            self._config.port,
        )

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _make_handler(self):
        calendar = self._calendar
        users = self._users
        bot_token = self._config.bot_token
        tz = self._tz

        class Handler(BaseHTTPRequestHandler):
            server_version = "satellite-webapp/1.0"
            sys_version = ""

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                log.debug("WebApp %s - %s", self.address_string(), format % args)

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path in {"/", "/connect", "/connect/", "/index.html"}:
                    _serve_html(self, _INDEX_FILE)
                    return
                if path == "/healthz":
                    _json_response(self, HTTPStatus.OK, {"status": "ok"})
                    return
                if path == "/api/calendar/status":
                    _handle_status(self, calendar, users, bot_token)
                    return
                if path == "/api/calendar/events":
                    _handle_list_events(self, calendar, users, bot_token, tz)
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/calendar/connect":
                    _handle_connect(self, calendar, users, bot_token)
                    return
                if path == "/api/calendar/events":
                    _handle_create_event(self, calendar, users, bot_token, tz)
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_DELETE(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/calendar/disconnect":
                    _handle_disconnect(self, calendar, users, bot_token)
                    return
                if path.startswith("/api/calendar/events/"):
                    _handle_delete_event(self, calendar, users, bot_token, path)
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

        return Handler


# --- helpers ----------------------------------------------------------------


def _safe_zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        log.warning("Unknown timezone %r; falling back to Europe/Moscow", name)
        return ZoneInfo("Europe/Moscow")


def _serve_html(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.is_file():
        _json_response(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        return
    body = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://telegram.org 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'",
    )
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except ValueError:
        return {}
    if length <= 0 or length > _MAX_BODY_BYTES:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _validated_user(
    handler: BaseHTTPRequestHandler,
    users: UserStore,
    bot_token: str,
    *,
    body: dict[str, Any] | None = None,
) -> int:
    """Возвращает telegram_user_id, если initData валидна и пользователь approved.

    Без approved-статуса возвращает HTTP 403 и поднимает ``_AbortRequest``,
    чтобы хендлер сразу завершился. Web App доступен только тем, кому
    одобрили заявку на доступ через админский флоу.
    """
    init_data = handler.headers.get("X-Telegram-Init-Data") or ""
    if not init_data and body is not None:
        init_data = str(body.get("initData") or "")
    try:
        validated = validate_init_data(init_data, bot_token=bot_token)
    except InitDataError as exc:
        log.info("Reject WebApp request: %s", exc)
        _json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        raise _AbortRequest()
    record = users.get(validated.user.id)
    if record is None or record.status != USER_STATUS_APPROVED:
        log.info(
            "Reject WebApp request: user_id=%s not approved (status=%s)",
            validated.user.id,
            getattr(record, "status", None),
        )
        _json_response(handler, HTTPStatus.FORBIDDEN, {"error": "not_approved"})
        raise _AbortRequest()
    return validated.user.id


class _AbortRequest(Exception):
    """Сигнал хендлеру: ответ уже отправлен, надо тихо выйти."""


def _handle_connect(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
) -> None:
    body = _read_json(handler)
    try:
        user_id = _validated_user(handler, users, bot_token, body=body)
    except _AbortRequest:
        return
    provider = str(body.get("provider") or PROVIDER_MAILRU).strip().lower()
    login = str(body.get("login") or "").strip()
    app_password = str(body.get("app_password") or body.get("token") or "").strip()
    if provider not in PROVIDER_IDS:
        _json_response(
            handler, HTTPStatus.BAD_REQUEST, {"error": "unknown_provider"}
        )
        return
    if provider == PROVIDER_YANDEX:
        _json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": "PROVIDER_NOT_IMPLEMENTED"},
        )
        return
    if not login or not app_password:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_fields"})
        return
    try:
        calendar.connect(
            user_id,
            provider_id=provider,
            credentials=ProviderCredentials(login=login, secret=app_password),
        )
    except CalendarProviderError as exc:
        _json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    _json_response(
        handler,
        HTTPStatus.OK,
        {"status": "connected", "provider": provider},
    )


def _handle_disconnect(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token)
    except _AbortRequest:
        return
    try:
        calendar.disconnect(user_id)
    except KeyError:
        _json_response(
            handler, HTTPStatus.OK, {"status": "disconnected"}
        )
        return
    _json_response(handler, HTTPStatus.OK, {"status": "disconnected"})


def _handle_status(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token)
    except _AbortRequest:
        return
    record = users.get(user_id)
    if record is None or not record.has_calendar:
        _json_response(
            handler,
            HTTPStatus.OK,
            {"connected": False, "status": "disconnected", "provider": None},
        )
        return
    try:
        status = calendar.check_connection(user_id)
        _json_response(
            handler,
            HTTPStatus.OK,
            {
                "provider": status.provider_id,
                "status": status.status,
                "connected": status.connected,
            },
        )
    except CalendarProviderError as exc:
        _json_response(
            handler,
            HTTPStatus.OK,
            {
                "connected": False,
                "status": exc.error_code.lower(),
                "provider": record.calendar_provider,
            },
        )


def _handle_list_events(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
    tz: tzinfo,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token)
    except _AbortRequest:
        return
    qs = parse_qs(urlparse(handler.path).query)
    today = datetime.now(tz=tz).date()
    start_date = _parse_date(qs.get("from", [None])[0]) or today
    end_date = _parse_date(qs.get("to", [None])[0]) or (today + timedelta(days=_EVENTS_DEFAULT_DAYS))
    if end_date < start_date:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_range"})
        return
    try:
        events = calendar.list_events(
            user_id, start_date=start_date, end_date=end_date, tz=tz
        )
    except CalendarNotConnectedError:
        _json_response(
            handler, HTTPStatus.CONFLICT, {"error": "not_connected"}
        )
        return
    except CalendarProviderError as exc:
        _json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    serialized = [_serialize_event(ev) for ev in events]
    _json_response(
        handler,
        HTTPStatus.OK,
        {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "events": serialized,
        },
    )


def _handle_create_event(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
    tz: tzinfo,
) -> None:
    body = _read_json(handler)
    try:
        user_id = _validated_user(handler, users, bot_token, body=body)
    except _AbortRequest:
        return
    title = str(body.get("title") or "").strip()
    start_raw = str(body.get("start") or "").strip()
    end_raw = str(body.get("end") or "").strip()
    location = (body.get("location") or None)
    description = (body.get("description") or None)
    if not title or not start_raw or not end_raw:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_fields"})
        return
    start = _parse_datetime(start_raw, tz)
    end = _parse_datetime(end_raw, tz)
    if start is None or end is None or end <= start:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_dates"})
        return
    payload = CalendarEventPayload(
        title=title,
        start=start,
        end=end,
        location=str(location).strip() if isinstance(location, str) and location.strip() else None,
        description=str(description).strip() if isinstance(description, str) and description.strip() else None,
    )
    try:
        ref = calendar.create_event(user_id, payload, tz=tz)
    except CalendarNotConnectedError:
        _json_response(
            handler, HTTPStatus.CONFLICT, {"error": "not_connected"}
        )
        return
    except CalendarProviderError as exc:
        _json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    _json_response(
        handler,
        HTTPStatus.CREATED,
        {"uid": ref.uid, "url": ref.url, "status": "created"},
    )


def _handle_delete_event(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
    path: str,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token)
    except _AbortRequest:
        return
    uid = path[len("/api/calendar/events/"):].strip("/")
    if not uid:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_uid"})
        return
    qs = parse_qs(urlparse(handler.path).query)
    url = qs.get("url", [None])[0]
    ref = CalendarEventRef(uid=uid, url=url or None)
    try:
        calendar.delete_event(user_id, ref)
    except CalendarNotConnectedError:
        _json_response(
            handler, HTTPStatus.CONFLICT, {"error": "not_connected"}
        )
        return
    except CalendarProviderError as exc:
        _json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    _json_response(handler, HTTPStatus.OK, {"status": "deleted"})


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: str, tz: tzinfo) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt


def _serialize_event(event: dict) -> dict:
    return {
        "uid": event.get("uid") or event.get("id"),
        "url": event.get("url"),
        "title": event.get("summary") or event.get("title") or "",
        "location": event.get("location") or "",
        "start": event.get("dtstart"),
        "end": event.get("dtend"),
        "status": event.get("status"),
        "all_day": bool(event.get("all_day")),
    }


def _json_response(
    handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any]
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)
