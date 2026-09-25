"""Real WebApp HTTP + browser + isolated stores; only remote provider is replaced."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright

from satellite.calendar.operation_log import CalendarOperationLog
from satellite.calendar.providers.base import (
    CalendarConnectionStatus,
    CalendarEventRef,
    CalendarProviderError,
)
from satellite.calendar.user_calendar_service import UserCalendarService
from satellite.security.token_vault import ProviderCredentials, TokenVault
from satellite.users import USER_STATUS_APPROVED, UserStore
from satellite.web.connect_token import ConnectTokenStore
from satellite.web.server import WebAppServer, WebAppServerConfig

USER_ID = 987654321


class IsolatedProvider:
    provider_id = "mailru"

    def __init__(self):
        self.events = []
        self.created = []
        self.deleted = []
        self.create_error = False

    def validate_credentials(self, credentials, *, caldav_url=None):
        return credentials.secret == "test-app-password", "https://calendar.example.test/cal/", None

    def get_connection_status(self, context):
        return CalendarConnectionStatus(True, "mailru", "connected")

    def list_events(self, context, **kwargs):
        return list(self.events)

    def create_event(self, context, payload, **kwargs):
        if self.create_error:
            raise CalendarProviderError("No write permission", error_code="CREATE_FAILED")
        self.created.append(payload)
        ref = CalendarEventRef(
            f"test-{len(self.created)}",
            f"https://calendar.example.test/cal/{len(self.created)}.ics",
        )
        self.events.append(
            {
                "uid": ref.uid,
                "url": ref.url,
                "summary": payload.title,
                "dtstart": payload.start.isoformat(),
                "dtend": payload.end.isoformat(),
                "attendees": [],
            }
        )
        return ref

    def delete_event(self, context, ref):
        self.deleted.append(ref)
        self.events = [event for event in self.events if event["uid"] != ref.uid]

    def close(self):
        pass


@pytest.fixture
def app(tmp_path):
    users = UserStore(tmp_path / "users.json")
    users.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=USER_ID,
        username="browser_test",
        display_name="Browser Test",
        default_status=USER_STATUS_APPROVED,
    )
    vault = TokenVault(Fernet.generate_key().decode())
    calendar = UserCalendarService(
        users=users, token_vault=vault, operation_log=CalendarOperationLog(tmp_path / "audit.jsonl")
    )
    provider = IsolatedProvider()
    calendar._provider_cache["mailru"] = provider
    clock = [1000.0]
    tokens = ConnectTokenStore(now_fn=lambda: clock[0])
    token = tokens.issue(USER_ID)
    server = WebAppServer(
        config=WebAppServerConfig(
            host="127.0.0.1", port=0, bot_token="isolated-test-token", connect_tokens=tokens
        ),
        calendar_service=calendar,
        users=users,
    )
    server.start()
    base = f"http://127.0.0.1:{server._httpd.server_port}"

    def connect():
        calendar.connect(
            USER_ID,
            provider_id="mailru",
            credentials=ProviderCredentials("test@example.test", "test-app-password"),
        )

    try:
        yield SimpleNamespace(
            url=base + "/connect/" + token,
            base=base,
            users=users,
            calendar=calendar,
            provider=provider,
            clock=clock,
            connect=connect,
            user_id=USER_ID,
            directory=tmp_path,
            vault=vault,
        )
    finally:
        server.stop()
        calendar.close()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page_factory(browser, request):
    contexts = []

    def create(*, timezone="Europe/Moscow", mobile=False, instant=None):
        context = browser.new_context(
            timezone_id=timezone,
            viewport={"width": 390 if mobile else 1100, "height": 844},
            is_mobile=mobile,
            has_touch=mobile,
        )
        context.route("https://telegram.org/**", lambda route: route.fulfill(status=200, body=""))
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        if instant is not None:
            page.clock.set_fixed_time(datetime.fromisoformat(instant))
        Path("test-results").mkdir(exist_ok=True)
        contexts.append(context)
        return page

    yield create
    for index, context in enumerate(contexts):
        directory = Path("test-results") / request.node.name / str(index)
        directory.mkdir(parents=True, exist_ok=True)
        for page in context.pages:
            page.screenshot(path=str(directory / "screen.png"), full_page=True)
        context.tracing.stop(path=str(directory / "trace.zip"))
        context.close()
