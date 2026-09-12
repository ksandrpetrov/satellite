"""Startup and shutdown contracts for the Telegram bot lifecycle."""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from satellite.telegram_bot.bot import TelegramBot
from satellite.users import UserStoreLoadError


def _bare_bot() -> TelegramBot:
    bot = TelegramBot.__new__(TelegramBot)
    bot._shutdown_lock = threading.Lock()
    bot._shutdown_done = False
    bot._shutdown_in_progress = False
    bot._stop_event = threading.Event()
    bot._scheduler = MagicMock()
    bot._webapp = MagicMock()
    bot._executor = MagicMock()
    bot._calendar_service = MagicMock()
    bot._telegram = MagicMock()
    bot._weather_client = MagicMock()
    return bot


@pytest.mark.parametrize(
    ("component", "method"),
    [
        ("_scheduler", "stop"),
        ("_webapp", "stop"),
        ("_executor", "shutdown"),
        ("_calendar_service", "close"),
        ("_telegram", "close"),
        ("_weather_client", "close"),
    ],
)
def test_shutdown_failure_does_not_skip_other_resources(
    component: str,
    method: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = _bare_bot()
    getattr(getattr(bot, component), method).side_effect = RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="satellite.telegram_bot.bot"):
        bot.shutdown()

    bot._scheduler.stop.assert_called_once_with()
    bot._webapp.stop.assert_called_once_with()
    bot._executor.shutdown.assert_called_once_with(wait=True, cancel_futures=False)
    bot._calendar_service.close.assert_called_once_with()
    bot._telegram.close.assert_called_once_with()
    bot._weather_client.close.assert_called_once_with()
    assert bot._stop_event.is_set()
    assert "Shutdown step failed" in caplog.text


def test_shutdown_is_idempotent() -> None:
    bot = _bare_bot()

    bot.shutdown()
    bot.shutdown()

    bot._scheduler.stop.assert_called_once_with()
    bot._webapp.stop.assert_called_once_with()
    bot._executor.shutdown.assert_called_once_with(wait=True, cancel_futures=False)
    bot._calendar_service.close.assert_called_once_with()
    bot._telegram.close.assert_called_once_with()


def _prepare_run(bot: TelegramBot) -> None:
    bot._settings = MagicMock()
    bot._settings.bot.workers = 2
    bot._settings.bot.long_poll_timeout_sec = 30
    bot._settings.bot.caldav_cache_ttl_sec = 300
    bot._settings.webapp.base_url = "https://example.test"
    bot._install_signal_handlers = MagicMock()
    bot._log_persistence_summary = MagicMock()
    bot._verify_encryption_key_against_existing_users = MagicMock()
    bot._register_identity_safely = MagicMock()
    bot._main_loop = MagicMock()


def test_run_cleans_up_when_webapp_start_fails() -> None:
    bot = _bare_bot()
    _prepare_run(bot)
    bot._webapp.start.side_effect = RuntimeError("bind failed")

    with pytest.raises(RuntimeError, match="bind failed"):
        bot.run()

    bot._scheduler.start.assert_not_called()
    bot._webapp.stop.assert_called_once_with()
    bot._scheduler.stop.assert_called_once_with()
    bot._calendar_service.close.assert_called_once_with()


def test_run_cleans_up_when_scheduler_start_fails() -> None:
    bot = _bare_bot()
    _prepare_run(bot)
    bot._scheduler.start.side_effect = RuntimeError("thread failed")

    with pytest.raises(RuntimeError, match="thread failed"):
        bot.run()

    bot._webapp.start.assert_called_once_with()
    bot._webapp.stop.assert_called_once_with()
    bot._scheduler.stop.assert_called_once_with()
    bot._calendar_service.close.assert_called_once_with()
    bot._weather_client.close.assert_called_once_with()


def test_startup_snapshot_precedes_strict_store_load(tmp_path) -> None:
    settings = MagicMock()
    settings.project_root = tmp_path
    settings.plan.tz_name = "Europe/Moscow"
    events: list[str] = []

    with (
        patch(
            "satellite.telegram_bot.bot.snapshot_all",
            side_effect=lambda _paths: events.append("snapshot") or [],
        ),
        patch(
            "satellite.telegram_bot.bot.UserStore",
            side_effect=lambda _path: (
                events.append("users"),
                (_ for _ in ()).throw(UserStoreLoadError("broken")),
            )[-1],
        ),
        patch("satellite.telegram_bot.bot.TelegramClient") as telegram_client,
        patch("satellite.telegram_bot.bot.WebAppServer") as webapp_server,
        patch("satellite.telegram_bot.bot.DigestScheduler") as scheduler,
    ):
        with pytest.raises(UserStoreLoadError):
            TelegramBot(settings)

    assert events == ["snapshot", "users"]
    telegram_client.assert_not_called()
    webapp_server.assert_not_called()
    scheduler.assert_not_called()


def test_bot_contexts_share_runtime_with_scheduler_but_other_bots_are_isolated(tmp_path) -> None:
    from dataclasses import replace

    from cryptography.fernet import Fernet

    from satellite.config import (
        AdminConfig,
        BotConfig,
        PlanConfig,
        SecurityConfig,
        Settings,
        TelegramConfig,
        WebAppConfig,
    )

    settings = Settings(
        telegram=TelegramConfig(bot_token="test:token"),
        plan=PlanConfig(),
        bot=BotConfig(workers=1),
        security=SecurityConfig(encryption_key=Fernet.generate_key().decode()),
        admin=AdminConfig(),
        webapp=WebAppConfig(),
        project_root=tmp_path / "first",
    )
    first = TelegramBot(settings)
    try:
        second = TelegramBot(replace(settings, project_root=tmp_path / "second"))
        try:
            one = first._build_handler_context()
            again = first._build_handler_context()
            other = second._build_handler_context()
            assert one.runtime is again.runtime
            assert one.runtime.event_tokens is first._scheduler._event_tokens
            assert one.runtime is not other.runtime
            assert one.runtime.event_tokens is not second._scheduler._event_tokens
            assert one.runtime.plan.try_acquire(1, "plan:today")
            assert not again.runtime.plan.try_acquire(1, "plan:today")
            assert other.runtime.plan.try_acquire(1, "plan:today")
        finally:
            second.shutdown()
    finally:
        first.shutdown()


@pytest.mark.parametrize("error_type", ["telegram", "unexpected"])
def test_polling_caps_backoff_and_resets_after_success(error_type) -> None:
    from types import SimpleNamespace

    from satellite.telegram_bot.api import TelegramError

    bot = _bare_bot()
    bot._settings = SimpleNamespace(bot=SimpleNamespace(long_poll_timeout_sec=30))
    bot._offset_tracker = SimpleNamespace(polling_offset=100)
    ctx = object()
    bot._build_handler_context = MagicMock(return_value=ctx)
    bot._sleep_interruptible = MagicMock()
    bot._dispatcher = MagicMock()
    updates = [{"update_id": 100}, {"update_id": 101}]
    failure = (
        TelegramError("unavailable") if error_type == "telegram" else RuntimeError("unexpected")
    )
    responses = iter([failure] * 7 + [updates, failure, []])

    def poll(offset, *, timeout):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        if result == []:
            bot._stop_event.set()
        return result

    def dispatch(_ctx, update):
        bot._offset_tracker.polling_offset = update["update_id"] + 1

    bot._telegram.get_updates.side_effect = poll
    bot._dispatcher.dispatch_update.side_effect = dispatch
    bot._main_loop()

    assert [call.args[0] for call in bot._sleep_interruptible.call_args_list] == [
        1,
        2,
        4,
        8,
        16,
        30,
        30,
        1,
    ]
    assert [call.args for call in bot._dispatcher.dispatch_update.call_args_list] == [
        (ctx, updates[0]),
        (ctx, updates[1]),
    ]
    assert bot._telegram.get_updates.call_count == 10
    assert bot._telegram.get_updates.call_args.args == (102,)
    assert all(call.kwargs == {"timeout": 30} for call in bot._telegram.get_updates.call_args_list)


def test_shutdown_during_batch_does_not_dispatch_remaining_updates() -> None:
    bot = _bare_bot()
    ctx = object()
    bot._build_handler_context = MagicMock(return_value=ctx)
    updates = [{"update_id": 1}, {"update_id": 2}]
    bot._poll_updates_or_backoff = MagicMock(return_value=updates)
    bot._dispatcher = MagicMock()
    bot._dispatcher.dispatch_update.side_effect = lambda *_: bot._stop_event.set()

    bot._main_loop()

    bot._dispatcher.dispatch_update.assert_called_once_with(ctx, updates[0])
    bot._poll_updates_or_backoff.assert_called_once()


def test_backoff_wait_stops_promptly_when_shutdown_is_requested(monkeypatch) -> None:
    monkeypatch.setattr("satellite.telegram_bot.bot.time.monotonic", lambda: 0.0)
    bot = _bare_bot()
    bot._stop_event.wait = MagicMock(side_effect=lambda **_: bot._stop_event.set())

    bot._sleep_interruptible(30)

    bot._stop_event.wait.assert_called_once_with(timeout=0.5)
    assert bot._stop_event.is_set()
