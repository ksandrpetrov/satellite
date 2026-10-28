"""MCP calendar contracts: real OAuth/HTTP boundaries with an offline provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.testclient import TestClient

from satellite.calendar.availability import find_free_slots
from satellite.calendar.providers.base import (
    CalendarEventRef,
    CalendarListEntry,
    CalendarProviderError,
)
from satellite.mail_calendar_mcp.accounts import (
    AccountLoadError,
    AccountPersistenceError,
    CalendarAccountStore,
)
from satellite.mail_calendar_mcp.oauth import (
    CODE_TTL,
    LOGIN_TTL,
    SCOPE,
    MailOAuthProvider,
    OAuthState,
)
from satellite.mail_calendar_mcp.package import package_plugin
from satellite.mail_calendar_mcp.server import create_app, create_server
from satellite.mail_calendar_mcp.service import MailCalendarService
from satellite.mail_calendar_mcp.settings import McpSettings
from satellite.messages_ru import MCP_INSTRUCTIONS
from satellite.security.token_vault import TokenVault

LOGIN = "owner@vk.team"
CALENDAR = "https://calendar.mail.ru/calendars/vk.team/owner/main/"
SECOND_CALENDAR = "https://calendar.mail.ru/calendars/vk.team/owner/team/"
TZ = ZoneInfo("Europe/Moscow")


def run(coro):
    return asyncio.run(coro)


def event(title="Review", start="10:00", end="11:00", *, day="2026-09-30", **extra):
    return {
        "uid": title,
        "url": CALENDAR + title + ".ics",
        "summary": title,
        "dtstart": f"{day}T{start}:00+03:00",
        "dtend": f"{day}T{end}:00+03:00",
        "calendar": "Work",
        **extra,
    }


class FakeProvider:
    def __init__(self):
        self.events = []
        self.writes = []
        self.fetches = []
        self.create_attempts = 0
        self.failure = None
        self.closed = False

    def close(self):
        self.closed = True

    def validate_credentials(self, credentials):
        return credentials.secret == "app-password", CALENDAR, None

    def list_calendars(self, context):
        return [CalendarListEntry("Work", CALENDAR), CalendarListEntry("Team", SECOND_CALENDAR)]

    def list_events(self, context, **kwargs):
        self.fetches.append((context, kwargs))
        if self.failure:
            raise self.failure
        return self.events

    list_events_for_invitations = list_events

    def create_event(self, context, payload, **kwargs):
        self.create_attempts += 1
        if self.failure:
            raise self.failure
        self.writes.append(("create", context, payload))
        return CalendarEventRef("created", context.primary_calendar_url + "created.ics")

    def set_attendee_partstat(self, context, ref, response):
        self.writes.append(("respond", context, ref, response))


@pytest.fixture
def calendar_stack(tmp_path):
    settings = McpSettings(
        "http://127.0.0.1:8765", Fernet.generate_key().decode(), frozenset({LOGIN}), tmp_path
    )
    accounts = CalendarAccountStore(tmp_path / "users.json", TokenVault(settings.encryption_key))
    provider = FakeProvider()
    service = MailCalendarService(settings, accounts, provider)
    state = OAuthState(tmp_path / "oauth.sqlite3", settings.encryption_key)
    oauth = MailOAuthProvider(settings, state)
    return settings, accounts, provider, service, state, oauth


def test_connection_stores_only_encrypted_credentials_and_loads_after_restart(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    account = service.connect(LOGIN, "app-password")
    disk = (settings.data_dir / "users.json").read_text()
    assert "app-password" not in disk
    assert LOGIN not in disk
    loaded = CalendarAccountStore(settings.data_dir / "users.json", accounts.vault)
    assert loaded.get(account.account_id) == account
    assert loaded.vault.decrypt(account.credentials_blob).secret == "app-password"
    assert service.profile(account.account_id)["timezone"] == "Europe/Moscow"
    state.close()


def test_unauthorized_account_and_bad_credentials_make_no_connection(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    with pytest.raises(ValueError):
        service.connect("another@mail.ru", "app-password")
    with pytest.raises(ValueError):
        service.connect(LOGIN, "wrong")
    assert not (settings.data_dir / "users.json").exists()
    state.close()


def test_account_commit_failure_preserves_disk_and_memory(calendar_stack, monkeypatch):
    settings, accounts, provider, service, state, oauth = calendar_stack
    first = service.connect(LOGIN, "app-password")
    before = (settings.data_dir / "users.json").read_bytes()

    def failed_replace(*args):
        raise OSError("disk full")

    monkeypatch.setattr("satellite.json_store.os.replace", failed_replace)
    with pytest.raises(AccountPersistenceError):
        service.connect(LOGIN, "app-password")
    assert accounts.get(first.account_id) == first
    assert (settings.data_dir / "users.json").read_bytes() == before
    state.close()


@pytest.mark.parametrize(
    "root", [[], {"version": 1, "accounts": []}, {"version": 1, "accounts": {"1": {}}}]
)
def test_corrupt_account_store_is_fatal(tmp_path, root):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(root))
    with pytest.raises(AccountLoadError):
        CalendarAccountStore(path, TokenVault(Fernet.generate_key().decode()))


def test_event_search_pagination_and_selection_use_account_context(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    owner = service.connect(LOGIN, "app-password").account_id
    provider.events = [event("Review 1"), event("Review 2"), event("Other")]
    calendars = service.calendars(owner)["calendars"]
    page = service.events(
        owner,
        date(2026, 9, 30),
        date(2026, 10, 1),
        query="review",
        limit=1,
        calendar_id=calendars[1]["calendar_id"],
    )
    assert page["total"] == 2
    assert page["has_more"] and page["next_offset"] == 1
    assert page["events"][0]["title"] == "Review 1"
    assert provider.fetches[-1][0].enabled_calendar_urls == (SECOND_CALENDAR,)
    assert CALENDAR not in page["events"][0]["event_id"]
    with pytest.raises(ValueError):
        service.events(owner, date(2026, 9, 30), date(2026, 9, 30))
    state.close()


def test_foreign_and_stale_identifiers_cannot_mutate_calendar(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    owner = service.connect(LOGIN, "app-password").account_id
    provider.events = [event()]
    ref = service.events(owner, date(2026, 9, 30), date(2026, 10, 1))["events"][0]["event_id"]
    with pytest.raises(ValueError):
        service.respond(owner + 1, ref, "ACCEPTED", confirm=True, confirm_series=False)
    bad = service._encode(
        owner, "event", url="https://evil.example/steal", uid="x", recurring=False
    )
    with pytest.raises(ValueError):
        service.respond(owner, bad, "ACCEPTED", confirm=True, confirm_series=False)
    service.connect(LOGIN, "app-password")
    with pytest.raises(ValueError):
        service.respond(owner, ref, "ACCEPTED", confirm=True, confirm_series=False)
    assert not provider.writes
    state.close()


def test_preview_creates_nothing_then_explicitly_creates_in_one_calendar(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    owner = service.connect(LOGIN, "app-password").account_id
    start = datetime(2026, 9, 30, 15, tzinfo=TZ)
    kwargs = {"calendar_id": None, "location": "Room 4", "description": "Agenda", "confirm": False}
    result = service.create(owner, "Sync", start, start + timedelta(hours=1), **kwargs)
    assert result["status"] == "preview" and provider.writes == []
    kwargs["confirm"] = True
    result = service.create(owner, "Sync", start, start + timedelta(hours=1), **kwargs)
    assert result["status"] == "created"
    assert len(provider.writes) == 1
    assert provider.writes[0][1].enabled_calendar_urls == (CALENDAR,)
    with pytest.raises(ValueError):
        service.create(
            owner, "Sync", start.replace(tzinfo=None), start + timedelta(hours=1), **kwargs
        )
    state.close()


def test_recurring_invitation_requires_series_authorization(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    owner = service.connect(LOGIN, "app-password").account_id
    provider.events = [event(rrule={"FREQ": ["WEEKLY"]})]
    ref = service.events(owner, date(2026, 9, 30), date(2026, 10, 1))["events"][0]["event_id"]
    result = service.respond(owner, ref, "DECLINED", confirm=True, confirm_series=False)
    assert result["status"] == "preview" and result["affects_entire_series"]
    assert provider.writes == []
    result = service.respond(owner, ref, "DECLINED", confirm=True, confirm_series=True)
    assert result["status"] == "updated" and len(provider.writes) == 1
    state.close()


def test_free_time_merges_overlaps_and_blocks_pending_and_all_day():
    events = [
        event("First", "10:00", "11:00"),
        event("Overlap", "10:30", "12:00"),
        event("Pending", "14:00", "15:00", attendees=[f"mailto:{LOGIN};PARTSTAT=NEEDS-ACTION"]),
        event("Cancelled", "12:00", "19:00", status="CANCELLED"),
    ]
    slots = find_free_slots(
        events, start_date=date(2026, 9, 30), end_date=date(2026, 10, 1), tz=TZ, login=LOGIN
    )
    assert [(a.strftime("%H:%M"), b.strftime("%H:%M")) for a, b in slots] == [
        ("12:00", "14:00"),
        ("15:00", "19:00"),
    ]
    events.append({"dtstart": "2026-09-30", "dtend": "2026-10-01", "summary": "Vacation"})
    assert find_free_slots(
        events, start_date=date(2026, 9, 30), end_date=date(2026, 10, 2), tz=TZ, login=LOGIN
    ) == [(datetime(2026, 10, 1, 10, tzinfo=TZ), datetime(2026, 10, 1, 19, tzinfo=TZ))]


def test_free_time_invalid_event_fails_instead_of_claiming_empty_calendar():
    with pytest.raises(ValueError):
        find_free_slots(
            [event(end="09:00")],
            start_date=date(2026, 9, 30),
            end_date=date(2026, 10, 1),
            tz=TZ,
            login=LOGIN,
        )


def oauth_client():
    return OAuthClientInformationFull(
        client_id="gpt",
        client_name="ChatGPT",
        redirect_uris=[AnyUrl("https://chatgpt.com/connector/oauth/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def test_oauth_tokens_persist_rotate_and_revoke_with_their_grant(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    client = oauth_client()
    run(oauth.register_client(client))
    first = oauth._issue("gpt", "123", [SCOPE])
    stored_bytes = (settings.data_dir / "oauth.sqlite3").read_bytes()
    assert first.access_token.encode() not in stored_bytes
    assert first.refresh_token.encode() not in stored_bytes
    assert b'"subject": "123"' not in stored_bytes
    state.close()
    reopened = OAuthState(settings.data_dir / "oauth.sqlite3", settings.encryption_key)
    oauth = MailOAuthProvider(settings, reopened)
    assert run(oauth.get_client("gpt")) == client
    token = run(oauth.load_access_token(first.access_token))
    assert token.subject == "123" and token.resource == settings.resource_url
    refresh = run(oauth.load_refresh_token(client, first.refresh_token))
    second = run(oauth.exchange_refresh_token(client, refresh, [SCOPE]))
    assert run(oauth.load_access_token(first.access_token)) is None
    assert run(oauth.load_refresh_token(client, first.refresh_token)) is None
    assert run(oauth.load_access_token(second.access_token)).subject == "123"
    run(oauth.revoke_token(run(oauth.load_access_token(second.access_token))))
    assert run(oauth.load_refresh_token(client, second.refresh_token)) is None
    reopened.close()


def test_oauth_rejects_untrusted_redirect_and_wrong_resource(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    client = oauth_client()
    client.redirect_uris = [AnyUrl("https://evil.example/callback")]
    with pytest.raises(RegistrationError):
        run(oauth.register_client(client))
    params = AuthorizationParams(
        state="test",
        scopes=[SCOPE],
        code_challenge="challenge",
        redirect_uri=AnyUrl("https://chatgpt.com/connector/oauth/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://elsewhere.example/mcp",
    )
    with pytest.raises(Exception) as exc:
        run(oauth.authorize(oauth_client(), params))
    assert "Resource does not match" in str(exc.value)
    state.close()


def http_stack(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    return create_app(create_server(settings, accounts, oauth, service), service, state)


def login_and_token(http, settings, *, before_connect=None):
    registration = http.post(
        settings.path_prefix + "/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chatgpt.com/connector/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE,
        },
    )
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    authorize = http.get(
        settings.path_prefix
        + "/authorize?"
        + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
                "scope": SCOPE,
                "state": "opaque-state",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": settings.resource_url,
            }
        ),
        follow_redirects=False,
    )
    assert authorize.status_code == 302, authorize.text
    form = http.get(authorize.headers["location"])
    # A native browser form must send its real Origin without leaking the ticket
    # in Referer. no-referrer would make HTML POSTs send Origin:null instead.
    assert form.headers["referrer-policy"] == "strict-origin"
    assert form.headers["cache-control"] == "no-store"
    csrf = re.search('name="csrf" value="([^"]+)"', form.text).group(1)
    ticket = re.search('name="ticket" value="([^"]+)"', form.text).group(1)
    if before_connect is not None:
        before_connect()
    connected = http.post(
        settings.connect_path,
        data={"ticket": ticket, "csrf": csrf, "login": LOGIN, "secret": "app-password"},
        headers={"origin": settings.origin},
        follow_redirects=False,
    )
    assert connected.status_code == 303, connected.text
    query = parse_qs(urlsplit(connected.headers["location"]).query)
    assert query["state"] == ["opaque-state"]
    token_data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": query["code"][0],
        "code_verifier": verifier,
        "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
        "resource": settings.resource_url,
    }
    token = http.post(settings.path_prefix + "/token", data=token_data)
    assert token.status_code == 200, token.text
    assert http.post(settings.path_prefix + "/token", data=token_data).status_code == 400
    return token.json()["access_token"]


def mcp_call(http, token, method, params=None, *, origin=None, path="/mcp", protocol="2025-06-18"):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if origin:
        headers["Origin"] = origin
    params = dict(params or {})
    if protocol == "2026-07-28":
        headers["Mcp-Method"] = method
        if "name" in params:
            headers["Mcp-Name"] = params["name"]
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": protocol,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    return http.post(
        path,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=headers,
    )


def test_real_http_oauth_pkce_mcp_discovery_and_tool_call(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        assert http.get("/healthz").json() == {"status": "ok"}
        metadata = http.get("/.well-known/oauth-authorization-server").json()
        assert metadata["issuer"] == settings.base_url
        resource = http.get("/.well-known/oauth-protected-resource/mcp").json()
        assert resource["authorization_servers"] == [settings.base_url]
        unauth = mcp_call(http, None, "tools/list")
        assert unauth.status_code == 401
        assert "oauth-protected-resource" in unauth.headers["www-authenticate"]
        token = login_and_token(http, settings)
        initialized = mcp_call(
            http,
            token,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == "mail_calendar_mcp"
        assert initialized.json()["result"]["instructions"] == MCP_INSTRUCTIONS
        listed = mcp_call(http, token, "tools/list").json()["result"]["tools"]
        assert len(listed) == 7
        write = next(t for t in listed if t["name"] == "mail_calendar_create_event")
        assert write["annotations"]["readOnlyHint"] is False
        assert all(t["_meta"]["securitySchemes"][0]["type"] == "oauth2" for t in listed)
        profile = mcp_call(
            http, token, "tools/call", {"name": "mail_calendar_get_profile", "arguments": {}}
        )
        assert profile.json()["result"]["structuredContent"]["email"] == LOGIN
        blocked = mcp_call(http, token, "tools/list", origin="https://evil.example")
        assert blocked.status_code == 403
    assert provider.closed


@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
def test_http_mcp_newer_clients_keep_authenticated_tools_and_limits(calendar_stack, protocol):
    settings, accounts, provider, service, state, oauth = calendar_stack
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        assert mcp_call(http, None, "tools/list", protocol=protocol).status_code == 401
        token = login_and_token(http, settings)
        if protocol == "2026-07-28":
            discovered = mcp_call(http, token, "server/discover", protocol=protocol)
            assert discovered.status_code == 200, discovered.text
            assert protocol in discovered.json()["result"]["supportedVersions"]
            assert discovered.json()["result"]["instructions"] == MCP_INSTRUCTIONS
        listed = mcp_call(http, token, "tools/list", protocol=protocol)
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["result"]["tools"]) == 7
        profile = mcp_call(
            http,
            token,
            "tools/call",
            {"name": "mail_calendar_get_profile", "arguments": {}},
            protocol=protocol,
        )
        assert profile.status_code == 200, profile.text
        assert profile.json()["result"]["structuredContent"]["email"] == LOGIN
        oversized = mcp_call(
            http,
            token,
            "tools/call",
            {
                "name": "mail_calendar_create_event",
                "arguments": {"title": "x" * (64 * 1024), "confirm": True},
            },
            protocol=protocol,
        )
        assert oversized.status_code == 413
        assert provider.writes == []
    assert provider.closed


def test_browser_login_can_take_ten_minutes_without_expiring_csrf(calendar_stack, monkeypatch):
    settings, accounts, provider, service, state, oauth = calendar_stack
    now = [time.time()]
    monkeypatch.setattr("satellite.mail_calendar_mcp.oauth.time.time", lambda: now[0])

    def delayed_login():
        now[0] += 600

    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        token = login_and_token(http, settings, before_connect=delayed_login)
        profile = mcp_call(
            http, token, "tools/call", {"name": "mail_calendar_get_profile", "arguments": {}}
        )
        assert profile.status_code == 200
        assert profile.json()["result"]["structuredContent"]["email"] == LOGIN


def test_login_link_expires_independently_of_short_lived_authorization_code(
    calendar_stack, monkeypatch
):
    settings, accounts, provider, service, state, oauth = calendar_stack
    now = [time.time()]
    monkeypatch.setattr("satellite.mail_calendar_mcp.oauth.time.time", lambda: now[0])
    client = oauth_client()
    run(oauth.register_client(client))
    params = AuthorizationParams(
        state="expiry-test",
        scopes=[SCOPE],
        code_challenge="challenge",
        redirect_uri=client.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=settings.resource_url,
    )
    first = run(oauth.authorize(client, params))
    ticket = parse_qs(urlsplit(first).query)["ticket"][0]
    oauth.prepare_form(ticket, "csrf")
    now[0] += 600
    pending = oauth.check_form(ticket, "csrf", "csrf")
    redirect = oauth.complete_login(pending, 123)
    code_value = parse_qs(urlsplit(redirect).query)["code"][0]
    code = run(oauth.load_authorization_code(client, code_value))
    assert code.expires_at == now[0] + CODE_TTL
    now[0] += CODE_TTL + 1
    assert run(oauth.load_authorization_code(client, code_value)) is None

    expired_link = run(oauth.authorize(client, params))
    now[0] += LOGIN_TTL + 1
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        expired = http.get(expired_link)
        assert expired.status_code == 400
        assert "Ссылка подключения недействительна или устарела" in expired.text
        assert 'href="https://chatgpt.com/plugins"' in expired.text
        assert "Проверьте email и пароль" not in expired.text
        assert not (settings.data_dir / "users.json").exists()


def test_prefixed_https_server_keeps_oauth_discovery_and_browser_login_at_correct_paths(tmp_path):
    settings = McpSettings(
        "https://calendar.example.com/mail-calendar",
        Fernet.generate_key().decode(),
        frozenset({LOGIN}),
        tmp_path,
    )
    accounts = CalendarAccountStore(tmp_path / "users.json", TokenVault(settings.encryption_key))
    provider = FakeProvider()
    service = MailCalendarService(settings, accounts, provider)
    state = OAuthState(tmp_path / "oauth.sqlite3", settings.encryption_key)
    oauth = MailOAuthProvider(settings, state)
    app = create_app(create_server(settings, accounts, oauth, service), service, state)
    with TestClient(app, base_url=settings.origin) as http:
        assert http.get("/mail-calendar/healthz").json() == {"status": "ok"}
        assert http.get("/connect").status_code == 404
        assert http.get("/healthz").status_code == 404
        metadata = http.get("/.well-known/oauth-authorization-server/mail-calendar")
        assert metadata.status_code == 200
        assert metadata.json()["issuer"] == settings.base_url
        assert metadata.json()["authorization_endpoint"] == settings.base_url + "/authorize"
        assert metadata.json()["registration_endpoint"] == settings.base_url + "/register"
        unauth = mcp_call(http, None, "tools/list", path="/mail-calendar/mcp")
        assert unauth.status_code == 401
        discovery_url = re.search(
            'resource_metadata="([^"]+)"', unauth.headers["www-authenticate"]
        ).group(1)
        resource = http.get(discovery_url)
        assert resource.status_code == 200
        assert resource.json()["resource"] == settings.resource_url
        assert resource.json()["authorization_servers"] == [settings.base_url]
        token = login_and_token(http, settings)
        result = mcp_call(
            http,
            token,
            "tools/call",
            {"name": "mail_calendar_get_profile", "arguments": {}},
            origin=settings.origin,
            path="/mail-calendar/mcp",
        )
        assert result.status_code == 200
        assert result.json()["result"]["structuredContent"]["email"] == LOGIN
    assert provider.closed


def test_http_connect_rejects_csrf_and_never_leaks_secrets(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        result = http.post(
            "/connect",
            data={"ticket": "unknown", "csrf": "unknown", "login": LOGIN, "secret": "super-secret"},
            headers={"origin": settings.base_url},
        )
        assert result.status_code == 403
        assert "super-secret" not in result.text and LOGIN not in result.text
        for origin in ("null", "https://evil.example", None):
            headers = {"origin": origin} if origin is not None else {}
            result = http.post("/connect", headers=headers)
            assert result.status_code == 403
            assert "Ссылка подключения недействительна или устарела" in result.text
            assert "Проверьте email и пароль" not in result.text


def test_tool_errors_hide_provider_payloads(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        token = login_and_token(http, settings)
        provider.failure = CalendarProviderError(
            "app-password private CalDAV reply", error_code="CALDAV_UNAVAILABLE"
        )
        result = mcp_call(
            http,
            token,
            "tools/call",
            {
                "name": "mail_calendar_list_events",
                "arguments": {"start_date": "2026-09-30", "end_date": "2026-10-01"},
            },
        ).json()["result"]
        assert result["isError"]
        assert "app-password" not in json.dumps(result)
        assert "private CalDAV" not in json.dumps(result)


def test_free_time_keeps_seconds_and_ignores_declined_meetings():
    busy = event()
    busy["dtend"] = "2026-09-30T11:00:59+03:00"
    declined = event("Declined", "11:00", "19:00", attendees=[f"mailto:{LOGIN};PARTSTAT=DECLINED"])
    slots = find_free_slots(
        [busy, declined],
        start_date=date(2026, 9, 30),
        end_date=date(2026, 10, 1),
        tz=TZ,
        login=LOGIN,
    )
    assert slots == [
        (datetime(2026, 9, 30, 11, 0, 59, tzinfo=TZ), datetime(2026, 9, 30, 19, tzinfo=TZ))
    ]
    with pytest.raises(ValueError):
        find_free_slots(
            [{**busy, "dtstart": "invalid"}],
            start_date=date(2026, 9, 30),
            end_date=date(2026, 10, 1),
            tz=TZ,
            login=LOGIN,
        )


@pytest.mark.parametrize("prefix", ["", "/mail-calendar"])
def test_https_plugin_package_contains_only_manifest_connection_and_skill(tmp_path, prefix):
    output = tmp_path / "plugin"
    archive = package_plugin("https://calendar.example.com" + prefix, output)
    with ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            "plugin.json",
            "mcp.json",
            "skills/mail-calendar/SKILL.md",
        }
        connection = json.loads(bundle.read("mcp.json"))
        assert connection["mcpServers"]["mail-calendar"] == {
            "type": "streamable-http",
            "url": "https://calendar.example.com" + prefix + "/mcp",
        }
        assert json.loads(bundle.read("plugin.json"))["name"] == "mail-calendar"
        assert b"MCP_ENCRYPTION_KEY" not in b"".join(
            bundle.read(name) for name in bundle.namelist()
        )
    with pytest.raises(ValueError):
        package_plugin("http://127.0.0.1:8765", tmp_path / "local")


def test_all_tools_over_authenticated_http_and_previews_do_not_write(calendar_stack, monkeypatch):
    from satellite.mail_calendar_mcp import service as service_module

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 30, 9, tzinfo=TZ)

    monkeypatch.setattr(service_module, "datetime", FrozenDateTime)
    settings, accounts, provider, service, state, oauth = calendar_stack
    provider.events = [event(attendees=[f"mailto:{LOGIN};PARTSTAT=NEEDS-ACTION"])]
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        token = login_and_token(http, settings)

        def call(name, **arguments):
            reply = mcp_call(
                http, token, "tools/call", {"name": name, "arguments": arguments}
            ).json()["result"]
            assert not reply.get("isError"), reply
            return reply["structuredContent"]

        calendars = call("mail_calendar_list_calendars")["calendars"]
        assert len(calendars) == 2
        dates = {"start_date": "2026-09-30", "end_date": "2026-10-01"}
        assert call("mail_calendar_list_events", **dates)["total"] == 1
        invitations = call("mail_calendar_list_invitations", **dates)["events"]
        assert len(invitations) == 1
        assert call("mail_calendar_find_free_time", **dates)["slots"] == [
            {"start": "2026-09-30T11:00:00+03:00", "end": "2026-09-30T19:00:00+03:00"}
        ]
        create = {
            "title": "Sync",
            "start": "2026-09-30T15:00:00+03:00",
            "end": "2026-09-30T16:00:00+03:00",
            "calendar_id": calendars[1]["calendar_id"],
        }
        assert call("mail_calendar_create_event", **create)["status"] == "preview"
        respond = {"event_id": invitations[0]["event_id"], "response": "ACCEPTED"}
        assert call("mail_calendar_respond_to_invitation", **respond)["status"] == "preview"
        assert provider.writes == []
        assert call("mail_calendar_create_event", **create, confirm=True)["status"] == "created"
        assert provider.writes[0][1].primary_calendar_url == SECOND_CALENDAR
        assert (
            call("mail_calendar_respond_to_invitation", **respond, confirm=True)["status"]
            == "updated"
        )
        assert provider.writes[1][3] == "ACCEPTED"


def test_uncertain_creation_returns_error_and_is_not_retried(calendar_stack):
    settings, accounts, provider, service, state, oauth = calendar_stack
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        token = login_and_token(http, settings)
        provider.failure = CalendarProviderError(
            "private response", error_code="CREATE_UNCONFIRMED"
        )
        result = mcp_call(
            http,
            token,
            "tools/call",
            {
                "name": "mail_calendar_create_event",
                "arguments": {
                    "title": "Sync",
                    "start": "2026-09-30T15:00:00+03:00",
                    "end": "2026-09-30T16:00:00+03:00",
                    "confirm": True,
                },
            },
        ).json()["result"]
        assert result["isError"]
        assert "Mail не подтвердил" in result["content"][0]["text"]
        assert "private response" not in json.dumps(result)
        assert provider.create_attempts == 1


def test_https_default_port_and_host_case_match_oauth_resource(tmp_path):
    settings = McpSettings(
        "https://CALENDAR.example.com:443/",
        Fernet.generate_key().decode(),
        frozenset({LOGIN}),
        tmp_path,
    )
    assert settings.base_url == "https://calendar.example.com"
    assert settings.resource_url == "https://calendar.example.com/mcp"


def test_read_only_evaluation_answers(calendar_stack, monkeypatch):
    from satellite.calendar.events import event_occurs_on
    from satellite.mail_calendar_mcp import service as service_module

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 30, 9, tzinfo=TZ)

    monkeypatch.setattr(service_module, "datetime", FrozenDateTime)
    settings, accounts, provider, service, state, oauth = calendar_stack
    review = event(
        "Review", "10:30", "12:00", description="Join https://meet.google.com/abc-defg-hij"
    )
    provider.events = [
        review,
        dict(review),
        event("Planning", "12:00", "13:00"),
        event(
            "Consultation", "15:00", "16:00", attendees=[f"mailto:{LOGIN};PARTSTAT=NEEDS-ACTION"]
        ),
        event("Declined", "16:00", "18:00", attendees=[f"mailto:{LOGIN};PARTSTAT=DECLINED"]),
        event("Cancelled", "14:00", "15:00", status="CANCELLED"),
        {
            "uid": "Vacation",
            "url": CALENDAR + "vacation.ics",
            "calendar": "Work",
            "summary": "Vacation",
            "dtstart": "2026-10-01",
            "dtend": "2026-10-02",
        },
    ]

    def ranged_events(context, *, start_date, end_date, tz):
        days = [
            start_date + timedelta(days=offset) for offset in range((end_date - start_date).days)
        ]
        return [ev for ev in provider.events if any(event_occurs_on(ev, day, tz) for day in days)]

    monkeypatch.setattr(provider, "list_events", ranged_events)
    monkeypatch.setattr(provider, "list_events_for_invitations", ranged_events)
    with TestClient(http_stack(calendar_stack), base_url=settings.base_url) as http:
        token = login_and_token(http, settings)

        def read(name, **arguments):
            result = mcp_call(
                http, token, "tools/call", {"name": name, "arguments": arguments}
            ).json()["result"]
            assert not result.get("isError"), result
            return result["structuredContent"]

        profile = read("mail_calendar_get_profile")
        calendars = read("mail_calendar_list_calendars")["calendars"]
        dates = {"start_date": "2026-09-30", "end_date": "2026-10-01"}
        meetings = []
        offset = 0
        while True:
            page = read("mail_calendar_list_events", **dates, limit=2, offset=offset)
            meetings.extend(page["events"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        slots = read("mail_calendar_find_free_time", **dates)["slots"]
        invitations = read("mail_calendar_list_invitations", **dates)["events"]
        following = read(
            "mail_calendar_find_free_time", start_date="2026-10-01", end_date="2026-10-02"
        )["slots"]
        review = read("mail_calendar_list_events", **dates, query="Review")["events"][0]
        lengths = [
            (
                datetime.fromisoformat(slot["end"]) - datetime.fromisoformat(slot["start"])
            ).total_seconds()
            / 60
            for slot in slots
        ]
        long = read("mail_calendar_find_free_time", **dates, duration_minutes=90)["slots"]
        answers = [
            next(item["name"] for item in calendars if item["primary"]),
            profile["timezone"],
            datetime.fromisoformat(long[0]["start"]).strftime("%H:%M"),
            str(int(max(lengths))),
            str(sum(ev["response"] != "DECLINED" for ev in meetings)),
            invitations[0]["title"],
            datetime.fromisoformat(slots[0]["start"]).strftime("%H:%M"),
            str(bool(following)),
            review["conference_url"],
            str(int(sum(lengths))),
        ]
        fixture = ET.parse(Path(__file__).parent / "fixtures" / "mail_calendar_evaluation.xml")
        expected = [pair.findtext("answer") for pair in fixture.getroot().findall("qa_pair")]
        assert len(expected) == 10 and answers == expected
        assert provider.writes == []
