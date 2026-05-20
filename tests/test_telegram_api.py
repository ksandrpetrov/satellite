"""Юнит-тесты Telegram API клиента."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from satellite.telegram_bot.api import TelegramClient, TelegramError


def test_send_chat_action_is_best_effort_without_retries() -> None:
    client = TelegramClient("token")
    client._session.request = MagicMock(side_effect=requests.Timeout("slow"))  # noqa: SLF001

    with pytest.raises(TelegramError, match="after 0 retries"):
        client.send_chat_action(123, timeout=0.1)

    client._session.request.assert_called_once()  # noqa: SLF001


def test_network_error_does_not_leak_bot_token() -> None:
    token = "123456:secret-token"
    client = TelegramClient(token)
    client._session.request = MagicMock(  # noqa: SLF001
        side_effect=requests.Timeout(
            f"GET https://api.telegram.org/bot{token}/sendMessage timed out"
        )
    )

    with pytest.raises(TelegramError) as exc_info:
        client.send_chat_action(123, timeout=0.1)

    message = str(exc_info.value)
    assert token not in message
    assert "<telegram-token>" in message


def test_long_poll_uses_separate_session_from_outgoing() -> None:
    """``getUpdates`` и исходящие запросы не должны делить пул соединений.

    Иначе долгий long-poll блокирует ``sendMessage``/``editMessageText``
    из воркер-пула — наблюдалось в проде, ответ задерживался на 30–60 с.
    """
    client = TelegramClient("token")
    assert client._session is not client._long_poll_session  # noqa: SLF001


def test_get_updates_does_not_block_send_message() -> None:
    """Висящий ``getUpdates`` не должен задерживать ``sendMessage``.

    Регрессия: раньше глобальный ``_request_lock`` заворачивал HTTP-запрос
    целиком, поэтому исходящее сообщение из воркера ждало long-poll до 30 с.
    """
    client = TelegramClient("token")

    long_poll_in_flight = threading.Event()
    long_poll_release = threading.Event()

    def _slow_long_poll(*_args, **_kwargs):
        long_poll_in_flight.set()
        if not long_poll_release.wait(timeout=2.0):
            raise AssertionError("long-poll release event not set")
        return _ok_response([])

    def _fast_send(*_args, **_kwargs):
        return _ok_response({"message_id": 7})

    client._long_poll_session.request = MagicMock(side_effect=_slow_long_poll)  # noqa: SLF001
    client._session.request = MagicMock(side_effect=_fast_send)  # noqa: SLF001

    poll_done = threading.Event()

    def _poll() -> None:
        client.get_updates(0, timeout=30)
        poll_done.set()

    poller = threading.Thread(target=_poll, name="test-long-poll", daemon=True)
    poller.start()
    assert long_poll_in_flight.wait(timeout=2.0), "long-poll did not start"

    started = time.monotonic()
    result = client.send_message(123, "hi")
    elapsed = time.monotonic() - started

    assert result == {"message_id": 7}
    assert elapsed < 0.5, (
        f"send_message blocked behind long-poll for {elapsed:.2f}s"
    )

    long_poll_release.set()
    assert poll_done.wait(timeout=2.0), "long-poll did not finish"


def _ok_response(result):
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"ok": True, "result": result}
    return response
