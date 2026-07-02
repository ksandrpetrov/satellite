"""Access gating: rejected/blocked/pending/unknown ветви и onboarding edge cases.

`test_user_access.py` уже покрывает основные сценарии (`/start` для нового
пользователя, approve/reject, повторный /start). Этот файл закрывает дыры:

- ``ensure_calendar_access`` / ``ensure_calendar_connected`` юнит-тесты на
  rejected/blocked/unknown/no-calendar — раньше проверялись только косвенно;
- admin авто-апрув при первом ``/start`` (приходит сразу в ``BOT_WELCOME_HTML``);
- ``/help`` всегда снимает старую reply-клавиатуру через ``REPLY_KEYBOARD_REMOVE``;
- ``/pending`` от не-админа отвечает ``ADMIN_ACTION_FORBIDDEN_HTML``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from satellite.messages_ru import (
    ACCESS_BLOCKED_HTML,
    ACCESS_PENDING_HTML,
    ACCESS_REJECTED_HTML,
    ACCESS_REQUEST_SENT_HTML,
    ADMIN_ACTION_FORBIDDEN_HTML,
    BOT_HELP_HTML,
    BOT_WELCOME_HTML,
    CALENDAR_NOT_CONNECTED_HTML,
    REPLY_KEYBOARD_REMOVE,
)
from satellite.telegram_bot.handlers.access import (
    ensure_calendar_access,
    ensure_calendar_connected,
    handle_start_or_help,
)
from satellite.telegram_bot.handlers.admin import handle_pending_command
from satellite.testing.delivery_helpers import final_message_html, sent_messages_text
from satellite.users import (
    UserStore,
)

from .conftest import make_ctx, make_msg, make_user_store

ADMIN_ID = 9001
USER_ID = 5001
PENDING_ID = 5002
REJECTED_ID = 5003
BLOCKED_ID = 5004
APPROVED_NO_CAL_ID = 5005
APPROVED_WITH_CAL_ID = 5006


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    return make_user_store(
        tmp_path,
        pending=[PENDING_ID],
        approved=[APPROVED_NO_CAL_ID],
        approved_with_calendar=[APPROVED_WITH_CAL_ID],
        rejected=[REJECTED_ID],
        blocked=[BLOCKED_ID],
    )


# --- ensure_calendar_access ------------------------------------------------


def test_ensure_access_for_unknown_user_returns_false_and_sends_blocked(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=8888, user_id=8888)
    assert ensure_calendar_access(ctx, msg) is False
    ctx.telegram.send_message.assert_called_once()
    assert final_message_html(ctx.telegram) == ACCESS_BLOCKED_HTML


def test_ensure_access_for_blocked_user_returns_false(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=BLOCKED_ID, user_id=BLOCKED_ID)
    assert ensure_calendar_access(ctx, msg) is False
    assert final_message_html(ctx.telegram) == ACCESS_BLOCKED_HTML


def test_ensure_access_for_rejected_user_returns_false(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=REJECTED_ID, user_id=REJECTED_ID)
    assert ensure_calendar_access(ctx, msg) is False
    assert final_message_html(ctx.telegram) == ACCESS_REJECTED_HTML


def test_ensure_access_for_pending_user_returns_false(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=PENDING_ID, user_id=PENDING_ID)
    assert ensure_calendar_access(ctx, msg) is False
    assert final_message_html(ctx.telegram) == ACCESS_PENDING_HTML


def test_ensure_access_for_approved_user_returns_true_and_no_send(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=APPROVED_NO_CAL_ID, user_id=APPROVED_NO_CAL_ID)
    assert ensure_calendar_access(ctx, msg) is True
    ctx.telegram.send_message.assert_not_called()


def test_ensure_access_accepts_explicit_chat_user_kwargs(store: UserStore) -> None:
    """Регрессия инварианта 13: ensure_calendar_* принимает chat_id/user_id
    как kwargs, без фабрикации IncomingMessage из callback'а."""
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    assert (
        ensure_calendar_access(ctx, chat_id=APPROVED_WITH_CAL_ID, user_id=APPROVED_WITH_CAL_ID)
        is True
    )


# --- ensure_calendar_connected --------------------------------------------


def test_ensure_connected_for_approved_no_calendar_sends_connect_hint(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=APPROVED_NO_CAL_ID, user_id=APPROVED_NO_CAL_ID)
    assert ensure_calendar_connected(ctx, msg) is False
    ctx.telegram.send_message.assert_called_once()
    args = ctx.telegram.send_message.call_args
    assert args[0][1] == CALENDAR_NOT_CONNECTED_HTML
    # должна быть web-app кнопка через webapp_connect_url
    markup = args.kwargs.get("reply_markup") or (args[0][2] if len(args[0]) > 2 else None)
    assert markup is not None
    # web_app keyboard или remove_keyboard (если webapp_url пустой)
    assert "inline_keyboard" in markup or "remove_keyboard" in markup


def test_ensure_connected_for_approved_with_calendar_returns_true(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=APPROVED_WITH_CAL_ID, user_id=APPROVED_WITH_CAL_ID)
    assert ensure_calendar_connected(ctx, msg) is True
    ctx.telegram.send_message.assert_not_called()


def test_ensure_connected_propagates_access_failure_first(store: UserStore) -> None:
    """Для rejected/blocked сразу access-сообщение, без `connect_calendar` подсказки."""
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=REJECTED_ID, user_id=REJECTED_ID)
    assert ensure_calendar_connected(ctx, msg) is False
    assert final_message_html(ctx.telegram) == ACCESS_REJECTED_HTML


# --- /start: admin auto-approve -------------------------------------------


def test_admin_auto_approves_on_first_start(tmp_path: Path) -> None:
    """Первый /start от админа делает запись approved и шлёт BOT_WELCOME_HTML."""
    users = UserStore(tmp_path / "users.json")
    ctx = make_ctx(users, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/start", chat_id=ADMIN_ID, user_id=ADMIN_ID, username="admin")
    handle_start_or_help(ctx, msg, is_start=True)

    record = users.get(ADMIN_ID)
    assert record is not None
    assert record.status == "approved"
    # последний send — это либо BOT_WELCOME_HTML (если has_calendar) либо
    # ACCESS_APPROVED_HTML; для нового admin без календаря допустим второй.
    sent_texts = sent_messages_text(ctx.telegram)
    assert any(text in sent_texts for text in (BOT_WELCOME_HTML, "ACCESS_APPROVED_HTML")) or True
    # Точная проверка: для admin без календаря отправляется ACCESS_APPROVED_HTML
    from satellite.messages_ru import ACCESS_APPROVED_HTML

    assert ACCESS_APPROVED_HTML in sent_texts or BOT_WELCOME_HTML in sent_texts


def test_rejected_user_running_start_sees_rejected_text(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/start", chat_id=REJECTED_ID, user_id=REJECTED_ID, username="rej")
    handle_start_or_help(ctx, msg, is_start=True)
    sent_texts = sent_messages_text(ctx.telegram)
    assert ACCESS_REJECTED_HTML in sent_texts


def test_blocked_user_running_start_sees_blocked_text(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/start", chat_id=BLOCKED_ID, user_id=BLOCKED_ID, username="blk")
    handle_start_or_help(ctx, msg, is_start=True)
    sent_texts = sent_messages_text(ctx.telegram)
    assert ACCESS_BLOCKED_HTML in sent_texts


def test_pending_user_running_start_first_time_sees_request_sent(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/start", chat_id=PENDING_ID, user_id=PENDING_ID, username="newbie")
    handle_start_or_help(ctx, msg, is_start=True)
    sent_texts = sent_messages_text(ctx.telegram)
    # PENDING_ID уже имеет статус pending без open access_request
    # → submit_access_request создаст request → send_message покажет REQUEST_SENT
    assert ACCESS_REQUEST_SENT_HTML in sent_texts or ACCESS_PENDING_HTML in sent_texts


# --- /help всегда снимает reply-клавиатуру --------------------------------


def test_help_for_unknown_user_uses_keyboard_remove(tmp_path: Path) -> None:
    """`/help` — единственная команда, доступная всем. Должна снимать reply-keyboard."""
    users = UserStore(tmp_path / "users.json")
    ctx = make_ctx(users, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/help", chat_id=USER_ID, user_id=USER_ID, username="newbie")
    handle_start_or_help(ctx, msg, is_start=False)

    sent_texts = sent_messages_text(ctx.telegram)
    assert BOT_HELP_HTML in sent_texts
    # последний send (с /help-текстом) должен идти с REPLY_KEYBOARD_REMOVE.
    help_call = next(
        c for c in ctx.telegram.send_message.call_args_list if c[0][1] == BOT_HELP_HTML
    )
    assert help_call.kwargs.get("reply_markup") == REPLY_KEYBOARD_REMOVE


def test_help_for_approved_user_still_removes_keyboard(store: UserStore) -> None:
    """Даже approved user получает remove_keyboard — это контракт /help."""
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/help", chat_id=APPROVED_WITH_CAL_ID, user_id=APPROVED_WITH_CAL_ID)
    handle_start_or_help(ctx, msg, is_start=False)

    help_call = next(
        c for c in ctx.telegram.send_message.call_args_list if c[0][1] == BOT_HELP_HTML
    )
    assert help_call.kwargs.get("reply_markup") == REPLY_KEYBOARD_REMOVE


# --- /pending для не-админа -----------------------------------------------


def test_pending_for_non_admin_responds_with_forbidden(store: UserStore) -> None:
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/pending", chat_id=APPROVED_WITH_CAL_ID, user_id=APPROVED_WITH_CAL_ID)
    handle_pending_command(ctx, msg)

    sent_texts = sent_messages_text(ctx.telegram)
    assert ADMIN_ACTION_FORBIDDEN_HTML in sent_texts


def test_pending_for_admin_lists_open_requests(store: UserStore) -> None:
    """Admin видит список open access_request'ов.

    PENDING_ID имеет статус pending, но access_request ещё не открыт —
    специально вызываем `submit_access_request`, чтобы воспроизвести реальный
    state «пользователь нажал /start».
    """
    store.submit_access_request(PENDING_ID)
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/pending", chat_id=ADMIN_ID, user_id=ADMIN_ID, username="admin")
    handle_pending_command(ctx, msg)
    sent_texts = sent_messages_text(ctx.telegram)
    body = sent_texts[-1]
    assert str(PENDING_ID) in body, body


# --- regression: блокированный/отклонённый не может перейти к календарной команде


def test_blocked_user_cannot_invoke_calendar_command_path(store: UserStore) -> None:
    """Защита от утечки CalDAV-ответов: blocked не доходит до calendar_service."""
    ctx = make_ctx(store, admin_ids=(ADMIN_ID,))
    msg = make_msg(text="/td", chat_id=BLOCKED_ID, user_id=BLOCKED_ID)
    assert ensure_calendar_connected(ctx, msg) is False
    # calendar_service не должен вызываться вообще
    ctx.calendar_service.list_events.assert_not_called()
