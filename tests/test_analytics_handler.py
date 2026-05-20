"""Регрессия handlers.analytics: непредвиденная ошибка не оставляет «🌀 сводит неделю…».

Когда `build_week_analytics` падает с любой ошибкой за пределами
`CalendarProviderError`/`CalendarNotConnectedError` (пример из прода —
``ModuleNotFoundError: No module named 'PIL'``), пользователь не должен
видеть оба сообщения: и зависший «Чайка сводит неделю по календарю…», и
generic-ошибку диспетчера. Хендлер обязан подменить loading-сообщение и
проглотить исключение.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from satellite.calendar.providers.base import (
    CalendarNotConnectedError,
    CalendarProviderError,
)
from satellite.messages_ru import (
    ANALYTICS_FETCH_STATUS,
    ERR_CALDAV_UNAVAILABLE_TEXT,
    ERR_GENERIC_HANDLER_TEXT,
)
from satellite.telegram_bot.handlers import IncomingCallback, handle_callback_query
from satellite.telegram_bot.handlers.analytics import CB_ANALYTICS_RUN
from satellite.users import CALENDAR_CONNECTED, USER_STATUS_APPROVED, UserStore


def _approved_user(tmp_path: Path) -> UserStore:
    store = UserStore(tmp_path / "users.json")
    store.upsert_from_telegram(
        telegram_user_id=1,
        chat_id=900,
        username="alice",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    store.set_calendar_connection(
        1,
        provider="mailru",
        encrypted_credentials="enc",
        primary_calendar_url="https://cal/primary",
    )
    store.mark_calendar_status(1, status=CALENDAR_CONNECTED)
    return store


def _ctx(tmp_path: Path, *, build_side_effect):
    users = _approved_user(tmp_path)
    ctx = MagicMock()
    ctx.users = users
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=False)
    ctx.webapp = MagicMock()
    ctx.webapp.base_url = ""
    ctx.calendar_state = MagicMock()
    ctx.calendar_state.get = MagicMock(return_value=None)
    ctx.digest_state = MagicMock()
    ctx.digest_state.is_waiting_for_time = MagicMock(return_value=False)
    ctx.digest_state.claim_callback = MagicMock(return_value=True)
    ctx.tz = ZoneInfo("Europe/Moscow")
    ctx.subscriptions = MagicMock()
    ctx.telegram = MagicMock()
    ctx.telegram.send_message = MagicMock(return_value={"message_id": 7777})
    ctx.telegram.edit_message_text = MagicMock(return_value={})
    ctx.telegram.send_photo = MagicMock(return_value={"message_id": 7778})
    ctx.telegram.delete_message = MagicMock(return_value=True)
    ctx.telegram.answer_callback_query = MagicMock(return_value=True)
    ctx.calendar_service = MagicMock()
    return ctx, users


def _run_analytics_callback(ctx, *, build_side_effect, monkeypatch):
    def fake_build(**_kwargs):
        if isinstance(build_side_effect, Exception):
            raise build_side_effect
        return build_side_effect

    monkeypatch.setattr(
        "satellite.telegram_bot.handlers.analytics.build_week_analytics",
        fake_build,
    )
    cb = IncomingCallback(
        update_id=42,
        callback_query_id="cb-analytics",
        chat_id=900,
        message_id=55,
        user_id=1,
        username="alice",
        data=CB_ANALYTICS_RUN,
    )
    handle_callback_query(ctx, cb)


def test_unexpected_exception_replaces_loading_message(
    tmp_path: Path, monkeypatch, caplog
):
    ctx, _users = _ctx(tmp_path, build_side_effect=None)
    err = ModuleNotFoundError("No module named 'PIL'")
    with caplog.at_level(logging.ERROR, logger="satellite.telegram_bot.handlers"):
        _run_analytics_callback(
            ctx, build_side_effect=err, monkeypatch=monkeypatch
        )

    loading_calls = [
        c
        for c in ctx.telegram.send_message.call_args_list
        if c.args[1] == ANALYTICS_FETCH_STATUS
    ]
    assert len(loading_calls) == 1, "Должно быть ровно одно loading-сообщение"

    edits = ctx.telegram.edit_message_text.call_args_list
    assert any(
        c.args[2] == ERR_GENERIC_HANDLER_TEXT for c in edits
    ), "Loading-сообщение обязано подмениться текстом ошибки через editMessageText"

    sent_texts = [c.args[1] for c in ctx.telegram.send_message.call_args_list]
    assert ERR_GENERIC_HANDLER_TEXT not in sent_texts, (
        "Generic ошибка не должна слаться отдельным сообщением — это даст "
        "пользователю две одинаковые ошибки в чате."
    )

    assert any(record.exc_info is not None for record in caplog.records), (
        "Стек ошибки обязан попасть в лог."
    )


def test_calendar_provider_error_uses_caldav_text(tmp_path: Path, monkeypatch):
    ctx, _users = _ctx(tmp_path, build_side_effect=None)
    err = CalendarProviderError("boom", error_code="CALDAV_UNAVAILABLE")
    _run_analytics_callback(ctx, build_side_effect=err, monkeypatch=monkeypatch)

    edits = ctx.telegram.edit_message_text.call_args_list
    assert any(
        c.args[2] == ERR_CALDAV_UNAVAILABLE_TEXT for c in edits
    ), "CalendarProviderError должен показывать ERR_CALDAV_UNAVAILABLE_TEXT"


def test_not_connected_error_uses_caldav_text(tmp_path: Path, monkeypatch):
    ctx, _users = _ctx(tmp_path, build_side_effect=None)
    err = CalendarNotConnectedError()
    _run_analytics_callback(ctx, build_side_effect=err, monkeypatch=monkeypatch)

    edits = ctx.telegram.edit_message_text.call_args_list
    assert any(
        c.args[2] == ERR_CALDAV_UNAVAILABLE_TEXT for c in edits
    ), "CalendarNotConnectedError должен показывать ERR_CALDAV_UNAVAILABLE_TEXT"
