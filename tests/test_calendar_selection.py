"""Тесты выбора календарей для плана."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.caldav_client import CalDAVService, CalendarHandle
from satellite.calendar.providers.base import CalendarListEntry
from satellite.calendar.selection import (
    calendar_callback_token,
    effective_enabled_calendar_urls,
    find_calendar_entry_by_token,
    sort_calendar_entries,
)
from satellite.messages_ru import (
    BUTTON_CALENDAR_SOURCES,
    CB_CAL_CLOSE,
    CB_CAL_TOGGLE_PREFIX,
    ERR_GENERIC_HANDLER_TEXT,
    build_calendar_sources_keyboard,
    button_text_is_calendar_sources,
)
from satellite.telegram_bot.handlers import (
    IncomingCallback,
    IncomingMessage,
    handle_callback_query,
    handle_message,
)
from satellite.telegram_bot.handlers.routing import is_calendar_sources_request
from satellite.users import (
    CALENDAR_CONNECTED,
    USER_STATUS_APPROVED,
    UserRecord,
    UserStore,
)


def test_effective_urls_prefers_explicit_list():
    record = UserRecord(
        telegram_user_id=1,
        primary_calendar_url="https://cal/a",
        enabled_calendar_urls=("https://cal/b",),
    )
    assert effective_enabled_calendar_urls(record) == ("https://cal/b",)


def test_effective_urls_falls_back_to_primary():
    record = UserRecord(
        telegram_user_id=1,
        primary_calendar_url="https://cal/a/",
        enabled_calendar_urls=(),
    )
    assert effective_enabled_calendar_urls(record) == ("https://cal/a",)


def test_user_store_persists_enabled_calendar_urls(tmp_path: Path):
    store = UserStore(tmp_path / "users.json")
    store.upsert_from_telegram(
        telegram_user_id=42,
        chat_id=100,
        username="alice",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    store.set_calendar_connection(
        42,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    updated = store.set_enabled_calendar_urls(
        42,
        calendar_urls=["https://cal/a", "https://cal/b", "https://cal/a"],
    )
    assert updated.enabled_calendar_urls == ("https://cal/a", "https://cal/b")
    reloaded = store.get(42)
    assert reloaded is not None
    assert reloaded.enabled_calendar_urls == ("https://cal/a", "https://cal/b")


def test_filter_handles_by_urls_strict_match():
    handles = [
        CalendarHandle(name="A", obj=object(), url="https://cal/a/"),
        CalendarHandle(name="B", obj=object(), url="https://cal/b"),
    ]
    service = CalDAVService(
        caldav_url="https://example/",
        login="u",
        app_password="p",
    )
    matched = service._filter_handles_by_urls(handles, ["https://cal/a"])
    assert len(matched) == 1
    assert matched[0].name == "A"
    empty = service._filter_handles_by_urls(handles, ["https://cal/missing"])
    assert empty == []


def _approved_user(tmp_path: Path) -> UserStore:
    store = UserStore(tmp_path / "users.json")
    store.upsert_from_telegram(
        telegram_user_id=1,
        chat_id=900,
        username="alice",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    store.set_calendar_connection(
        1,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    store.mark_calendar_status(1, status=CALENDAR_CONNECTED)
    return store


def _ctx(tmp_path: Path, *, calendars: list[CalendarListEntry] | None):
    users = _approved_user(tmp_path)
    ctx = MagicMock()
    ctx.users = users
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = ""
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.digest_state = MagicMock()
    ctx.digest_state.is_waiting_for_time = MagicMock(return_value=False)
    ctx.tz = ZoneInfo("Europe/Moscow")
    ctx.subscriptions = MagicMock()
    ctx.telegram = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 1001})
    ctx.telegram.edit_message_text = MagicMock(return_value={})
    ctx.telegram.answer_callback_query = MagicMock(return_value=True)
    ctx.calendar_service = MagicMock()
    if calendars is not None:
        ctx.calendar_service.list_calendars = MagicMock(return_value=calendars)
    return ctx


def test_calendar_sources_button_opens_inline_keyboard(tmp_path: Path):
    calendars = [
        CalendarListEntry(name="Работа", url="https://cal/work"),
        CalendarListEntry(name="Личное", url="https://cal/home"),
    ]
    ctx = _ctx(tmp_path, calendars=calendars)
    msg = IncomingMessage(
        update_id=1,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_CALENDAR_SOURCES,
    )
    handle_message(ctx, msg)
    ctx.telegram.send_message.assert_called_once()
    markup = ctx.telegram.send_message.call_args.kwargs.get("reply_markup")
    assert markup is not None
    rows = markup["inline_keyboard"]
    assert len(rows) == 3
    toggle_data = {row[0]["callback_data"] for row in rows[:-1]}
    assert f"{CB_CAL_TOGGLE_PREFIX}{calendar_callback_token('https://cal/home')}" in toggle_data
    assert f"{CB_CAL_TOGGLE_PREFIX}{calendar_callback_token('https://cal/work')}" in toggle_data


def test_toggle_disables_secondary_calendar(tmp_path: Path):
    calendars = [
        CalendarListEntry(name="Работа", url="https://cal/work"),
        CalendarListEntry(name="Личное", url="https://cal/home"),
    ]
    ctx = _ctx(tmp_path, calendars=calendars)
    users = ctx.users
    users.set_enabled_calendar_urls(1, calendar_urls=["https://cal/work", "https://cal/home"])
    cb = IncomingCallback(
        update_id=2,
        callback_query_id="cb1",
        chat_id=900,
        message_id=55,
        user_id=1,
        username="alice",
        data=f"{CB_CAL_TOGGLE_PREFIX}{calendar_callback_token('https://cal/home')}",
    )
    handle_callback_query(ctx, cb)
    record = users.get(1)
    assert record is not None
    assert record.enabled_calendar_urls == ("https://cal/work",)


def test_cannot_disable_last_calendar(tmp_path: Path):
    calendars = [
        CalendarListEntry(name="Работа", url="https://cal/work"),
        CalendarListEntry(name="Личное", url="https://cal/home"),
    ]
    ctx = _ctx(tmp_path, calendars=calendars)
    users = ctx.users
    users.set_enabled_calendar_urls(1, calendar_urls=["https://cal/work"])
    cb = IncomingCallback(
        update_id=3,
        callback_query_id="cb2",
        chat_id=900,
        message_id=56,
        user_id=1,
        username="alice",
        data=f"{CB_CAL_TOGGLE_PREFIX}{calendar_callback_token('https://cal/work')}",
    )
    handle_callback_query(ctx, cb)
    record = users.get(1)
    assert record is not None
    assert record.enabled_calendar_urls == ("https://cal/work",)
    ctx.telegram.answer_callback_query.assert_called()
    notice = ctx.telegram.answer_callback_query.call_args.kwargs.get("text", "")
    assert "хотя бы один" in notice.lower() or "Нужен" in notice


def test_single_calendar_shows_hint(tmp_path: Path):
    ctx = _ctx(
        tmp_path,
        calendars=[CalendarListEntry(name="Один", url="https://cal/one")],
    )
    msg = IncomingMessage(
        update_id=4,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text=BUTTON_CALENDAR_SOURCES,
    )
    handle_message(ctx, msg)
    text = ctx.telegram.send_message.call_args.args[1]
    assert "один календарь" in text.lower()


@pytest.mark.parametrize(
    "raw",
    [BUTTON_CALENDAR_SOURCES, "/calendars", "/calendar_sources@mybot"],
)
def test_calendar_sources_request_recognized(raw: str):
    assert button_text_is_calendar_sources(raw) or is_calendar_sources_request(raw)


def test_toggle_uses_url_token_when_list_order_changes(tmp_path: Path):
    """Регрессия: индекс в callback_data ломался при другом порядке CalDAV."""
    calendars = [
        CalendarListEntry(name="Личное", url="https://cal/home"),
        CalendarListEntry(name="Работа", url="https://cal/work"),
    ]
    ctx = _ctx(tmp_path, calendars=calendars)
    users = ctx.users
    users.set_enabled_calendar_urls(1, calendar_urls=["https://cal/work", "https://cal/home"])
    # Пользователь нажал кнопку «Работа», когда она была второй; CalDAV вернул её первой.
    ctx.calendar_service.list_calendars.return_value = [
        CalendarListEntry(name="Работа", url="https://cal/work"),
        CalendarListEntry(name="Личное", url="https://cal/home"),
    ]
    cb = IncomingCallback(
        update_id=20,
        callback_query_id="cb-reorder",
        chat_id=900,
        message_id=88,
        user_id=1,
        username="alice",
        data=f"{CB_CAL_TOGGLE_PREFIX}{calendar_callback_token('https://cal/work')}",
    )
    handle_callback_query(ctx, cb)
    record = users.get(1)
    assert record is not None
    assert record.enabled_calendar_urls == ("https://cal/home",)


def test_sort_calendar_entries_is_stable_by_url():
    entries = sort_calendar_entries(
        [
            CalendarListEntry(name="Z", url="https://cal/z"),
            CalendarListEntry(name="A", url="https://cal/a"),
        ]
    )
    assert [e.url for e in entries] == ["https://cal/a", "https://cal/z"]


def test_find_calendar_entry_by_token():
    entries = [
        CalendarListEntry(name="A", url="https://cal/a/"),
        CalendarListEntry(name="B", url="https://cal/b"),
    ]
    token = calendar_callback_token("https://cal/b")
    found = find_calendar_entry_by_token(entries, token)
    assert found is not None
    assert found.name == "B"


def test_build_calendar_sources_keyboard_marks_enabled():
    kb = build_calendar_sources_keyboard(
        calendars=[("A", "https://cal/a"), ("B", "https://cal/b")],
        enabled_urls={"https://cal/a"},
        url_tokens=[
            calendar_callback_token("https://cal/a"),
            calendar_callback_token("https://cal/b"),
        ],
    )
    assert "✅" in kb["inline_keyboard"][0][0]["text"]
    assert "⬜" in kb["inline_keyboard"][1][0]["text"]


# --- Регрессия: toggle/close не должны падать с TypeError в edit_callback_message --


def _assert_no_generic_error(ctx) -> None:
    sent_texts = [c.args[1] for c in ctx.telegram.send_message.call_args_list]
    assert ERR_GENERIC_HANDLER_TEXT not in sent_texts, (
        "Пользователь получил generic error — значит хендлер кинул исключение."
    )


def test_toggle_updates_inline_keyboard_without_generic_error(tmp_path: Path):
    calendars = [
        CalendarListEntry(name="Работа", url="https://cal/work"),
        CalendarListEntry(name="Личное", url="https://cal/home"),
    ]
    ctx = _ctx(tmp_path, calendars=calendars)
    ctx.users.set_enabled_calendar_urls(1, calendar_urls=["https://cal/work", "https://cal/home"])
    cb = IncomingCallback(
        update_id=10,
        callback_query_id="cb-toggle",
        chat_id=900,
        message_id=77,
        user_id=1,
        username="alice",
        data=f"{CB_CAL_TOGGLE_PREFIX}{calendar_callback_token('https://cal/home')}",
    )
    handle_callback_query(ctx, cb)
    ctx.telegram.edit_message_text.assert_called_once()
    _assert_no_generic_error(ctx)


def test_close_calendar_sources_without_generic_error(tmp_path: Path):
    ctx = _ctx(tmp_path, calendars=None)
    cb = IncomingCallback(
        update_id=11,
        callback_query_id="cb-close",
        chat_id=900,
        message_id=78,
        user_id=1,
        username="alice",
        data=CB_CAL_CLOSE,
    )
    handle_callback_query(ctx, cb)
    ctx.telegram.edit_message_text.assert_called_once()
    _assert_no_generic_error(ctx)
