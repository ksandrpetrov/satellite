"""Юнит-тесты ``edit_or_send_message``: попытка редактирования и fallback на send."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.message_editing import edit_or_send_message


def _fake_telegram() -> MagicMock:
    telegram = MagicMock()
    telegram.edit_message_text = MagicMock(return_value={"message_id": 7, "edited": True})
    telegram.send_message = MagicMock(return_value={"message_id": 8})
    return telegram


def test_edit_succeeds_no_new_message_sent() -> None:
    telegram = _fake_telegram()

    result = edit_or_send_message(
        telegram,
        chat_id=42,
        message_id=7,
        text="<b>Готово</b>",
    )

    assert result == {"message_id": 7, "edited": True}
    telegram.edit_message_text.assert_called_once()
    telegram.send_message.assert_not_called()


def test_edit_propagates_parse_mode_and_keyboard() -> None:
    telegram = _fake_telegram()
    keyboard = {"keyboard": [[{"text": "Сегодня"}]], "resize_keyboard": True}

    edit_or_send_message(
        telegram,
        chat_id=42,
        message_id=7,
        text="итог",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
        disable_web_page_preview=False,
    )

    kwargs = telegram.edit_message_text.call_args.kwargs
    assert kwargs["parse_mode"] == "MarkdownV2"
    assert kwargs["reply_markup"] == keyboard
    assert kwargs["disable_web_page_preview"] is False


def test_edit_fails_then_falls_back_to_send(caplog: pytest.LogCaptureFixture) -> None:
    telegram = _fake_telegram()
    telegram.edit_message_text = MagicMock(
        side_effect=TelegramError("Bad Request: message is not modified")
    )

    with caplog.at_level(logging.WARNING, logger="satellite.telegram_bot.message_editing"):
        result = edit_or_send_message(
            telegram,
            chat_id=42,
            message_id=7,
            text="итог",
            parse_mode="HTML",
        )

    assert result == {"message_id": 8}
    telegram.edit_message_text.assert_called_once()
    telegram.send_message.assert_called_once()
    send_kwargs = telegram.send_message.call_args.kwargs
    assert send_kwargs["parse_mode"] == "HTML"
    assert any(
        record.levelno == logging.WARNING
        and "Falling back to new message" in record.getMessage()
        for record in caplog.records
    )


def test_fallback_can_use_keyboard_without_passing_it_to_edit() -> None:
    telegram = _fake_telegram()
    telegram.edit_message_text = MagicMock(
        side_effect=TelegramError("Bad Request: message can't be edited")
    )
    keyboard = {"keyboard": [[{"text": "Сегодня"}]], "resize_keyboard": True}

    edit_or_send_message(
        telegram,
        chat_id=42,
        message_id=7,
        text="итог",
        reply_markup=None,
        fallback_reply_markup=keyboard,
    )

    edit_kwargs = telegram.edit_message_text.call_args.kwargs
    send_kwargs = telegram.send_message.call_args.kwargs
    assert edit_kwargs["reply_markup"] is None
    assert send_kwargs["reply_markup"] == keyboard


def test_unexpected_edit_exception_also_falls_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telegram = _fake_telegram()
    telegram.edit_message_text = MagicMock(side_effect=RuntimeError("oops"))

    with caplog.at_level(logging.WARNING, logger="satellite.telegram_bot.message_editing"):
        result = edit_or_send_message(
            telegram,
            chat_id=10,
            message_id=99,
            text="итог",
        )

    assert result == {"message_id": 8}
    telegram.send_message.assert_called_once()
    assert any(
        record.levelno == logging.WARNING
        and "Unexpected error editing message" in record.getMessage()
        for record in caplog.records
    )


def test_missing_message_id_sends_directly_without_edit() -> None:
    telegram = _fake_telegram()

    result = edit_or_send_message(
        telegram,
        chat_id=42,
        message_id=None,
        text="итог",
    )

    assert result == {"message_id": 8}
    telegram.edit_message_text.assert_not_called()
    telegram.send_message.assert_called_once()


def test_send_kwargs_default_to_html_and_preview_disabled() -> None:
    telegram = _fake_telegram()

    edit_or_send_message(telegram, chat_id=1, message_id=None, text="x")

    kwargs = telegram.send_message.call_args.kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["disable_web_page_preview"] is True
    assert kwargs["reply_markup"] is None


def test_send_failure_propagates() -> None:
    telegram = _fake_telegram()
    telegram.edit_message_text = MagicMock(side_effect=TelegramError("nope"))
    telegram.send_message = MagicMock(side_effect=TelegramError("network down"))

    with pytest.raises(TelegramError, match="network down"):
        edit_or_send_message(telegram, chat_id=1, message_id=2, text="x")
