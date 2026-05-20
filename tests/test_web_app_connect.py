"""Web App sendData → подключение календаря в боте."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from satellite.telegram_bot.handlers.calendar_setup import handle_web_app_connect
from satellite.telegram_bot.handlers.context import IncomingMessage
from satellite.users import USER_STATUS_APPROVED, UserStore


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    store = UserStore(tmp_path / "users.json")
    store.upsert_from_telegram(
        telegram_user_id=42,
        chat_id=42,
        username="alice",
        display_name="Alice",
        default_status=USER_STATUS_APPROVED,
    )
    return store


def _ctx(users: UserStore) -> MagicMock:
    ctx = MagicMock()
    ctx.users = users
    ctx.calendar_service = MagicMock()
    ctx.telegram = MagicMock()
    return ctx


def test_web_app_connect_calls_calendar_service(users: UserStore) -> None:
    ctx = _ctx(users)
    payload = json.dumps(
        {
            "action": "connect",
            "provider": "mailru",
            "login": "u@vk.team",
            "app_password": "secret",
        }
    )
    msg = IncomingMessage(
        update_id=1,
        chat_id=42,
        user_id=42,
        username="alice",
        display_name="Alice",
        text="",
        web_app_data=payload,
    )
    handle_web_app_connect(ctx, msg)
    ctx.calendar_service.connect.assert_called_once()
    ctx.telegram.send_message.assert_called_once()
