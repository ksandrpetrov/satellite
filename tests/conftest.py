"""Общие фикстуры и builder'ы для всех тестов Satellite.

Цель — снизить boilerplate в business-flow-тестах, не пряча контракт.
Builder'ы — pure (без I/O, без monkeypatch), фикстуры собирают их в готовые
объекты на ``tmp_path``.
"""

from __future__ import annotations

import socket
from collections.abc import Iterable
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from satellite.calendar.stats import NormalizedEvent
from satellite.calendar.time_utils import parse_hhmm
from satellite.telegram_bot.handlers.context import IncomingCallback, IncomingMessage
from satellite.testing.delivery_helpers import (
    callback_edit_html,
    callback_edit_markup,
    callback_edit_was_called,
    final_message_html,
    final_reply_markup,
    sent_messages_text,
)

# --- event builder (исторический, для калькулятора метрик) -----------------


def make_event(
    title: str,
    start: str,
    end: str,
    *,
    location: str | None = None,
    conference_url: str | None = None,
    is_cancelled: bool = False,
    is_pending: bool = False,
    is_tentative: bool = False,
) -> NormalizedEvent:
    """Удобный конструктор NormalizedEvent из ``HH:MM`` для тестов.

    Production-путь строит NormalizedEvent через ``normalize_caldav_event``;
    в юнит-тестах метрик мы пропускаем CalDAV-словарь и сразу собираем
    нормализованное событие — это устраняет второй путь нормализации.
    """
    return NormalizedEvent(
        title=title,
        start_minutes=parse_hhmm(start),
        end_minutes=parse_hhmm(end),
        location=location,
        conference_url=conference_url,
        is_cancelled=is_cancelled,
        is_pending=is_pending,
        is_tentative=is_tentative,
    )


# --- ActionGuard reset (autouse) -------------------------------------------


@pytest.fixture(autouse=True)
def _reset_action_guards():
    """Сбрасывает module-level ``ActionGuard``-синглтоны между тестами.

    Назначение: guard-ы (analytics/plan/upcoming/invitations/manage/partstat)
    держат cooldown per ``(chat_id, action)``. Без сброса cooldown с прошлого
    теста ловит повторный вызов команды (``/td`` и т.п.) в текущем тесте, и
    тот видит 0 ``send`` вместо ожидаемого 1 (с логом
    ``Plan run skipped (duplicate within cooldown)``).

    Импорты внутри фикстуры — чтобы collect-time не падал, если кто-то
    переименует/удалит соответствующие модули.
    """
    from satellite.calendar.event_token_cache import reset_event_token_cache
    from satellite.telegram_bot.handlers import analytics as _analytics
    from satellite.telegram_bot.handlers import calendar_foreign as _foreign
    from satellite.telegram_bot.handlers import calendar_invitations as _invitations
    from satellite.telegram_bot.handlers import calendar_list as _upcoming
    from satellite.telegram_bot.handlers import calendar_manage as _manage
    from satellite.telegram_bot.handlers import partstat_flow as _partstat
    from satellite.telegram_bot.handlers import plan as _plan
    from satellite.telegram_bot.handlers import settings_hub as _settings_hub
    from satellite.telegram_bot.handlers.calendar_view import clear_calendar_list_cache

    reset_event_token_cache()
    clear_calendar_list_cache()
    _foreign.clear_foreign_list_cache()

    for guard in (
        _analytics._analytics_run_guard,
        _plan._plan_run_guard,
        _upcoming._upcoming_guard,
        _invitations._invitations_open_guard,
        _manage._manage_open_guard,
        _partstat._partstat_respond_guard,
    ):
        guard.reset()
    _settings_hub.reset_settings_hub_message_tracker()
    yield


# --- Telegram client mock --------------------------------------------------


def make_fake_telegram() -> MagicMock:
    """Готовый MagicMock-стенд для ``TelegramClient`` в handler-тестах.

    Возвращаемые значения совпадают с тем, что Telegram реально шлёт в
    happy-path (``message_id`` есть, ``answer_callback_query`` True, и т.д.).
    """
    tg = MagicMock()
    tg.send_message = MagicMock(return_value={"message_id": 100})
    tg.send_message_draft = MagicMock(return_value=False)
    tg.send_rich_message_draft = MagicMock(return_value=False)
    tg.send_rich_message = MagicMock(return_value={"message_id": 1})
    tg.edit_message_rich = MagicMock(return_value={"message_id": 100})
    tg.edit_message_text = MagicMock(return_value={"message_id": 100})
    tg.answer_callback_query = MagicMock(return_value=True)
    tg.send_photo = MagicMock(return_value={"message_id": 101})
    tg.send_chat_action = MagicMock(return_value=True)
    tg.delete_message = MagicMock(return_value=True)
    tg.set_chat_menu_button = MagicMock(return_value=True)
    tg.bot_token = "test-token:12345"
    return tg


# Re-export for backward compatibility in tests that import from conftest via pytest.
__all__ = [
    "callback_edit_html",
    "callback_edit_markup",
    "callback_edit_was_called",
    "final_message_html",
    "final_reply_markup",
    "sent_messages_text",
]


# --- IncomingMessage / IncomingCallback builders ---------------------------


def make_msg(
    *,
    text: str | None,
    chat_id: int = 5001,
    user_id: int | None = 5001,
    username: str | None = "alice",
    display_name: str | None = "Alice",
    message_id: int | None = None,
    web_app_data: str | None = None,
    update_id: int = 1,
) -> IncomingMessage:
    return IncomingMessage(
        update_id=update_id,
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        display_name=display_name,
        text=text,
        message_id=message_id,
        web_app_data=web_app_data,
    )


_CALLBACK_SEQ = 0


def make_callback(
    *,
    data: str | None,
    chat_id: int = 5001,
    user_id: int | None = 5001,
    username: str | None = "alice",
    message_id: int = 42,
    update_id: int | None = None,
    callback_query_id: str | None = None,
) -> IncomingCallback:
    """IncomingCallback с уникальным id (важно: dispatcher dedup'ит по id)."""
    global _CALLBACK_SEQ
    _CALLBACK_SEQ += 1
    return IncomingCallback(
        update_id=update_id if update_id is not None else 1000 + _CALLBACK_SEQ,
        callback_query_id=callback_query_id or f"cb-{_CALLBACK_SEQ}",
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        username=username,
        data=data,
    )


# --- UserStore presets -----------------------------------------------------


def make_user_store(
    tmp_path: Path,
    *,
    pending: Iterable[int] = (),
    approved: Iterable[int] = (),
    approved_with_calendar: Iterable[int] = (),
    rejected: Iterable[int] = (),
    blocked: Iterable[int] = (),
    primary_calendar_url: str = "https://cal.example/primary/",
) -> Any:
    """UserStore с пред-заполненными статусами для разных user_id.

    Возвращает экземпляр ``UserStore`` (Path: ``tmp_path / "users.json"``).
    Sequence values — telegram_user_id. Пользователь идёт по одной ветке;
    overlap между группами не допустим (assert внутри).
    """
    from satellite.users import (
        CALENDAR_CONNECTED,
        USER_STATUS_APPROVED,
        USER_STATUS_BLOCKED,
        USER_STATUS_PENDING,
        USER_STATUS_REJECTED,
        UserStore,
    )

    store = UserStore(tmp_path / "users.json")

    all_ids = (
        list(pending)
        + list(approved)
        + list(approved_with_calendar)
        + list(rejected)
        + list(blocked)
    )
    assert len(set(all_ids)) == len(all_ids), "duplicate telegram_user_id in make_user_store groups"

    def _seed(uid: int, *, status: str, with_calendar: bool = False) -> None:
        store.upsert_from_telegram(
            telegram_user_id=uid,
            chat_id=uid,
            username=f"user{uid}",
            display_name=f"User {uid}",
            default_status=status,
        )
        if with_calendar:
            store.set_calendar_connection(
                uid,
                provider="mailru",
                encrypted_credentials="encrypted-blob",
                primary_calendar_url=primary_calendar_url,
            )
            store.mark_calendar_status(uid, status=CALENDAR_CONNECTED)

    for uid in pending:
        _seed(uid, status=USER_STATUS_PENDING)
    for uid in approved:
        _seed(uid, status=USER_STATUS_APPROVED)
    for uid in approved_with_calendar:
        _seed(uid, status=USER_STATUS_APPROVED, with_calendar=True)
    for uid in rejected:
        _seed(uid, status=USER_STATUS_REJECTED)
    for uid in blocked:
        _seed(uid, status=USER_STATUS_BLOCKED)
    return store


# --- HandlerContext factory ------------------------------------------------


def make_ctx(
    users: Any,
    *,
    tz: str | tzinfo = "Europe/Moscow",
    telegram: MagicMock | None = None,
    calendar_service: MagicMock | None = None,
    subscriptions: Any | None = None,
    admin_ids: Iterable[int] = (),
    webapp_base_url: str = "https://example.com/connect",
) -> MagicMock:
    """``MagicMock(spec=HandlerContext)``-подобный стенд для handler-тестов.

    Сохраняет публичные атрибуты ``HandlerContext`` (см. handlers/context.py);
    `spec=HandlerContext` не используем, чтобы можно было свободно патчить
    атрибуты, которых нет в продакшен-объекте.
    """
    from satellite.config import AdminConfig

    ctx = MagicMock()
    ctx.users = users
    ctx.admin = AdminConfig(telegram_ids=tuple(admin_ids))
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = webapp_base_url

    from satellite.telegram_bot.handlers.calendar_state import CalendarStateStore
    from satellite.telegram_bot.handlers.digest_state import DigestStateStore
    from satellite.web.connect_token import ConnectTokenStore

    ctx.connect_tokens = ConnectTokenStore()
    ctx.calendar_state = CalendarStateStore()
    ctx.digest_state = DigestStateStore()
    ctx.tz = ZoneInfo(tz) if isinstance(tz, str) else tz
    ctx.telegram = telegram if telegram is not None else make_fake_telegram()
    ctx.calendar_service = calendar_service if calendar_service is not None else MagicMock()
    ctx.subscriptions = subscriptions if subscriptions is not None else MagicMock()
    ctx.weather_config = MagicMock()
    ctx.weather_client = None
    ctx._plan_builder = MagicMock()
    ctx.plan_builder = MagicMock(return_value=ctx._plan_builder)
    ctx.plan_config = MagicMock()
    return ctx


# --- fake UserCalendarService ----------------------------------------------


class FakeCalendarService:
    """Лёгкий заместитель ``UserCalendarService`` для handler-тестов.

    Контракт совпадает с тем, что зовут handler'ы (``list_events``,
    ``list_events_for_invitations``, ``set_attendee_partstat``, ``create_event``,
    ``disconnect``); другие методы добавить по месту.
    """

    def __init__(
        self,
        *,
        events: list[dict[str, Any]] | None = None,
        invitations: list[dict[str, Any]] | None = None,
        raise_on_list: Exception | None = None,
        raise_on_invitations: Exception | None = None,
        raise_on_create: Exception | None = None,
        raise_on_partstat: Exception | None = None,
    ) -> None:
        self.events = list(events or [])
        self.invitations = list(invitations or [])
        self.raise_on_list = raise_on_list
        self.raise_on_invitations = raise_on_invitations
        self.raise_on_create = raise_on_create
        self.raise_on_partstat = raise_on_partstat
        self.list_calls: list[dict[str, Any]] = []
        self.list_invitations_calls: list[dict[str, Any]] = []
        self.create_calls: list[Any] = []
        self.partstat_calls: list[Any] = []
        self.disconnect_calls: list[int] = []

    def list_events(self, user_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_calls.append({"user_id": user_id, **kwargs})
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return list(self.events)

    def list_events_for_invitations(self, user_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_invitations_calls.append({"user_id": user_id, **kwargs})
        if self.raise_on_invitations is not None:
            raise self.raise_on_invitations
        return list(self.invitations)

    def set_attendee_partstat(self, user_id: int, **kwargs: Any) -> None:
        self.partstat_calls.append({"user_id": user_id, **kwargs})
        if self.raise_on_partstat is not None:
            raise self.raise_on_partstat

    def create_event(self, user_id: int, payload: Any, *, tz: tzinfo) -> Any:
        self.create_calls.append({"user_id": user_id, "payload": payload, "tz": tz})
        if self.raise_on_create is not None:
            raise self.raise_on_create
        return MagicMock()

    def disconnect(self, user_id: int) -> None:
        self.disconnect_calls.append(user_id)


# --- frozen clock ----------------------------------------------------------


def freeze_now(monkeypatch: pytest.MonkeyPatch, *, module: str, now: datetime) -> None:
    """Подменяет ``datetime.datetime.now`` в конкретном модуле на фиксированное значение.

    Используем по-модульный patch, потому что разные хендлеры вызывают
    `datetime.now(...)` через `from datetime import datetime` (имя
    закреплено за модулем при импорте).
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            if tz is None:
                return now.replace(tzinfo=None)
            if now.tzinfo is None:
                return now.replace(tzinfo=tz)
            return now.astimezone(tz)

    monkeypatch.setattr(f"{module}.datetime", _FrozenDatetime)


# --- web request helper ----------------------------------------------------


def free_tcp_port() -> int:
    """Возвращает свободный TCP порт на 127.0.0.1 — для started_server-фикстур."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
