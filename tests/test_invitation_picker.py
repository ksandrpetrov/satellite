"""Invitation number picker, detail actions and safe return to the list."""

import pytest

from satellite.calendar.callback_tokens import event_callback_token
from satellite.calendar.providers.base import CalendarProviderError
from satellite.invitations_view import load_pending_invitations_screen
from satellite.messages_ru import (
    CB_INV_BACK,
    CB_INV_PICK_PREFIX,
    CB_INV_RESPOND_PREFIX,
    CB_SETTINGS_CALENDAR_BACK,
    INVITATIONS_RESPOND_FAIL_TEXT,
    INVITATIONS_SERIES_LABEL,
)
from satellite.telegram_bot.handlers import handle_callback_query

from .conftest import make_callback
from .test_business_flows_invitations import CHAT_ID, TZ, USER_ID, _ctx, _reply_markup
from .test_invitation_series import NOW, occurrence


def setup_picker(hub=False):
    events = [occurrence(day, summary="<Team & Sync>") for day in range(3)]
    events.append(occurrence(2, summary="Other", url="https://cal/other.ics"))
    ctx = _ctx(events=events)
    screen = load_pending_invitations_screen(
        ctx.calendar_service,
        USER_ID,
        event_tokens=ctx.runtime.event_tokens,
        tz=TZ,
        now=NOW,
        from_settings_hub=hub,
    )
    ctx.calendar_service.list_events_for_invitations.reset_mock()
    return ctx, screen, event_callback_token(events[0]["url"])


def click(ctx, data):
    handle_callback_query(ctx, make_callback(data=data, chat_id=CHAT_ID, user_id=USER_ID))


def test_pick_shows_only_selected_series_and_back_restores_hub_list():
    ctx, screen, token = setup_picker(hub=True)
    click(ctx, CB_INV_PICK_PREFIX + token)
    call = ctx.telegram.edit_message_rich.call_args
    text = call.args[2]["html"]
    assert "&lt;Team &amp; Sync&gt;" in text
    assert INVITATIONS_SERIES_LABEL in text
    assert "Other" not in text
    rows = _reply_markup(ctx)["inline_keyboard"]
    assert [b["text"] for b in rows[0]] == ["Принять", "Отклонить", "Может быть"]
    assert [b["callback_data"] for b in rows[0]] == [
        CB_INV_RESPOND_PREFIX + token + ":" + code for code in "adt"
    ]
    assert rows[1][0]["callback_data"] == CB_INV_BACK
    ctx.calendar_service.set_attendee_partstat.assert_not_called()
    click(ctx, CB_INV_BACK)
    assert _reply_markup(ctx) == {"inline_keyboard": screen.keyboard["inline_keyboard"][-3:]}
    assert CB_SETTINGS_CALENDAR_BACK in {
        b["callback_data"] for row in screen.keyboard["inline_keyboard"] for b in row
    }
    ctx.calendar_service.list_events_for_invitations.assert_not_called()


@pytest.mark.parametrize("code", ["a", "d", "t"])
def test_inline_answer_returns_remaining_meeting_blocks(code):
    ctx, screen, token = setup_picker()
    labels = {
        "a": ("success", "Принять"),
        "d": ("danger", "Отклонить"),
        "t": ("primary", "Может быть"),
    }
    for action, (style, label) in labels.items():
        assert (
            f'<tg-button type="callback_data" style="{style}" '
            f'data="{CB_INV_RESPOND_PREFIX}{token}:{action}">{label}</tg-button>'
        ) in screen.rich_text
    assert CB_INV_PICK_PREFIX not in screen.rich_text
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":" + code)
    rows = _reply_markup(ctx)["inline_keyboard"]
    assert len(rows[0]) == 1
    assert rows[0][0]["text"] == "✅ Принять все"
    text = ctx.telegram.edit_message_rich.call_args.args[2]["html"]
    assert text.count('<tg-button type="callback_data"') == 3
    assert CB_INV_RESPOND_PREFIX + token not in text
    assert "Other" in text
    ctx.calendar_service.set_attendee_partstat.assert_called_once()


def test_failed_answer_keeps_detail_and_retry_buttons():
    ctx, _, token = setup_picker()
    click(ctx, CB_INV_PICK_PREFIX + token)
    keyboard = _reply_markup(ctx)
    ctx.calendar_service.set_attendee_partstat.side_effect = CalendarProviderError("unavailable")
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    assert _reply_markup(ctx) == keyboard
    assert INVITATIONS_RESPOND_FAIL_TEXT in ctx.telegram.edit_message_rich.call_args.args[2]["html"]
    assert len(ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending) == 2


def test_unknown_pick_returns_list_without_calendar_mutation():
    ctx, screen, _ = setup_picker()
    click(ctx, CB_INV_PICK_PREFIX + "unknown")
    assert _reply_markup(ctx) == {"inline_keyboard": screen.keyboard["inline_keyboard"][-3:]}
    ctx.calendar_service.set_attendee_partstat.assert_not_called()
    ctx.calendar_service.list_events_for_invitations.assert_not_called()


def test_expired_pick_reloads_list_before_allowing_selection(monkeypatch):
    ctx, _, token = setup_picker()
    monkeypatch.setattr(ctx.runtime.event_tokens, "get_invitations_snapshot", lambda _: None)
    click(ctx, CB_INV_PICK_PREFIX + token)
    ctx.calendar_service.list_events_for_invitations.assert_called_once()
    ctx.calendar_service.set_attendee_partstat.assert_not_called()
