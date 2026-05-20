"""Регистрация команд бота в Telegram (меню рядом с полем ввода).

Telegram отрисовывает список команд из ``setMyCommands`` в кнопке «Меню» (или
``MenuButtonCommands``) рядом с полем ввода. Раз зарегистрированные команды
кешируются на стороне клиента, поэтому повторный вызов на каждом старте —
дёшево и идемпотентно: Telegram просто перезатирает старое описание.

Список ниже — единственный источник правды для UI-меню. Реальная маршрутизация
команд живёт в :mod:`satellite.telegram_bot.handlers`; короткие алиасы
(``td``/``tm``/``dat``) и текстовые кнопки старой reply-клавиатуры там
по-прежнему распознаются, но в меню Telegram не показываются.
"""

from __future__ import annotations

import logging
from typing import Iterable

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


def _to_payload(items: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"command": cmd, "description": desc} for cmd, desc in items]


def setup_bot_commands(
    telegram: TelegramClient,
    *,
    commands: Iterable[tuple[str, str]] = BOT_COMMANDS,
) -> bool:
    """Регистрирует команды бота в меню Telegram.

    Кнопку «Меню» (Web App, команды и т.д.) бот не трогает — её настраивают в
    BotFather. Возвращает ``True``, если ``setMyCommands`` прошёл; ``False`` при
    сбое. Падение не пробрасывается: бот должен подняться даже если Telegram
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
    except Exception:  # noqa: BLE001 - сетевой/JSON-сбой не должен валить бот
        success = False
        log.exception("Unexpected error while calling setMyCommands")

    return success
