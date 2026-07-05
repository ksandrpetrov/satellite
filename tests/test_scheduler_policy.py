"""Unit tests for satellite.scheduler_policy."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from satellite.scheduler_policy import should_fire_at, should_fire_for_user
from satellite.subscriptions import DIGEST_DAYS_WEEKDAYS, DigestSettings

TZ = ZoneInfo("Europe/Moscow")


def _settings(**kwargs) -> DigestSettings:
    base = dict(
        chat_id=1,
        telegram_user_id=1,
        username="alice",
        digest_enabled=True,
        digest_days=DIGEST_DAYS_WEEKDAYS,
        digest_time="09:00",
        digest_timezone="Europe/Moscow",
        last_digest_sent_date=None,
    )
    base.update(kwargs)
    return DigestSettings(**base)


def test_should_fire_at_invalid_time_returns_false() -> None:
    now = datetime(2026, 5, 11, 9, 0, tzinfo=TZ)
    assert not should_fire_at(
        enabled=True,
        days=DIGEST_DAYS_WEEKDAYS,
        time_str="not-a-time",
        last_sent_iso=None,
        now_in_user_tz=now,
        chat_id=1,
    )


def test_should_fire_for_user_delegates_to_should_fire_at() -> None:
    now = datetime(2026, 5, 11, 9, 0, tzinfo=TZ)
    assert should_fire_for_user(settings=_settings(), now_in_user_tz=now)
