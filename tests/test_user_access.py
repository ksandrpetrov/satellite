"""Интеграционные тесты заявок на доступ: UserStore + access/admin handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from satellite.config import AdminConfig
from satellite.messages_ru import (
    ACCESS_APPROVED_HTML,
    ACCESS_APPROVED_KEYBOARD_HINT,
    ACCESS_PENDING_HTML,
    ACCESS_REJECTED_HTML,
    ACCESS_REQUEST_SENT_HTML,
    BOT_HELP_HTML,
    CB_ADMIN_APPROVE_PREFIX,
    CB_ADMIN_REJECT_PREFIX,
    build_approved_main_keyboard,
)
from satellite.telegram_bot.handlers.access import handle_start_or_help
from satellite.telegram_bot.handlers.admin import (
    handle_pending_command,
    route_admin_callback,
)
from satellite.telegram_bot.handlers.context import (
    HandlerContext,
    IncomingCallback,
    IncomingMessage,
)
from satellite.testing.delivery_helpers import final_message_html
from satellite.users import (
    ACCESS_REQUEST_PENDING,
    USER_STATUS_APPROVED,
    USER_STATUS_PENDING,
    USER_STATUS_REJECTED,
    UserStore,
    UserStorePersistenceError,
)

ADMIN_ID = 9001
USER_ID = 5001
CHAT_ID = 5001


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "users.json")


def _ctx(users: UserStore) -> MagicMock:
    ctx = MagicMock(spec=HandlerContext)
    ctx.users = users
    ctx.admin = AdminConfig(telegram_ids=(ADMIN_ID,))
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = "https://example.com"
    from satellite.web.connect_token import ConnectTokenStore

    ctx.connect_tokens = ConnectTokenStore()
    ctx.telegram = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 1})
    ctx.telegram.answer_callback_query = MagicMock()
    return ctx


def _user_msg(*, text: str) -> IncomingMessage:
    return IncomingMessage(
        update_id=1,
        chat_id=CHAT_ID,
        user_id=USER_ID,
        username="newbie",
        display_name="New User",
        text=text,
    )


def _admin_cb(*, data: str, callback_id: str = "cb1") -> IncomingCallback:
    return IncomingCallback(
        update_id=2,
        callback_query_id=callback_id,
        chat_id=ADMIN_ID,
        message_id=10,
        user_id=ADMIN_ID,
        username="admin",
        data=data,
    )


def test_start_opens_access_request_and_notifies_admin(users: UserStore) -> None:
    ctx = _ctx(users)
    handle_start_or_help(ctx, _user_msg(text="/start"), is_start=True)

    record = users.get(USER_ID)
    assert record is not None
    assert record.status == USER_STATUS_PENDING
    assert record.access_request_status == ACCESS_REQUEST_PENDING
    assert record.chat_id == CHAT_ID
    assert users.list_pending_requests() == [record]

    user_msg = ctx.telegram.send_message.call_args_list[-1][0][1]
    assert user_msg == ACCESS_REQUEST_SENT_HTML
    admin_msg = ctx.telegram.send_message.call_args_list[0][0][1]
    assert "Новый пользователь" in admin_msg
    assert str(USER_ID) in admin_msg


def test_second_start_does_not_spam_admin(users: UserStore) -> None:
    ctx = _ctx(users)
    handle_start_or_help(ctx, _user_msg(text="/start"), is_start=True)
    ctx.telegram.send_message.reset_mock()

    handle_start_or_help(ctx, _user_msg(text="/start"), is_start=True)

    assert ctx.telegram.send_message.call_count == 1
    assert final_message_html(ctx.telegram) == ACCESS_PENDING_HTML


def test_help_opens_request_for_pending_user_without_prior_start(users: UserStore) -> None:
    ctx = _ctx(users)
    handle_start_or_help(ctx, _user_msg(text="/help"), is_start=False)

    record = users.get(USER_ID)
    assert record is not None
    assert record.access_request_status == ACCESS_REQUEST_PENDING
    assert users.list_pending_requests() == [record]

    assert final_message_html(ctx.telegram) == BOT_HELP_HTML
    admin_msg = ctx.telegram.send_message.call_args_list[0][0][1]
    assert "Новый пользователь" in admin_msg


def test_admin_approve_notifies_user(users: UserStore) -> None:
    users.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=CHAT_ID,
        username="newbie",
        display_name="New",
    )
    users.submit_access_request(USER_ID)
    ctx = _ctx(users)

    route_admin_callback(ctx, _admin_cb(data=f"{CB_ADMIN_APPROVE_PREFIX}{USER_ID}"))

    record = users.get(USER_ID)
    assert record is not None
    assert record.status == USER_STATUS_APPROVED
    assert users.list_pending_requests() == []
    ctx.telegram.answer_callback_query.assert_called_once_with("cb1", text=None)
    user_calls = [c for c in ctx.telegram.send_message.call_args_list if c[0][0] == CHAT_ID]
    assert len(user_calls) == 2
    assert user_calls[0][0][1] == ACCESS_APPROVED_HTML
    assert user_calls[0].kwargs["reply_markup"]["inline_keyboard"][0][0]["web_app"]
    assert user_calls[1][0][1] == ACCESS_APPROVED_KEYBOARD_HINT
    assert user_calls[1].kwargs["reply_markup"] == build_approved_main_keyboard()


def test_admin_reject_notifies_user(users: UserStore) -> None:
    users.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=CHAT_ID,
        username="newbie",
        display_name="New",
    )
    users.submit_access_request(USER_ID)
    ctx = _ctx(users)

    route_admin_callback(ctx, _admin_cb(data=f"{CB_ADMIN_REJECT_PREFIX}{USER_ID}"))

    record = users.get(USER_ID)
    assert record is not None
    assert record.status == USER_STATUS_REJECTED
    user_notify = final_message_html(ctx.telegram)
    assert user_notify == ACCESS_REJECTED_HTML


def test_non_admin_cannot_approve(users: UserStore) -> None:
    users.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=CHAT_ID,
        username="newbie",
        display_name="New",
    )
    users.submit_access_request(USER_ID)
    ctx = _ctx(users)
    cb = _admin_cb(data=f"{CB_ADMIN_APPROVE_PREFIX}{USER_ID}")
    cb = IncomingCallback(
        update_id=cb.update_id,
        callback_query_id=cb.callback_query_id,
        chat_id=USER_ID,
        message_id=cb.message_id,
        user_id=USER_ID,
        username=cb.username,
        data=cb.data,
    )

    route_admin_callback(ctx, cb)

    assert users.get(USER_ID).status == USER_STATUS_PENDING
    ctx.telegram.answer_callback_query.assert_called_with("cb1", text="Недостаточно прав")


def test_save_raises_persistence_error_on_disk_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError при записи не должен теряться: caller должен видеть исключение."""
    store = UserStore(tmp_path / "users.json")
    real_replace = __import__("os").replace

    def failing_replace(src: str, dst: str) -> None:
        if str(dst).endswith("users.json"):
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", failing_replace)

    with pytest.raises(UserStorePersistenceError):
        store.upsert_from_telegram(
            telegram_user_id=USER_ID,
            chat_id=CHAT_ID,
            username="newbie",
            display_name="New",
        )


def test_pending_command_lists_open_requests(users: UserStore) -> None:
    users.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=CHAT_ID,
        username="newbie",
        display_name="New",
    )
    users.submit_access_request(USER_ID)
    ctx = _ctx(users)
    msg = IncomingMessage(
        update_id=3,
        chat_id=ADMIN_ID,
        user_id=ADMIN_ID,
        username="admin",
        display_name="Admin",
        text="/pending",
    )

    handle_pending_command(ctx, msg)

    body = final_message_html(ctx.telegram)
    assert str(USER_ID) in body
    assert "New" in body
