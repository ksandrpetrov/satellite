"""Визуальные улучшения Telegram Bot API: typing, effects, реакции.

Используем только официальные методы Bot API (9.x–10.x). Всё best-effort:
при отказе API (группа, старый клиент, нет прав) сценарий не ломается.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from ..seagull import templates as seagull_templates
from .api import TelegramClient, TelegramError

if TYPE_CHECKING:
    from .handlers.context import HandlerContext, IncomingMessage

log = logging.getLogger(__name__)

# Animated message effects (private 1:1). ID из Bot API / MTProto effects.
EFFECT_PARTY = "5046509860389126442"  # 🎉
EFFECT_FIRE = "5104841245755180586"  # 🔥
EFFECT_SPARKLES = "5089460564141278042"  # ✨
EFFECT_HEART = "5159385139981059251"  # ❤️
EFFECT_THUMBS_UP = "5107584321108051014"  # 👍

_MENU_BUTTON_COMMANDS: dict[str, str] = {"type": "commands"}

# Сценарии для pick_scenario_reaction / react_to_command
SCENARIO_PLAN = "plan"
SCENARIO_UPCOMING = "upcoming"
SCENARIO_INVITATIONS = "invitations"
SCENARIO_MANAGE = "manage"
SCENARIO_CREATE = "create"
SCENARIO_START_APPROVED = "start_approved"
SCENARIO_CONNECT = "connect"
SCENARIO_SUBSCRIBE = "subscribe"
SCENARIO_ADMIN_PENDING = "admin_pending"
SCENARIO_INVITATION_RESPOND = "invitation_respond"
SCENARIO_MANAGE_RESPOND = "manage_respond"

REACTION_PARTY = "🎉"
REACTION_FIRE = "🔥"
REACTION_HEART = "❤️"
REACTION_EYES = "👀"
REACTION_WRITING_HAND = "✍️"
REACTION_OK_HAND = "✅"
REACTION_THINKING = "🤔"

_CHAT_ACTION_REFRESH_SEC = 4.0

# Реакции с is_big=True — финальные «праздничные» жесты.
_BIG_REACTIONS = frozenset({REACTION_PARTY, REACTION_HEART, REACTION_FIRE, REACTION_OK_HAND})


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


def pick_upcoming_message_effect(text: str) -> str | None:
    if "Ближайшие события" in text and "нет" not in text.lower():
        return EFFECT_SPARKLES
    return None


def pick_scenario_reaction(
    scenario: str,
    *,
    plan_html: str | None = None,
) -> str:
    """Emoji для ``setMessageReaction`` по контексту команды."""
    if scenario == SCENARIO_PLAN and plan_html:
        if seagull_templates.MAIN_STORM in plan_html or seagull_templates.MAIN_DENSE in plan_html:
            return REACTION_FIRE
        return REACTION_PARTY
    mapping = {
        SCENARIO_UPCOMING: REACTION_EYES,
        SCENARIO_INVITATIONS: REACTION_EYES,
        SCENARIO_MANAGE: REACTION_EYES,
        SCENARIO_CREATE: REACTION_WRITING_HAND,
        SCENARIO_START_APPROVED: REACTION_HEART,
        SCENARIO_CONNECT: REACTION_OK_HAND,
        SCENARIO_SUBSCRIBE: REACTION_PARTY,
        SCENARIO_ADMIN_PENDING: REACTION_EYES,
        SCENARIO_INVITATION_RESPOND: REACTION_PARTY,
        SCENARIO_MANAGE_RESPOND: REACTION_PARTY,
    }
    return mapping.get(scenario, REACTION_PARTY)


def react_to_user_message(
    telegram: TelegramClient,
    chat_id: int | None,
    message_id: int | None,
    *,
    emoji: str = "🎉",
    is_big: bool | None = None,
) -> None:
    """Ставит реакцию на сообщение пользователя (команда / кнопка). Best-effort."""
    if chat_id is None or message_id is None:
        return
    if not is_private_chat(chat_id):
        return
    big = is_big if is_big is not None else emoji in _BIG_REACTIONS
    try:
        telegram.set_message_reaction(
            chat_id,
            message_id,
            reaction=[{"type": "emoji", "emoji": emoji}],
            is_big=big,
        )
    except TelegramError as exc:
        log.debug("setMessageReaction skipped: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.debug("setMessageReaction unexpected failure: %s", exc)


def react_to_command(
    ctx: HandlerContext,
    msg: IncomingMessage,
    scenario: str,
    *,
    plan_html: str | None = None,
) -> None:
    """Реакция на исходное сообщение пользователя по сценарию."""
    emoji = pick_scenario_reaction(scenario, plan_html=plan_html)
    react_to_user_message(
        ctx.telegram,
        msg.chat_id,
        msg.message_id,
        emoji=emoji,
    )


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
