"""Browser regressions: date boundaries, durable feedback, auth and isolated CRUD."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect


def open_create(page, app, title="Browser meeting"):
    page.goto(app.url, wait_until="networkidle")
    page.locator('[data-tab="create"]').click()
    page.locator("#evTitle").fill(title)
    page.locator(".wizard-step.active .create-next").click()


def confirm_form(page, *, date=None, duration="60"):
    if date:
        page.locator("#evDate").fill(date)
    page.locator(".wizard-step.active .create-next").click()
    page.locator("#evStart").fill("10:30")
    page.locator(".wizard-step.active .create-next").click()
    page.locator("#evDuration").fill(duration)
    page.locator(".wizard-step.active .create-next").click()


@pytest.mark.parametrize(
    "timezone,instant,today,tomorrow",
    [
        ("Europe/Moscow", "2026-09-25T21:05:00+00:00", "2026-09-26", "2026-09-27"),
        ("Pacific/Kiritimati", "2026-12-31T10:05:00+00:00", "2027-01-01", "2027-01-02"),
        ("America/New_York", "2026-03-08T06:30:00+00:00", "2026-03-08", "2026-03-09"),
        ("UTC", "2026-01-31T23:59:00+00:00", "2026-01-31", "2026-02-01"),
    ],
)
def test_local_today_tomorrow_and_submitted_date(
    app, page_factory, timezone, instant, today, tomorrow
):
    app.connect()
    page = page_factory(timezone=timezone, instant=instant)
    open_create(page, app)
    expect(page.locator("#evDate")).to_have_value(today)
    page.locator('[data-date-preset="tomorrow"]').click()
    expect(page.locator("#evDate")).to_have_value(tomorrow)
    page.locator('[data-date-preset="today"]').click()
    expect(page.locator("#evDate")).to_have_value(today)
    confirm_form(page)
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_be_visible()
    expect(page.locator("#createStatus")).to_contain_text("Событие создано")
    expect(page.locator("#evTitle")).to_be_visible()
    expect(page.locator("#evTitle")).to_have_value("")
    assert len(app.provider.created) == 1
    assert app.provider.created[0].start.date().isoformat() == today
    submitted_local = app.provider.created[0].start.astimezone(ZoneInfo(timezone))
    assert (submitted_local.hour, submitted_local.minute) == (10, 30)
    assert submitted_local.date().isoformat() == today
    assert app.provider.created[0].end - app.provider.created[0].start == timedelta(hours=1)


def test_nonexistent_dst_time_is_not_silently_shifted(app, page_factory):
    app.connect()
    page = page_factory(timezone="America/New_York", instant="2026-03-08T06:00:00+00:00")
    open_create(page, app)
    page.locator(".wizard-step.active .create-next").click()
    page.locator("#evStart").fill("02:30")
    page.locator(".wizard-step.active .create-next").click()
    expect(page.locator("#createStatus")).to_contain_text("перевода часов")
    expect(page.locator("#evStart")).to_be_visible()
    assert not app.provider.created


def test_fractional_duration_is_not_silently_truncated(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app)
    confirm_form(page, duration="1.9")
    expect(page.locator("#evDuration")).to_be_visible()
    expect(page.locator("#createStatus")).to_contain_text("длительность в минутах")
    assert not app.provider.created


def test_failed_calendar_load_is_not_shown_as_empty_list(app, page_factory):
    app.connect()
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    page.route(
        "**/api/calendar/events*",
        lambda route: route.fulfill(
            status=502,
            content_type="application/json",
            body='{"error":"CALDAV_UNAVAILABLE","message":"Не удалось загрузить календарь"}',
        ),
    )
    page.locator('[data-tab="events"]').click()
    expect(page.locator("#eventsStatus")).to_contain_text("Не удалось загрузить календарь")
    expect(page.locator("#eventsList")).not_to_contain_text("встреч нет")
    page.unroute("**/api/calendar/events*")
    page.locator("#refreshBtn").click()
    expect(page.locator("#eventsList")).to_contain_text("встреч нет")


def test_connect_create_delete_disconnect_on_mobile(app, page_factory):
    page = page_factory(mobile=True)
    page.goto(app.url, wait_until="networkidle")
    page.locator("#login").fill("test@example.test")
    page.locator("#token").fill("test-app-password")
    page.locator("#connectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("Календарь подключён")
    expect(page.locator("#token")).to_have_value("")
    record = app.users.get(app.user_id)
    assert record.has_calendar
    assert app.vault.decrypt(record.encrypted_credentials).secret == "test-app-password"
    assert "test-app-password" not in (app.directory / "users.json").read_text()
    title = "<Release & demo> " + "LongTitle" * 30
    open_create(page, app, title)
    today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    confirm_form(page, date=today)
    expect(page.locator("#createConfirmBox .ev-title")).to_have_text(title)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path="test-results/mobile-confirm.png", full_page=True)
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_contain_text("Событие создано")
    page.locator('[data-tab="events"]').click()
    expect(page.locator(".event-line")).to_contain_text(title)
    assert page.locator(".event-line script, .event-line img").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path="test-results/mobile-events.png", full_page=True)
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Удалить", exact=True).click()
    expect(page.locator("#eventsList")).to_contain_text("встреч нет")
    expect(page.locator("#eventsStatus")).to_be_visible()
    expect(page.locator("#eventsStatus")).to_contain_text("Событие удалено")
    assert len(app.provider.deleted) == 1
    assert not app.provider.events
    page.locator('[data-tab="connection"]').click()
    page.locator("#disconnectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("Календарь отключён")
    assert not app.users.get(app.user_id).has_calendar


def test_expired_auth_does_not_create_event_and_retains_draft(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app, "Retain draft")
    confirm_form(page)
    app.clock[0] += 901
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_be_visible()
    expect(page.locator("#createStatus")).not_to_contain_text("Событие создано")
    expect(page.locator("#createConfirmBox")).to_contain_text("Retain draft")
    expect(page.locator("#createConfirmBtn")).to_be_enabled()
    assert not app.provider.created


def test_network_failure_then_retry_preserves_form(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app)
    confirm_form(page)
    page.route("**/api/calendar/events*", lambda route: route.abort("connectionfailed"))
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_be_visible()
    expect(page.locator("#createConfirmBtn")).to_be_enabled()
    assert not app.provider.created
    page.unroute("**/api/calendar/events*")
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_contain_text("Событие создано")
    assert len(app.provider.created) == 1


def test_write_denied_does_not_reset_form(app, page_factory):
    app.connect()
    app.provider.create_error = True
    page = page_factory()
    open_create(page, app)
    confirm_form(page)
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_contain_text("Проверьте права записи")
    expect(page.locator("#createConfirmBox")).to_contain_text("Browser meeting")
    expect(page.locator("#createConfirmBtn")).to_be_enabled()
    assert not app.provider.created


def test_missing_auth_and_connect_validation(app, page_factory):
    page = page_factory()
    page.goto(app.base + "/connect", wait_until="networkidle")
    page.locator("#connectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("Укажите email")
    page.locator("#login").fill("test@example.test")
    page.locator("#token").fill("test-app-password")
    page.locator("#connectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("Откройте окно снова из бота")
    assert not app.users.get(app.user_id).has_calendar
