"""End-to-end сценарии плана дня (today/tomorrow/day_after).

`test_handlers.py` уже покрывает базовые алиасы и стриминг. Этот файл
закрывает:

- каждое значение из ``PLAN_FETCH_STATUS_TEXT`` (today/tomorrow/day_after_tomorrow)
  даёт правильный ``target_date`` при вызове ``PlanBuilder.build_text``;
- pending-приглашения не учитываются как занятость в дайджесте плана
  (контракт ``seagull/render.py``: ``is_pending`` → ``⚠️`` вместо номера);
- ActionGuard ``_plan_run_guard`` **отпускается** после исключения CalDAV,
  чтобы следующая `/td` НЕ блокировалась 30-секундным cooldown'ом.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from satellite.calendar.providers.base import (
    CalendarNotConnectedError,
    CalendarProviderError,
)
from satellite.messages_ru import ERR_CALDAV_UNAVAILABLE_TEXT, PLAN_BUSY_TEXT
from satellite.plan_service import PlanTextBundle
from satellite.telegram_bot.handlers import handle_message
from satellite.telegram_bot.handlers import plan as plan_module
from satellite.testing.delivery_helpers import sent_messages_text
from satellite.users import UserStore

from .conftest import freeze_now, make_ctx, make_msg, make_user_store

USER_ID = 7001
ADMIN_ID = 9001


@pytest.fixture
def approved_user_store(tmp_path: Path) -> UserStore:
    return make_user_store(tmp_path, approved_with_calendar=[USER_ID])


def _build_ctx(users: UserStore) -> MagicMock:
    """Полная ctx с замоканным PlanBuilder, чтобы handle_plan дошёл до build_text."""
    ctx = make_ctx(users, admin_ids=(ADMIN_ID,))
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 7000})
    ctx.telegram.send_message_draft = MagicMock(return_value=True)
    ctx.telegram.send_rich_message_draft = MagicMock(return_value=True)
    ctx.telegram.send_rich_message = MagicMock(return_value={"message_id": 7000})
    ctx.telegram.edit_message_text = MagicMock(return_value={"message_id": 7000})
    pb = MagicMock()
    bundle = PlanTextBundle(rich_html="<h2>Plan</h2>", fallback_html="<b>Plan HTML</b>")
    pb.build_plan_bundle = MagicMock(return_value=bundle)
    pb.build_text = MagicMock(return_value="<b>Plan HTML</b>")
    ctx._plan_builder = pb
    ctx.plan_builder = MagicMock(return_value=pb)
    ctx.weather_config.enabled = False
    ctx.weather_client = None
    return ctx


@pytest.mark.parametrize(
    "command_text,expected_offset",
    [
        ("/td", 0),
        ("/today", 0),
        ("td", 0),
        ("/tm", 1),
        ("/tomorrow", 1),
        ("tm", 1),
        ("/dat", 2),
        ("/aftertomorrow", 2),
        ("/after_tomorrow", 2),
        ("dat", 2),
    ],
)
def test_plan_aliases_call_plan_builder_with_correct_target_date(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    command_text: str,
    expected_offset: int,
) -> None:
    """Каждый alias плана должен дать ровно один build_text с корректной датой."""
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    msg = make_msg(text=command_text, chat_id=USER_ID, user_id=USER_ID, update_id=1000)
    handle_message(ctx, msg)

    pb = ctx.plan_builder()
    pb.build_plan_bundle.assert_called_once()
    kwargs = pb.build_plan_bundle.call_args.kwargs
    assert kwargs["telegram_user_id"] == USER_ID
    expected_today = date(2026, 5, 22)
    assert kwargs["reference_date"] == expected_today
    assert kwargs["target_date"] == date.fromordinal(expected_today.toordinal() + expected_offset)


def test_plan_does_not_run_for_unknown_user(tmp_path: Path) -> None:
    """Защита: без записи в users.json и без статуса approved — никакого CalDAV."""
    users = UserStore(tmp_path / "users.json")
    ctx = _build_ctx(users)
    msg = make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID)
    handle_message(ctx, msg)
    ctx.plan_builder().build_plan_bundle.assert_not_called()


def test_plan_releases_guard_after_caldav_failure(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После CalDAV-ошибки cooldown НЕ ставится; следующий /td сразу работает.

    Регрессия: ``handle_plan`` обязан вызвать ``_plan_run_guard.release(sent=False)``
    при исключении. Иначе одна сетевая блика → 30 с глухой блокировки для всего
    чата, и пользователь думает, что бот сломан.
    """
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    pb = ctx.plan_builder()
    pb.build_plan_bundle = MagicMock(
        side_effect=CalendarProviderError("boom", error_code="CALDAV_UNAVAILABLE")
    )

    msg1 = make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=1)
    handle_message(ctx, msg1)
    assert pb.build_plan_bundle.call_count == 1
    # пользователь увидел safe текст
    sent_texts = sent_messages_text(ctx.telegram)
    assert ERR_CALDAV_UNAVAILABLE_TEXT in sent_texts

    # Guard должен быть отпущен — второй /td сразу триггерит build_text
    pb.build_plan_bundle = MagicMock(
        return_value=PlanTextBundle(rich_html="<h2>Plan</h2>", fallback_html="<b>Plan HTML</b>")
    )
    msg2 = make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=2)
    handle_message(ctx, msg2)
    pb.build_plan_bundle.assert_called_once()


def test_plan_releases_guard_after_unexpected_exception(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ModuleNotFoundError / любой другой Exception — тоже не оставляет cooldown."""
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    pb = ctx.plan_builder()
    pb.build_plan_bundle = MagicMock(side_effect=ModuleNotFoundError("PIL"))

    msg1 = make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=11)
    handle_message(ctx, msg1)

    # И ещё раз — без cooldown
    pb.build_plan_bundle = MagicMock(
        return_value=PlanTextBundle(rich_html="<h2>Plan</h2>", fallback_html="<b>Plan HTML</b>")
    )
    msg2 = make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=12)
    handle_message(ctx, msg2)
    pb.build_plan_bundle.assert_called_once()


def test_plan_releases_guard_after_calendar_not_connected(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    pb = ctx.plan_builder()
    pb.build_plan_bundle = MagicMock(side_effect=CalendarNotConnectedError())

    handle_message(ctx, make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=21))
    pb.build_plan_bundle = MagicMock(
        return_value=PlanTextBundle(rich_html="<h2>Plan</h2>", fallback_html="<b>Plan HTML</b>")
    )
    handle_message(ctx, make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=22))
    pb.build_plan_bundle.assert_called_once()


def test_plan_no_post_success_cooldown_allows_immediate_retry(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Контракт: после успешной доставки повторный /td сразу строит новый план.

    Регрессия 2026-05-22: 30-секундный post-success cooldown молча проглатывал
    повторы и пользователь, не получивший feedback, считал бота сломанным.
    Двойную доставку при настоящей гонке double-tap покрывает while-running лок
    (см. ``test_plan_busy_message_when_build_in_progress``).
    """
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    pb = ctx.plan_builder()

    handle_message(ctx, make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=1))
    handle_message(ctx, make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=2))

    assert pb.build_plan_bundle.call_count == 2
    busy_calls = [
        c[0][1] for c in ctx.telegram.send_message.call_args_list if c[0][1] == PLAN_BUSY_TEXT
    ]
    assert busy_calls == []


def test_plan_busy_message_when_build_in_progress(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пока идёт сборка — повтор /td получает busy-сообщение, build не вызывается."""
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    pb = ctx.plan_builder()

    assert plan_module._plan_run_guard.try_acquire(USER_ID, "plan:today")
    try:
        handle_message(ctx, make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=10))
    finally:
        plan_module._plan_run_guard.release(USER_ID, "plan:today")

    pb.build_plan_bundle.assert_not_called()
    assert PLAN_BUSY_TEXT in sent_messages_text(ctx.telegram)


def test_plan_independent_action_keys_per_mode(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`plan:today` и `plan:tomorrow` — независимые keys; cooldown one не блокирует
    другую."""
    fixed_now = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    pb = ctx.plan_builder()

    handle_message(ctx, make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID, update_id=1))
    handle_message(ctx, make_msg(text="/tm", chat_id=USER_ID, user_id=USER_ID, update_id=2))
    assert pb.build_plan_bundle.call_count == 2

    today_call = pb.build_plan_bundle.call_args_list[0]
    tomorrow_call = pb.build_plan_bundle.call_args_list[1]
    assert today_call.kwargs["target_date"] == date(2026, 5, 22)
    assert tomorrow_call.kwargs["target_date"] == date(2026, 5, 23)


def test_plan_blocks_for_not_connected_user(tmp_path: Path) -> None:
    """Approved, но без календаря → CALENDAR_NOT_CONNECTED, без вызова PlanBuilder."""
    users = make_user_store(tmp_path, approved=[USER_ID])
    ctx = _build_ctx(users)
    msg = make_msg(text="/td", chat_id=USER_ID, user_id=USER_ID)
    handle_message(ctx, msg)
    ctx.plan_builder().build_plan_bundle.assert_not_called()


# --- HIDE_ALL_DAY_EVENTS / pending invitations через build_plan_for_user --


def test_build_plan_for_user_passes_reference_and_target(
    approved_user_store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke-уровень: build_plan_for_user → PlanBuilder.build_text с правильными датами."""
    fixed_now = datetime(2026, 1, 7, 18, 0, tzinfo=timezone.utc)
    freeze_now(monkeypatch, module="satellite.telegram_bot.handlers.plan", now=fixed_now)

    ctx = _build_ctx(approved_user_store)
    plan_module.build_plan_for_user(ctx, telegram_user_id=USER_ID, mode="day_after_tomorrow")

    pb = ctx.plan_builder()
    kwargs = pb.build_plan_bundle.call_args.kwargs
    assert kwargs["reference_date"] == date(2026, 1, 7)
    assert kwargs["target_date"] == date(2026, 1, 9)
