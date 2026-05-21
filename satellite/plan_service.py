"""Сервис сборки плана дня: CalDAV → фильтр → текст «чайки».

Единая точка истины для сборки текста плана: используется и интерактивным
ботом, и фоновым `DigestScheduler`. Календарные credentials берутся из
``UserCalendarService`` per-user — глобального Mail.ru-токена больше нет.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, tzinfo

from .calendar.events import filter_events_for_user
from .calendar.stats import DayCalendarStats, WorkdayOptions
from .calendar.user_calendar_service import UserCalendarService
from .config import PlanConfig, WeatherConfig
from .seagull.digest import prepare_seagull_stats, render_digest_from_stats
from .seagull.rules import SeagullTexts, build_seagull_texts
from .weather.analyzer import summarize_for_digest_day
from .weather.client import WeatherForecastClient
from .weather.templates import build_weather_message

log = logging.getLogger(__name__)

_WEATHER_PREFETCH_JOIN_SEC = 6.0
_WEATHER_FETCH_INLINE = object()


@dataclass(frozen=True)
class PlanBuilder:
    """Чистая обёртка над «достать → отфильтровать → собрать текст»."""

    calendar_service: UserCalendarService
    plan_config: PlanConfig
    tz: tzinfo
    weather_config: WeatherConfig | None = None
    weather_client: WeatherForecastClient | None = None

    def build_day_stats(
        self,
        *,
        telegram_user_id: int,
        target_date: date,
        reference_date: date,
    ) -> tuple[DayCalendarStats, SeagullTexts]:
        """Сборка статистики дня (без weather/render).

        Тот же путь сбора, что используется в :meth:`build_text` для дайджеста —
        чтобы share-карточки и текстовый дайджест видели идентичные данные.
        """
        events, login = self.calendar_service.fetch_events_for_day(
            telegram_user_id,
            target_date,
            tz=self.tz,
        )
        visible, hidden_meals = filter_events_for_user(
            events,
            target_date,
            tz=self.tz,
            login=login,
            hide_all_day=self.plan_config.hide_all_day_events,
            hide_lunch=self.plan_config.hide_lunch_events,
        )
        stats, _meal_footer = prepare_seagull_stats(
            visible,
            target_date,
            tz=self.tz,
            reference_date=reference_date,
            login=login,
            hidden_meal_events=hidden_meals,
        )
        return stats, build_seagull_texts(stats)

    def build_text(
        self,
        *,
        telegram_user_id: int,
        target_date: date,
        reference_date: date,
        on_progress: Callable[[str], None] | None = None,
    ) -> str:
        started_at = time.monotonic()
        cfg = self.weather_config
        client = self.weather_client
        prefetch_box: dict[str, object | None] = {}
        prefetch_thread: threading.Thread | None = None

        def _prefetch_hourly() -> None:
            assert client is not None and cfg is not None
            prefetch_box["forecast"] = client.get_forecast_for_date(cfg, target_date)

        if cfg is not None and cfg.enabled and client is not None:
            prefetch_thread = threading.Thread(
                target=_prefetch_hourly,
                name="satellite-weather-prefetch",
                daemon=True,
            )
            prefetch_thread.start()

        caldav_started = time.monotonic()
        events, login = self.calendar_service.fetch_events_for_day(
            telegram_user_id,
            target_date,
            tz=self.tz,
        )
        caldav_elapsed = time.monotonic() - caldav_started
        visible, hidden_meals = filter_events_for_user(
            events,
            target_date,
            tz=self.tz,
            login=login,
            hide_all_day=self.plan_config.hide_all_day_events,
            hide_lunch=self.plan_config.hide_lunch_events,
        )
        stats, meal_footer = prepare_seagull_stats(
            visible,
            target_date,
            tz=self.tz,
            reference_date=reference_date,
            login=login,
            hidden_meal_events=hidden_meals,
        )
        opts = WorkdayOptions()
        prefetched: object | None
        if prefetch_thread is not None:
            prefetch_thread.join(timeout=_WEATHER_PREFETCH_JOIN_SEC)
            if prefetch_thread.is_alive():
                log.warning(
                    "Weather prefetch did not finish within %.0fs; skipping weather block",
                    _WEATHER_PREFETCH_JOIN_SEC,
                )
                prefetched = None
            else:
                prefetched = prefetch_box.get("forecast")
        else:
            prefetched = _WEATHER_FETCH_INLINE

        if on_progress is not None:
            on_progress(
                render_digest_from_stats(
                    stats,
                    meal_footer,
                    escape_html=True,
                    weather_line=None,
                )
            )

        weather_started = time.monotonic()
        weather_line = self._build_weather_line(
            stats,
            target_date,
            reference_date,
            opts,
            prefetched_forecast=prefetched,
        )
        weather_elapsed = time.monotonic() - weather_started
        rendered = render_digest_from_stats(
            stats,
            meal_footer,
            escape_html=True,
            weather_line=weather_line,
        )
        log.info(
            "Built plan: user_id=%s date=%s events=%d caldav=%.2fs weather=%.2fs total=%.2fs",
            telegram_user_id,
            target_date.isoformat(),
            len(events),
            caldav_elapsed,
            weather_elapsed,
            time.monotonic() - started_at,
        )
        return rendered

    def _build_weather_line(
        self,
        stats,
        target_date: date,
        reference_date: date,
        opts: WorkdayOptions,
        *,
        prefetched_forecast: object | None,
    ) -> str | None:
        cfg = self.weather_config
        client = self.weather_client
        if cfg is None or not cfg.enabled or client is None:
            return None
        try:
            if prefetched_forecast is _WEATHER_FETCH_INLINE:
                bundle = client.get_forecast_for_date(cfg, target_date)
            else:
                bundle = prefetched_forecast  # type: ignore[assignment]
            if bundle is None or not bundle.hours:
                return None
            hours = list(bundle.hours)
            current_for_today = bundle.current if target_date == reference_date else None
            summary = summarize_for_digest_day(
                hours,
                stats,
                opts,
                location_name=cfg.location_name,
                tz_name=cfg.timezone,
                reference_date=reference_date,
                current_conditions=current_for_today,
            )
            return build_weather_message(
                summary,
                show_normal_weather=cfg.show_normal_weather,
                message_seed=target_date.isoformat(),
                digest_is_today=(target_date == reference_date),
            )
        except Exception:  # noqa: BLE001
            log.exception("Weather block skipped due to unexpected error")
            return None
