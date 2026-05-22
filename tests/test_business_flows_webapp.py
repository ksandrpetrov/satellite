"""Web App: initData errors, credentials hygiene, API coverage."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest

from satellite.users import USER_STATUS_APPROVED, USER_STATUS_PENDING, UserStore
from satellite.web.server import WebAppServer, WebAppServerConfig

from .conftest import free_tcp_port

BOT_TOKEN = "test-token:12345"


def _make_init_data(
    user_id: int,
    *,
    username: str = "alice",
    token: str = BOT_TOKEN,
    auth_date: int | None = None,
    bad_signature: bool = False,
) -> str:
    auth_date = auth_date if auth_date is not None else int(time.time())
    user_payload = json.dumps(
        {"id": user_id, "username": username, "first_name": "A"},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    params = {"auth_date": str(auth_date), "query_id": "q1", "user": user_payload}
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if bad_signature:
        sig = "deadbeef" * 8
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
def webapp(tmp_path: Path):
    users = UserStore(tmp_path / "users.json")
    calendar = MagicMock()
    port = free_tcp_port()
    server = WebAppServer(
        config=WebAppServerConfig(
            host="127.0.0.1",
            port=port,
            bot_token=BOT_TOKEN,
            tz_name="Europe/Moscow",
        ),
        calendar_service=calendar,
        users=users,
    )
    server.start()
    try:
        yield server, users, calendar, f"http://127.0.0.1:{port}"
    finally:
        server.stop()


def _approve(users: UserStore, uid: int, *, with_calendar: bool = False) -> None:
    users.upsert_from_telegram(
        telegram_user_id=uid,
        chat_id=uid,
        username="alice",
        display_name="Alice",
        default_status=USER_STATUS_APPROVED,
    )
    if with_calendar:
        users.set_calendar_connection(
            uid,
            provider="mailru",
            encrypted_credentials="encrypted-blob",
            primary_calendar_url="https://example/cal/",
        )


def test_init_data_bad_signature_returns_401(webapp) -> None:
    _server, users, _cal, base = webapp
    _approve(users, 1)
    init_data = _make_init_data(1, bad_signature=True)
    status, body = _http("GET", base + "/api/calendar/status", init_data=init_data)
    assert status == HTTPStatus.UNAUTHORIZED
    assert body.get("error") == "bad_signature"


def test_init_data_expired_returns_401(webapp) -> None:
    _server, users, _cal, base = webapp
    _approve(users, 1)
    old = int(time.time()) - 86400 * 2
    init_data = _make_init_data(1, auth_date=old)
    status, body = _http("GET", base + "/api/calendar/status", init_data=init_data)
    assert status == HTTPStatus.UNAUTHORIZED
    assert body.get("error") in ("expired", "bad_signature", "auth_date_expired")


def test_connect_never_stores_raw_password_in_users_json(webapp, tmp_path: Path) -> None:
    from cryptography.fernet import Fernet

    from satellite.security.token_vault import TokenVault

    _server, users, calendar, base = webapp
    _approve(users, 42)
    init_data = _make_init_data(42)
    raw_password = "SuperSecretAppPassword123!"
    vault = TokenVault(Fernet.generate_key().decode())

    def _fake_connect(user_id, *, provider_id, credentials, caldav_url=None):
        blob = vault.encrypt(credentials)
        users.set_calendar_connection(
            user_id,
            provider=provider_id,
            encrypted_credentials=blob,
            primary_calendar_url=caldav_url or "https://cal/",
        )

    calendar.connect = MagicMock(side_effect=_fake_connect)
    status, _body = _http(
        "POST",
        base + "/api/calendar/connect",
        init_data=init_data,
        body={
            "provider": "mailru",
            "login": "user@mail.ru",
            "app_password": raw_password,
        },
    )
    assert status == HTTPStatus.OK
    calendar.connect.assert_called_once()
    raw_json = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert raw_password not in raw_json
    record = users.get(42)
    assert record is not None
    assert record.encrypted_credentials
    assert record.encrypted_credentials != raw_password


def test_list_events_passes_from_to_query(webapp) -> None:
    _server, users, calendar, base = webapp
    _approve(users, 1, with_calendar=True)
    init_data = _make_init_data(1)
    status, _body = _http(
        "GET",
        base + "/api/calendar/events?from=2026-05-01&to=2026-05-31",
        init_data=init_data,
    )
    assert status == HTTPStatus.OK
    call = calendar.list_events.call_args
    assert call.kwargs["start_date"].isoformat() == "2026-05-01"
    assert call.kwargs["end_date"].isoformat() == "2026-05-31"


def test_delete_event_without_url_still_deletes(webapp) -> None:
    """DELETE без ?url= передаёт ``url=None`` в CalendarEventRef (контракт API)."""
    _server, users, calendar, base = webapp
    _approve(users, 1, with_calendar=True)
    calendar.delete_event = MagicMock()
    init_data = _make_init_data(1)
    status, body = _http(
        "DELETE",
        base + "/api/calendar/events/some-uid",
        init_data=init_data,
    )
    assert status == HTTPStatus.OK
    assert body["status"] == "deleted"
    ref = calendar.delete_event.call_args.args[1]
    assert ref.uid == "some-uid"
    assert ref.url is None


def test_pending_user_gets_403_on_every_api_route(webapp) -> None:
    from satellite.web.server import API_ROUTES

    _server, users, _cal, base = webapp
    users.upsert_from_telegram(
        telegram_user_id=99,
        chat_id=99,
        username="pending",
        display_name=None,
        default_status=USER_STATUS_PENDING,
    )
    init_data = _make_init_data(99)
    for route in API_ROUTES:
        path = route.path or (route.path_prefix or "evt") + "x"
        url = base + path
        status, _body = _http(
            route.method,
            url,
            init_data=init_data,
            body=None if route.method == "GET" else {},
        )
        assert status == HTTPStatus.FORBIDDEN, f"{route.method} {path} → {status}"
