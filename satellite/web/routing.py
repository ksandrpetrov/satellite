"""Маршрутизация HTTP-запросов Web App-сервера и общий ``Deps``.

Хендлеры регистрируются как ``(method, path-matcher, fn)`` в общей таблице
:data:`ROUTES`. Каждый хендлер принимает только ``BaseHTTPRequestHandler``
и :class:`Deps` (общий контейнер ссылок на сервисы). Любой новый endpoint
добавляется одной строкой в таблице и одной функцией в ``web/api/``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from http.server import BaseHTTPRequestHandler

from ..calendar.user_calendar_service import UserCalendarService
from ..config import PlanConfig
from ..users import UserStore
from .connect_token import ConnectTokenStore


@dataclass(frozen=True)
class Deps:
    """Общий контейнер ссылок на сервисы, передаваемый каждому хендлеру."""

    calendar: UserCalendarService
    users: UserStore
    bot_token: str
    connect_tokens: ConnectTokenStore
    plan_config: PlanConfig
    tz: tzinfo


HandlerFn = Callable[[BaseHTTPRequestHandler, Deps], None]


@dataclass(frozen=True)
class Route:
    """Один маршрут таблицы: точный путь или предикат + handler."""

    method: str
    handler: HandlerFn
    path: str | None = None
    path_prefix: str | None = None

    def matches(self, method: str, path: str) -> bool:
        if method != self.method:
            return False
        if self.path is not None:
            return path == self.path
        if self.path_prefix is not None:
            return path.startswith(self.path_prefix)
        return False


def find_route(routes: list[Route], method: str, path: str) -> HandlerFn | None:
    for route in routes:
        if route.matches(method, path):
            return route.handler
    return None
