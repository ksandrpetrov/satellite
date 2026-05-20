"""Визуальные улучшения Telegram Bot API: typing, effects, реакции.

Используем только официальные методы Bot API (9.x–10.x). Всё best-effort:
при отказе API (группа, старый клиент, нет прав) сценарий не ломается.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ..seagull import templates as seagull_templates
from .api import TelegramClient, TelegramError

log = logging.getLogger(__name__)

# Animated message effects (private 1:1). ID из Bot API / MTProto effects.
# https://core.telegram.org/bots/api#sendmessage — message_effect_id
EFFECT_PARTY = "5046509860389126442"  # 🎉
EFFECT_FIRE = "5104841245755180586"  # 🔥
EFFECT_SPARKLES = "5089460564141278042"  # ✨
EFFECT_HEART = "5159385139981059251"  # ❤️

_CHAT_ACTION_REFRESH_SEC = 4.0


def is_private_chat(chat_id: int | None) -> bool:
    """Личный чат: положительный ``chat_id`` (группы/каналы — отрицательные)."""
    return isinstance(chat_id, int) and chat_id > 0


def pick_plan_message_effect(plan_html: str) -> str | None:
    """Подбирает эффект финального дайджеста по фразам из ``seagull.templates``."""
    if not plan_html:
        return None
    if seagull_templates.MAIN_STORM in plan_html:
        return EFFECT_FIRE
    if seagull_templates.MAIN_DENSE in plan_html:
        return EFFECT_FIRE
    if seagull_templates.MAIN_EMPTY in plan_html:
        return EFFECT_SPARKLES
    if seagull_templates.MAIN_LIGHT in plan_html:
        return EFFECT_SPARKLES
    return EFFECT_PARTY


def pick_upcoming_message_effect(text: str) -> str | None:
    if "Ближайшие события" in text and "нет" not in text.lower():
        return EFFECT_SPARKLES
    return None


class TypingIndicator:
    """Фоновый ``sendChatAction`` пока идёт долгая операция.

    Telegram сбрасывает статус через ~5 с — поэтому обновляем каждые 4 с.
    """

    def __init__(
        self,
        telegram: TelegramClient,
        chat_id: int,
        *,
        action: str = "typing",
        message_thread_id: int | None = None,
    ) -> None:
        self._telegram = telegram
        self._chat_id = chat_id
        self._action = action
        self._message_thread_id = message_thread_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._send_once()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"typing-{self._chat_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(_CHAT_ACTION_REFRESH_SEC):
            self._send_once()

    def _send_once(self) -> None:
        try:
            self._telegram.send_chat_action(
                self._chat_id,
                self._action,
                message_thread_id=self._message_thread_id,
            )
        except TelegramError as exc:
            log.debug("sendChatAction skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.debug("sendChatAction unexpected failure: %s", exc)


def react_to_user_message(
    telegram: TelegramClient,
    chat_id: int | None,
    message_id: int | None,
    *,
    emoji: str = "🎉",
    is_big: bool = True,
) -> None:
    """Ставит реакцию на сообщение пользователя (команда / кнопка). Best-effort."""
    if chat_id is None or message_id is None:
        return
    try:
        telegram.set_message_reaction(
            chat_id,
            message_id,
            reaction=[{"type": "emoji", "emoji": emoji}],
            is_big=is_big,
        )
    except TelegramError as exc:
        log.debug("setMessageReaction skipped: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.debug("setMessageReaction unexpected failure: %s", exc)
