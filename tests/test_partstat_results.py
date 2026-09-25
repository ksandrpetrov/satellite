"""Visible progress, reliable receipts, stale lists and isolated runtime state."""

import pytest

from satellite.calendar.callback_tokens import event_callback_token
from satellite.calendar.providers.base import CalendarProviderError
from satellite.messages_ru import CB_INV_REFRESH, CB_INV_RESPOND_PREFIX, CB_MANAGE_RESPOND_PREFIX
from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.handlers import handle_callback_query
from satellite.telegram_bot.handlers.partstat_results import PartstatResultStore
from satellite.telegram_bot.presenters.bundle import ScreenBundle

from .conftest import make_callback
from .test_business_flows_invitations import CHAT_ID, USER_ID
from .test_invitation_accept_all import bulk_button
from .test_invitation_picker import click, setup_picker


def result_text(ctx):
    return ctx.telegram.edit_message_rich.call_args.args[2]["html"]


def test_bulk_progress_precedes_every_write_and_persists_named_series_result():
    ctx, screen, _ = setup_picker()
    observed = []

    def write(*args):
        observed.append(ctx.telegram.edit_message_text.call_args.args[2])
        assert (
            "Принято"
            not in ctx.telegram.answer_callback_query.call_args.kwargs.get("text", "").split(".")[0]
        )

    ctx.calendar_service.set_attendee_partstat.side_effect = write
    click(ctx, bulk_button(screen))
    assert "Обработано 0 из 2" in observed[0]
    assert "Обработано 1 из 2" in observed[1]
    assert "Принято: 1" in observed[1]
    assert "Принято встреч и серий: 2" in result_text(ctx)
    assert "Принята вся серия" in result_text(ctx)
    assert "&lt;Team &amp; Sync&gt;" in result_text(ctx)
    assert "Other" in result_text(ctx)


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("recovery", ["same_button", "refresh"])
def test_delivery_failure_recovers_result_without_calendar_writes(bulk, recovery):
    ctx, screen, token = setup_picker()
    data = bulk_button(screen) if bulk else CB_INV_RESPOND_PREFIX + token + ":a"
    ctx.telegram.edit_message_rich.side_effect = TelegramError("Too Many Requests: retry after 1")
    ctx.telegram.edit_message_text.side_effect = TelegramError("network unavailable")
    click(ctx, data)
    writes = ctx.calendar_service.set_attendee_partstat.call_count
    assert writes == (2 if bulk else 1)
    ctx.telegram.edit_message_rich.side_effect = None
    ctx.telegram.edit_message_text.side_effect = None
    click(ctx, data if recovery == "same_button" else CB_INV_REFRESH)
    assert "Принята вся серия" in result_text(ctx)
    assert ctx.calendar_service.set_attendee_partstat.call_count == writes
    ctx.calendar_service.list_events_for_invitations.assert_not_called()
    ctx.telegram.send_message.assert_not_called()
    ctx.telegram.send_rich_message.assert_not_called()


def test_mixed_failed_unconfirmed_and_success_preserve_only_unresolved():
    ctx, screen, _ = setup_picker()
    snapshot = ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID)
    third = dict(snapshot.pending[1], url="https://cal/third.ics", summary="Third")
    pending = [*snapshot.pending, third]
    ctx.runtime.event_tokens.register_invitations_screen(
        USER_ID,
        pending=pending,
        all_events=pending,
        login=snapshot.login,
        moment=snapshot.moment,
        truncated=False,
    )
    from satellite.messages_ru import invitation_accept_all_callback

    data = invitation_accept_all_callback([event_callback_token(e["url"]) for e in pending])
    ctx.calendar_service.set_attendee_partstat.side_effect = [
        None,
        CalendarProviderError("offline"),
        CalendarProviderError("unknown", error_code="PARTSTAT_UPDATE_UNCONFIRMED"),
    ]
    click(ctx, data)
    assert "Принято встреч и серий: 1" in result_text(ctx)
    assert "Не удалось принять: 1" in result_text(ctx)
    assert "Результат пока не подтверждён: 1" in result_text(ctx)
    assert [
        e["url"] for e in ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending
    ] == [e["url"] for e in pending[1:]]
    click(ctx, data)  # old whole-batch button replays the outcome
    assert ctx.calendar_service.set_attendee_partstat.call_count == 3


def test_complete_failure_can_retry_after_result_is_delivered():
    ctx, screen, _ = setup_picker()
    ctx.calendar_service.set_attendee_partstat.side_effect = CalendarProviderError("offline")
    click(ctx, bulk_button(screen))
    assert "Принято встреч и серий: 0" in result_text(ctx)
    assert "Не удалось принять: 2" in result_text(ctx)
    assert len(ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending) == 2
    ctx.calendar_service.set_attendee_partstat.side_effect = None
    click(ctx, bulk_button(screen))
    assert ctx.calendar_service.set_attendee_partstat.call_count == 4
    assert ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID).pending == []


def test_receipts_expire_at_thirty_minutes_and_are_user_message_scoped(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(
        "satellite.telegram_bot.handlers.partstat_results.time.monotonic", lambda: clock[0]
    )
    store = PartstatResultStore(max_results=2)
    bundle = ScreenBundle("<p>result</p>", "result", {"inline_keyboard": []})
    key = (1, 2, 3, "inv:all:batch")
    receipt = store.save(key, bundle, ("a",), allow_retry=False)
    bundle.reply_markup["inline_keyboard"].append([{"text": "changed"}])
    assert store.get(key).bundle.reply_markup == {"inline_keyboard": []}
    assert store.get((2, 2, 3, key[3])) is None
    assert store.get((1, 2, 4, key[3])) is None
    assert store.undelivered(1, 2, 3) == receipt
    store.mark_delivered(receipt)
    assert store.undelivered(1, 2, 3) is None
    clock[0] += 1799
    assert store.get(key) is not None
    clock[0] += 1
    assert store.get(key) is None
    assert PartstatResultStore().get(key) is None  # restart: runtime receipt is not durable


def test_receipts_are_bounded_and_new_decision_invalidates_old_results():
    store = PartstatResultStore(max_results=2)
    bundle = ScreenBundle("result", "result", None)
    for msg in range(3):
        store.save((1, 1, msg, "accept"), bundle, ("a",), allow_retry=False)
    assert store.get((1, 1, 0, "accept")) is None
    store.invalidate(2, "a")
    assert store.get((1, 1, 1, "accept")) is not None
    store.invalidate(1, "a")
    assert store.get((1, 1, 1, "accept")) is None
    assert store.get((1, 1, 2, "accept")) is None


def test_expired_batch_cannot_accept_new_selection():
    ctx, screen, _ = setup_picker()
    ctx.runtime.event_tokens._ttl_sec = 0
    click(ctx, bulk_button(screen))
    ctx.calendar_service.set_attendee_partstat.assert_not_called()
    ctx.calendar_service.list_events_for_invitations.assert_called_once()


def test_answer_from_manage_invalidates_invitation_batch():
    ctx, screen, token = setup_picker()
    snapshot = ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID)
    ctx.runtime.event_tokens.register_manage_screen(
        USER_ID,
        events=snapshot.pending,
        login=snapshot.login,
        moment=snapshot.moment,
        truncated=False,
    )
    click(ctx, CB_MANAGE_RESPOND_PREFIX + token + ":d")
    click(ctx, bulk_button(screen))
    assert ctx.calendar_service.set_attendee_partstat.call_count == 1
    assert ctx.calendar_service.set_attendee_partstat.call_args.args[2] == "DECLINED"


def test_new_decision_is_not_discarded_by_previous_answer_cooldown():
    ctx, _, token = setup_picker()
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":d")
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    assert [call.args[2] for call in ctx.calendar_service.set_attendee_partstat.call_args_list] == [
        "ACCEPTED",
        "DECLINED",
        "ACCEPTED",
    ]


def test_inflight_decision_is_shared_by_invitations_and_manage():
    ctx, _, token = setup_picker()

    def during_write(*args):
        handle_callback_query(
            ctx,
            make_callback(
                data=CB_MANAGE_RESPOND_PREFIX + token + ":d",
                chat_id=CHAT_ID,
                user_id=USER_ID,
                message_id=99,
            ),
        )

    ctx.calendar_service.set_attendee_partstat.side_effect = during_write
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    assert ctx.calendar_service.set_attendee_partstat.call_count == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_largest_batch_long_titles_is_deliverable_and_escaped(legacy):
    import re
    from html import unescape

    from satellite.invitations_view import MAX_INVITATIONS
    from satellite.messages_ru import invitation_accept_all_callback

    ctx, _, _ = setup_picker()
    snapshot = ctx.runtime.event_tokens.get_invitations_snapshot(USER_ID)
    events = [
        dict(snapshot.pending[0], url=f"https://cal/long-{i}.ics", summary="<>&" * 500)
        for i in range(MAX_INVITATIONS)
    ]
    ctx.runtime.event_tokens.register_invitations_screen(
        USER_ID,
        pending=events,
        all_events=events,
        login=snapshot.login,
        moment=snapshot.moment,
        truncated=True,
    )
    if legacy:
        ctx.telegram.edit_message_rich.side_effect = TelegramError("unsupported rich")
    click(ctx, invitation_accept_all_callback([event_callback_token(e["url"]) for e in events]))
    text = ctx.telegram.edit_message_text.call_args.args[2] if legacy else result_text(ctx)
    visible = unescape(re.sub(r"<[^>]+>", "", text))
    assert len(visible) < 4096
    assert "<>&" not in text
    assert "&lt;&gt;&amp;" in text
    assert ctx.calendar_service.set_attendee_partstat.call_count == MAX_INVITATIONS
    assert "Обнови список" in text


def test_not_modified_response_counts_as_delivered_without_fallback():
    ctx, _, token = setup_picker()
    ctx.telegram.edit_message_rich.side_effect = TelegramError(
        "Bad Request: message is not modified"
    )
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    assert ctx.runtime.partstat_results.undelivered(USER_ID, CHAT_ID, 42) is None
    # Only the initial progress used legacy edit; final rich response was already there.
    assert ctx.telegram.edit_message_text.call_count == 1
    ctx.telegram.send_message.assert_not_called()


def test_changed_decision_keeps_original_event_name():
    ctx, _, token = setup_picker()
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":d")
    assert "Отклонена вся серия" in result_text(ctx)
    assert "&lt;Team &amp; Sync&gt;" in result_text(ctx)


def test_confirmed_response_survives_disconnect_during_refresh():
    from satellite.calendar.providers.base import CalendarNotConnectedError

    ctx, _, token = setup_picker()
    ctx.runtime.event_tokens._ttl_sec = 0

    def write(*args):
        ctx.calendar_service.require_connection.side_effect = CalendarNotConnectedError()

    ctx.calendar_service.set_attendee_partstat.side_effect = write
    click(ctx, CB_INV_RESPOND_PREFIX + token + ":a")
    assert "Принята вся серия" in result_text(ctx)
    ctx.telegram.send_message.assert_not_called()
