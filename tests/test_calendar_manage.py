"""Раздел «Изменить статус встречи»: фильтрация, роутинг, callbacks."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from satellite.calendar.callback_tokens import event_callback_token
from satellite.calendar.events import collect_manageable_events
from satellite.calendar.providers.base import CalendarEventRef
from satellite.messages_ru import (
    BUTTON_MANAGE_EVENTS,
    CB_MANAGE_BACK,
    CB_MANAGE_CLOSE,
    CB_MANAGE_PICK_PREFIX,
    CB_MANAGE_REFRESH,
    CB_MANAGE_RESPOND_PREFIX,
    MANAGE_CLOSED_TEXT,
    MANAGE_EMPTY_HTML,
    MANAGE_RESPOND_ACCEPTED,
    MANAGE_RESPOND_DECLINED,
    MANAGE_RESPOND_TENTATIVE,
    build_manage_detail_keyboard,
    build_manage_list_keyboard,
)
from satellite.telegram_bot.handlers import (
    IncomingCallback,
    IncomingMessage,
    handle_callback_query,
    handle_message,
    recognize_message,
)
from satellite.telegram_bot.handlers.routing import ManageEventsCommand
from satellite.users import USER_STATUS_APPROVED

TZ = ZoneInfo("Europe/Moscow")
LOGIN = "me@mail.ru"


def _ev(
    *,
    summary: str = "Standup",
    partstat: str | None = "ACCEPTED",
    url: str = "https://cal/e/1.ics",
    start: str = "2026-05-21T14:00:00+03:00",
    end: str = "2026-05-21T15:00:00+03:00",
    uid: str = "uid-1",
) -> dict:
    attendees: list[str] = []
    if partstat is not None:
        attendees.append(f"mailto:{LOGIN};PARTSTAT={partstat}")
    return {
        "uid": uid,
        "summary": summary,
        "url": url,
        "dtstart": start,
        "dtend": end,
        "attendees": attendees,
    }


# --- collect_manageable_events --------------------------------------------


def test_collect_manageable_events_includes_attended_with_any_partstat():
    """Берём все встречи, где у пользователя есть ATTENDEE-запись, любой PARTSTAT."""
    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)
    events = [
        _ev(summary="Accepted", partstat="ACCEPTED", url="https://e/1"),
        _ev(summary="Tentative", partstat="TENTATIVE", url="https://e/2"),
        _ev(summary="Declined", partstat="DECLINED", url="https://e/3"),
        _ev(summary="NeedsAction", partstat="NEEDS-ACTION", url="https://e/4"),
    ]
    out = collect_manageable_events(events, LOGIN, TZ, now=now, max_events=10)
    titles = [ev["summary"] for ev in out]
    # все 4 — у каждого есть ATTENDEE-запись с PARTSTAT, любой
    assert titles == ["Accepted", "Tentative", "Declined", "NeedsAction"]


def test_collect_manageable_events_skips_events_without_user_attendee():
    """Встречи без ATTENDEE для пользователя — это его собственные. Пропускаем."""
    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)
    events = [
        _ev(summary="Own meeting", partstat=None, url="https://e/own"),
        _ev(summary="Invited", partstat="ACCEPTED", url="https://e/inv"),
    ]
    out = collect_manageable_events(events, LOGIN, TZ, now=now, max_events=10)
    assert [ev["summary"] for ev in out] == ["Invited"]


def test_collect_manageable_events_skips_past_and_cancelled():
    now = datetime(2026, 5, 21, 12, 0, tzinfo=TZ)
    events = [
        _ev(
            summary="Past",
            start="2026-05-20T10:00:00+03:00",
            end="2026-05-20T11:00:00+03:00",
            url="https://e/past",
        ),
        {
            **_ev(summary="Cancelled", url="https://e/cx"),
            "status": "CANCELLED",
        },
        _ev(summary="Future"),
    ]
    out = collect_manageable_events(events, LOGIN, TZ, now=now, max_events=10)
    assert [ev["summary"] for ev in out] == ["Future"]


def test_collect_manageable_events_skips_events_without_url():
    """Без url мы не сможем обновить PARTSTAT на сервере — такие не показываем."""
    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)
    events = [
        _ev(summary="NoURL", url=""),
        _ev(summary="Good"),
    ]
    out = collect_manageable_events(events, LOGIN, TZ, now=now, max_events=10)
    assert [ev["summary"] for ev in out] == ["Good"]


# --- recognize_message ----------------------------------------------------


def test_recognize_manage_command():
    assert isinstance(recognize_message(BUTTON_MANAGE_EVENTS), ManageEventsCommand)
    assert isinstance(recognize_message("/manage"), ManageEventsCommand)
    assert isinstance(recognize_message("/edit"), ManageEventsCommand)
    assert isinstance(recognize_message("/status"), ManageEventsCommand)
    assert isinstance(recognize_message("/manage@SomeBot"), ManageEventsCommand)


# --- keyboards -------------------------------------------------------------


def test_manage_list_keyboard_has_refresh_and_close():
    kb = build_manage_list_keyboard([("tok1", "1️⃣ 14:00 · Standup")])
    flat = [btn for row in kb["inline_keyboard"] for btn in row]
    callbacks = [btn["callback_data"] for btn in flat]
    assert f"{CB_MANAGE_PICK_PREFIX}tok1" in callbacks
    assert CB_MANAGE_REFRESH in callbacks
    assert CB_MANAGE_CLOSE in callbacks


def test_manage_detail_keyboard_marks_current_partstat():
    """Текущий статус помечается ✓, чтобы пользователь видел исходное состояние."""
    kb = build_manage_detail_keyboard("tok", partstat="ACCEPTED")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert any("Принять" in lbl and "✓" in lbl for lbl in labels)
    assert any("Может быть" in lbl and "✓" not in lbl for lbl in labels)
    assert any("Отклонить" in lbl and "✓" not in lbl for lbl in labels)


def test_manage_detail_keyboard_back_to_list():
    kb = build_manage_detail_keyboard("tok", partstat=None)
    callbacks = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
    assert CB_MANAGE_BACK in callbacks


# --- end-to-end через handle_message / handle_callback_query --------------


def _approved_user(*, has_calendar: bool = True) -> MagicMock:
    record = MagicMock()
    record.status = USER_STATUS_APPROVED
    record.has_calendar = has_calendar
    return record


def _ctx(*, events: list[dict] | None = None) -> MagicMock:
    record = _approved_user()
    ctx = MagicMock()
    ctx.users = MagicMock()
    ctx.users.get = MagicMock(return_value=record)
    ctx.users.upsert_from_telegram = MagicMock(return_value=record)
    ctx.users.submit_access_request = MagicMock(return_value=(record, True))
    ctx.tz = TZ
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.admin.telegram_ids = ()
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = "https://example.com/connect"
    from satellite.web.connect_token import ConnectTokenStore

    ctx.connect_tokens = ConnectTokenStore()
    ctx.digest_state = MagicMock()
    ctx.digest_state.is_waiting_for_time = MagicMock(return_value=False)
    ctx.digest_state.clear = MagicMock()
    ctx.digest_state.claim_callback = MagicMock(return_value=True)
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.calendar_state.clear = MagicMock()
    ctx.subscriptions = MagicMock()
    ctx.subscriptions.is_subscribed = MagicMock(return_value=False)
    ctx.telegram = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 999})
    ctx.telegram.edit_message_text = MagicMock(return_value={})
    ctx.telegram.send_message_draft = MagicMock(return_value=True)
    ctx.telegram.send_chat_action = MagicMock(return_value=True)
    ctx.telegram.answer_callback_query = MagicMock(return_value=True)
    ctx.calendar_service = MagicMock()

    connected = MagicMock()
    connected.context = MagicMock()
    connected.context.login = LOGIN
    ctx.calendar_service.require_connection = MagicMock(return_value=connected)
    ctx.calendar_service.list_events_for_invitations = MagicMock(return_value=list(events or []))
    ctx.calendar_service.set_attendee_partstat = MagicMock()
    return ctx


_cb_seq = 0


def _cb(chat_id: int, data: str, *, message_id: int = 42) -> IncomingCallback:
    global _cb_seq
    _cb_seq += 1
    return IncomingCallback(
        update_id=1000 + _cb_seq,
        callback_query_id=f"mng-cb-{_cb_seq}",
        chat_id=chat_id,
        message_id=message_id,
        user_id=1,
        username="alice",
        data=data,
    )


def test_handle_open_manage_events_shows_list_with_buttons(monkeypatch):
    """`/manage` шлёт loading и редактирует его в список встреч."""
    import satellite.telegram_bot.handlers.calendar_manage as cm

    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(cm, "datetime", _FixedDatetime)

    ctx = _ctx(events=[_ev(summary="Standup", url="https://e/standup")])
    msg = IncomingMessage(
        update_id=1,
        chat_id=900,
        user_id=1,
        username="alice",
        display_name=None,
        text="/manage",
    )
    handle_message(ctx, msg)

    ctx.telegram.send_message_draft.assert_called()
    ctx.telegram.send_message.assert_called_once()
    ctx.telegram.edit_message_text.assert_not_called()
    rendered = ctx.telegram.send_message.call_args[0][1]
    assert "Standup" in rendered
    keyboard = ctx.telegram.send_message.call_args.kwargs.get("reply_markup")
    assert isinstance(keyboard, dict)
    callbacks = [btn["callback_data"] for row in keyboard["inline_keyboard"] for btn in row]
    expected_token = event_callback_token("https://e/standup")
    assert f"{CB_MANAGE_PICK_PREFIX}{expected_token}" in callbacks


def test_handle_open_manage_events_empty_when_nothing_to_manage(monkeypatch):
    import satellite.telegram_bot.handlers.calendar_manage as cm

    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(cm, "datetime", _FixedDatetime)

    ctx = _ctx(events=[])
    msg = IncomingMessage(
        update_id=2,
        chat_id=901,
        user_id=1,
        username="alice",
        display_name=None,
        text="/manage",
    )
    handle_message(ctx, msg)

    assert ctx.telegram.send_message.call_args[0][1] == MANAGE_EMPTY_HTML


def test_manage_pick_opens_detail_with_action_buttons(monkeypatch):
    """Тап по строке встречи → детальный экран с действиями."""
    import satellite.telegram_bot.handlers.calendar_manage as cm

    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(cm, "datetime", _FixedDatetime)

    url = "https://e/standup"
    ctx = _ctx(events=[_ev(summary="Standup", url=url, partstat="TENTATIVE")])
    token = event_callback_token(url)

    handle_callback_query(ctx, _cb(900, f"{CB_MANAGE_PICK_PREFIX}{token}"))

    edit_kw = ctx.telegram.edit_message_text.call_args
    text = edit_kw[0][2]
    assert "Standup" in text
    keyboard = edit_kw.kwargs.get("reply_markup")
    labels = [btn["text"] for row in keyboard["inline_keyboard"] for btn in row]
    # Текущий статус TENTATIVE подсвечен «✓»
    assert any("Может быть" in lbl and "✓" in lbl for lbl in labels)


def test_manage_respond_calls_set_attendee_partstat_and_refreshes(monkeypatch):
    """Тап «Отклонить» → set_attendee_partstat(DECLINED) + возврат в список + тост."""
    import satellite.telegram_bot.handlers.calendar_manage as cm

    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(cm, "datetime", _FixedDatetime)

    url = "https://e/standup"
    ctx = _ctx(events=[_ev(summary="Standup", url=url, uid="uid-x")])
    token = event_callback_token(url)

    handle_callback_query(ctx, _cb(900, f"{CB_MANAGE_RESPOND_PREFIX}{token}:d"))

    ctx.calendar_service.set_attendee_partstat.assert_called_once()
    args = ctx.calendar_service.set_attendee_partstat.call_args
    assert args.args[0] == 1
    ref = args.args[1]
    assert isinstance(ref, CalendarEventRef)
    assert ref.url == url
    assert ref.uid == "uid-x"
    assert args.args[2] == "DECLINED"

    # answerCallbackQuery с тостом «Отклонено»
    ack = ctx.telegram.answer_callback_query.call_args
    assert ack.kwargs.get("text") == MANAGE_RESPOND_DECLINED


def test_manage_respond_accept_uses_accept_toast(monkeypatch):
    import satellite.telegram_bot.handlers.calendar_manage as cm

    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(cm, "datetime", _FixedDatetime)

    url = "https://e/accept"
    ctx = _ctx(events=[_ev(summary="Demo", url=url, partstat="TENTATIVE")])
    token = event_callback_token(url)

    handle_callback_query(ctx, _cb(900, f"{CB_MANAGE_RESPOND_PREFIX}{token}:a"))

    args = ctx.calendar_service.set_attendee_partstat.call_args
    assert args.args[2] == "ACCEPTED"
    ack = ctx.telegram.answer_callback_query.call_args
    assert ack.kwargs.get("text") == MANAGE_RESPOND_ACCEPTED


def test_manage_respond_tentative_uses_tentative_toast(monkeypatch):
    import satellite.telegram_bot.handlers.calendar_manage as cm

    now = datetime(2026, 5, 21, 10, 0, tzinfo=TZ)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(cm, "datetime", _FixedDatetime)

    url = "https://e/t"
    ctx = _ctx(events=[_ev(summary="Demo", url=url, partstat="ACCEPTED")])
    token = event_callback_token(url)

    handle_callback_query(ctx, _cb(900, f"{CB_MANAGE_RESPOND_PREFIX}{token}:t"))

    args = ctx.calendar_service.set_attendee_partstat.call_args
    assert args.args[2] == "TENTATIVE"
    ack = ctx.telegram.answer_callback_query.call_args
    assert ack.kwargs.get("text") == MANAGE_RESPOND_TENTATIVE


def test_manage_close_callback_clears_keyboard():
    """«Закрыть» убирает inline-клавиатуру с сообщения."""
    ctx = _ctx(events=[])
    handle_callback_query(ctx, _cb(900, CB_MANAGE_CLOSE))
    edit_kw = ctx.telegram.edit_message_text.call_args
    assert edit_kw[0][2] == MANAGE_CLOSED_TEXT
    assert edit_kw.kwargs.get("reply_markup") is None
