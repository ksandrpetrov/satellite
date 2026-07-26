"""Цикл long-polling Telegram-бота с пулом воркеров и graceful shutdown."""

from __future__ import annotations

import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import FrameType
from typing import Any
from zoneinfo import ZoneInfo

from ..backup import snapshot_all
from ..calendar.operation_log import CalendarOperationLog
from ..calendar.user_calendar_service import UserCalendarService
from ..config import Settings
from ..plan_service import PlanBuilder
from ..scheduler import DigestScheduler
from ..security.token_vault import TokenVault
from ..subscriptions import SubscriptionStore
from ..users import UserStore
from ..weather.client import WeatherForecastClient
from ..web.connect_token import ConnectTokenStore
from ..web.server import WebAppServer, WebAppServerConfig
from .api import TelegramClient, TelegramError
from .commands import setup_bot_identity
from .concurrency import ChatLockManager
from .handlers import HandlerContext
from .handlers.calendar_state import CalendarStateStore
from .handlers.digest_state import DigestStateStore
from .offset_store import OffsetStore
from .offset_tracker import OffsetTracker
from .startup_checks import (
    log_persistence_summary,
    verify_encryption_key_against_existing_users,
)
from .startup_checks import (
    warn_if_users_lost as warn_if_users_lost,
)
from .update_dispatcher import UpdateDispatcher

log = logging.getLogger(__name__)

_ERROR_BACKOFF_INITIAL_SEC = 1.0
_ERROR_BACKOFF_MAX_SEC = 30.0
_ERROR_BACKOFF_MULTIPLIER = 2.0


class TelegramBot:
    """Long-polling Telegram-бот. Управляет жизненным циклом и оркеструет компоненты."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tz = ZoneInfo(settings.plan.tz_name)
        logs_dir = settings.project_root / "logs"
        self._users_path = logs_dir / "users.json"
        self._subscriptions_path = logs_dir / "subscriptions.json"
        # Снапшоты снимаются до строгого чтения stores: повреждённый файл
        # сохраняется для ручного восстановления, а запуск прекращается.
        self._startup_snapshots = snapshot_all([self._users_path, self._subscriptions_path])
        self._users = UserStore(self._users_path)
        self._subscriptions = SubscriptionStore(self._subscriptions_path)
        self._telegram = TelegramClient(settings.telegram.bot_token)
        self._token_vault = TokenVault(settings.security.encryption_key)
        self._operation_log = CalendarOperationLog(logs_dir / "calendar_ops.jsonl")
        self._calendar_service = UserCalendarService(
            users=self._users,
            token_vault=self._token_vault,
            operation_log=self._operation_log,
            cache_ttl_sec=settings.bot.caldav_cache_ttl_sec,
        )
        self._offset_store = OffsetStore(logs_dir / "telegram-offset.json")
        self._offset_tracker = OffsetTracker(self._offset_store)
        self._weather_client: WeatherForecastClient | None = (
            WeatherForecastClient() if settings.weather.enabled else None
        )
        self._chat_locks = ChatLockManager()
        self._digest_state = DigestStateStore()
        self._calendar_state = CalendarStateStore()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.bot.workers,
            thread_name_prefix="satellite-bot",
        )
        self._stop_event = threading.Event()
        self._shutdown_done = False
        self._shutdown_in_progress = False
        self._shutdown_lock = threading.Lock()
        self._connect_tokens = ConnectTokenStore(
            storage_path=logs_dir / "connect-tokens.json",
        )
        self._webapp = WebAppServer(
            config=WebAppServerConfig(
                host=settings.webapp.host,
                port=settings.webapp.port,
                bot_token=settings.telegram.bot_token,
                tz_name=settings.plan.tz_name,
                connect_tokens=self._connect_tokens,
            ),
            calendar_service=self._calendar_service,
            users=self._users,
        )
        self._plan_builder = PlanBuilder(
            calendar_service=self._calendar_service,
            plan_config=settings.plan,
            tz=self._tz,
            weather_config=settings.weather,
            weather_client=self._weather_client,
        )
        self._scheduler = DigestScheduler(
            digest_config=settings.digest,
            plan_config=settings.plan,
            tz=self._tz,
            subscriptions=self._subscriptions,
            users=self._users,
            calendar_service=self._calendar_service,
            telegram=self._telegram,
            stop_event=self._stop_event,
            weather_config=settings.weather,
            weather_client=self._weather_client,
        )
        self._dispatcher = UpdateDispatcher(
            executor=self._executor,
            chat_locks=self._chat_locks,
            offset_tracker=self._offset_tracker,
            stop_event=self._stop_event,
            max_pending_updates=settings.bot.workers * 2,
        )

    def run(self) -> None:
        self._install_signal_handlers()
        log.info(
            "Bot started: workers=%d long_poll=%ds cache_ttl=%ds digest_mode=%s webapp=%s",
            self._settings.bot.workers,
            self._settings.bot.long_poll_timeout_sec,
            self._settings.bot.caldav_cache_ttl_sec,
            self._settings.digest.mode,
            self._settings.webapp.base_url or "<not configured>",
        )
        self._log_persistence_summary()
        self._verify_encryption_key_against_existing_users()
        self._register_identity_safely()
        self._webapp.start()
        self._scheduler.start()
        try:
            self._main_loop()
        finally:
            self.shutdown()

    def _log_persistence_summary(self) -> None:
        log_persistence_summary(
            users=self._users,
            subscriptions=self._subscriptions,
            users_path=self._users_path,
            subscriptions_path=self._subscriptions_path,
            encryption_key=self._settings.security.encryption_key,
            startup_snapshots=self._startup_snapshots,
        )

    def _verify_encryption_key_against_existing_users(self) -> None:
        verify_encryption_key_against_existing_users(
            users=self._users,
            token_vault=self._token_vault,
            encryption_key=self._settings.security.encryption_key,
        )

    def _register_identity_safely(self) -> None:
        try:
            setup_bot_identity(self._telegram)
        except Exception:  # noqa: BLE001
            log.exception("Bot identity setup failed; continuing without menu/profile")

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_done or self._shutdown_in_progress:
                return
            self._shutdown_in_progress = True
        try:
            self._stop_event.set()
            log.info("Shutting down: waiting for in-flight handlers ...")
            steps = [
                ("scheduler", self._scheduler.stop),
                ("Web App", self._webapp.stop),
                (
                    "handler worker pool",
                    lambda: self._executor.shutdown(wait=True, cancel_futures=False),
                ),
                ("Telegram client", self._telegram.close),
            ]
            if self._weather_client is not None:
                steps.append(("weather client", self._weather_client.close))
            for label, closer in steps:
                try:
                    closer()
                except Exception:  # noqa: BLE001 - cleanup остальных обязан продолжиться
                    log.exception("Shutdown step failed: %s", label)
        finally:
            with self._shutdown_lock:
                self._shutdown_done = True
                self._shutdown_in_progress = False
        log.info("Stopped.")

    def _install_signal_handlers(self) -> None:
        def _handler(signum: int, _frame: FrameType | None) -> None:
            log.info("Received signal %s, stopping", signum)
            self._stop_event.set()

        try:
            signal.signal(signal.SIGTERM, _handler)
            signal.signal(signal.SIGINT, _handler)
        except ValueError:
            pass

    def _build_handler_context(self) -> HandlerContext:
        return HandlerContext(
            telegram=self._telegram,
            calendar_service=self._calendar_service,
            users=self._users,
            plan_config=self._settings.plan,
            tz=self._tz,
            admin=self._settings.admin,
            webapp=self._settings.webapp,
            connect_tokens=self._connect_tokens,
            subscriptions=self._subscriptions,
            weather_config=self._settings.weather,
            weather_client=self._weather_client,
            digest_state=self._digest_state,
            calendar_state=self._calendar_state,
            _plan_builder=self._plan_builder,
        )

    def _main_loop(self) -> None:
        ctx = self._build_handler_context()
        backoff = _ERROR_BACKOFF_INITIAL_SEC

        while not self._stop_event.is_set():
            updates = self._poll_updates_or_backoff(backoff)
            if updates is None:
                backoff = min(backoff * _ERROR_BACKOFF_MULTIPLIER, _ERROR_BACKOFF_MAX_SEC)
                continue
            backoff = _ERROR_BACKOFF_INITIAL_SEC

            for update in updates:
                if self._stop_event.is_set():
                    break
                self._dispatcher.dispatch_update(ctx, update)

    def _poll_updates_or_backoff(self, backoff: float) -> list[dict[str, Any]] | None:
        try:
            return self._telegram.get_updates(
                self._offset_tracker.polling_offset,
                timeout=self._settings.bot.long_poll_timeout_sec,
            )
        except TelegramError as exc:
            log.warning("Failed to fetch updates: %s; sleeping %.1fs", exc, backoff)
        except Exception:  # noqa: BLE001
            log.exception("Unexpected error fetching updates; sleeping %.1fs", backoff)
        self._sleep_interruptible(backoff)
        return None

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop_event.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            self._stop_event.wait(timeout=min(0.5, remaining))
