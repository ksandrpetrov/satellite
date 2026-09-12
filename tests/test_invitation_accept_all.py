"""Bulk accept affects the shown snapshot and preserves failed invitations."""

import pytest

from satellite.calendar.providers.base import CalendarProviderError
from satellite.messages_ru import CB_INV_ACCEPT_ALL_PREFIX, CB_INV_RESPOND_PREFIX
from satellite.telegram_bot.api import TelegramError

from .test_business_flows_invitations import USER_ID, _reply_markup
from .test_invitation_picker import click, setup_picker


def bulk_button(screen):
    return next(
        b["callback_data"]
        for row in screen.keyboard["inline_keyboard"]
        for b in row
        if b["callback_data"].startswith(CB_INV_ACCEPT_ALL_PREFIX)
    )


def test_accept_all_updates_each_resource_once_and_removes_button():
    ctx, screen, _ = setup_picker()
    click(ctx, bulk_button(screen))
    calls = ctx.calendar_service.set_attendee_partstat.call_args_list
    assert len(calls) == 2
    assert {c.args[1].url for c in calls} == {ev["url"] for ev in screen.pending}
    assert all(c.args[0] == USER_ID and c.args[2] == "ACCEPTED" for c in calls)
    assert ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending == []
    assert not any(
        b["callback_data"].startswith(CB_INV_ACCEPT_ALL_PREFIX)
        for row in _reply_markup(ctx)["inline_keyboard"]
        for b in row
    )


def test_partial_failure_keeps_only_failed_and_retry_does_not_repeat_success():
    ctx, screen, _ = setup_picker()
    ctx.calendar_service.set_attendee_partstat.side_effect = [
        CalendarProviderError("offline"),
        None,
    ]
    click(ctx, bulk_button(screen))
    pending = ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending
    assert [e["url"] for e in pending] == [screen.pending[0]["url"]]
    text = ctx.telegram.edit_message_rich.call_args.args[2]["html"]
    assert "Принято встреч и серий: 1" in text
    assert "Не удалось принять: 1" in text
    retry = next(
        b["callback_data"]
        for row in _reply_markup(ctx)["inline_keyboard"]
        for b in row
        if b["callback_data"].startswith(CB_INV_ACCEPT_ALL_PREFIX)
    )
    ctx.calendar_service.set_attendee_partstat.side_effect = None
    click(ctx, retry)
    assert ctx.calendar_service.set_attendee_partstat.call_count == 3
    assert ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending == []


def test_stale_batch_button_does_not_accept_changed_selection():
    ctx, screen, token = setup_picker()
    ctx.runtime.event_tokens.remove_invitations_pending(USER_ID, token)
    click(ctx, bulk_button(screen))
    ctx.calendar_service.set_attendee_partstat.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_single_answer_preserves_correct_html_format(legacy):
    ctx, _, token = setup_picker()
    if legacy:
        ctx.telegram.edit_message_rich.side_effect = TelegramError("unavailable")
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    if legacy:
        text = ctx.telegram.edit_message_text.call_args.args[2]
        assert "<p>" not in text
        assert "\n" in text
    else:
        text = ctx.telegram.edit_message_rich.call_args.args[2]["html"]
        assert "<p>" in text
        assert '<tg-button type="callback_data"' in text
        assert "<blockquote" not in text
    assert "Other" in text


def test_truncated_batch_reports_more_invitations_without_claiming_inbox_empty():
    from dataclasses import replace

    ctx, screen, _ = setup_picker()
    cache = ctx.runtime.event_tokens
    snapshot = cache.get_invitations_snapshot(USER_ID)
    cache.register_invitations_screen(
        USER_ID,
        pending=snapshot.pending,
        all_events=snapshot.pending,
        login=snapshot.login,
        moment=snapshot.moment,
        truncated=True,
    )
    click(ctx, bulk_button(replace(screen, truncated=True)))
    text = ctx.telegram.edit_message_rich.call_args.args[2]["html"]
    assert "Обнови список" in text
    assert "Всё разобрано" not in text
    assert cache.get_invitations_snapshot(USER_ID).truncated
    assert ctx.calendar_service.set_attendee_partstat.call_count == 2


def test_batch_guard_blocks_duplicate_click():
    ctx, screen, _ = setup_picker()
    data = bulk_button(screen)
    from .test_business_flows_invitations import CHAT_ID

    assert ctx.runtime.partstat_respond.try_acquire(CHAT_ID, data)
    click(ctx, data)
    ctx.calendar_service.set_attendee_partstat.assert_not_called()
