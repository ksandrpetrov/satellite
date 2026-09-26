"""Real HTTP CalDAV → provider → user service → product output, without live accounts."""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pytest
from caldav import Calendar, DAVClient
from cryptography.fernet import Fernet

from satellite.analytics.service import build_week_analytics
from satellite.calendar.caldav_client import CalDAVService, CalendarHandle
from satellite.calendar.caldav_shared import _DiscoveryResult
from satellite.calendar.operation_log import CalendarOperationLog
from satellite.calendar.period_stats import build_analytics_report
from satellite.calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarProviderError,
)
from satellite.calendar.providers.mailru import MailruCalendarProvider
from satellite.calendar.user_calendar_service import UserCalendarService
from satellite.config import PlanConfig
from satellite.meeting_exclusions import MeetingExclusionService
from satellite.plan_service import PlanBuilder
from satellite.scheduler import DigestScheduler
from satellite.security.token_vault import ProviderCredentials, TokenVault
from satellite.subscriptions import SubscriptionStore
from satellite.web.calendar_api_service import CalendarApiService

from .conftest import make_fake_telegram, make_user_store

DAY = date(2026, 9, 21)
LOGIN = "audit@example.test"
USER_ID = 501


def ics(uid, start="100000", end="110000", *, partstat="ACCEPTED", extra=""):
    attendee = f"ATTENDEE;PARTSTAT={partstat}:mailto:{LOGIN}\r\n" if partstat else ""
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Audit//EN\r\nBEGIN:VEVENT\r\n"
        f"UID:{uid}\r\nSUMMARY:{uid}\r\nDTSTAMP:20260920T000000Z\r\n"
        f"DTSTART:20260921T{start}Z\r\nDTEND:20260921T{end}Z\r\n"
        f"{attendee}{extra}END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


@pytest.fixture
def product(tmp_path, monkeypatch, request):
    state = SimpleNamespace(
        calendars={"/one/": {}, "/two/": {}},
        failed=set(),
        calls=[],
        write_mode="ok",
        write_versions=[],
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body, content_type):
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if status == 200 and content_type.startswith("text/calendar"):
                self.send_header("ETag", '"1"')
            self.end_headers()
            self.wfile.write(payload)

        def do_REPORT(self):
            query = ElementTree.fromstring(self.rfile.read(int(self.headers["Content-Length"])))
            state.calls.append(("REPORT", self.path))
            if self.path in state.failed:
                self.reply(503, "Unavailable", "text/plain")
                return
            requested = {urlsplit(node.text).path for node in query.findall("{DAV:}href")}
            entries = []
            for uid, payload in state.calendars[self.path].items():
                href = self.path + uid + ".ics"
                if requested and href not in requested:
                    continue
                entries.append(
                    f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>"
                    f"<c:calendar-data>{escape(payload)}</c:calendar-data>"
                    '<d:getetag>"1"</d:getetag></d:prop>'
                    "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
                )
            body = (
                '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                + "".join(entries)
                + "</d:multistatus>"
            )
            self.reply(207, body, "application/xml; charset=utf-8")

        def do_GET(self):
            state.calls.append(("GET", self.path))
            parent, _, filename = unquote(self.path).rpartition("/")
            payload = state.calendars.get(parent + "/", {}).get(filename.removesuffix(".ics"))
            self.reply(200 if payload else 404, payload or "", "text/calendar; charset=utf-8")

        def do_PUT(self):
            payload = self.rfile.read(int(self.headers["Content-Length"])).decode()
            state.calls.append(("PUT", self.path))
            state.write_versions.append(self.headers.get("If-Match"))
            parent, _, filename = unquote(self.path).rpartition("/")
            if state.write_mode == "conflict":
                self.reply(412, "Changed", "text/plain")
                return
            if parent == "/one" and state.write_mode == "forbidden":
                self.reply(403, "Read only", "text/plain")
                return
            failing = parent == "/one" and state.write_mode.startswith("500_")
            if not failing or state.write_mode == "500_committed":
                state.calendars[parent + "/"][filename.removesuffix(".ics")] = payload
            self.reply(500 if failing else 201, "", "text/plain")

        def do_DELETE(self):
            state.calls.append(("DELETE", self.path))
            parent, _, filename = unquote(self.path).rpartition("/")
            state.calendars[parent + "/"].pop(filename.removesuffix(".ics"), None)
            self.reply(204, "", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop_server():
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    request.addfinalizer(stop_server)
    base = f"http://127.0.0.1:{server.server_port}"
    client = DAVClient(url=base, username=LOGIN, password="test", timeout=2)
    handles = [
        CalendarHandle(path, Calendar(client=client, url=base + path), base + path)
        for path in state.calendars
    ]
    dav = CalDAVService(caldav_url=base, login=LOGIN, app_password="test")
    request.addfinalizer(dav.close)
    discovery = _DiscoveryResult(base, handles, time.monotonic(), LOGIN, client)
    dav._cache = discovery
    monkeypatch.setattr(dav, "_ensure_discovery", lambda: discovery)
    provider = MailruCalendarProvider()
    monkeypatch.setattr(provider, "_service", lambda _credentials: dav)
    monkeypatch.setattr(provider, "_service_for_invitations", lambda _credentials: dav)
    users = make_user_store(tmp_path, approved_with_calendar=[USER_ID])
    vault = TokenVault(Fernet.generate_key().decode())
    users.set_calendar_connection(
        USER_ID,
        provider="mailru",
        encrypted_credentials=vault.encrypt(ProviderCredentials(LOGIN, "test")),
        primary_calendar_url=base + "/one/",
    )
    users.set_enabled_calendar_urls(USER_ID, calendar_urls=tuple(handle.url for handle in handles))
    calendar = UserCalendarService(
        users=users,
        token_vault=vault,
        operation_log=CalendarOperationLog(tmp_path / "audit.jsonl"),
    )
    calendar._provider_cache["mailru"] = provider
    request.addfinalizer(calendar.close)
    builder = PlanBuilder(calendar_service=calendar, plan_config=PlanConfig(), tz=UTC)
    yield SimpleNamespace(
        state=state,
        calendar=calendar,
        builder=builder,
        users=users,
        vault=vault,
        tmp_path=tmp_path,
        base=base,
    )


@pytest.mark.parametrize(
    "partstat,marker",
    [
        ("NEEDS-ACTION", "⚠️"),
        ("DELEGATED", "⚠️"),
        ("TENTATIVE", "⚖️"),
    ],
)
def test_unconfirmed_event_stays_visible_but_does_not_change_reports(product, partstat, marker):
    product.state.calendars["/one/"]["Invitation"] = ics("Invitation", partstat=partstat)
    bundle = product.builder.build_plan_bundle(
        telegram_user_id=USER_ID,
        target_date=DAY,
        reference_date=DAY,
    )
    assert "Invitation" in bundle.fallback_html and "Invitation" in bundle.rich_html
    assert marker in bundle.fallback_html and marker in bundle.rich_html
    assert "Занято: 0 мин" in bundle.fallback_html
    assert "Свободно: 8 ч" in bundle.fallback_html
    assert "0 мин" in bundle.rich_html and "8 ч" in bundle.rich_html
    events = product.calendar.list_events_for_analytics(
        USER_ID, start_date=DAY, end_date=DAY, tz=UTC
    )
    report = build_analytics_report(events, DAY, tz=UTC, login=LOGIN)
    assert report.current.total_meetings == report.current.total_busy == 0
    assert report.current.total_free == 2400
    assert ("REPORT", "/one/") in product.state.calls


def test_full_plan_and_analytics_agree_on_mixed_real_ics(product):
    primary = product.state.calendars["/one/"]
    primary.update(
        {
            "Accepted": ics("Accepted"),
            "Overlap": ics("Overlap", "103000", "120000"),
            "Pending": ics("Pending", "090000", "200000", partstat="NEEDS-ACTION"),
            "Tentative": ics("Tentative", "140000", "150000", partstat="TENTATIVE"),
            "Own": ics("Own", "160000", "163000", partstat=None),
            "Declined": ics("Declined", "170000", "180000", partstat="DECLINED"),
            "Cancelled": ics("Cancelled", "170000", "180000", extra="STATUS:CANCELLED\r\n"),
        }
    )
    product.state.calendars["/two/"]["Accepted-copy"] = primary["Accepted"]
    bundle = product.builder.build_plan_bundle(
        telegram_user_id=USER_ID,
        target_date=DAY,
        reference_date=DAY,
    )
    assert "Занято: 2 ч 30 мин" in bundle.fallback_html
    assert "Свободно: 5 ч 30 мин" in bundle.fallback_html
    for rendered in (bundle.rich_html, bundle.fallback_html):
        assert rendered.count("Accepted") == 1
        assert "Declined" not in rendered and "Cancelled" not in rendered
        assert "Pending" in rendered and "Tentative" in rendered
    events = product.calendar.list_events_for_analytics(
        USER_ID, start_date=DAY, end_date=DAY, tz=UTC
    )
    report = build_analytics_report(events, DAY, tz=UTC, login=LOGIN)
    assert report.current.total_busy == 150
    assert report.current.total_free == 2250
    assert report.current.total_meetings == 3
    assert report.current.total_overlaps == 1
    png, caption, rich_caption = build_week_analytics(
        telegram_user_id=USER_ID,
        reference_date=DAY,
        tz=UTC,
        calendar_service=product.calendar,
        users=product.users,
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert "2 ч 30 мин" in caption and "2 ч 30 мин" in rich_caption


@pytest.mark.parametrize("kind", ["daily", "pending"])
def test_failed_calendar_is_not_successful_empty_digest_and_can_retry(product, kind):
    product.state.failed.add("/two/")
    subscriptions = SubscriptionStore(product.tmp_path / "subscriptions.json")
    subscriptions.update_settings(
        USER_ID,
        "auditor",
        digest_enabled=kind == "daily",
        digest_time="08:00",
        digest_timezone="UTC",
        pending_digest_enabled=kind == "pending",
        pending_digest_time="08:00",
        pending_digest_timezone="UTC",
    )
    telegram = make_fake_telegram()
    exclusions = MeetingExclusionService(users=product.users, token_vault=product.vault)
    scheduler = DigestScheduler(
        plan_config=PlanConfig(),
        tz=UTC,
        subscriptions=subscriptions,
        users=product.users,
        calendar_service=product.calendar,
        meeting_exclusions=exclusions,
        telegram=telegram,
        now_fn=lambda zone: datetime(2026, 9, 21, 9, tzinfo=UTC).astimezone(zone),
    )
    marker = "last_digest_sent_date" if kind == "daily" else "last_pending_digest_sent_date"
    try:
        assert scheduler.tick() == 0
        assert getattr(subscriptions.get(USER_ID), marker) is None
        telegram.send_message.assert_not_called()
        telegram.send_rich_message.assert_not_called()
        product.state.failed.clear()
        assert scheduler.tick() == (1 if kind == "daily" else 0)
        assert getattr(subscriptions.get(USER_ID), marker) == DAY.isoformat()
        assert scheduler.tick() == 0
    finally:
        scheduler.stop()


def test_partial_calendar_propagates_to_plan_and_web_as_error(product):
    product.state.failed.add("/two/")
    with pytest.raises(CalendarProviderError):
        product.builder.build_plan_bundle(
            telegram_user_id=USER_ID, target_date=DAY, reference_date=DAY
        )
    api = CalendarApiService(calendar=product.calendar, users=product.users, tz=UTC)
    result = api.list_events(USER_ID, {"from": DAY.isoformat(), "to": DAY.isoformat()})
    assert result.status == 502
    assert result.payload["error"] == "CALDAV_UNAVAILABLE"
    assert "events" not in result.payload


def create_payload():
    return CalendarEventPayload(
        title="Create once",
        start=datetime(2026, 9, 21, 10, tzinfo=UTC),
        end=datetime(2026, 9, 21, 11, tzinfo=UTC),
    )


def test_lost_create_response_is_reconciled_without_cross_calendar_duplicate(product):
    product.state.write_mode = "500_committed"
    ref = product.calendar.create_event(USER_ID, create_payload(), tz=UTC)
    assert sum(len(events) for events in product.state.calendars.values()) == 1
    assert "/one/" in ref.url
    assert not product.state.calendars["/two/"]


def test_unconfirmed_creation_never_falls_back_to_another_calendar(product):
    product.state.write_mode = "500_uncommitted"
    with pytest.raises(CalendarProviderError) as raised:
        product.calendar.create_event(USER_ID, create_payload(), tz=UTC)
    assert raised.value.error_code == "CREATE_UNCONFIRMED"
    assert not product.state.calendars["/two/"]
    assert not any(
        method == "PUT" and path.startswith("/two/") for method, path in product.state.calls
    )


def test_readonly_fallback_and_delete_use_real_caldav_http(product):
    product.state.write_mode = "forbidden"
    ref = product.calendar.create_event(USER_ID, create_payload(), tz=UTC)
    assert "/two/" in ref.url
    assert sum(len(events) for events in product.state.calendars.values()) == 1
    product.calendar.delete_event(USER_ID, ref)
    assert not any(product.state.calendars.values())


@pytest.mark.parametrize("mode", ["ok", "500_committed"])
@pytest.mark.parametrize("partstat,busy", [("ACCEPTED", 60), ("TENTATIVE", 0), ("DECLINED", 0)])
def test_invitation_response_is_verified_idempotent_and_changes_metrics(
    product, mode, partstat, busy
):
    product.state.calendars["/one/"]["Invitation"] = ics("Invitation", partstat="NEEDS-ACTION")
    product.state.write_mode = mode
    ref = CalendarEventRef("Invitation", product.base + "/one/Invitation.ics")
    product.calendar.set_attendee_partstat(USER_ID, ref, partstat)
    assert product.state.write_versions == ['"1"']
    assert f"PARTSTAT={partstat}" in product.state.calendars["/one/"]["Invitation"]
    product.calendar.set_attendee_partstat(USER_ID, ref, partstat)
    assert product.state.write_versions == ['"1"']  # Same answer does not write twice.
    events = product.calendar.list_events_for_analytics(
        USER_ID, start_date=DAY, end_date=DAY, tz=UTC
    )
    report = build_analytics_report(events, DAY, tz=UTC, login=LOGIN)
    assert report.current.total_busy == busy
    assert report.current.total_free == 2400 - busy
    assert report.current.total_meetings == (1 if partstat == "ACCEPTED" else 0)


def test_repeated_partstat_version_conflict_does_not_overwrite_calendar(product):
    original = ics("Invitation", partstat="NEEDS-ACTION")
    product.state.calendars["/one/"]["Invitation"] = original
    product.state.write_mode = "conflict"
    ref = CalendarEventRef("Invitation", product.base + "/one/Invitation.ics")
    with pytest.raises(CalendarProviderError) as raised:
        product.calendar.set_attendee_partstat(USER_ID, ref, "ACCEPTED")
    assert raised.value.error_code == "PARTSTAT_UPDATE_FAILED"
    assert product.state.calendars["/one/"]["Invitation"] == original
    assert product.state.write_versions == ['"1"', '"1"']


def test_web_api_does_not_claim_success_after_unconfirmed_create(product):
    product.state.write_mode = "500_uncommitted"
    api = CalendarApiService(calendar=product.calendar, users=product.users, tz=UTC)
    result = api.create_event(
        USER_ID,
        {
            "title": "Unconfirmed",
            "start": "2026-09-21T10:00:00Z",
            "duration_minutes": 60,
        },
    )
    assert result.status == 502
    assert result.payload["error"] == "CREATE_UNCONFIRMED"
    assert "Проверь календарь перед повтором" in result.payload["message"]
    assert not any(product.state.calendars.values())
