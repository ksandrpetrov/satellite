"""Settings hub: callback routing и навигация назад."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import satellite.messages_ru as messages_core
from satellite.messages_ru import (
    CB_ANALYTICS_BACK,
    CB_DIGEST_BACK,
    CB_DIGEST_CLOSE,
    CB_PENDING_DIGEST_BACK,
    CB_SETTINGS_ANALYTICS,
    CB_SETTINGS_BACK,
    CB_SETTINGS_DIGEST,
    SETTINGS_HUB_TEXT,
)
from satellite.subscriptions import SubscriptionStore
from satellite.telegram_bot.handlers import handle_callback_query
from satellite.testing.delivery_helpers import callback_edit_html, callback_edit_was_called

from .conftest import make_callback, make_ctx, make_user_store

CHAT_ID = 8301
USER_ID = 8301


@pytest.fixture
def ctx(tmp_path: Path) -> MagicMock:
    users = make_user_store(tmp_path, approved_with_calendar=[USER_ID])
    store = SubscriptionStore(tmp_path / "subs.json")
    c = make_ctx(users, subscriptions=store)
    c.tz = ZoneInfo("Europe/Moscow")
    c.telegram.send_message = MagicMock(return_value={"message_id": 8300})
    c.telegram.edit_message_rich = MagicMock(return_value={"message_id": 8300})
    c.telegram.edit_message_text = MagicMock(return_value={})
    c.telegram.answer_callback_query = MagicMock(return_value=True)
    c.calendar_service.check_connection = MagicMock(return_value=MagicMock(connected=True))
    c.calendar_service.disconnect = MagicMock()
    return c


@pytest.mark.parametrize(
    "callback_data",
    [
        CB_SETTINGS_DIGEST,
        CB_SETTINGS_ANALYTICS,
        CB_SETTINGS_BACK,
    ],
)
def test_settings_hub_entry_callbacks_route(ctx: MagicMock, callback_data: str) -> None:
    handle_callback_query(
        ctx,
        make_callback(data=callback_data, chat_id=CHAT_ID, user_id=USER_ID),
    )
    assert callback_edit_was_called(ctx.telegram) or ctx.telegram.send_rich_message.called


def test_digest_back_returns_to_hub(ctx: MagicMock) -> None:
    handle_callback_query(
        ctx,
        make_callback(data=CB_DIGEST_BACK, chat_id=CHAT_ID, user_id=USER_ID),
    )
    text = callback_edit_html(ctx.telegram)
    assert SETTINGS_HUB_TEXT.split()[0] in text or "Настройки" in text
    ctx.telegram.answer_callback_query.assert_called()


def test_analytics_back_returns_to_hub(ctx: MagicMock) -> None:
    handle_callback_query(
        ctx,
        make_callback(data=CB_ANALYTICS_BACK, chat_id=CHAT_ID, user_id=USER_ID),
    )
    text = callback_edit_html(ctx.telegram)
    assert "Настройки" in text or SETTINGS_HUB_TEXT[:10] in text


def test_pending_digest_back_routes(ctx: MagicMock) -> None:
    handle_callback_query(
        ctx,
        make_callback(data=CB_PENDING_DIGEST_BACK, chat_id=CHAT_ID, user_id=USER_ID),
    )
    ctx.telegram.answer_callback_query.assert_called()


def test_unknown_callback_is_answered_without_crash(ctx: MagicMock) -> None:
    handle_callback_query(
        ctx,
        make_callback(data="totally_unknown_cb", chat_id=CHAT_ID, user_id=USER_ID),
    )
    ctx.telegram.answer_callback_query.assert_called()


def test_every_digest_callback_constant_has_handler(ctx: MagicMock) -> None:
    """Каждый CB_DIGEST_* (кроме prefix) обрабатывается route_settings_callback."""
    from satellite.telegram_bot.handlers.settings import route_settings_callback

    for name, value in sorted(
        (n, v) for n, v in vars(messages_core).items() if n.startswith("CB_DIGEST_")
    ):
        if name.endswith("_PREFIX"):
            continue
        if value in (CB_DIGEST_BACK, CB_DIGEST_CLOSE):
            continue
        claimed = route_settings_callback(
            ctx,
            make_callback(data=value, chat_id=CHAT_ID, user_id=USER_ID),
        )
        assert claimed, f"{name}={value!r} не обработан route_settings_callback"
