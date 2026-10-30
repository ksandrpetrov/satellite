"""Real SDK contract boundary with no network: count, reserve, settle, fail closed."""

import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest
from cryptography.fernet import Fernet
from openai import APIStatusError

from satellite.assistant.config import MAX_INPUT_NUSD, OUTPUT_NUSD, AiConfig
from satellite.assistant.provider import AiUnavailable, ResponsesProvider, TurnBudget, usage_cost
from satellite.assistant.store import AiStore


@pytest.fixture
def provider(tmp_path):
    store = AiStore(tmp_path / "ai.json", Fernet.generate_key().decode())
    client = MagicMock()
    client.responses.input_tokens.count.return_value = SimpleNamespace(input_tokens=100)
    client.responses.create.return_value.model_dump.return_value = {
        "status": "completed",
        "output": [],
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 10},
            "output_tokens": 80,
            "output_tokens_details": {"reasoning_tokens": 60},
        },
    }
    return ResponsesProvider(AiConfig(), store, "Europe/Moscow", client=client)


def request(provider):
    return provider.request(
        1,
        TurnBudget(time.monotonic() + 120),
        instructions="calendar",
        input_items=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "name": "read_calendar"}],
    )


def test_count_payload_matches_generation_and_all_usage_is_settled(provider):
    request(provider)
    counted = provider.client.responses.input_tokens.count.call_args.kwargs
    created = provider.client.responses.create.call_args.kwargs
    assert all(created[k] == v for k, v in counted.items() if k != "timeout")
    assert created["store"] is False
    assert created["parallel_tool_calls"] is False
    assert created["service_tier"] == "default"
    month = datetime.now(provider.tz).strftime("%Y-%m")
    assert provider.store.usage(month)["cost"] == 70 * 2000 + 20 * 100 + 10 * 2500 + 80 * 10000
    assert provider.store.usage(month)["reserved"] == 0


@pytest.mark.parametrize("status", [401, 429])
def test_definite_api_rejection_releases_reservation(provider, status):
    response = httpx2.Response(
        status, request=httpx2.Request("POST", "https://api.openai.com/v1/responses")
    )
    provider.client.responses.create.side_effect = APIStatusError(
        "rejected", response=response, body={}
    )
    with pytest.raises(APIStatusError):
        request(provider)
    usage = provider.store.usage(datetime.now(provider.tz).strftime("%Y-%m"))
    assert usage["cost"] == 0 and usage["errors"] == 1


def test_timeout_keeps_maximum_reservation_and_does_not_retry(provider):
    provider.client.responses.create.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        request(provider)
    usage = provider.store.usage(datetime.now(provider.tz).strftime("%Y-%m"))
    assert usage["cost"] == 100 * MAX_INPUT_NUSD + 4000 * OUTPUT_NUSD
    assert provider.client.responses.create.call_count == 1


def test_context_and_deadline_limits_stop_before_paid_call(provider):
    provider.client.responses.input_tokens.count.return_value.input_tokens = 24001
    with pytest.raises(AiUnavailable):
        request(provider)
    provider.client.responses.create.assert_not_called()
    with pytest.raises(AiUnavailable):
        provider.request(1, TurnBudget(time.monotonic() - 1), instructions="", input_items=[])
    with pytest.raises(AiUnavailable):
        provider.request(1, TurnBudget(time.monotonic() + 100, 0), instructions="", input_items=[])
    assert usage_cost(None) is None
    assert usage_cost({"input_tokens": -1, "output_tokens": 1}) is None
