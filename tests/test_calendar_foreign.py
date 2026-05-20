"""Тесты чужих (пошаренных) календарей."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.events import format_single_day_events_lines
from satellite.calendar.providers.base import CalendarListEntry
from satellite.calendar.selection import calendar_callback_token, foreign_calendar_entries
from satellite.messages_ru import (
    BUTTON_DAY_AFTER,
    BUTTON_FOREIGN_CALENDARS,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    CB_FOREIGN_DAY_PREFIX,
    CB_FOREIGN_PICK_PREFIX,
    build_foreign_day_keyboard,
    button_text_is_foreign_calendars,
)
from satellite.telegram_bot.handlers.routing import is_foreign_calendars_request
from satellite.users import USER_STATUS_APPROVED, UserStore, CALENDAR_CONNECTED

TZ = ZoneInfo("Europe/Moscow")


def test_foreign_calendar_entries_excludes_primary():
    calendars = [
        CalendarListEntry(name="Мой", url="https://cal/primary"),
        CalendarListEntry(name="Александра Качина", url="https://cal/shared"),
    ]
    foreign = foreign_calendar_entries(
        calendars, primary_calendar_url="https://cal/primary/"
    )
    assert len(foreign) == 1
    assert foreign[0].name == "Александра Качина"


def test_button_and_command_routing():
    assert button_text_is_foreign_calendars(BUTTON_FOREIGN_CALENDARS)
    assert is_foreign_calendars_request(BUTTON_FOREIGN_CALENDARS)
    assert is_foreign_calendars_request("/foreign")
    assert not is_foreign_calendars_request("/today")


def test_foreign_day_keyboard_offers_today_tomorrow_and_day_after():
    """Под чужим календарём — три дня вперёд, как и в плане Чайки."""
    kb = build_foreign_day_keyboard(calendar_token="abc123456789")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert BUTTON_TODAY in labels
    assert BUTTON_TOMORROW in labels
    assert BUTTON_DAY_AFTER in labels
    # Возврат к списку календарей — отдельная строка
    assert any("списку" in lbl.lower() for lbl in labels)
    # day_offset кодируется в callback_data в формате "{prefix}{idx}:{offset}"
    offsets = set()
    for row in kb["inline_keyboard"]:
        for btn in row:
            data = btn.get("callback_data", "")
            if data.startswith(CB_FOREIGN_DAY_PREFIX):
                payload = data[len(CB_FOREIGN_DAY_PREFIX):]
                _idx, _, offset = payload.partition(":")
                offsets.add(offset)
    assert offsets == {"0", "1", "2"}


def test_format_single_day_events_lines():
    ref = date(2026, 5, 20)
    events = [
        {
            "summary": "Созвон",
            "dtstart": datetime(2026, 5, 20, 10, 0, tzinfo=TZ).isoformat(),
            "dtend": datetime(2026, 5, 20, 11, 0, tzinfo=TZ).isoformat(),
        },
    ]
    lines = format_single_day_events_lines(events, TZ, ref, ref)
    assert lines[0].startswith("<b>Сегодня")
    assert lines[1].startswith("1️⃣ ")
    assert "Созвон" in lines[1]


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "users.json")


def test_foreign_calendars_callback_flow(users: UserStore) -> None:
    from satellite.telegram_bot.handlers import (
        HandlerContext,
        IncomingCallback,
        handle_callback_query,
    )

    user_id = 100
    users.upsert_from_telegram(
        telegram_user_id=user_id,
        chat_id=user_id,
        username="petrov",
        display_name="Александр Петров",
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        user_id,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    users.mark_calendar_status(user_id, status=CALENDAR_CONNECTED)

    ctx = MagicMock(spec=HandlerContext)
    ctx.users = users
    ctx.tz = TZ
    ctx.calendar_service = MagicMock()
    ctx.calendar_service.list_calendars.return_value = [
        CalendarListEntry(name="Мой", url="https://cal/primary"),
        CalendarListEntry(name="Александра Качина", url="https://cal/shared"),
    ]
    ctx.calendar_service.list_events.return_value = [
        {
            "summary": "Встреча",
            "dtstart": datetime(2026, 5, 20, 14, 0, tzinfo=TZ).isoformat(),
            "dtend": datetime(2026, 5, 20, 15, 0, tzinfo=TZ).isoformat(),
        },
    ]
    ctx.telegram = MagicMock()
    ctx.telegram.edit_message_text = MagicMock()
    ctx.telegram.answer_callback_query = MagicMock()
    ctx.digest_state = MagicMock()
    ctx.digest_state.claim_callback.return_value = True

    cb = IncomingCallback(
        update_id=1,
        callback_query_id="cb1",
        chat_id=user_id,
        message_id=5,
        user_id=user_id,
        username="petrov",
        data=f"{CB_FOREIGN_DAY_PREFIX}{calendar_callback_token('https://cal/shared')}:0",
    )

    handle_callback_query(ctx, cb)

    ctx.calendar_service.list_events.assert_called_once()
    call_kw = ctx.calendar_service.list_events.call_args.kwargs
    assert call_kw["calendar_urls"] == ("https://cal/shared",)
    edit_text = ctx.telegram.edit_message_text.call_args_list[-1][0][2]
    assert "Александра Качина" in edit_text
    assert "Встреча" in edit_text
