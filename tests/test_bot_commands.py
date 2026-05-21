"""Тесты регистрации идентичности бота в Telegram."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.commands import BOT_COMMANDS, setup_bot_commands, setup_bot_identity

EXPECTED_COMMANDS = (
    "start",
    "today",
    "tomorrow",
    "aftertomorrow",
    "upcoming",
    "invitations",
    "manage",
    "create",
    "settings",
    "help",
)


def test_bot_commands_list_matches_spec():
    commands = [cmd for cmd, _desc in BOT_COMMANDS]
    assert commands == list(EXPECTED_COMMANDS)
    assert "digest" not in commands
    assert "stopdigest" not in commands
    for _cmd, desc in BOT_COMMANDS:
        assert desc and isinstance(desc, str)


def test_setup_bot_identity_registers_all_steps():
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(return_value=True)
    telegram.set_my_name = MagicMock(return_value=True)
    telegram.set_my_short_description = MagicMock(return_value=True)
    telegram.set_my_description = MagicMock(return_value=True)
    telegram.set_chat_menu_button = MagicMock(return_value=True)

    ok = setup_bot_identity(telegram)

    assert ok is True
    telegram.set_my_commands.assert_called_once()
    payload = telegram.set_my_commands.call_args.args[0]
    assert [item["command"] for item in payload] == list(EXPECTED_COMMANDS)
    telegram.set_my_name.assert_called_once()
    telegram.set_my_short_description.assert_called_once()
    telegram.set_my_description.assert_called_once()
    telegram.set_chat_menu_button.assert_called_once_with(menu_button={"type": "commands"})


def test_setup_bot_commands_is_alias():
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(return_value=True)
    telegram.set_my_name = MagicMock(return_value=True)
    telegram.set_my_short_description = MagicMock(return_value=True)
    telegram.set_my_description = MagicMock(return_value=True)
    telegram.set_chat_menu_button = MagicMock(return_value=True)

    assert setup_bot_commands(telegram) is True
    assert telegram.set_my_commands.called


def test_setup_bot_identity_does_not_raise_on_telegram_error(caplog):
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(side_effect=TelegramError("nope"))
    telegram.set_my_name = MagicMock(return_value=True)
    telegram.set_my_short_description = MagicMock(return_value=True)
    telegram.set_my_description = MagicMock(return_value=True)
    telegram.set_chat_menu_button = MagicMock(return_value=True)

    with caplog.at_level("ERROR", logger="satellite.telegram_bot.commands"):
        ok = setup_bot_identity(telegram)

    assert ok is False
    assert any("setMyCommands" in r.getMessage() for r in caplog.records)


def test_telegram_client_set_my_commands_serializes_payload(monkeypatch):
    from satellite.telegram_bot.api import TelegramClient

    client = TelegramClient("test-token")
    captured: dict = {}

    def fake_call(method_name, *, data=None, timeout=None, max_retries=None, **_):
        captured["method"] = method_name
        captured["data"] = data
        return True

    monkeypatch.setattr(client, "_call", fake_call)

    payload = [
        {"command": "start", "description": "Перезапустить бота"},
        {"command": "today", "description": "Встречи на сегодня"},
    ]
    client.set_my_commands(payload)

    assert captured["method"] == "setMyCommands"
    decoded = json.loads(captured["data"]["commands"])
    assert decoded == payload


def test_telegram_client_set_chat_menu_button_serializes_menu(monkeypatch):
    from satellite.telegram_bot.api import TelegramClient

    client = TelegramClient("test-token")
    captured: dict = {}

    def fake_call(method_name, *, data=None, timeout=None, max_retries=None, **_):
        captured["method"] = method_name
        captured["data"] = data
        return True

    monkeypatch.setattr(client, "_call", fake_call)

    client.set_chat_menu_button(menu_button={"type": "commands"})

    assert captured["method"] == "setChatMenuButton"
    decoded = json.loads(captured["data"]["menu_button"])
    assert decoded == {"type": "commands"}
