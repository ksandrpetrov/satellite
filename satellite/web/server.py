"""Embedded HTTP server for Telegram Web App.

Поднимает локальный ThreadingHTTPServer, отдающий статическую SPA-страницу
``/connect`` и REST API ``/api/calendar/*`` для подключения календаря и
управления событиями. Все запросы к API авторизуются по Telegram
``initData`` (HMAC по bot token) и дополнительно фильтруются по
``UserStore`` (статус ``approved``).

HTTPS делегируется внешнему reverse proxy (nginx на хосте в production,
ngrok/Cloudflare Tunnel локально). Локально сервер слушает на
``WEBAPP_HOST:WEBAPP_PORT``.

Структура пакета: общий ``routing`` собирает таблицу маршрутов, конкретные
хендлеры живут в ``web/api/``, статичные страницы — в ``web/static_pages``.
Этот модуль отвечает только за lifecycle ThreadingHTTPServer и dispatch.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import tzinfo
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..calendar.user_calendar_service import UserCalendarService
from ..users import UserStore
from .api import (
    handle_connect,
    handle_create_event,
    handle_delete_event,
    handle_disconnect,
    handle_list_events,
    handle_status,
)
from .connect_token import ConnectTokenStore
from .parsing import connect_token_from_path, request_path
from .responses import json_response
from .routing import Deps, Route, find_route
from .static_pages import StaticPage, serve_html

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_FILE = _STATIC_DIR / "connect.html"

_CONNECT_PAGE = StaticPage(path=_INDEX_FILE, csp_img_src="'self' data:")


@dataclass(frozen=True)
class WebAppServerConfig:
    host: str
    port: int
    bot_token: str
    tz_name: str = "Europe/Moscow"
    connect_tokens: ConnectTokenStore | None = None


# --- routing table ---------------------------------------------------------

API_ROUTES: list[Route] = [
    Route(method="GET", path="/api/calendar/status", handler=handle_status),
    Route(method="GET", path="/api/calendar/events", handler=handle_list_events),
    Route(method="POST", path="/api/calendar/connect", handler=handle_connect),
    Route(method="POST", path="/api/calendar/events", handler=handle_create_event),
    Route(
        method="DELETE",
        path="/api/calendar/disconnect",
        handler=handle_disconnect,
    ),
    Route(
        method="DELETE",
        path_prefix="/api/calendar/events/",
        handler=handle_delete_event,
    ),
]


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
        self._deps = Deps(
            calendar=self._calendar,
            users=self._users,
            bot_token=self._config.bot_token,
            connect_tokens=self._connect_tokens,
            tz=self._tz,
        )
        self._thread: threading.Thread | None = None
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self._config.host, self._config.port), handler)
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
        deps = self._deps

        class Handler(BaseHTTPRequestHandler):
            server_version = "satellite-webapp/1.0"
            sys_version = ""

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                log.debug("WebApp %s - %s", self.address_string(), format % args)

            def do_GET(self) -> None:  # noqa: N802
                if _maybe_serve_html_or_health(self):
                    return
                _dispatch(self, "GET", deps)

            def do_POST(self) -> None:  # noqa: N802
                _dispatch(self, "POST", deps)

            def do_DELETE(self) -> None:  # noqa: N802
                _dispatch(self, "DELETE", deps)

        return Handler


# --- helpers ---------------------------------------------------------------


def _safe_zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        log.warning("Unknown timezone %r; falling back to Europe/Moscow", name)
        return ZoneInfo("Europe/Moscow")


def _maybe_serve_html_or_health(handler: BaseHTTPRequestHandler) -> bool:
    """Сначала статические страницы и healthz — они GET и не идут через API-таблицу."""
    path = request_path(handler)
    path_token = connect_token_from_path(path)
    if path in {"/", "/connect", "/connect/", "/index.html"} or path_token:
        serve_html(handler, _CONNECT_PAGE, path_token=path_token)
        return True
    if path == "/healthz":
        json_response(handler, HTTPStatus.OK, {"status": "ok"})
        return True
    return False


def _dispatch(handler: BaseHTTPRequestHandler, method: str, deps: Deps) -> None:
    path = request_path(handler)
    route = find_route(API_ROUTES, method, path)
    if route is None:
        json_response(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        return
    try:
        route(handler, deps)
    except Exception:  # noqa: BLE001 - request thread must fail closed
        log.exception("WebApp request failed method=%s path=%s", method, path)
        try:
            json_response(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "request_failed"})
        except Exception:  # noqa: BLE001 - connection may already be broken
            log.exception("Failed to send safe 500 response method=%s path=%s", method, path)
