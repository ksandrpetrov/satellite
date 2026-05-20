"""Тесты подбора реакций и сценариев visual.py."""

from __future__ import annotations

from satellite.seagull import templates as seagull_templates
from satellite.telegram_bot.visual import (
    SCENARIO_PLAN,
    SCENARIO_UPCOMING,
    pick_plan_message_effect,
    pick_scenario_reaction,
)


def test_pick_scenario_reaction_plan_storm() -> None:
    html = seagull_templates.MAIN_STORM + " rest"
    assert pick_scenario_reaction(SCENARIO_PLAN, plan_html=html) == "🔥"


def test_pick_scenario_reaction_plan_default_party() -> None:
    html = seagull_templates.MAIN_LIGHT
    assert pick_scenario_reaction(SCENARIO_PLAN, plan_html=html) == "🎉"


def test_pick_scenario_reaction_upcoming_eyes() -> None:
    assert pick_scenario_reaction(SCENARIO_UPCOMING) == "👀"


def test_pick_plan_message_effect_storm() -> None:
    assert pick_plan_message_effect(seagull_templates.MAIN_STORM) is not None
