"""Тесты доставки rich-сообщений с fallback на legacy HTML."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.message_delivery import deliver_rich_or_html, edit_rich_or_html


@pytest.fixture
def telegram() -> MagicMock:
    tg = MagicMock()
    tg.send_rich_message = MagicMock(return_value={"message_id": 1})
    tg.send_message = MagicMock(return_value={"message_id": 2})
    tg.edit_message_rich = MagicMock(return_value={"message_id": 3})
    tg.edit_message_text = MagicMock(return_value={"message_id": 4})
    return tg


def test_deliver_rich_or_html_uses_send_rich_message(telegram: MagicMock) -> None:
    result = deliver_rich_or_html(
        telegram,
        123,
        rich_html="<h2>Rich</h2>",
        fallback_html="<b>Legacy</b>",
    )
    assert result == {"message_id": 1}
    telegram.send_rich_message.assert_called_once()
    telegram.send_message.assert_not_called()


def test_deliver_rich_or_html_falls_back_when_method_unavailable(telegram: MagicMock) -> None:
    telegram.send_rich_message.side_effect = TelegramError(
        "Bad Request: method sendRichMessage not found"
    )
    result = deliver_rich_or_html(
        telegram,
        123,
        rich_html="<table><tr><td>x</td></tr></table>",
        fallback_html="<b>Legacy</b>",
        reply_markup={"inline_keyboard": []},
    )
    assert result == {"message_id": 2}
    telegram.send_message.assert_called_once_with(
        123,
        "<b>Legacy</b>",
        reply_markup={"inline_keyboard": []},
        message_effect_id=None,
    )


def test_deliver_rich_or_html_falls_back_on_other_telegram_error(telegram: MagicMock) -> None:
    telegram.send_rich_message.side_effect = TelegramError("Bad Request: RICH_PARSE_ERROR")
    deliver_rich_or_html(
        telegram,
        123,
        rich_html="<details open><summary>x</summary></details>",
        fallback_html="<b>Legacy</b>",
    )
    telegram.send_message.assert_called_once()


def test_edit_rich_or_html_falls_back_to_legacy_html(telegram: MagicMock) -> None:
    telegram.edit_message_rich.side_effect = TelegramError(
        "Bad Request: unknown method sendRichMessage"
    )
    edit_rich_or_html(
        telegram,
        123,
        55,
        rich_html="<h3>Rich</h3>",
        fallback_html="<b>Legacy</b>",
        reply_markup=None,
    )
    telegram.edit_message_text.assert_called_once_with(
        123,
        55,
        "<b>Legacy</b>",
        reply_markup=None,
    )
