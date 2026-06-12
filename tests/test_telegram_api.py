"""Юнит-тесты Telegram API клиента."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from satellite.telegram_bot.api import TelegramClient, TelegramError


def test_answer_callback_query_is_best_effort_without_retries() -> None:
    client = TelegramClient("token")
    client._session.request = MagicMock(side_effect=requests.Timeout("slow"))  # noqa: SLF001

    with pytest.raises(TelegramError, match="after 0 retries"):
        client.answer_callback_query("cb-1")

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
        client.send_message(123, "hi")

    message = str(exc_info.value)
    assert token not in message
    assert "<telegram-token>" in message


def test_send_rich_message_posts_json_payload() -> None:
    client = TelegramClient("token")
    client._session.request = MagicMock(  # noqa: SLF001
        return_value=_ok_response({"message_id": 11})
    )
    payload = {"html": "<p>hi</p>", "skip_entity_detection": True}
    result = client.send_rich_message(123, payload)
    assert result == {"message_id": 11}
    call = client._session.request.call_args  # noqa: SLF001
    assert "sendRichMessage" in call[0][1]
    assert '"html": "<p>hi</p>"' in call.kwargs["data"]["rich_message"]


def test_send_rich_message_draft_posts_to_dedicated_method() -> None:
    client = TelegramClient("token")
    client._session.request = MagicMock(  # noqa: SLF001
        return_value=_ok_response(True)
    )
    payload = {"html": "<p>draft</p>"}
    assert client.send_rich_message_draft(123, 42, payload) is True
    call = client._session.request.call_args  # noqa: SLF001
    assert "sendRichMessageDraft" in call[0][1]
    assert call.kwargs["data"]["draft_id"] == 42


def test_send_message_draft_posts_to_dedicated_method() -> None:
    client = TelegramClient("token")
    client._session.request = MagicMock(  # noqa: SLF001
        return_value=_ok_response(True)
    )
    assert client.send_message_draft(123, 99, "hi", parse_mode="HTML") is True
    call = client._session.request.call_args  # noqa: SLF001
    assert "sendMessageDraft" in call[0][1]
    assert call.kwargs["data"]["draft_id"] == 99


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
    assert elapsed < 0.5, f"send_message blocked behind long-poll for {elapsed:.2f}s"

    long_poll_release.set()
    assert poll_done.wait(timeout=2.0), "long-poll did not finish"


def _capture_call_snapshots(side_effects: list) -> tuple[MagicMock, list[dict]]:
    """Mock ``_call`` так, чтобы сохранять снимок ``data`` на момент каждого вызова.

    Клиент переиспользует один и тот же словарь между первичным и retry-вызовом
    (просто удаляя ``message_effect_id``), поэтому пост-фактум осмотр
    ``call_args_list[i].kwargs["data"]`` показал бы один и тот же объект уже без
    эффекта. Снимок копируем синхронно из ``side_effect``.
    """
    snapshots: list[dict] = []
    iterator = iter(side_effects)

    def _capture(*_args, **kwargs) -> object:
        snapshots.append(dict(kwargs["data"]))
        outcome = next(iterator)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return MagicMock(side_effect=_capture), snapshots


def test_send_photo_retries_without_effect_on_premium_required() -> None:
    """Telegram отвечает ``PREMIUM_ACCOUNT_REQUIRED`` — повторяем без эффекта.

    Регрессия из прода: пользователь без Premium → анимированный эффект ✨ в
    `sendPhoto` валит весь ответ с аналитикой; клиент должен сам выкинуть
    `message_effect_id` и переотправить.
    """
    client = TelegramClient("token")
    mock_call, snapshots = _capture_call_snapshots(
        [
            TelegramError(
                'sendPhoto: HTTP 400: {"ok":false,"error_code":400,'
                '"description":"Bad Request: PREMIUM_ACCOUNT_REQUIRED"}'
            ),
            {"message_id": 42},
        ]
    )
    client._call = mock_call  # noqa: SLF001

    result = client.send_photo(
        123,
        b"PNG",
        caption="cap",
        message_effect_id="5089460564141278042",
    )

    assert result == {"message_id": 42}
    assert len(snapshots) == 2
    assert snapshots[0]["message_effect_id"] == "5089460564141278042"
    assert "message_effect_id" not in snapshots[1]


def test_send_message_retries_without_effect_on_premium_required() -> None:
    """``sendMessage`` тоже должен переотправляться без эффекта (тот же кейс)."""
    client = TelegramClient("token")
    mock_call, snapshots = _capture_call_snapshots(
        [
            TelegramError(
                'sendMessage: HTTP 400: {"ok":false,"error_code":400,'
                '"description":"Bad Request: PREMIUM_ACCOUNT_REQUIRED"}'
            ),
            {"message_id": 7},
        ]
    )
    client._call = mock_call  # noqa: SLF001

    result = client.send_message(123, "hi", message_effect_id="5089460564141278042")

    assert result == {"message_id": 7}
    assert len(snapshots) == 2
    assert snapshots[0]["message_effect_id"] == "5089460564141278042"
    assert "message_effect_id" not in snapshots[1]


def test_send_message_retries_without_effect_on_message_effect_error() -> None:
    """Также реагируем на старое сообщение Telegram про сам `message_effect_id`."""
    client = TelegramClient("token")
    client._call = MagicMock(  # noqa: SLF001
        side_effect=[
            TelegramError("sendMessage: HTTP 400: Bad Request: message_effect_id invalid"),
            {"message_id": 8},
        ]
    )

    result = client.send_message(123, "hi", message_effect_id="bogus")

    assert result == {"message_id": 8}
    assert client._call.call_count == 2  # noqa: SLF001


def test_send_message_does_not_retry_on_unrelated_errors() -> None:
    """Ошибки, не связанные с эффектом, наружу — не маскируем."""
    client = TelegramClient("token")
    client._call = MagicMock(  # noqa: SLF001
        side_effect=TelegramError("sendMessage: HTTP 403: Forbidden: bot was blocked")
    )

    with pytest.raises(TelegramError, match="bot was blocked"):
        client.send_message(123, "hi", message_effect_id="5089460564141278042")

    client._call.assert_called_once()  # noqa: SLF001


def test_send_message_retries_without_tg_emoji_on_custom_emoji_error() -> None:
    client = TelegramClient("token")
    mock_call, snapshots = _capture_call_snapshots(
        [
            TelegramError("sendMessage: HTTP 400: Bad Request: CUSTOM_EMOJI_ID_INVALID"),
            {"message_id": 9},
        ]
    )
    client._call = mock_call  # noqa: SLF001

    html = '<tg-emoji emoji-id="1">🪶</tg-emoji> hi'
    result = client.send_message(123, html)

    assert result == {"message_id": 9}
    assert len(snapshots) == 2
    assert "<tg-emoji" in snapshots[0]["text"]
    assert "<tg-emoji" not in snapshots[1]["text"]
    assert "🪶" in snapshots[1]["text"]


def test_send_message_retries_without_tg_emoji_on_document_invalid() -> None:
    """``DOCUMENT_INVALID`` — типичный ответ Telegram на ``<tg-emoji>`` у бота
    без купленного имени на Fragment. Тоже должно лечиться снятием тегов.
    """
    client = TelegramClient("token")
    mock_call, snapshots = _capture_call_snapshots(
        [
            TelegramError(
                'sendMessage: HTTP 400: {"ok":false,"error_code":400,'
                '"description":"Bad Request: DOCUMENT_INVALID"}'
            ),
            {"message_id": 17},
        ]
    )
    client._call = mock_call  # noqa: SLF001

    html = '<tg-emoji emoji-id="1">🪶</tg-emoji> привет'
    result = client.send_message(123, html)

    assert result == {"message_id": 17}
    assert len(snapshots) == 2
    assert "<tg-emoji" in snapshots[0]["text"]
    assert "<tg-emoji" not in snapshots[1]["text"]
    assert "🪶" in snapshots[1]["text"]


def test_send_message_link_preview_options_json() -> None:
    client = TelegramClient("token")
    captured: dict = {}

    def fake_call(method_name, *, data=None, timeout=None, max_retries=None, **_):
        captured["data"] = data
        return {"message_id": 1}

    client._call = fake_call  # noqa: SLF001
    client.send_message(
        123,
        "see https://example.com",
        link_preview_options={"url": "https://example.com", "show_above_text": True},
        disable_web_page_preview=False,
    )
    import json

    opts = json.loads(captured["data"]["link_preview_options"])
    assert opts["show_above_text"] is True
    assert "disable_web_page_preview" not in captured["data"]


def test_set_my_name_description_short_description(monkeypatch) -> None:
    client = TelegramClient("test-token")
    methods: list[str] = []

    def fake_call(method_name, *, data=None, timeout=None, max_retries=None, **_):
        methods.append(method_name)
        return True

    monkeypatch.setattr(client, "_call", fake_call)

    client.set_my_name("Чайка")
    client.set_my_description("desc")
    client.set_my_short_description("short")

    assert methods == ["setMyName", "setMyDescription", "setMyShortDescription"]


def _ok_response(result):
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"ok": True, "result": result}
    return response
