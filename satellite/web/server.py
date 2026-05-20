"""Embedded HTTP server for Telegram Web App calendar connection."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..calendar.providers.base import CalendarProviderError
from ..calendar.providers.registry import PROVIDER_MAILRU, PROVIDER_YANDEX
from ..calendar.user_calendar_service import UserCalendarService
from ..security.token_vault import ProviderCredentials
from .init_data import InitDataError, validate_init_data

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class WebAppServerConfig:
    host: str
    port: int
    bot_token: str


class WebAppServer:
    def __init__(
        self,
        *,
        config: WebAppServerConfig,
        calendar_service: UserCalendarService,
    ) -> None:
        self._config = config
        self._calendar = calendar_service
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
            self._httpd = None
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _make_handler(self):
        calendar = self._calendar
        bot_token = self._config.bot_token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                log.debug("WebApp %s - %s", self.address_string(), format % args)

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path in {"/connect", "/connect/"}:
                    return _serve_file(self, _STATIC_DIR / "connect.html", "text/html")
                if path == "/api/calendar/status":
                    return _handle_status(self, calendar, bot_token)
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/calendar/connect":
                    return _handle_connect(self, calendar, bot_token)
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_DELETE(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/calendar/disconnect":
                    return _handle_disconnect(self, calendar, bot_token)
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

        return Handler


def _serve_file(handler: BaseHTTPRequestHandler, path: Path, content_type: str) -> None:
    if not path.is_file():
        _json_response(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        return
    body = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type + "; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _validated_user(
    handler: BaseHTTPRequestHandler, bot_token: str
) -> tuple[int, str | None]:
    init_data = handler.headers.get("X-Telegram-Init-Data") or ""
    if not init_data:
        body = _read_json(handler)
        init_data = str(body.get("initData") or "")
    validated = validate_init_data(init_data, bot_token=bot_token)
    username = (validated.user.username or "").lower() or None
    return validated.user.id, username


def _handle_connect(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    bot_token: str,
) -> None:
    try:
        user_id, _username = _validated_user(handler, bot_token)
    except InitDataError:
        _json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return
    body = _read_json(handler)
    provider = str(body.get("provider") or PROVIDER_MAILRU).strip().lower()
    login = str(body.get("login") or "").strip()
    app_password = str(body.get("app_password") or body.get("token") or "").strip()
    if provider == PROVIDER_YANDEX:
        _json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": "provider_not_implemented"},
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
        {"status": "connected", "provider": provider, "masked": True},
    )


def _handle_disconnect(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    bot_token: str,
) -> None:
    try:
        user_id, _username = _validated_user(handler, bot_token)
    except InitDataError:
        _json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return
    calendar.disconnect(user_id)
    _json_response(handler, HTTPStatus.OK, {"status": "disconnected", "masked": True})


def _handle_status(
    handler: BaseHTTPRequestHandler,
    calendar: UserCalendarService,
    bot_token: str,
) -> None:
    try:
        user_id, _username = _validated_user(handler, bot_token)
    except InitDataError:
        _json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
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
                "masked": True,
            },
        )
    except CalendarProviderError:
        _json_response(
            handler,
            HTTPStatus.OK,
            {"status": "disconnected", "connected": False, "masked": True},
        )


def _json_response(
    handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any]
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
