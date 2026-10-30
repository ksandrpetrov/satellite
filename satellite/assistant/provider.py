"""Official Responses SDK adapter with preflight counting and durable reservations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openai import APIStatusError, OpenAI

from .config import CACHED_INPUT_NUSD, INPUT_NUSD, MAX_INPUT_NUSD, OUTPUT_NUSD, AiConfig
from .store import AiStore

log = logging.getLogger(__name__)


class AiUnavailable(RuntimeError):
    pass


@dataclass
class TurnBudget:
    deadline: float
    remaining_requests: int = 6

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AiUnavailable("AI turn deadline exceeded")
        return remaining


def usage_cost(usage: dict[str, Any] | None) -> int | None:
    if not usage:
        return None
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    details = usage.get("input_tokens_details") or {}
    cached, written = details.get("cached_tokens", 0), details.get("cache_write_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (inp, out, cached, written)):
        return None
    assert isinstance(inp, int) and isinstance(out, int)
    if cached + written > inp:
        return None
    # Explicit 30-minute cache TTL; output_tokens already includes reasoning.
    return (
        (inp - cached - written) * INPUT_NUSD
        + cached * CACHED_INPUT_NUSD
        + written * 2_500
        + out * OUTPUT_NUSD
    )


class ResponsesProvider:
    def __init__(
        self, config: AiConfig, store: AiStore, tz_name: str, *, client: Any = None
    ) -> None:
        self.config, self.store, self.tz = config, store, ZoneInfo(tz_name)
        # No automatic retries: an unanswered paid request retains its reservation.
        self.client = client or OpenAI(api_key=config.api_key, max_retries=0, timeout=45)

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        user_id: int,
        budget: TurnBudget,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        optimize: bool = False,
    ) -> dict[str, Any]:
        if budget.remaining_requests <= 0:
            raise AiUnavailable("AI request limit reached")
        budget.remaining_requests -= 1
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": input_items,
            "instructions": instructions,
            "reasoning": {"effort": "medium" if optimize else "low"},
        }
        if tools:
            payload.update(tools=tools, tool_choice="required", parallel_tool_calls=False)
        request_id = None
        try:
            count = self.client.responses.input_tokens.count(
                **payload, timeout=min(15, budget.remaining())
            ).input_tokens
            if count > self.config.max_input_tokens or count < 0:
                raise AiUnavailable("AI context too large")
            month = datetime.now(self.tz).strftime("%Y-%m")
            reserve = count * MAX_INPUT_NUSD + self.config.max_output_tokens * OUTPUT_NUSD
            request_id = self.store.reserve(user_id, month, reserve, self.config.monthly_limit_usd)
            response = self.client.responses.create(
                **payload,
                max_output_tokens=self.config.max_output_tokens,
                service_tier="default",
                store=False,
                prompt_cache_options={"mode": "implicit", "ttl": "30m"},
                timeout=min(55, budget.remaining()),
            ).model_dump()
            self.store.settle(user_id, request_id, usage_cost(response.get("usage")))
            if response.get("status") != "completed":
                raise AiUnavailable("AI response incomplete")
            return response
        except Exception as exc:
            if request_id:
                definite = isinstance(exc, APIStatusError) and exc.status_code in (
                    400,
                    401,
                    403,
                    404,
                    422,
                    429,
                )
                self.store.settle(user_id, request_id, 0 if definite else None, error=True)
            log.warning(
                "AI request failed user_id=%s error_type=%s status=%s",
                user_id,
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            raise
