"""Визуальные улучшения Telegram Bot API: typing, effects, кнопка «Меню».

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
EFFECT_PARTY = "5046509860389126442"  # 🎉
EFFECT_FIRE = "5104841245755180586"  # 🔥
EFFECT_SPARKLES = "5089460564141278042"  # ✨
EFFECT_HEART = "5159385139981059251"  # ❤️

_MENU_BUTTON_COMMANDS: dict[str, str] = {"type": "commands"}

_CHAT_ACTION_REFRESH_SEC = 4.0


def is_private_chat(chat_id: int | None) -> bool:
    """Личный чат: положительный ``chat_id`` (группы/каналы — отрицательные)."""
    return isinstance(chat_id, int) and chat_id > 0


def private_message_effect(effect_id: str | None, chat_id: int | None) -> str | None:
    """``message_effect_id`` только в личных чатах."""
    if effect_id and is_private_chat(chat_id):
        return effect_id
    return None


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


def pick_invitations_effect(text: str) -> str | None:
    """Эффект для экрана приглашений, если есть что разбирать."""
    if "Приглашения" in text and "нет" not in text.lower():
        return EFFECT_SPARKLES
    return None


def pick_upcoming_message_effect(text: str) -> str | None:
    if "Ближайшие события" in text and "нет" not in text.lower():
        return EFFECT_SPARKLES
    return None


def pick_analytics_effect(*, load_percent: float | None = None) -> str | None:
    """Эффект для финальной подписи недельной аналитики."""
    if load_percent is None:
        return EFFECT_SPARKLES
    if load_percent >= 85:
        return EFFECT_FIRE
    if load_percent <= 35:
        return EFFECT_SPARKLES
    return EFFECT_PARTY


def send_with_effect(
    telegram: TelegramClient,
    chat_id: int,
    text: str,
    *,
    message_effect_id: str | None = None,
    reply_markup: dict | list | str | None = None,
    parse_mode: str | None = "HTML",
) -> dict[str, Any] | None:
    """``sendMessage`` с эффектом в личке и безопасным fallback."""
    try:
        return telegram.send_message(
            chat_id,
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_effect_id=private_message_effect(message_effect_id, chat_id),
        )
    except TelegramError as exc:
        log.warning("send_with_effect failed chat_id=%s: %s", chat_id, exc)
        return None


def set_default_menu_button(telegram: TelegramClient) -> None:
    """Глобально: кнопка «Меню» → список команд."""
    try:
        telegram.set_chat_menu_button(menu_button=_MENU_BUTTON_COMMANDS)
    except TelegramError as exc:
        log.debug("setChatMenuButton default skipped: %s", exc)


def set_webapp_menu_button(
    telegram: TelegramClient,
    chat_id: int,
    webapp_url: str,
    *,
    text: str = "📅 Календарь",
) -> None:
    """Per-chat: кнопка «Меню» открывает Web App connect."""
    if not webapp_url:
        set_default_menu_button_for_chat(telegram, chat_id)
        return
    try:
        telegram.set_chat_menu_button(
            chat_id=chat_id,
            menu_button={"type": "web_app", "text": text, "web_app": {"url": webapp_url}},
        )
    except TelegramError as exc:
        log.debug("setChatMenuButton web_app skipped chat=%s: %s", chat_id, exc)


def set_default_menu_button_for_chat(telegram: TelegramClient, chat_id: int) -> None:
    """Per-chat: сброс на список команд."""
    try:
        telegram.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=_MENU_BUTTON_COMMANDS,
        )
    except TelegramError as exc:
        log.debug("setChatMenuButton commands skipped chat=%s: %s", chat_id, exc)


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
