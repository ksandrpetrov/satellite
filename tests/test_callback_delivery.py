"""Порядок Telegram API в callback-хелперах доставки."""

from __future__ import annotations

from unittest.mock import MagicMock

from satellite.telegram_bot.handlers.context import IncomingCallback
from satellite.telegram_bot.handlers.delivery import (
    ack_callback_with_loading,
    respond_callback_nav,
)
from satellite.telegram_bot.presenters.bundle import ScreenBundle

from .conftest import make_fake_telegram


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.telegram = make_fake_telegram()
    return ctx


def _cb() -> IncomingCallback:
    return IncomingCallback(
        update_id=1,
        callback_query_id="cb-delivery",
        chat_id=900,
        message_id=42,
        user_id=1,
        username="alice",
        data="test",
    )


def test_ack_callback_with_loading_acks_before_edit() -> None:
    ctx = _ctx()
    cb = _cb()
    manager = MagicMock()
    manager.attach_mock(ctx.telegram.answer_callback_query, "ack")
    manager.attach_mock(ctx.telegram.edit_message_text, "edit")

    ack_callback_with_loading(
        ctx,
        cb,
        status_html="⏳ Загружаю…",
        toast="Загружаю…",
    )

    call_names = [call[0] for call in manager.mock_calls]
    assert call_names.index("ack") < call_names.index("edit")


def test_respond_callback_nav_acks_before_edit() -> None:
    ctx = _ctx()
    cb = _cb()
    bundle = ScreenBundle(
        rich_html="<b>Экран</b>",
        fallback_html="<b>Экран</b>",
        reply_markup={"inline_keyboard": []},
    )
    manager = MagicMock()
    manager.attach_mock(ctx.telegram.answer_callback_query, "ack")
    manager.attach_mock(ctx.telegram.edit_message_rich, "edit")

    respond_callback_nav(ctx, cb, bundle, toast="Готово")

    call_names = [call[0] for call in manager.mock_calls]
    assert call_names.index("ack") < call_names.index("edit")
    ctx.telegram.answer_callback_query.assert_called_with("cb-delivery", text="Готово")
