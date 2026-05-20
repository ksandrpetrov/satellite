"""Тесты регистрации команд бота в Telegram command menu.

Покрываем:
- ``setup_bot_commands`` вызывает ``setMyCommands`` со всем списком из ТЗ;
- ``setup_bot_commands`` включает ``MenuButtonCommands`` через ``setChatMenuButton``;
- падение Telegram API не пробрасывается наружу (бот должен подняться);
- ``TelegramClient.set_my_commands`` сериализует команды в JSON-payload.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.commands import BOT_COMMANDS, setup_bot_commands


# В меню сознательно нет /digest и /stopdigest: включение и отключение
# дайджеста делается из /settings (там же дни и время). Сами команды
# /digest и /stopdigest остаются рабочими как текстовые — см. handlers.py.
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
    """Меню Telegram содержит компактный набор без /digest и /stopdigest."""
    commands = [cmd for cmd, _desc in BOT_COMMANDS]
    assert commands == list(EXPECTED_COMMANDS)
    # /digest и /stopdigest не должны попадать в меню — они открываются из
    # /settings и продолжают работать только как набираемые команды.
    assert "digest" not in commands
    assert "stopdigest" not in commands
    # каждое описание непустое — иначе Telegram отрисует пустую строку
    for _cmd, desc in BOT_COMMANDS:
        assert desc and isinstance(desc, str)


def test_setup_bot_commands_registers_all_commands_and_menu_button():
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(return_value=True)
    telegram.set_chat_menu_button = MagicMock(return_value=True)

    ok = setup_bot_commands(telegram)

    assert ok is True
    telegram.set_my_commands.assert_called_once()
    payload = telegram.set_my_commands.call_args.args[0]
    assert [item["command"] for item in payload] == list(EXPECTED_COMMANDS)
    # каждая запись имеет описание
    for item in payload:
        assert "description" in item and item["description"]

    telegram.set_chat_menu_button.assert_called_once()
    menu_kw = telegram.set_chat_menu_button.call_args.kwargs
    assert menu_kw["menu_button"] == {"type": "commands"}


def test_setup_bot_commands_sets_webapp_menu_when_url_configured():
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(return_value=True)
    telegram.set_chat_menu_button = MagicMock(return_value=True)

    ok = setup_bot_commands(
        telegram, menu_webapp_url="https://example.com/connect"
    )

    assert ok is True
    menu_kw = telegram.set_chat_menu_button.call_args.kwargs
    assert menu_kw["menu_button"]["type"] == "web_app"
    assert menu_kw["menu_button"]["web_app"]["url"] == "https://example.com/connect"


def test_setup_bot_commands_does_not_raise_on_telegram_error(caplog):
    """Если Telegram API упал — мы логируем и возвращаем False, но не падаем."""
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(side_effect=TelegramError("nope"))
    telegram.set_chat_menu_button = MagicMock(return_value=True)

    with caplog.at_level("ERROR", logger="satellite.telegram_bot.commands"):
        ok = setup_bot_commands(telegram)

    assert ok is False
    # menu button всё равно пытаемся выставить — отдельная операция
    telegram.set_chat_menu_button.assert_called_once()
    assert any("setMyCommands" in r.getMessage() for r in caplog.records)


def test_setup_bot_commands_survives_menu_button_failure():
    telegram = MagicMock()
    telegram.set_my_commands = MagicMock(return_value=True)
    telegram.set_chat_menu_button = MagicMock(side_effect=TelegramError("nope"))

    ok = setup_bot_commands(telegram)
    assert ok is False
    telegram.set_my_commands.assert_called_once()


def test_telegram_client_set_my_commands_serializes_payload(monkeypatch):
    """``TelegramClient.set_my_commands`` шлёт JSON-сериализованные ``commands``."""
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
    assert "commands" in captured["data"]
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
