"""Тесты setChatMenuButton хелперов."""

from __future__ import annotations

from unittest.mock import MagicMock

from satellite.telegram_bot.visual import (
    set_default_menu_button,
    set_default_menu_button_for_chat,
    set_webapp_menu_button,
)


def test_set_webapp_menu_button_posts_web_app() -> None:
    telegram = MagicMock()
    set_webapp_menu_button(telegram, 123, "https://example.com/connect")
    telegram.set_chat_menu_button.assert_called_once()
    kwargs = telegram.set_chat_menu_button.call_args.kwargs
    assert kwargs["chat_id"] == 123
    assert kwargs["menu_button"]["type"] == "web_app"


def test_set_webapp_menu_button_empty_url_falls_back_to_commands() -> None:
    telegram = MagicMock()
    set_webapp_menu_button(telegram, 123, "")
    telegram.set_chat_menu_button.assert_called_once()
    assert telegram.set_chat_menu_button.call_args.kwargs["menu_button"] == {
        "type": "commands"
    }


def test_set_default_menu_button_global() -> None:
    telegram = MagicMock()
    set_default_menu_button(telegram)
    telegram.set_chat_menu_button.assert_called_once_with(
        menu_button={"type": "commands"}
    )


def test_set_default_menu_button_for_chat() -> None:
    telegram = MagicMock()
    set_default_menu_button_for_chat(telegram, 99)
    telegram.set_chat_menu_button.assert_called_once_with(
        chat_id=99,
        menu_button={"type": "commands"},
    )
