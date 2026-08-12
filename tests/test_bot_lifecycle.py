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
