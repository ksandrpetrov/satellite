"""Высокоуровневые сценарии: запуск Telegram-бота."""

from __future__ import annotations

import logging

from .config import Settings, assert_telegram_bot_token_valid, load_settings
from .logging_setup import setup_logging
from .telegram_bot.bot import TelegramBot
from .telegram_bot.instance_lock import InstanceLock, InstanceLockError

log = logging.getLogger(__name__)


def run_bot(*, settings: Settings | None = None) -> None:
    """Запускает интерактивного Telegram-бота с long-polling."""
    if settings is None:
        settings = load_settings(
            require_telegram=True,
            require_admin=True,
            require_webapp=True,
            require_encryption_key=True,
        )
        assert_telegram_bot_token_valid(settings.telegram.bot_token)
    setup_logging(
        level=settings.log_level,
        log_file=settings.project_root / "logs" / "bot.log",
    )
    lock = InstanceLock(settings.project_root / "logs" / "bot.lock")
    try:
        lock.acquire()
    except InstanceLockError as exc:
        log.error(
            "Refusing to start: another bot instance is already running (%s). "
            "Stop it first to avoid duplicate replies to users.",
            exc,
        )
        raise SystemExit(1) from exc
    try:
        bot = TelegramBot(settings)
        try:
            bot.run()
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            bot.shutdown()
    finally:
        lock.release()


def bot_cli(_argv: list[str] | None = None) -> None:
    run_bot()
