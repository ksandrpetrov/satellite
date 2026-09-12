"""Data-driven digest settings bindings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from satellite.subscriptions import SubscriptionStore
from satellite.telegram_bot.handlers.runtime import HandlerRuntime
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
    ctx.runtime = HandlerRuntime()
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


def test_partial_updates_keep_other_digest_and_unmentioned_fields(tmp_path: Path) -> None:
    from satellite.telegram_bot.handlers.settings_bindings import days_value, time_value

    store = SubscriptionStore(tmp_path / "subs.json")
    ctx = MagicMock()
    ctx.subscriptions = store
    before = store.update_settings(
        1,
        "alice",
        telegram_user_id=1,
        digest_enabled=True,
        digest_days="weekdays",
        digest_time="09:15",
        pending_digest_enabled=True,
        pending_digest_days="1010101",
        pending_digest_time="18:45",
    )
    for kind in ("daily", "pending"):
        binding = bindings_for(kind)
        updated = update_settings(
            ctx, 1, "alice", telegram_user_id=1, bindings=binding, enabled=False
        )
        assert enabled_value(updated, binding) is False
        assert days_value(updated, binding) == days_value(before, binding)
        assert time_value(updated, binding) == time_value(before, binding)
        other = bindings_for("pending" if kind == "daily" else "daily")
        assert enabled_value(updated, other) == enabled_value(before, other)
        assert days_value(updated, other) == days_value(before, other)
        assert time_value(updated, other) == time_value(before, other)
        before = updated
    reloaded = SubscriptionStore(tmp_path / "subs.json").get_or_create(
        1, "alice", telegram_user_id=1
    )
    assert reloaded == before
