"""Тесты доставки rich-сообщений с fallback на legacy HTML."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from satellite.presentation.delivery import deliver_rich_or_html, edit_rich_or_html
from satellite.telegram_bot.api import TelegramError


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


@pytest.mark.parametrize("edit", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
def test_embedded_callback_replaces_only_matching_keyboard_button(telegram, edit, fallback):
    from copy import deepcopy

    markup = {
        "inline_keyboard": [
            [{"text": "Ответить", "callback_data": "pick:1"}],
            [{"text": "Обновить", "callback_data": "refresh"}],
        ]
    }
    original = deepcopy(markup)
    rich = '<p>Meeting</p><tg-button-row><tg-button type="callback_data" data="pick:1">Ответить</tg-button></tg-button-row>'
    rich_method = telegram.edit_message_rich if edit else telegram.send_rich_message
    legacy_method = telegram.edit_message_text if edit else telegram.send_message
    if fallback:
        rich_method.side_effect = TelegramError("unsupported button")
    if edit:
        edit_rich_or_html(
            telegram, 1, 2, rich_html=rich, fallback_html="Meeting", reply_markup=markup
        )
    else:
        deliver_rich_or_html(
            telegram, 1, rich_html=rich, fallback_html="Meeting", reply_markup=markup
        )
    assert rich_method.call_args.kwargs["reply_markup"] == {
        "inline_keyboard": [original["inline_keyboard"][1]]
    }
    if fallback:
        assert legacy_method.call_args.kwargs["reply_markup"] == original
    else:
        legacy_method.assert_not_called()
    assert markup == original
