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


def test_draft_survives_tab_switch_and_repeated_tab_click(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app, "Keep this meeting")
    page.locator("#evDate").fill("2027-02-14")
    page.locator('[data-tab="events"]').click()
    page.locator('[data-tab="create"]').click()
    expect(page.locator("#evDate")).to_be_visible()
    expect(page.locator("#evDate")).to_have_value("2027-02-14")
    page.locator('[data-tab="create"]').click()
    confirm_form(page)
    expect(page.locator("#createConfirmBox")).to_contain_text("Keep this meeting")


def test_create_keyboard_labels_focus_and_tabs(app, page_factory):
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    tab = page.get_by_role("tab", name="Подключение", exact=True)
    tab.focus()
    page.keyboard.press("End")
    expect(page.get_by_role("tab", name="Создать", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    field = page.get_by_label("Как назвать событие?", exact=False)
    field.fill("Accessible meeting")
    page.locator(".wizard-step.active .create-next").click()
    expect(page.get_by_label("На какую дату?", exact=False)).to_be_focused()
    confirm_form(page)
    expect(page.locator("#createConfirmBox")).to_be_focused()
    page.locator("#createCancelBtn").click()
    expect(field).to_be_focused()
    expect(field).to_have_value("")


@pytest.mark.parametrize(
    "timezone,date,start,duration,end_fragment",
    [
        ("Europe/Moscow", "2026-12-31", "23:30", "60", "01.01.2027 00:30"),
        ("America/New_York", "2026-03-08", "01:30", "120", "04:30"),
        ("America/New_York", "2026-11-01", "00:30", "180", "02:30"),
        ("America/New_York", "2026-11-01", "01:30", "30", "01:00"),
    ],
)
def test_confirmation_matches_actual_end(
    app, page_factory, timezone, date, start, duration, end_fragment
):
    app.connect()
    page = page_factory(timezone=timezone)
    open_create(page, app)
    page.locator("#evDate").fill(date)
    page.locator(".wizard-step.active .create-next").click()
    page.locator("#evStart").fill(start)
    page.locator(".wizard-step.active .create-next").click()
    page.locator("#evDuration").fill(duration)
    page.locator(".wizard-step.active .create-next").click()
    expect(page.locator("#createConfirmBox")).to_contain_text(end_fragment)
    if date == "2026-11-01":
        expect(page.locator("#createConfirmBox")).to_contain_text("UTC-04:00")
        expect(page.locator("#createConfirmBox")).to_contain_text("UTC-05:00")
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_contain_text("Событие создано")
    payload = app.provider.created[0]
    assert (payload.end - payload.start).total_seconds() == int(duration) * 60
    assert (
        payload.end.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M").endswith(end_fragment)
    )


def test_invalid_success_response_does_not_claim_creation(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app)
    confirm_form(page)
    page.route(
        "**/api/calendar/events*",
        lambda route: route.fulfill(status=200, body="<html>proxy</html>"),
    )
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_contain_text("Проверьте календарь")
    expect(page.locator("#createConfirmBox")).to_contain_text("Browser meeting")
    assert not app.provider.created


def test_slow_create_cannot_be_cancelled_or_submitted_twice(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app)
    confirm_form(page)
    requests = []
    page.route("**/api/calendar/events*", lambda route: requests.append(route))
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createCancelBtn")).to_be_disabled()
    expect(page.locator("#createConfirmBtn")).to_be_disabled()
    expect(page.locator("#createStatus")).to_contain_text("Создаём")
    page.locator('[data-tab="connection"]').click()
    page.locator('[data-tab="create"]').click()
    expect(page.locator("#createConfirmBox")).to_contain_text("Browser meeting")
    assert len(requests) == 1
    requests[0].continue_()
    expect(page.locator("#createStatus")).to_contain_text("Событие создано")
    assert len(app.provider.created) == 1


@pytest.mark.parametrize("width", [320, 390, 430])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_large_text_layout_and_touch_targets(app, page_factory, width, theme):
    page = page_factory(mobile=True, width=width, theme=theme)
    page.goto(app.url, wait_until="networkidle")
    page.add_style_tag(content="html { font-size: 30px !important; }")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for button in page.get_by_role("tab").all():
        assert button.bounding_box()["height"] >= 44
    page.locator('[data-tab="create"]').click()
    page.locator("#evTitle").fill("ДлинноеНазвание" * 30)
    page.locator(".wizard-step.active .create-next").click()
    confirm_form(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(
        path=f"test-results/layout-{page.context.browser.browser_type.name}-{width}-{theme}.png",
        full_page=True,
    )


def test_stale_events_response_cannot_overwrite_newer_list(app, page_factory):
    app.connect()
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    held = []
    page.route("**/api/calendar/events*", lambda route: held.append(route))
    page.locator('[data-tab="events"]').click()
    page.wait_for_function("document.querySelector('#eventsList .spinner') !== null")
    page.locator("#refreshBtn").click()
    # Route callbacks are dispatched during Playwright waits; neither response is released yet.
    expect(page.locator("#eventsList")).to_contain_text("собирает")
    assert len(held) == 2
    held[1].fulfill(
        json={
            "groups": [{"header": "Сегодня", "events": [{"title": "New result"}]}],
            "empty": False,
        }
    )
    expect(page.locator("#eventsList")).to_contain_text("New result")
    held[0].fulfill(json={"groups": [], "empty": True})
    page.wait_for_load_state("networkidle")
    expect(page.locator("#eventsList")).to_contain_text("New result")


def test_slow_write_times_out_without_claiming_failure_or_losing_draft(app, page_factory):
    app.connect()
    page = page_factory()
    open_create(page, app, "Uncertain result")
    confirm_form(page)
    page.clock.install()
    held = []
    page.route("**/api/calendar/events*", lambda route: held.append(route))
    page.locator("#createConfirmBtn").click()
    expect(page.locator("#createStatus")).to_contain_text("Создаём")
    page.clock.fast_forward(31000)
    expect(page.locator("#createStatus")).to_contain_text("Проверьте календарь")
    expect(page.locator("#createConfirmBtn")).to_be_enabled()
    expect(page.locator("#createConfirmBox")).to_contain_text("Uncertain result")
    assert len(held) == 1
    held[0].abort()


def test_keyboard_validation_announces_error_and_focuses_field(app, page_factory):
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    page.locator('[data-tab="create"]').click()
    page.locator(".wizard-step.active .create-next").click()
    expect(page.locator("#evTitle")).to_be_focused()
    expect(page.locator("#evTitle")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#evTitle")).to_have_attribute("aria-describedby", "createStatus")
    expect(page.locator("#createStatus")).to_have_attribute("aria-live", "polite")
    page.locator("#evTitle").fill("Corrected")
    expect(page.locator("#evTitle")).not_to_have_attribute("aria-invalid", "true")


def test_invalid_list_payload_is_not_empty_calendar(app, page_factory):
    app.connect()
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    page.route("**/api/calendar/events*", lambda route: route.fulfill(json={}))
    page.locator('[data-tab="events"]').click()
    expect(page.locator("#eventsStatus")).to_be_visible()
    expect(page.locator("#eventsList")).not_to_contain_text("встреч нет")


def test_disconnect_clears_connected_hint(app, page_factory):
    app.connect()
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    expect(page.locator("#userHint")).to_contain_text("Календарь подключён")
    page.locator("#disconnectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("Календарь отключён")
    expect(page.locator("#userHint")).not_to_contain_text("Календарь подключён")


def test_connection_actions_cannot_race_and_recover_after_error(app, page_factory):
    page = page_factory()
    page.goto(app.url, wait_until="networkidle")
    page.locator("#login").fill("test@example.test")
    page.locator("#token").fill("test-app-password")
    held = []
    page.route("**/api/calendar/connect*", lambda route: held.append(route))
    page.locator("#connectBtn").click()
    expect(page.locator("#disconnectBtn")).to_be_disabled()
    expect(page.locator("#checkBtn")).to_be_disabled()
    expect(page.locator("#login")).to_be_disabled()
    assert len(held) == 1
    held[0].fulfill(
        status=503, json={"error": "storage_unavailable", "message": "Попробуйте позже."}
    )
    expect(page.locator("#connectStatus")).to_contain_text("Попробуйте позже")
    expect(page.locator("#disconnectBtn")).to_be_enabled()
    expect(page.locator("#login")).to_have_value("test@example.test")
    expect(page.locator("#token")).to_have_value("test-app-password")
    assert not app.users.get(app.user_id).has_calendar


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_fallback_theme_text_contrast(app, page_factory, theme):
    page = page_factory(theme=theme)
    page.goto(app.url, wait_until="networkidle")
    colors = page.evaluate("""() => {
      const style = (selector) => getComputedStyle(document.querySelector(selector));
      return [
        [style('h1').color, style('html').backgroundColor],
        [style('.hint').color, style('html').backgroundColor],
        [style('#connectBtn').color, style('#connectBtn').backgroundColor],
        [style('#disconnectBtn').color, style('html').backgroundColor],
      ];
    }""")

    def luminance(rgb):
        import re

        values = [int(value) / 255 for value in re.findall(r"\d+", rgb)[:3]]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(
            value * weight for value, weight in zip(linear, [0.2126, 0.7152, 0.0722], strict=True)
        )

    for foreground, background in colors:
        bright, dark = sorted([luminance(foreground), luminance(background)], reverse=True)
        assert (bright + 0.05) / (dark + 0.05) >= 4.5, (foreground, background)


def test_reduced_motion_stops_spinner(app, page_factory):
    page = page_factory()
    page.emulate_media(reduced_motion="reduce")
    page.goto(app.url, wait_until="networkidle")
    held = []
    page.route("**/api/calendar/events*", lambda route: held.append(route))
    page.locator('[data-tab="events"]').click()
    expect(page.locator(".spinner")).to_have_css("animation-name", "none")
    held[0].fulfill(json={"groups": [], "empty": True})


def test_disconnect_in_second_window_cancels_pending_connect(app, page_factory, monkeypatch):
    from threading import Event

    entered, release = Event(), Event()
    original = app.provider.validate_credentials

    def validate(credentials, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(credentials, **kwargs)

    monkeypatch.setattr(app.provider, "validate_credentials", validate)
    first, second = page_factory(), page_factory()
    first.goto(app.url, wait_until="networkidle")
    second.goto(app.url, wait_until="networkidle")
    first.locator("#login").fill("test@example.test")
    first.locator("#token").fill("test-app-password")
    first.locator("#connectBtn").click()
    try:
        assert entered.wait(5)
        second.locator("#disconnectBtn").click()
        expect(second.locator("#connectStatus")).to_contain_text("Календарь отключён")
    finally:
        release.set()
    expect(first.locator("#connectStatus")).to_contain_text("Подключение календаря изменилось")
    assert not app.users.get(app.user_id).has_calendar
    first.locator("#connectBtn").click()
    expect(first.locator("#connectStatus")).to_contain_text("Календарь подключён")
    assert app.users.get(app.user_id).has_calendar
