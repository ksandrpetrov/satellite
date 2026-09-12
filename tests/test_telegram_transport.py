"""HTTP failures exercised through the public Telegram API, without live requests."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
import requests

from satellite.telegram_bot.api import TelegramClient, TelegramError

TOKEN = "123456:test-only-secret"


def response(status: int, payload: dict | None = None, *, body: str = "", headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = (json.dumps(payload) if payload is not None else body).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def transport(monkeypatch):
    client = TelegramClient(TOKEN, backoff_base_sec=1, backoff_cap_sec=10)
    request = Mock()
    monkeypatch.setattr(client._session, "request", request)
    waits = []
    monkeypatch.setattr("satellite.telegram_bot.api.client.time.sleep", waits.append)
    monkeypatch.setattr("satellite.telegram_bot.api.client.random.uniform", lambda *_: 0)
    try:
        yield client, request, waits
    finally:
        client.close()


@pytest.mark.parametrize("failure", [408, 500, 502, 503, 504, "timeout", "oserror"])
def test_transient_failure_retries_once_with_unchanged_message(transport, failure):
    client, request, waits = transport
    first = (
        requests.Timeout("slow")
        if failure == "timeout"
        else OSError("connection reset")
        if failure == "oserror"
        else response(failure)
    )
    request.side_effect = [first, response(200, {"ok": True, "result": {"message_id": 7}})]
    assert client.send_message(42, "hello") == {"message_id": 7}
    assert request.call_count == 2
    assert request.call_args_list[0] == request.call_args_list[1]
    assert waits == [1]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_http_failure_does_not_retry_or_expose_token(transport, status, caplog):
    client, request, waits = transport
    request.return_value = response(status, body=f"Rejected https://api.telegram.org/bot{TOKEN}")
    with pytest.raises(TelegramError) as error:
        client.send_message(42, "hello")
    assert f"HTTP {status}" in str(error.value)
    assert TOKEN not in str(error.value) + caplog.text
    request.assert_called_once()
    assert waits == []


@pytest.mark.parametrize(
    "payload,headers,expected_wait",
    [
        ({"parameters": {"retry_after": 3}}, {"Retry-After": "7"}, 3),
        ({"parameters": {"retry_after": "bad"}}, {"Retry-After": "4"}, 4),
        (None, {"Retry-After": "2"}, 2),
        ({"parameters": {"retry_after": -1}}, {"Retry-After": "bad"}, 1),
        ({"parameters": {"retry_after": 100}}, {}, 10),
    ],
)
def test_rate_limit_obeys_wait_sources_and_cap(transport, payload, headers, expected_wait):
    client, request, waits = transport
    request.side_effect = [
        response(429, payload, body="not JSON", headers=headers),
        response(200, {"ok": True, "result": {"message_id": 8}}),
    ]
    assert client.send_message(42, "hello") == {"message_id": 8}
    assert request.call_count == 2
    assert waits == [expected_wait]


@pytest.mark.parametrize("status", [429, 503])
def test_retry_budget_stops_repeated_failure(transport, status):
    client, request, waits = transport
    request.return_value = response(status, {"parameters": {"retry_after": 2}})
    with pytest.raises(TelegramError, match="after 1 retries"):
        client.send_message(42, "hello")
    assert request.call_count == 2
    assert len(waits) == 1


@pytest.mark.parametrize("kind", ["invalid_json", "api_error"])
def test_unsuccessful_200_is_not_reported_as_delivery(transport, kind):
    client, request, waits = transport
    request.return_value = (
        response(200, body="not JSON")
        if kind == "invalid_json"
        else response(200, {"ok": False, "description": f"failed {TOKEN}"})
    )
    with pytest.raises(TelegramError) as error:
        client.send_message(42, "hello")
    assert TOKEN not in str(error.value)
    assert waits == []
    request.assert_called_once()


def test_effect_then_html_rejection_preserves_message_and_keyboard(transport):
    client, request, waits = transport
    snapshots = []
    replies = iter(
        [
            response(400, body="PREMIUM_ACCOUNT_REQUIRED"),
            response(400, body="CUSTOM_EMOJI_ID_INVALID"),
            response(200, {"ok": True, "result": {"message_id": 9}}),
        ]
    )

    def capture(*_args, **kwargs):
        snapshots.append(dict(kwargs["data"]))
        return next(replies)

    request.side_effect = capture
    keyboard = {"inline_keyboard": [[{"text": "Open", "callback_data": "open"}]]}
    result = client.send_message(
        42,
        '<tg-emoji emoji-id="1">🪶</tg-emoji> hello',
        message_effect_id="effect",
        reply_markup=keyboard,
    )
    assert result == {"message_id": 9}
    assert len(snapshots) == 3
    assert snapshots[0]["message_effect_id"] == "effect"
    assert "message_effect_id" not in snapshots[1]
    assert "message_effect_id" not in snapshots[2]
    assert "tg-emoji" in snapshots[1]["text"]
    assert snapshots[2]["text"] == "🪶 hello"
    assert all(json.loads(item["reply_markup"]) == keyboard for item in snapshots)
    assert all(item["chat_id"] == 42 for item in snapshots)
    assert waits == []
