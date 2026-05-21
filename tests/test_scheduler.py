"""Тесты планировщика per-user дайджеста.

Старый ``should_fire``/``_LastFiredStore`` ушли вместе с переходом на
индивидуальные расписания: теперь решение принимается на каждого подписчика
отдельно (см. ``should_fire_for_user``), а защита от двойной отправки живёт
в ``SubscriptionStore.mark_digest_sent``.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from satellite.config import DigestConfig
from satellite.digest_utils import is_digest_day_allowed, resolve_target_date
from satellite.invitations_view import InvitationsScreen
from satellite.scheduler import (
    DigestScheduler,
    should_fire_for_user,
    should_fire_pending_for_user,
)
from satellite.subscriptions import (
    DIGEST_DAYS_ALL,
    DIGEST_DAYS_WEEKDAYS,
    DigestSettings,
    SubscriptionStore,
)
from satellite.telegram_bot.api import TelegramError
from satellite.users import USER_STATUS_APPROVED, UserStore

TZ = ZoneInfo("Europe/Moscow")


def _at(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _settings(
    chat_id: int = 1,
    *,
    enabled: bool = True,
    days: str = DIGEST_DAYS_WEEKDAYS,
    time_str: str = "09:00",
    last_sent: str | None = None,
) -> DigestSettings:
    return DigestSettings(
        chat_id=chat_id,
        telegram_user_id=chat_id,
        username="alice",
        digest_enabled=enabled,
        digest_days=days,
        digest_time=time_str,
        digest_timezone="Europe/Moscow",
        last_digest_sent_date=last_sent,
    )


# --- should_fire_for_user ---------------------------------------------------


def test_fires_when_time_matches_and_weekday_ok():
    # 2026-05-11 — понедельник
    assert should_fire_for_user(
        settings=_settings(time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 11, 9, 0),
    )


def test_does_not_fire_when_disabled():
    assert not should_fire_for_user(
        settings=_settings(enabled=False, time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 11, 9, 0),
    )


def test_does_not_fire_when_minute_differs():
    assert not should_fire_for_user(
        settings=_settings(time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 11, 9, 1),
    )
    assert not should_fire_for_user(
        settings=_settings(time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 11, 8, 59),
    )


def test_does_not_fire_on_saturday_for_weekdays_mode():
    # 2026-05-09 — суббота
    assert not should_fire_for_user(
        settings=_settings(days=DIGEST_DAYS_WEEKDAYS, time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 9, 9, 0),
    )


def test_does_not_fire_on_sunday_for_weekdays_mode():
    # 2026-05-10 — воскресенье
    assert not should_fire_for_user(
        settings=_settings(days=DIGEST_DAYS_WEEKDAYS, time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 10, 9, 0),
    )


def test_fires_on_weekend_for_all_days_mode():
    assert should_fire_for_user(
        settings=_settings(days=DIGEST_DAYS_ALL, time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 9, 9, 0),
    )
    assert should_fire_for_user(
        settings=_settings(days=DIGEST_DAYS_ALL, time_str="09:00"),
        now_in_user_tz=_at(2026, 5, 10, 9, 0),
    )


def test_fires_at_custom_time():
    assert should_fire_for_user(
        settings=_settings(time_str="08:30"),
        now_in_user_tz=_at(2026, 5, 11, 8, 30),
    )
    assert not should_fire_for_user(
        settings=_settings(time_str="08:30"),
        now_in_user_tz=_at(2026, 5, 11, 9, 0),
    )


def test_does_not_fire_if_already_sent_today():
    assert not should_fire_for_user(
        settings=_settings(time_str="09:00", last_sent="2026-05-11"),
        now_in_user_tz=_at(2026, 5, 11, 9, 0),
    )


def test_fires_again_next_day():
    # вчера отправляли, сегодня — новая отправка.
    assert should_fire_for_user(
        settings=_settings(time_str="09:00", last_sent="2026-05-10"),
        now_in_user_tz=_at(2026, 5, 11, 9, 0),
    )


def test_invalid_digest_time_does_not_fire():
    assert not should_fire_for_user(
        settings=_settings(time_str="bad-value"),
        now_in_user_tz=_at(2026, 5, 11, 9, 0),
    )


def _settings_pending(
    chat_id: int = 1,
    *,
    enabled: bool = True,
    days: str = DIGEST_DAYS_WEEKDAYS,
    time_str: str = "10:00",
    last_sent: str | None = None,
) -> DigestSettings:
    base = _settings(
        chat_id,
        enabled=False,
        days=days,
        time_str="09:00",
    )
    return DigestSettings(
        chat_id=base.chat_id,
        telegram_user_id=base.telegram_user_id,
        username=base.username,
        digest_enabled=False,
        digest_days=base.digest_days,
        digest_time=base.digest_time,
        digest_timezone=base.digest_timezone,
        pending_digest_enabled=enabled,
        pending_digest_days=days,
        pending_digest_time=time_str,
        pending_digest_timezone=base.digest_timezone,
        last_pending_digest_sent_date=last_sent,
    )


def test_pending_fires_at_default_time():
    assert should_fire_pending_for_user(
        settings=_settings_pending(time_str="10:00"),
        now_in_user_tz=_at(2026, 5, 11, 10, 0),
    )


def test_pending_does_not_fire_if_already_sent_today():
    assert not should_fire_pending_for_user(
        settings=_settings_pending(time_str="10:00", last_sent="2026-05-11"),
        now_in_user_tz=_at(2026, 5, 11, 10, 0),
    )


# --- is_digest_day_allowed --------------------------------------------------


def test_is_day_allowed_weekdays():
    for wd in (0, 1, 2, 3, 4):
        assert is_digest_day_allowed(DIGEST_DAYS_WEEKDAYS, wd)
    assert not is_digest_day_allowed(DIGEST_DAYS_WEEKDAYS, 5)
    assert not is_digest_day_allowed(DIGEST_DAYS_WEEKDAYS, 6)


def test_is_day_allowed_all_days():
    for wd in range(7):
        assert is_digest_day_allowed(DIGEST_DAYS_ALL, wd)


# --- resolve_target_date ----------------------------------------------------


def test_resolve_target_date():
    today = date(2026, 5, 11)
    assert resolve_target_date("today", today) == date(2026, 5, 11)
    assert resolve_target_date("tomorrow", today) == date(2026, 5, 12)
    assert resolve_target_date("day_after_tomorrow", today) == date(2026, 5, 13)
    assert resolve_target_date("unknown_mode", today) == date(2026, 5, 12)  # fallback


# --- интеграционный тик ----------------------------------------------------


def _make_scheduler(
    *,
    tmp_path: Path,
    now: datetime,
) -> tuple[DigestScheduler, SubscriptionStore, MagicMock]:
    store = SubscriptionStore(tmp_path / "subs.json")
    users = UserStore(tmp_path / "users.json")
    for uid, username in ((1, "alice"), (2, "bob")):
        users.upsert_from_telegram(
            telegram_user_id=uid,
            chat_id=uid,
            username=username,
            display_name=None,
            default_status=USER_STATUS_APPROVED,
        )
        users.set_calendar_connection(
            uid,
            provider="mailru",
            encrypted_credentials="encrypted",
            primary_calendar_url="https://example/caldav/",
        )
    telegram = MagicMock()
    telegram.send_message = MagicMock(return_value={"message_id": 1})
    calendar_service = MagicMock()
    digest_config = DigestConfig(mode="tomorrow")
    plan_config = MagicMock()
    scheduler = DigestScheduler(
        digest_config=digest_config,
        plan_config=plan_config,
        tz=TZ,
        subscriptions=store,
        users=users,
        calendar_service=calendar_service,
        telegram=telegram,
        tick_interval_sec=30.0,
        now_fn=lambda _tz: now,
    )
    scheduler._plan_builder = MagicMock()
    scheduler._plan_builder.build_text = MagicMock(return_value="<b>Plan</b>")
    return scheduler, store, telegram


def test_tick_sends_only_to_users_matching_time(tmp_path: Path):
    # 2026-05-11 — понедельник, 09:00 МСК
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    # alice: 09:00 будни — должна получить
    store.subscribe(1, "alice")
    # bob: 08:30 — не должен (другое время)
    store.subscribe(2, "bob")
    store.update_settings(2, "bob", digest_time="08:30")

    delivered = scheduler.tick()
    assert delivered == 1
    assert telegram.send_message.call_count == 1
    chat_ids = {call.args[0] for call in telegram.send_message.call_args_list}
    assert chat_ids == {1}


def test_tick_respects_last_digest_sent_date_protection(tmp_path: Path):
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    # имитация: уже отправляли сегодня
    store.mark_digest_sent(1, date(2026, 5, 11))

    assert scheduler.tick() == 0
    telegram.send_message.assert_not_called()


def test_tick_marks_last_sent_after_delivery(tmp_path: Path):
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")

    scheduler.tick()
    assert store.get(1).last_digest_sent_date == "2026-05-11"


def test_tick_does_not_mark_last_sent_when_send_fails(tmp_path: Path):
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    telegram.send_message.side_effect = TelegramError("network down")

    assert scheduler.tick() == 0
    assert store.get(1).last_digest_sent_date is None


def test_tick_does_not_mark_last_sent_when_user_has_no_calendar(tmp_path: Path):
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(3, "charlie")

    assert scheduler.tick() == 0
    assert store.get(3).last_digest_sent_date is None
    telegram.send_message.assert_not_called()


def test_tick_does_not_double_send_within_same_tick_cycle(tmp_path: Path):
    """После пометки повторный tick в ту же минуту ничего не делает."""
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")

    assert scheduler.tick() == 1
    assert scheduler.tick() == 0
    assert telegram.send_message.call_count == 1


def test_tick_skips_disabled_users(tmp_path: Path):
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.unsubscribe(1)

    assert scheduler.tick() == 0
    telegram.send_message.assert_not_called()


def test_tick_skips_weekend_for_weekdays_user(tmp_path: Path):
    # суббота
    now = _at(2026, 5, 9, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")  # weekdays-only по умолчанию

    assert scheduler.tick() == 0


def test_tick_delivers_on_weekend_for_all_days_user(tmp_path: Path):
    now = _at(2026, 5, 9, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_days=DIGEST_DAYS_ALL)

    assert scheduler.tick() == 1


def test_tick_delivers_at_custom_user_time(tmp_path: Path):
    # 08:30 МСК среда
    now = _at(2026, 5, 13, 8, 30)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_time="08:30")

    assert scheduler.tick() == 1


def test_tick_does_not_deliver_at_default_time_for_custom_time_user(tmp_path: Path):
    # пользователь установил 08:30, сейчас 09:00 — не пора
    now = _at(2026, 5, 13, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_time="08:30")

    assert scheduler.tick() == 0


def test_tick_one_failed_user_does_not_block_others(tmp_path: Path):
    """Падение одного пользователя не должно прерывать обработку остальных."""
    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.subscribe(2, "bob")

    seen: list[int] = []

    def send_side_effect(chat_id, *_args, **_kwargs):
        seen.append(chat_id)
        if chat_id == 1:
            raise RuntimeError("boom")
        return {"message_id": 1}

    telegram.send_message.side_effect = send_side_effect

    scheduler.tick()  # не падает
    assert 2 in seen  # bob всё равно дошёл до отправки


def test_tick_pending_silent_skip_when_empty(tmp_path: Path, monkeypatch):
    from unittest.mock import patch

    now = _at(2026, 5, 11, 10, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_enabled=False, pending_digest_enabled=True)

    empty_screen = InvitationsScreen(
        pending=[],
        text="empty",
        keyboard={"inline_keyboard": []},
        truncated=False,
        login="alice@mail.ru",
    )
    with patch(
        "satellite.scheduler.load_pending_invitations_screen",
        return_value=empty_screen,
    ):
        assert scheduler.tick() == 0
    telegram.send_message.assert_not_called()
    assert store.get(1).last_pending_digest_sent_date is None


def test_tick_pending_sends_with_keyboard_and_marks_sent(tmp_path: Path):
    from unittest.mock import patch

    now = _at(2026, 5, 11, 10, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.update_settings(1, "alice", digest_enabled=False, pending_digest_enabled=True)

    screen = InvitationsScreen(
        pending=[{"url": "https://cal/event/1", "summary": "Sync"}],
        text="<b>inv</b>",
        keyboard={"inline_keyboard": [[{"text": "1", "callback_data": "x"}]]},
        truncated=False,
        login="alice@mail.ru",
    )
    with patch(
        "satellite.scheduler.load_pending_invitations_screen",
        return_value=screen,
    ):
        assert scheduler.tick() == 1
    assert store.get(1).last_pending_digest_sent_date == "2026-05-11"
    call = telegram.send_message.call_args
    assert call.kwargs.get("reply_markup") == screen.keyboard


def test_tick_sends_both_daily_and_pending(tmp_path: Path):
    from unittest.mock import patch

    now = _at(2026, 5, 11, 9, 0)
    scheduler, store, telegram = _make_scheduler(tmp_path=tmp_path, now=now)
    store.subscribe(1, "alice")
    store.update_settings(
        1,
        "alice",
        pending_digest_enabled=True,
        pending_digest_time="09:00",
    )

    screen = InvitationsScreen(
        pending=[{"url": "https://cal/event/1", "summary": "Sync"}],
        text="<b>inv</b>",
        keyboard={"inline_keyboard": []},
        truncated=False,
        login="alice@mail.ru",
    )
    with patch(
        "satellite.scheduler.load_pending_invitations_screen",
        return_value=screen,
    ):
        assert scheduler.tick() == 2
    assert telegram.send_message.call_count == 2
    assert store.get(1).last_digest_sent_date == "2026-05-11"
    assert store.get(1).last_pending_digest_sent_date == "2026-05-11"
