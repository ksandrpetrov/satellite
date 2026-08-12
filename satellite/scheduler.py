"""Фоновый scheduler для per-user дайджестов (план дня и непринятые встречи).

Дизайн:

- Один поток просыпается каждые ``tick_interval_sec`` (по умолчанию 30 с)
  и сверяет ``HH:MM`` в часовом поясе пользователя с его расписанием.
- Стреляем, если: день недели разрешён, локальное время ``>=`` scheduled,
  и сегодня этому пользователю ещё не отправляли/не проверяли пустой pending.
- Durable marker и process-local checkpoint ставятся после успешной обработки.
  Checkpoint защищает от дубля в текущем процессе, даже если запись marker
  на диск не удалась.
- Догон после пропуска: если бот рестартился / тик упал / сеть моргнула
  ровно в минуту scheduled — следующий тик в этот же день всё равно
  отправит дайджест (а не молча потеряет слот до завтра). Окно «догона» —
  до конца локальных суток пользователя; если день закончился без
  отправки, scheduled-слот этого дня считается потерянным.
- Каждый подписчик обрабатывается независимо (фейл одного не валит остальных).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, tzinfo
from enum import Enum, auto
from zoneinfo import ZoneInfo

from . import scheduler_policy
from .calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from .calendar.user_calendar_service import UserCalendarService
from .config import PlanConfig, WeatherConfig
from .digest_utils import DIGEST_MODE_TODAY, resolve_target_date
from .invitations_view import load_pending_invitations_screen
from .meeting_exclusions import MeetingExclusionService
from .plan_service import PlanBuilder
from .presentation.delivery import deliver_rich_or_html
from .subscriptions import (
    DigestSettings,
    SubscriptionStore,
    SubscriptionStorePersistenceError,
)
from .telegram_bot.api import TelegramClient, TelegramError
from .telegram_bot.visual import is_private_chat, pick_plan_message_effect
from .users import UserStore
from .weather.client import WeatherForecastClient

log = logging.getLogger(__name__)

_DEFAULT_TICK_SEC = 30.0
_DEFAULT_MAX_PARALLEL_DELIVERIES = 4


class _DigestKind(Enum):
    DAILY = auto()
    PENDING = auto()


class _PendingDeliveryOutcome(Enum):
    SENT = auto()
    EMPTY = auto()
    FAILED = auto()


class DigestScheduler:
    """Тикающий планировщик. Запускается отдельным потоком."""

    def __init__(
        self,
        *,
        plan_config: PlanConfig,
        tz: tzinfo,
        subscriptions: SubscriptionStore,
        users: UserStore,
        calendar_service: UserCalendarService,
        meeting_exclusions: MeetingExclusionService,
        telegram: TelegramClient,
        stop_event: threading.Event | None = None,
        tick_interval_sec: float = _DEFAULT_TICK_SEC,
        max_parallel_deliveries: int = _DEFAULT_MAX_PARALLEL_DELIVERIES,
        now_fn: Callable[[tzinfo], datetime] | None = None,
        weather_config: WeatherConfig | None = None,
        weather_client: WeatherForecastClient | None = None,
    ) -> None:
        self._plan_config = plan_config
        self._tz = tz
        self._subscriptions = subscriptions
        self._users = users
        self._calendar_service = calendar_service
        self._meeting_exclusions = meeting_exclusions
        self._telegram = telegram
        self._plan_builder = PlanBuilder(
            calendar_service=calendar_service,
            plan_config=plan_config,
            tz=tz,
            weather_config=weather_config,
            weather_client=weather_client,
        )
        self._stop_event = stop_event or threading.Event()
        self._tick_interval_sec = tick_interval_sec
        self._max_parallel_deliveries = max(1, int(max_parallel_deliveries))
        self._now_fn = now_fn or (lambda tz_: datetime.now(tz=tz_))
        self._thread: threading.Thread | None = None
        self._tz_cache: dict[str, ZoneInfo] = {}
        self._checkpoint_lock = threading.Lock()
        self._processed_dates: dict[tuple[_DigestKind, int], date] = {}
        # Общий пул на все тики: потоки спавнятся лениво по мере submit'ов,
        # закрывается в stop().
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_parallel_deliveries,
            thread_name_prefix="satellite-scheduler",
        )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="satellite-digest-scheduler",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Digest scheduler started: per-user schedule; tick=%.0fs auto_plan_date=today "
            "fire_window=catch_up_same_day",
            self._tick_interval_sec,
        )

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._tick_interval_sec + 2)
        self._pool.shutdown(wait=True, cancel_futures=True)

    def tick(self) -> int:
        """Один логический шаг. Возвращает число успешно отправленных дайджестов."""
        subscriptions = self._subscriptions.list_active()
        if not subscriptions:
            return 0
        daily_due = daily_sent = daily_failed = 0
        pending_due = pending_sent = pending_failed = 0
        for result in self._delivery_results(subscriptions):
            if result is None:
                continue
            d_due, d_sent, d_fail, p_due, p_sent, p_fail = result
            daily_due += d_due
            daily_sent += d_sent
            daily_failed += d_fail
            pending_due += p_due
            pending_sent += p_sent
            pending_failed += p_fail
        if daily_due or pending_due or daily_failed or pending_failed:
            log.info(
                "Digest scheduler tick: checked=%d daily_due=%d daily_sent=%d "
                "daily_failed=%d pending_due=%d pending_sent=%d pending_failed=%d",
                len(subscriptions),
                daily_due,
                daily_sent,
                daily_failed,
                pending_due,
                pending_sent,
                pending_failed,
            )
        return daily_sent + pending_sent

    def _delivery_results(
        self, subscriptions: list[DigestSettings]
    ) -> Iterator[tuple[int, int, int, int, int, int] | None]:
        """Результаты ``_maybe_deliver`` по всем подписчикам через общий пул.

        ``None`` — доставка одному пользователю упала (уже залогировано);
        фейл одного не валит остальных. При ``stop_event`` отменяем ещё не
        начатые доставки и выходим.
        """
        futures = {self._pool.submit(self._maybe_deliver, sub): sub for sub in subscriptions}
        for future in as_completed(futures):
            if self._stop_event.is_set():
                for pending_future in futures:
                    pending_future.cancel()
                return
            sub = futures[future]
            try:
                yield future.result()
            except Exception:  # noqa: BLE001 - один пользователь не валит остальных
                log.exception(
                    "Failed to deliver digest to chat_id=%s username=%s",
                    sub.chat_id,
                    sub.username,
                )
                yield None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - тик не должен валить поток
                log.exception("Digest scheduler tick failed")
            self._stop_event.wait(timeout=self._tick_interval_sec)

    def _user_tz(self, name: str) -> tzinfo:
        try:
            cached = self._tz_cache.get(name)
            if cached is not None:
                return cached
            zi = ZoneInfo(name)
            self._tz_cache[name] = zi
            return zi
        except Exception:  # noqa: BLE001 - неизвестная зона
            log.warning("Unknown timezone %r; falling back to scheduler default", name)
            return self._tz

    def _maybe_deliver(self, sub: DigestSettings) -> tuple[int, int, int, int, int, int]:
        """(daily_due, daily_sent, daily_fail, pending_due, pending_sent, pending_fail)."""
        daily_due = daily_sent = daily_failed = 0
        pending_due = pending_sent = pending_failed = 0

        user_tz_daily = self._user_tz(sub.digest_timezone)
        now_daily = self._now_fn(user_tz_daily)
        daily_date = now_daily.date()
        daily_processed = self._was_processed(_DigestKind.DAILY, sub.chat_id, daily_date)
        if not daily_processed and scheduler_policy.should_fire_for_user(
            settings=sub,
            now_in_user_tz=now_daily,
        ):
            daily_due = 1
            log.info(
                "Daily digest firing at %s for chat_id=%s username=%s",
                now_daily.isoformat(timespec="seconds"),
                sub.chat_id,
                sub.username,
            )
            delivered = self._deliver_daily(sub, today=daily_date)
            if delivered:
                self._mark_processed(_DigestKind.DAILY, sub.chat_id, daily_date)
                try:
                    self._subscriptions.mark_digest_sent(sub.chat_id, daily_date)
                except SubscriptionStorePersistenceError:
                    daily_failed = 1
                    log.warning(
                        "Daily digest delivered but last_digest_sent_date was not saved "
                        "(chat_id=%s username=%s); process-local checkpoint prevents a "
                        "duplicate until restart. Check logs/subscriptions.json permissions "
                        "and disk space",
                        sub.chat_id,
                        sub.username,
                        exc_info=True,
                    )
                else:
                    daily_sent = 1
            else:
                daily_failed = 1

        user_tz_pending = self._user_tz(sub.pending_digest_timezone)
        now_pending = self._now_fn(user_tz_pending)
        pending_date = now_pending.date()
        pending_processed = self._was_processed(
            _DigestKind.PENDING,
            sub.chat_id,
            pending_date,
        )
        if not pending_processed and scheduler_policy.should_fire_pending_for_user(
            settings=sub,
            now_in_user_tz=now_pending,
        ):
            pending_due = 1
            log.info(
                "Pending digest firing at %s for chat_id=%s username=%s",
                now_pending.isoformat(timespec="seconds"),
                sub.chat_id,
                sub.username,
            )
            result = self._deliver_pending(
                sub,
                now_local=now_pending,
            )
            if result in (
                _PendingDeliveryOutcome.SENT,
                _PendingDeliveryOutcome.EMPTY,
            ):
                self._mark_processed(_DigestKind.PENDING, sub.chat_id, pending_date)
                try:
                    self._subscriptions.mark_pending_digest_sent(sub.chat_id, pending_date)
                except SubscriptionStorePersistenceError:
                    pending_failed = 1
                    log.warning(
                        "Pending digest processed but last_pending_digest_sent_date was not "
                        "saved (chat_id=%s username=%s); process-local checkpoint prevents "
                        "repeat work until restart. Check logs/subscriptions.json permissions "
                        "and disk space",
                        sub.chat_id,
                        sub.username,
                        exc_info=True,
                    )
                else:
                    if result is _PendingDeliveryOutcome.SENT:
                        pending_sent = 1
            elif result is _PendingDeliveryOutcome.FAILED:
                pending_failed = 1

        return daily_due, daily_sent, daily_failed, pending_due, pending_sent, pending_failed

    def _was_processed(self, kind: _DigestKind, chat_id: int, target_date: date) -> bool:
        with self._checkpoint_lock:
            return self._processed_dates.get((kind, chat_id)) == target_date

    def _mark_processed(self, kind: _DigestKind, chat_id: int, target_date: date) -> None:
        with self._checkpoint_lock:
            self._processed_dates[(kind, chat_id)] = target_date

    def _resolve_telegram_user_id(self, sub: DigestSettings) -> int | None:
        user_record = self._users.get(sub.telegram_user_id)
        if user_record is None:
            log.warning(
                "Digest skip: chat_id=%s telegram_user_id=%s user not found in users.json",
                sub.chat_id,
                sub.telegram_user_id,
            )
            return None
        if not user_record.has_calendar:
            log.warning(
                "Digest skip: chat_id=%s telegram_user_id=%s calendar not connected",
                sub.chat_id,
                sub.telegram_user_id,
            )
            return None
        return user_record.telegram_user_id

    def _deliver_daily(self, sub: DigestSettings, *, today: date) -> bool:
        telegram_user_id = self._resolve_telegram_user_id(sub)
        if telegram_user_id is None:
            return False

        # Per-user «Дайджест на сегодня» — всегда план на текущий день в TZ пользователя.
        target_date = resolve_target_date(DIGEST_MODE_TODAY, today)

        user_record = self._users.get(telegram_user_id)
        weather_in_plan = user_record.weather_in_plan_enabled if user_record is not None else True
        try:
            exclusion_policy = self._meeting_exclusions.policy_for_user(telegram_user_id)
            plan_bundle = self._plan_builder.build_plan_bundle(
                telegram_user_id=telegram_user_id,
                target_date=target_date,
                reference_date=today,
                weather_in_plan_enabled=weather_in_plan,
                exclusion_policy=exclusion_policy,
            )
        except (CalendarNotConnectedError, CalendarProviderError) as exc:
            log.error(
                "Daily digest calendar failure for chat_id=%s username=%s: %s",
                sub.chat_id,
                sub.username,
                exc,
            )
            return False

        effect = (
            pick_plan_message_effect(plan_bundle.fallback_html)
            if is_private_chat(sub.chat_id)
            else None
        )
        try:
            deliver_rich_or_html(
                self._telegram,
                sub.chat_id,
                rich_html=plan_bundle.rich_html,
                fallback_html=plan_bundle.fallback_html,
                message_effect_id=effect,
            )
            log.info(
                "Daily digest sent: chat_id=%s username=%s",
                sub.chat_id,
                sub.username,
            )
            return True
        except TelegramError as exc:
            log.error(
                "Daily digest send failed: chat_id=%s username=%s: %s",
                sub.chat_id,
                sub.username,
                exc,
            )
            return False

    def _deliver_pending(
        self,
        sub: DigestSettings,
        *,
        now_local: datetime,
    ) -> _PendingDeliveryOutcome:
        telegram_user_id = self._resolve_telegram_user_id(sub)
        if telegram_user_id is None:
            return _PendingDeliveryOutcome.FAILED

        user_tz = self._user_tz(sub.pending_digest_timezone)
        try:
            screen = load_pending_invitations_screen(
                self._calendar_service,
                telegram_user_id,
                tz=user_tz,
                now=now_local,
            )
        except (CalendarNotConnectedError, CalendarProviderError) as exc:
            log.error(
                "Pending digest calendar failure for chat_id=%s username=%s: %s",
                sub.chat_id,
                sub.username,
                exc,
            )
            return _PendingDeliveryOutcome.FAILED

        if not screen.pending:
            log.info(
                "Pending digest skipped (empty): chat_id=%s username=%s",
                sub.chat_id,
                sub.username,
            )
            return _PendingDeliveryOutcome.EMPTY

        try:
            deliver_rich_or_html(
                self._telegram,
                sub.chat_id,
                rich_html=screen.rich_text,
                fallback_html=screen.text,
                reply_markup=screen.keyboard,
            )
            log.info(
                "Pending digest sent: chat_id=%s username=%s count=%d",
                sub.chat_id,
                sub.username,
                len(screen.pending),
            )
            return _PendingDeliveryOutcome.SENT
        except TelegramError as exc:
            log.error(
                "Pending digest send failed: chat_id=%s username=%s: %s",
                sub.chat_id,
                sub.username,
                exc,
            )
            return _PendingDeliveryOutcome.FAILED
