"""Data-driven digest settings bindings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from satellite.subscriptions import SubscriptionStore
from satellite.telegram_bot.handlers.settings_bindings import (
    BINDINGS,
    bindings_for,
    enabled_value,
    update_settings,
)
from satellite.telegram_bot.handlers.settings_callbacks import DIGEST_KIND_DAILY


def test_bindings_cover_daily_and_pending() -> None:
    assert set(BINDINGS) == {"daily", "pending"}


def test_update_settings_toggle_enabled(tmp_path: Path) -> None:
    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(1, "alice", telegram_user_id=1)
    settings = store.get_or_create(1, "alice", telegram_user_id=1)
    bindings = bindings_for(DIGEST_KIND_DAILY)
    ctx = MagicMock()
    ctx.subscriptions = store
    updated = update_settings(
        ctx,
        1,
        "alice",
        telegram_user_id=1,
        bindings=bindings,
        enabled=not enabled_value(settings, bindings),
    )
    assert updated.digest_enabled is not enabled_value(settings, bindings)
