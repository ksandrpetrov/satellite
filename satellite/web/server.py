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

from ..calendar.events import build_upcoming_events_groups
from ..calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ..calendar.providers.registry import PROVIDER_IDS, PROVIDER_MAILRU, PROVIDER_YANDEX
from ..calendar.user_calendar_service import UserCalendarService
from ..security.token_vault import ProviderCredentials
from ..users import USER_STATUS_APPROVED, UserStore, UserStorePersistenceError
from .connect_token import ConnectTokenStore
from .init_data import InitDataError, validate_init_data

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_FILE = _STATIC_DIR / "connect.html"
_MAX_BODY_BYTES = 64 * 1024
_EVENTS_DEFAULT_DAYS = 14
_UPCOMING_VIEW_DAYS = 7


@dataclass(frozen=True)
class WebAppServerConfig:
    host: str
    port: int
    bot_token: str
    tz_name: str = "Europe/Moscow"
    connect_tokens: ConnectTokenStore | None = None


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
        self._connect_tokens = config.connect_tokens or ConnectTokenStore()
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
        connect_tokens = self._connect_tokens
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
                    _handle_status(self, calendar, users, bot_token, connect_tokens)
                    return
                if path == "/api/calendar/events":
                    _handle_list_events(
                        self, calendar, users, bot_token, connect_tokens, tz
                    )
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/calendar/connect":
                    _handle_connect(self, calendar, users, bot_token, connect_tokens)
                    return
                if path == "/api/calendar/events":
                    _handle_create_event(
                        self, calendar, users, bot_token, connect_tokens, tz
                    )
                    return
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_DELETE(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/calendar/disconnect":
                    _handle_disconnect(
                        self, calendar, users, bot_token, connect_tokens
                    )
                    return
                if path.startswith("/api/calendar/events/"):
                    _handle_delete_event(
                        self, calendar, users, bot_token, connect_tokens, path
                    )
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
    handler.send_header("Referrer-Policy", "no-referrer")
    # Не ставим X-Frame-Options: SAMEORIGIN — ломает WebView Telegram Desktop/Web.
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://telegram.org 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'self' https://web.telegram.org https://*.web.telegram.org "
        "https://telegram.org https://*.telegram.org",
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


def _extract_init_data(
    handler: BaseHTTPRequestHandler,
    body: dict[str, Any] | None = None,
) -> str:
    """initData из заголовка, JSON-тела или query (nginx часто не проксирует кастомные headers)."""
    init_data = (handler.headers.get("X-Telegram-Init-Data") or "").strip()
    if init_data:
        return init_data
    if body is not None:
        from_body = str(body.get("initData") or "").strip()
        if from_body:
            return from_body
    qs = parse_qs(urlparse(handler.path).query)
    from_query = (qs.get("initData") or [""])[0].strip()
    return from_query


def _extract_connect_token(
    handler: BaseHTTPRequestHandler,
    body: dict[str, Any] | None = None,
) -> str:
    token = (handler.headers.get("X-Connect-Token") or "").strip()
    if token:
        return token
    if body is not None:
        from_body = str(body.get("t") or body.get("connect_token") or "").strip()
        if from_body:
            return from_body
    qs = parse_qs(urlparse(handler.path).query)
    return (qs.get("t") or [""])[0].strip()


def _user_id_from_connect_token(
    handler: BaseHTTPRequestHandler,
    users: UserStore,
    connect_tokens: ConnectTokenStore,
    *,
    body: dict[str, Any] | None = None,
) -> int | None:
    token = _extract_connect_token(handler, body)
    if not token:
        return None
    user_id = connect_tokens.resolve(token)
    if user_id is None:
        log.info("Reject WebApp request: invalid or expired connect token")
        _json_response(
            handler,
            HTTPStatus.UNAUTHORIZED,
            {"error": "connect_token_invalid", "message": "Connect link expired"},
        )
        raise _AbortRequest()
    record = users.get(user_id)
    if record is None or record.status != USER_STATUS_APPROVED:
        log.info(
            "Reject WebApp request: connect token user_id=%s not approved (status=%s)",
            user_id,
            getattr(record, "status", None),
        )
        _json_response(handler, HTTPStatus.FORBIDDEN, {"error": "not_approved"})
        raise _AbortRequest()
    return user_id


def _validated_user(
    handler: BaseHTTPRequestHandler,
    users: UserStore,
    bot_token: str,
    connect_tokens: ConnectTokenStore,
    *,
    body: dict[str, Any] | None = None,
) -> int:
    """Возвращает telegram_user_id, если initData валидна и пользователь approved.

    Без approved-статуса возвращает HTTP 403 и поднимает ``_AbortRequest``,
    чтобы хендлер сразу завершился. Web App доступен только тем, кому
    одобрили заявку на доступ через админский флоу.
    """
    init_data = _extract_init_data(handler, body)
    if init_data:
        try:
            validated = validate_init_data(init_data, bot_token=bot_token)
        except InitDataError as exc:
            log.info("Reject WebApp request: %s", exc)
            _json_response(
                handler,
                HTTPStatus.UNAUTHORIZED,
                {"error": exc.code, "message": str(exc)},
            )
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

    user_id = _user_id_from_connect_token(
        handler, users, connect_tokens, body=body
    )
    if user_id is not None:
        return user_id

    log.info("Reject WebApp request: missing initData and connect token")
    _json_response(
        handler,
        HTTPStatus.UNAUTHORIZED,
        {
            "error": "no_init_data",
            "message": "Missing initData (open Web App from Telegram bot button)",
        },
    )
    raise _AbortRequest()


class _AbortRequest(Exception):
    """Сигнал хендлеру: ответ уже отправлен, надо тихо выйти."""


def _handle_connect(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
    connect_tokens: ConnectTokenStore,
) -> None:
    body = _read_json(handler)
    try:
        user_id = _validated_user(
            handler, users, bot_token, connect_tokens, body=body
        )
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
    caldav_url = str(body.get("caldav_url") or "").strip() or None
    try:
        calendar.connect(
            user_id,
            provider_id=provider,
            credentials=ProviderCredentials(login=login, secret=app_password),
            caldav_url=caldav_url,
        )
    except CalendarProviderError as exc:
        _json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    except UserStorePersistenceError as exc:
        log.error("Persistence error during connect: %s", exc)
        _json_response(
            handler,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {"error": "storage_unavailable"},
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
    connect_tokens: ConnectTokenStore,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token, connect_tokens)
    except _AbortRequest:
        return
    try:
        calendar.disconnect(user_id)
    except KeyError:
        _json_response(
            handler, HTTPStatus.OK, {"status": "disconnected"}
        )
        return
    except UserStorePersistenceError as exc:
        log.error("Persistence error during disconnect: %s", exc)
        _json_response(
            handler,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {"error": "storage_unavailable"},
        )
        return
    _json_response(handler, HTTPStatus.OK, {"status": "disconnected"})


def _handle_status(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    users: UserStore,
    bot_token: str,
    connect_tokens: ConnectTokenStore,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token, connect_tokens)
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
    connect_tokens: ConnectTokenStore,
    tz: tzinfo,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token, connect_tokens)
    except _AbortRequest:
        return
    qs = parse_qs(urlparse(handler.path).query)
    today = datetime.now(tz=tz).date()
    view = (qs.get("view", [None])[0] or "").strip().lower()
    if view == "upcoming":
        days = _parse_positive_int(qs.get("days", [None])[0], default=_UPCOMING_VIEW_DAYS)
        if days is None or days > 31:
            _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_days"})
            return
        end_date = today + timedelta(days=days)
        try:
            events = calendar.list_events(
                user_id, start_date=today, end_date=end_date, tz=tz
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
        groups = build_upcoming_events_groups(
            events, tz, today, days=days
        )
        _json_response(
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

    start_date = _parse_date(qs.get("from", [None])[0]) or today
    end_date = _parse_date(qs.get("to", [None])[0]) or (
        today + timedelta(days=_EVENTS_DEFAULT_DAYS)
    )
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
    connect_tokens: ConnectTokenStore,
    tz: tzinfo,
) -> None:
    body = _read_json(handler)
    try:
        user_id = _validated_user(
            handler, users, bot_token, connect_tokens, body=body
        )
    except _AbortRequest:
        return
    title = str(body.get("title") or "").strip()
    start_raw = str(body.get("start") or "").strip()
    end_raw = str(body.get("end") or "").strip()
    duration_raw = body.get("duration_minutes")
    location = body.get("location")
    description = body.get("description")
    if not title or not start_raw:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "missing_fields"})
        return
    start = _parse_datetime(start_raw, tz)
    if start is None:
        _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_dates"})
        return
    end: datetime | None = None
    if end_raw:
        end = _parse_datetime(end_raw, tz)
    elif duration_raw is not None:
        try:
            minutes = int(duration_raw)
        except (TypeError, ValueError):
            minutes = 0
        if minutes <= 0 or minutes > 24 * 60:
            _json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_duration"})
            return
        end = start + timedelta(minutes=minutes)
    if end is None or end <= start:
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
    connect_tokens: ConnectTokenStore,
    path: str,
) -> None:
    try:
        user_id = _validated_user(handler, users, bot_token, connect_tokens)
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


def _parse_positive_int(value: str | None, *, default: int) -> int | None:
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


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
