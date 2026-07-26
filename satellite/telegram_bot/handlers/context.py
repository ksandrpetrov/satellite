"""Плоский DI-контейнер хендлеров и DTO Telegram updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import tzinfo

from ...calendar.user_calendar_service import UserCalendarService
from ...config import AdminConfig, PlanConfig, WeatherConfig, WebAppConfig
from ...plan_service import PlanBuilder
from ...subscriptions import SubscriptionStore
from ...users import UserStore
from ...weather.client import WeatherForecastClient
from ...web.connect_token import ConnectTokenStore
from ..api import TelegramClient
from .calendar_state import CalendarStateStore
from .digest_state import DigestStateStore

PlanMode = str  # "today" | "tomorrow" | "day_after_tomorrow"
SubscriptionAction = str  # "subscribe" | "unsubscribe"


@dataclass(frozen=True)
class HandlerContext:
    telegram: TelegramClient
    calendar_service: UserCalendarService
    users: UserStore
    plan_config: PlanConfig
    tz: tzinfo
    admin: AdminConfig
    webapp: WebAppConfig
    connect_tokens: ConnectTokenStore
    subscriptions: SubscriptionStore
    weather_config: WeatherConfig
    weather_client: WeatherForecastClient | None
    digest_state: DigestStateStore
    calendar_state: CalendarStateStore
    _plan_builder: PlanBuilder

    def plan_builder(self) -> PlanBuilder:
        return self._plan_builder


@dataclass(frozen=True)
class IncomingMessage:
    update_id: int
    chat_id: int | None
    user_id: int | None
    username: str | None
    display_name: str | None
    text: str | None
    message_id: int | None = None
    web_app_data: str | None = None


@dataclass(frozen=True)
class IncomingCallback:
    update_id: int
    callback_query_id: str
    chat_id: int | None
    message_id: int | None
    user_id: int | None
    username: str | None
    data: str | None
