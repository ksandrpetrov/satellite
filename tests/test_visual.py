"""Юнит-тесты визуального слоя Telegram."""

from __future__ import annotations

from unittest.mock import MagicMock

from satellite.seagull import templates as t
from satellite.telegram_bot.visual import (
    EFFECT_FIRE,
    EFFECT_PARTY,
    EFFECT_SPARKLES,
    TypingIndicator,
    is_private_chat,
    pick_plan_message_effect,
    react_to_user_message,
)


def test_is_private_chat() -> None:
    assert is_private_chat(12345)
    assert not is_private_chat(-100123)
    assert not is_private_chat(None)


def test_pick_plan_effect_storm() -> None:
    assert pick_plan_message_effect(t.MAIN_STORM) == EFFECT_FIRE


def test_pick_plan_effect_empty() -> None:
    assert pick_plan_message_effect(t.MAIN_EMPTY) == EFFECT_SPARKLES


def test_pick_plan_effect_default() -> None:
    assert pick_plan_message_effect(t.MAIN_NORMAL) == EFFECT_PARTY


def test_typing_indicator_sends_chat_action() -> None:
    tg = MagicMock()
    tg.send_chat_action = MagicMock(return_value=True)
    indicator = TypingIndicator(tg, 42, action="typing")
    indicator.start()
    indicator.stop()
    assert tg.send_chat_action.call_count >= 1
    tg.send_chat_action.assert_called_with(42, "typing", message_thread_id=None)


def test_react_to_user_message() -> None:
    tg = MagicMock()
    tg.set_message_reaction = MagicMock(return_value=True)
    react_to_user_message(tg, 1, 99, emoji="🔥")
    tg.set_message_reaction.assert_called_once()
