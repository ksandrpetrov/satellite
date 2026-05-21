"""Контекст хендлеров и плоские DTO для сообщений / callback_query.

``HandlerContext`` — общий контейнер сервисов, передаваемый в каждый
хендлер. Поля сгруппированы по ролям:

- **messaging** (telegram, visual, delivery) — отправка/редактирование сообщений;
- **identity** (users, admin, connect_tokens, webapp) — кто и какой статус;
- **calendar** (calendar_service, _plan_builder) — CalDAV и сборка дайджеста;
- **scheduling** (subscriptions, weather_config, weather_client) — фоновые задачи;
- **ui state** (digest_state, calendar_state, plan_config, tz) — конкретный экран/сессия.

Свойства :meth:`messaging`/:meth:`identity`/:meth:`calendar`/:meth:`scheduling`
возвращают immutable views — новые хендлеры могут принимать только нужный
срез вместо всего god-объекта. Поля остаются плоскими ради backward-compat.
"""

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
class MessagingContext:
    telegram: TelegramClient


@dataclass(frozen=True)
class IdentityContext:
    users: UserStore
    admin: AdminConfig
    connect_tokens: ConnectTokenStore
    webapp: WebAppConfig


@dataclass(frozen=True)
class CalendarContext:
    calendar_service: UserCalendarService
    plan_builder: PlanBuilder


@dataclass(frozen=True)
class SchedulingContext:
    subscriptions: SubscriptionStore
    weather_config: WeatherConfig
    weather_client: WeatherForecastClient | None


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

    @property
    def messaging(self) -> MessagingContext:
        return MessagingContext(telegram=self.telegram)

    @property
    def identity(self) -> IdentityContext:
        return IdentityContext(
            users=self.users,
            admin=self.admin,
            connect_tokens=self.connect_tokens,
            webapp=self.webapp,
        )

    @property
    def calendar(self) -> CalendarContext:
        return CalendarContext(
            calendar_service=self.calendar_service,
            plan_builder=self._plan_builder,
        )

    @property
    def scheduling(self) -> SchedulingContext:
        return SchedulingContext(
            subscriptions=self.subscriptions,
            weather_config=self.weather_config,
            weather_client=self.weather_client,
        )


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
