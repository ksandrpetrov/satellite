"""Цикл long-polling Telegram-бота с пулом воркеров и graceful shutdown."""

from __future__ import annotations

import hashlib
import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from zoneinfo import ZoneInfo

from ..backup import snapshot_all
from ..calendar.operation_log import CalendarOperationLog
from ..calendar.user_calendar_service import UserCalendarService
from ..config import Settings
from ..plan_service import PlanBuilder
from ..scheduler import DigestScheduler
from ..security.token_vault import TokenDecryptError, TokenVault
from ..subscriptions import SubscriptionStore
from ..users import USER_STATUS_APPROVED, UserStore
from ..weather.client import WeatherForecastClient
from ..web.connect_token import ConnectTokenStore
from ..web.server import WebAppServer, WebAppServerConfig
from .api import TelegramClient, TelegramError
from .calendar_state import CalendarStateStore
from .commands import setup_bot_identity
from .concurrency import ChatLockManager
from .digest_state import DigestStateStore
from .handlers import (
    HandlerContext,
    IncomingCallback,
    IncomingMessage,
    extract_callback_query,
    extract_message,
    handle_callback_query,
    handle_message,
    is_update_callback,
    is_update_message,
)
from .offset_store import OffsetStore
from .offset_tracker import OffsetTracker

log = logging.getLogger(__name__)

_ERROR_BACKOFF_INITIAL_SEC = 1.0
_ERROR_BACKOFF_MAX_SEC = 30.0
_ERROR_BACKOFF_MULTIPLIER = 2.0


class TelegramBot:
    """Long-polling Telegram-бот. Управляет жизненным циклом и оркеструет компоненты."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tz = ZoneInfo(settings.plan.tz_name)
        self._telegram = TelegramClient(settings.telegram.bot_token)
        logs_dir = settings.project_root / "logs"
        self._users_path = logs_dir / "users.json"
        self._subscriptions_path = logs_dir / "subscriptions.json"
        # Снапшоты до открытия сторов: если кто-то руками подменил файл и сейчас
        # запись битая, мы успеем сохранить его как-есть до того, как сторы
        # перезапишут диск своим in-memory представлением.
        self._startup_snapshots = snapshot_all(
            [self._users_path, self._subscriptions_path]
        )
        self._users = UserStore(self._users_path)
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
        self._subscriptions = SubscriptionStore(self._subscriptions_path)
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
                plan_config=settings.plan,
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
        """Печатает в журнал, сколько пользователей и подписок загрузилось.

        Нужно, чтобы при каждом ``systemctl restart`` админ видел в журнале
        стабильные числа («users approved=2 connected=2 subs active=2») и не
        ловил ложное «после деплоя всё сбросилось». Падать здесь нельзя — это
        диагностика, а не валидация.
        """
        users = self._users.list_all()
        approved = sum(1 for rec in users if rec.status == USER_STATUS_APPROVED)
        with_calendar = sum(1 for rec in users if rec.has_calendar)
        subs_all = self._subscriptions.list_all()
        subs_active = sum(1 for sub in subs_all if sub.digest_enabled)
        snapshots = [str(path) for path in self._startup_snapshots]
        log.info(
            "Persistence loaded: users total=%d approved=%d calendar_connected=%d "
            "subscriptions total=%d active=%d users_path=%s subscriptions_path=%s "
            "key_fingerprint=%s snapshots=%s",
            len(users),
            approved,
            with_calendar,
            len(subs_all),
            subs_active,
            self._users_path,
            self._subscriptions_path,
            _encryption_key_fingerprint(self._settings.security.encryption_key),
            snapshots or "[]",
        )

    def _verify_encryption_key_against_existing_users(self) -> None:
        """Пробует расшифровать хоть один существующий ``encrypted_credentials``.

        Сценарий, ради которого это нужно: админ случайно перегенерил
        ``TOKEN_ENCRYPTION_KEY`` в ``.env`` (или ``.env`` уехал из бэкапа со
        старого хоста). Бот стартует, но все подключения календарей становятся
        «битыми» — пользователи видят «настройки сбросились». Лучше один раз
        громко крикнуть в журнал, чем молча работать с осиротевшими записями.
        """
        candidates = [
            rec
            for rec in self._users.list_all()
            if rec.encrypted_credentials and rec.status == USER_STATUS_APPROVED
        ]
        if not candidates:
            return
        for rec in candidates:
            try:
                self._token_vault.decrypt(rec.encrypted_credentials or "")
            except TokenDecryptError:
                continue
            return
        log.critical(
            "Encryption self-check failed: %d approved users have credentials, "
            "but none decrypt with current TOKEN_ENCRYPTION_KEY (fingerprint=%s). "
            "The key was likely rotated since users connected their calendars. "
            "Restore the previous .env (or logs/backups snapshot) to keep settings; "
            "see docs/troubleshooting.md.",
            len(candidates),
            _encryption_key_fingerprint(self._settings.security.encryption_key),
        )

    def _register_identity_safely(self) -> None:
        try:
            setup_bot_identity(self._telegram)
        except Exception:  # noqa: BLE001
            log.exception("Bot identity setup failed; continuing without menu/profile")

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        self._stop_event.set()
        log.info("Shutting down: waiting for in-flight handlers ...")
        self._scheduler.stop()
        self._webapp.stop()
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._telegram.close()
        if self._weather_client is not None:
            self._weather_client.close()
        log.info("Stopped.")

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):  # noqa: ANN001
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
                self._dispatch_update(ctx, update)

    def _poll_updates_or_backoff(self, backoff: float) -> list[dict] | None:
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

    def _dispatch_update(self, ctx: HandlerContext, update: dict) -> None:
        update_id = int(update.get("update_id") or 0)
        if update_id <= 0:
            return

        if not self._offset_tracker.mark_dispatched(update_id):
            return

        if is_update_callback(update):
            self._dispatch_callback(ctx, update, update_id)
            return
        if is_update_message(update):
            self._dispatch_message(ctx, update, update_id)
            return
        self._offset_tracker.mark_completed(update_id)

    def _dispatch_message(
        self, ctx: HandlerContext, update: dict, update_id: int
    ) -> None:
        msg = extract_message(update)

        try:
            future = self._executor.submit(self._run_message_handler, ctx, msg)
        except RuntimeError:
            log.info("Executor shut down; deferring update_id=%s", msg.update_id)
            return

        future.add_done_callback(
            lambda _fut, _msg=msg: self._on_message_done(_msg)
        )

    def _dispatch_callback(
        self, ctx: HandlerContext, update: dict, update_id: int
    ) -> None:
        cb = extract_callback_query(update)
        if cb is None:
            self._offset_tracker.mark_completed(update_id)
            return

        try:
            future = self._executor.submit(self._run_callback_handler, ctx, cb)
        except RuntimeError:
            log.info(
                "Executor shut down; deferring callback update_id=%s", cb.update_id
            )
            return

        future.add_done_callback(
            lambda _fut, _cb=cb: self._offset_tracker.mark_completed(_cb.update_id)
        )

    def _run_message_handler(
        self, ctx: HandlerContext, msg: IncomingMessage
    ) -> None:
        lock = self._chat_locks.acquire(msg.chat_id)
        with lock:
            handle_message(ctx, msg)

    def _run_callback_handler(
        self, ctx: HandlerContext, cb: IncomingCallback
    ) -> None:
        lock = self._chat_locks.acquire(cb.chat_id)
        with lock:
            handle_callback_query(ctx, cb)

    def _on_message_done(self, msg: IncomingMessage) -> None:
        self._offset_tracker.mark_completed(msg.update_id)

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop_event.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            self._stop_event.wait(timeout=min(0.5, remaining))


def _encryption_key_fingerprint(encryption_key: str) -> str:
    """Короткий отпечаток ключа шифрования для журнала.

    SHA256 over the key, truncated to 8 hex chars. Не позволяет восстановить
    ключ, но даёт визуальный «равно/не равно» между перезапусками — если
    ``key_fingerprint`` поменялся, значит ``.env`` подменили (или его
    перегенерировал ``make env`` / ``scripts/install.sh``).
    """
    digest = hashlib.sha256(encryption_key.encode("utf-8")).hexdigest()
    return digest[:8]
