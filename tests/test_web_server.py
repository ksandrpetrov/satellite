"""Тесты embedded Web App HTTP-сервера: healthz, approval gate, events CRUD."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest

from satellite.calendar.providers.base import (
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from satellite.users import USER_STATUS_APPROVED, USER_STATUS_PENDING, UserStore
from satellite.web.server import WebAppServer, WebAppServerConfig

BOT_TOKEN = "test-token:12345"


# --- helpers ---------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make_init_data(user_id: int, *, username: str = "alice", token: str = BOT_TOKEN) -> str:
    auth_date = int(time.time())
    user_payload = json.dumps(
        {"id": user_id, "username": username, "first_name": "A"},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    params = {
        "auth_date": str(auth_date),
        "query_id": "q1",
        "user": user_payload,
    }
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = sig
    return urlencode(params)


def _http(method: str, url: str, *, init_data: str = "", body: dict | None = None):
    data = None
    headers = {"Content-Type": "application/json"}
    if init_data:
        headers["X-Telegram-Init-Data"] = init_data
    if body is not None:
        payload = dict(body)
        if init_data and "initData" not in payload:
            payload["initData"] = init_data
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return exc.code, json.loads(body_text or "{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": body_text}


@pytest.fixture
def started_server(tmp_path: Path):
    users = UserStore(tmp_path / "users.json")
    calendar = MagicMock()
    port = _free_port()
    server = WebAppServer(
        config=WebAppServerConfig(
            host="127.0.0.1", port=port, bot_token=BOT_TOKEN, tz_name="Europe/Moscow"
        ),
        calendar_service=calendar,
        users=users,
    )
    server.start()
    try:
        yield server, users, calendar, f"http://127.0.0.1:{port}"
    finally:
        server.stop()


def _approve_user(users: UserStore, user_id: int, *, with_calendar: bool = False) -> None:
    users.upsert_from_telegram(
        telegram_user_id=user_id,
        chat_id=user_id,
        username="alice",
        display_name="Alice",
        default_status=USER_STATUS_APPROVED,
    )
    if with_calendar:
        users.set_calendar_connection(
            user_id,
            provider="mailru",
            encrypted_credentials="encrypted",
            primary_calendar_url="https://example/cal/",
        )


# --- tests -----------------------------------------------------------------


def test_healthz_does_not_require_auth(started_server):
    _server, _users, _calendar, base = started_server
    status, body = _http("GET", base + "/healthz")
    assert status == 200
    assert body == {"status": "ok"}


def test_connect_html_served_with_security_headers(started_server):
    _server, _users, _calendar, base = started_server
    req = urllib.request.Request(base + "/connect", method="GET")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors" in resp.headers["Content-Security-Policy"]
        assert "telegram.org" in resp.headers["Content-Security-Policy"]
        assert "Content-Security-Policy" in resp.headers


def test_status_without_init_data_returns_401(started_server):
    _server, _users, _calendar, base = started_server
    status, body = _http("GET", base + "/api/calendar/status")
    assert status == 401
    assert body["error"] == "no_init_data"


def test_status_for_pending_user_returns_403(started_server):
    _server, users, _calendar, base = started_server
    users.upsert_from_telegram(
        telegram_user_id=42,
        chat_id=42,
        username="alice",
        display_name="Alice",
        default_status=USER_STATUS_PENDING,
    )
    init = _make_init_data(42)
    status, body = _http("GET", base + "/api/calendar/status", init_data=init)
    assert status == 403
    assert body["error"] == "not_approved"


def test_status_for_approved_without_calendar(started_server):
    _server, users, _calendar, base = started_server
    _approve_user(users, 100)
    init = _make_init_data(100)
    status, body = _http("GET", base + "/api/calendar/status", init_data=init)
    assert status == 200
    assert body == {"connected": False, "status": "disconnected", "provider": None}


def test_status_accepts_init_data_in_query_without_header(started_server):
    """nginx иногда не проксирует X-Telegram-Init-Data — дублируем initData в query."""
    from urllib.parse import quote

    _server, users, _calendar, base = started_server
    _approve_user(users, 101)
    init = _make_init_data(101)
    url = base + "/api/calendar/status?initData=" + quote(init, safe="")
    status, body = _http("GET", url)
    assert status == 200
    assert body["connected"] is False


def test_connect_rejects_pending_user(started_server):
    _server, users, _calendar, base = started_server
    users.upsert_from_telegram(
        telegram_user_id=7,
        chat_id=7,
        username="bob",
        display_name=None,
        default_status=USER_STATUS_PENDING,
    )
    init = _make_init_data(7, username="bob")
    status, _ = _http(
        "POST",
        base + "/api/calendar/connect",
        init_data=init,
        body={"provider": "mailru", "login": "x@mail.ru", "app_password": "p"},
    )
    assert status == 403


def test_connect_happy_path(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 200)
    init = _make_init_data(200)
    calendar.connect = MagicMock()
    status, body = _http(
        "POST",
        base + "/api/calendar/connect",
        init_data=init,
        body={"provider": "mailru", "login": "x@mail.ru", "app_password": "secret"},
    )
    assert status == 200
    assert body["status"] == "connected"
    assert body["provider"] == "mailru"
    calendar.connect.assert_called_once()


def test_connect_invalid_provider_returns_400(started_server):
    _server, users, _calendar, base = started_server
    _approve_user(users, 201)
    init = _make_init_data(201)
    status, body = _http(
        "POST",
        base + "/api/calendar/connect",
        init_data=init,
        body={"provider": "icloud", "login": "x@mail.ru", "app_password": "p"},
    )
    assert status == 400
    assert body["error"] == "unknown_provider"


def test_connect_provider_error_propagates_code(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 202)
    calendar.connect = MagicMock(
        side_effect=CalendarProviderError("nope", error_code="AUTH_FAILED")
    )
    init = _make_init_data(202)
    status, body = _http(
        "POST",
        base + "/api/calendar/connect",
        init_data=init,
        body={"provider": "mailru", "login": "x@mail.ru", "app_password": "p"},
    )
    assert status == 400
    assert body["error"] == "AUTH_FAILED"


def test_disconnect_endpoint(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 300, with_calendar=True)
    calendar.disconnect = MagicMock()
    init = _make_init_data(300)
    status, body = _http("DELETE", base + "/api/calendar/disconnect", init_data=init)
    assert status == 200
    assert body["status"] == "disconnected"
    calendar.disconnect.assert_called_once_with(300)


def test_list_events_when_not_connected(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 400)
    calendar.list_events = MagicMock(side_effect=CalendarNotConnectedError())
    init = _make_init_data(400)
    status, body = _http("GET", base + "/api/calendar/events", init_data=init)
    assert status == 409
    assert body["error"] == "not_connected"


def test_list_events_serializes_payload(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 401, with_calendar=True)
    calendar.list_events = MagicMock(
        return_value=[
            {
                "uid": "u1",
                "summary": "Дейли",
                "location": "Zoom",
                "dtstart": "2026-05-12T10:00:00+03:00",
                "dtend": "2026-05-12T10:30:00+03:00",
                "url": "https://cal/e1.ics",
            },
        ]
    )
    init = _make_init_data(401)
    status, body = _http(
        "GET",
        base + "/api/calendar/events?from=2026-05-12&to=2026-05-15",
        init_data=init,
    )
    assert status == 200
    assert body["from"] == "2026-05-12"
    assert body["to"] == "2026-05-15"
    assert body["events"][0]["title"] == "Дейли"
    assert body["events"][0]["uid"] == "u1"


def test_create_event_validates_dates(started_server):
    _server, users, _calendar, base = started_server
    _approve_user(users, 500, with_calendar=True)
    init = _make_init_data(500)
    status, body = _http(
        "POST",
        base + "/api/calendar/events",
        init_data=init,
        body={"title": "T", "start": "2026-05-12T10:00", "end": "2026-05-12T09:00"},
    )
    assert status == 400
    assert body["error"] == "invalid_dates"


def test_create_event_happy_path(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 501, with_calendar=True)
    calendar.create_event = MagicMock(
        return_value=CalendarEventRef(uid="uid-1", url="https://cal/e1.ics")
    )
    init = _make_init_data(501)
    status, body = _http(
        "POST",
        base + "/api/calendar/events",
        init_data=init,
        body={
            "title": "Дейли",
            "start": "2026-05-12T10:00",
            "end": "2026-05-12T11:00",
            "location": "Zoom",
        },
    )
    assert status == 201
    assert body["uid"] == "uid-1"
    calendar.create_event.assert_called_once()


def test_delete_event_passes_url_query(started_server):
    _server, users, calendar, base = started_server
    _approve_user(users, 600, with_calendar=True)
    calendar.delete_event = MagicMock()
    init = _make_init_data(600)
    status, body = _http(
        "DELETE",
        base + "/api/calendar/events/uid-1?url=" + urlencode({"u": "https://cal/e1.ics"})[2:],
        init_data=init,
    )
    assert status == 200
    assert body["status"] == "deleted"
    args, _kwargs = calendar.delete_event.call_args
    assert args[0] == 600
    assert args[1].uid == "uid-1"


def test_unknown_path_returns_404(started_server):
    _server, _users, _calendar, base = started_server
    status, body = _http("GET", base + "/nope")
    assert status == 404
    assert body["error"] == "not_found"


def test_init_data_invalid_signature_returns_401(started_server):
    _server, users, _calendar, base = started_server
    _approve_user(users, 700)
    bad = _make_init_data(700, token="wrong-token")
    status, _ = _http("GET", base + "/api/calendar/status", init_data=bad)
    assert status == 401
