"""Фоновый scheduler для per-user дайджеста.

Дизайн (Вариант А из ТЗ):

- Один поток просыпается каждые ``tick_interval_sec`` (по умолчанию 30 с)
  и сверяет ``HH:MM`` в часовом поясе пользователя с его ``digest_time``.
- Если совпало, день недели разрешён, и сегодня этому пользователю ещё
  не отправляли — стреляем; ``last_digest_sent_date`` записываем только после
  успешного ``sendMessage``.
- Каждый подписчик обрабатывается независимо (фейл одного не валит остальных).
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, tzinfo
from typing import Callable
from zoneinfo import ZoneInfo

from .calendar.providers.base import CalendarNotConnectedError, CalendarProviderError
from .calendar.time_utils import parse_hhmm
from .calendar.user_calendar_service import UserCalendarService
from .config import DigestConfig, PlanConfig, WeatherConfig
from .digest_utils import is_digest_day_allowed, resolve_target_date
from .plan_service import PlanBuilder
from .subscriptions import DigestSettings, SubscriptionStore
from .telegram_bot.api import TelegramClient, TelegramError
from .telegram_bot.visual import is_private_chat, pick_plan_message_effect
from .users import UserStore
from .weather.client import WeatherForecastClient

log = logging.getLogger(__name__)

_DEFAULT_TICK_SEC = 30.0


def should_fire_for_user(
    *,
    settings: DigestSettings,
    now_in_user_tz: datetime,
) -> bool:
    """Чистая функция-решатель для одного пользователя."""
    if not settings.digest_enabled:
        return False
    if not is_digest_day_allowed(settings.digest_days, now_in_user_tz.weekday()):
        return False
    try:
        scheduled_minutes = parse_hhmm(settings.digest_time)
    except ValueError:
        log.warning(
            "Invalid digest_time for chat_id=%s: %r",
            settings.chat_id,
            settings.digest_time,
        )
        return False
    current_minutes = now_in_user_tz.hour * 60 + now_in_user_tz.minute
    if current_minutes != scheduled_minutes:
        return False
    today_iso = now_in_user_tz.date().isoformat()
    if settings.last_digest_sent_date == today_iso:
        return False
    return True


class DigestScheduler:
    """Тикающий планировщик. Запускается отдельным потоком."""

    def __init__(
        self,
        *,
        digest_config: DigestConfig,
        plan_config: PlanConfig,
        tz: tzinfo,
        subscriptions: SubscriptionStore,
        users: UserStore,
        calendar_service: UserCalendarService,
        telegram: TelegramClient,
        stop_event: threading.Event | None = None,
        tick_interval_sec: float = _DEFAULT_TICK_SEC,
        now_fn: Callable[[tzinfo], datetime] | None = None,
        weather_config: WeatherConfig | None = None,
        weather_client: WeatherForecastClient | None = None,
    ) -> None:
        self._digest_config = digest_config
        self._plan_config = plan_config
        self._tz = tz
        self._subscriptions = subscriptions
        self._users = users
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
        self._now_fn = now_fn or (lambda tz_: datetime.now(tz=tz_))
        self._thread: threading.Thread | None = None
        self._tz_cache: dict[str, ZoneInfo] = {}

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
            "Digest scheduler started: per-user schedule; tick=%.0fs mode=%s",
            self._tick_interval_sec,
            self._digest_config.mode,
        )

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._tick_interval_sec + 2)

    def tick(self) -> int:
        """Один логический шаг. Возвращает количество успешно отправленных дайджестов."""
        subscriptions = self._subscriptions.list()
        if not subscriptions:
            return 0
        due = 0
        delivered = 0
        failed = 0
        for sub in subscriptions:
            if self._stop_event.is_set():
                break
            try:
                result = self._maybe_deliver(sub)
                if result is None:
                    continue
                due += 1
                if result:
                    delivered += 1
                else:
                    failed += 1
            except Exception:  # noqa: BLE001 - один пользователь не валит остальных
                failed += 1
                log.exception(
                    "Failed to deliver digest to chat_id=%s username=%s",
                    sub.chat_id,
                    sub.username,
                )
        if due or failed:
            log.info(
                "Digest scheduler tick: checked=%d due=%d sent=%d failed=%d",
                len(subscriptions),
                due,
                delivered,
                failed,
            )
        return delivered

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

    def _maybe_deliver(self, sub: DigestSettings) -> bool | None:
        user_tz = self._user_tz(sub.digest_timezone)
        now_local = self._now_fn(user_tz)
        if not should_fire_for_user(settings=sub, now_in_user_tz=now_local):
            return None
        today = now_local.date()
        log.info(
            "Digest firing at %s for chat_id=%s username=%s",
            now_local.isoformat(timespec="seconds"),
            sub.chat_id,
            sub.username,
        )
        delivered = self._deliver(sub, today=today)
        if delivered:
            self._subscriptions.mark_digest_sent(sub.chat_id, today)
        return delivered

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

    def _deliver(self, sub: DigestSettings, *, today: date) -> bool:
        telegram_user_id = self._resolve_telegram_user_id(sub)
        if telegram_user_id is None:
            return False

        target_date = resolve_target_date(self._digest_config.mode, today)

        try:
            plan_text = self._plan_builder.build_text(
                telegram_user_id=telegram_user_id,
                target_date=target_date,
                reference_date=today,
            )
        except (CalendarNotConnectedError, CalendarProviderError) as exc:
            log.error(
                "Digest calendar failure for chat_id=%s username=%s: %s",
                sub.chat_id,
                sub.username,
                exc,
            )
            return False

        effect = (
            pick_plan_message_effect(plan_text)
            if is_private_chat(sub.chat_id)
            else None
        )
        try:
            self._telegram.send_message(
                sub.chat_id,
                plan_text,
                message_effect_id=effect,
            )
            log.info(
                "Digest sent: chat_id=%s username=%s",
                sub.chat_id,
                sub.username,
            )
            return True
        except TelegramError as exc:
            log.error(
                "Digest send failed: chat_id=%s username=%s: %s",
                sub.chat_id,
                sub.username,
                exc,
            )
            return False
