"""Регистрация идентичности бота в Telegram (меню, профиль, кнопка «Меню»).

На каждом старте идемпотентно вызываем ``setMyCommands``, ``setMyName``,
``setMyDescription``, ``setMyShortDescription`` и дефолтный
``setChatMenuButton`` (список команд). Per-chat ``MenuButtonWebApp`` ставится
в хендлерах при подключении календаря.
"""

from __future__ import annotations

import logging
from typing import Iterable

from ..messages_ru import (
    BOT_DESCRIPTION_RU,
    BOT_NAME_RU,
    BOT_SHORT_DESCRIPTION_RU,
)
from .api import TelegramClient, TelegramError

log = logging.getLogger(__name__)


# (command, description). Описания пишем без ведущего слэша — Telegram сам
# добавит его в меню. Порядок задаёт порядок отображения в клиенте.
#
# В меню сознательно нет /digest и /stopdigest: включение и отключение дайджеста
# доступны из /settings (там же, где настройки дней и времени), чтобы меню не
# распухало и подписка управлялась в одном месте. Сами команды /digest и
# /stopdigest по-прежнему работают как текстовые — см. handlers.py.
BOT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "Перезапустить бота"),
    ("today", "Встречи на сегодня"),
    ("tomorrow", "Встречи на завтра"),
    ("aftertomorrow", "Встречи на послезавтра"),
    ("upcoming", "Ближайшие события"),
    ("invitations", "Ответить на приглашения"),
    ("manage", "Изменить статус встречи"),
    ("create", "Создать событие"),
    ("settings", "Настройки"),
    ("help", "Как пользоваться ботом"),
)

_MENU_BUTTON_COMMANDS: dict[str, str] = {"type": "commands"}


def _to_payload(items: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"command": cmd, "description": desc} for cmd, desc in items]


def setup_bot_identity(
    telegram: TelegramClient,
    *,
    commands: Iterable[tuple[str, str]] = BOT_COMMANDS,
) -> bool:
    """Регистрирует команды, профиль и дефолтную кнопку «Меню» в Telegram.

    Возвращает ``True``, если все шаги прошли; ``False`` при любом сбое.
    Исключения не пробрасываются — бот должен подняться даже если Telegram
    временно не отвечает.
    """
    payload = _to_payload(commands)
    success = True

    try:
        telegram.set_my_commands(payload)
        log.info("Registered %d bot commands in Telegram menu", len(payload))
    except TelegramError as exc:
        success = False
        log.error("Failed to register bot commands via setMyCommands: %s", exc)
    except Exception:  # noqa: BLE001
        success = False
        log.exception("Unexpected error while calling setMyCommands")

    try:
        telegram.set_my_name(BOT_NAME_RU)
        log.info("Registered bot name via setMyName")
    except TelegramError as exc:
        success = False
        log.error("Failed setMyName: %s", exc)
    except Exception:  # noqa: BLE001
        success = False
        log.exception("Unexpected error while calling setMyName")

    try:
        telegram.set_my_short_description(BOT_SHORT_DESCRIPTION_RU)
        log.info("Registered bot short description via setMyShortDescription")
    except TelegramError as exc:
        success = False
        log.error("Failed setMyShortDescription: %s", exc)
    except Exception:  # noqa: BLE001
        success = False
        log.exception("Unexpected error while calling setMyShortDescription")

    try:
        telegram.set_my_description(BOT_DESCRIPTION_RU)
        log.info("Registered bot description via setMyDescription")
    except TelegramError as exc:
        success = False
        log.error("Failed setMyDescription: %s", exc)
    except Exception:  # noqa: BLE001
        success = False
        log.exception("Unexpected error while calling setMyDescription")

    try:
        telegram.set_chat_menu_button(menu_button=_MENU_BUTTON_COMMANDS)
        log.info("Registered default MenuButtonCommands via setChatMenuButton")
    except TelegramError as exc:
        success = False
        log.error("Failed setChatMenuButton: %s", exc)
    except Exception:  # noqa: BLE001
        success = False
        log.exception("Unexpected error while calling setChatMenuButton")

    return success


def setup_bot_commands(
    telegram: TelegramClient,
    *,
    commands: Iterable[tuple[str, str]] = BOT_COMMANDS,
) -> bool:
    """Обратная совместимость: алиас ``setup_bot_identity``."""
    return setup_bot_identity(telegram, commands=commands)
