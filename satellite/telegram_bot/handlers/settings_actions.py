"""Reusable settings/calendar actions shared across entrypoints."""

from __future__ import annotations

import logging

from ...users.store import UserStorePersistenceError
from .context import HandlerContext

log = logging.getLogger(__name__)


def toggle_weather_in_plan(ctx: HandlerContext, user_id: int) -> bool | None:
    """Flip weather-in-plan flag and return the new value."""
    record = ctx.users.get(user_id)
    if record is None:
        return None
    new_enabled = not record.weather_in_plan_enabled
    try:
        ctx.users.set_weather_in_plan_enabled(user_id, enabled=new_enabled)
    except KeyError:
        return None
    except UserStorePersistenceError:
        log.exception("Failed to persist weather_in_plan for user_id=%s", user_id)
        raise
    return new_enabled
