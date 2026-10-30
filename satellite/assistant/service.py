"""One bounded turn: human-only intent → calendar use case → read-only explanation."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ..calendar.providers.base import CalendarProviderError
from ..calendar.user_calendar_service import UserCalendarService
from ..messages_ru import (
    AI_BUDGET,
    AI_BUSY,
    AI_ERROR,
    AI_EVENT_CHANGED,
    AI_NOT_ORGANIZER,
    AI_READ_FALLBACK,
    AI_TIMED_ONLY,
    AI_UNCONFIRMED,
    ai_report_text,
)
from .calendar_tools import CalendarTools, mutation_from_dict
from .config import AiConfig
from .prompts import PLANNER, WRITER, calendar_tools
from .provider import AiUnavailable, ResponsesProvider, TurnBudget
from .store import AiStore, BudgetExceeded

log = logging.getLogger(__name__)


class AssistantService:
    def __init__(
        self,
        config: AiConfig,
        store: AiStore,
        provider: ResponsesProvider,
        calendar: UserCalendarService,
        *,
        workers: int = 4,
    ) -> None:
        self.config, self.store, self.provider, self.calendar = config, store, provider, calendar
        self._slots = threading.BoundedSemaphore(max(0, min(2, config.concurrency, workers - 1)))
        self._active_lock = threading.Lock()
        self._active_users: set[int] = set()

    def is_running(self, user_id: int | None) -> bool:
        with self._active_lock:
            return user_id in self._active_users

    def close(self) -> None:
        self.provider.close()

    def reset(self, user_id: int) -> None:
        self.store.reset(user_id)

    def respond(
        self, user_id: int, update_id: int, text: str, tz_name: str, *, now: datetime | None = None
    ) -> str:
        if not self._slots.acquire(blocking=False):
            return AI_BUSY
        with self._active_lock:
            if user_id in self._active_users:
                self._slots.release()
                return AI_BUSY
            self._active_users.add(user_id)
        try:
            return self._respond(user_id, update_id, text, ZoneInfo(tz_name), now=now)
        except Exception as exc:
            # Never log exception text/body: provider and calendar errors can contain PII.
            log.warning(
                "AI turn failed user_id=%s update_id=%s error_type=%s code=%s",
                user_id,
                update_id,
                type(exc).__name__,
                getattr(exc, "error_code", None),
            )
            if isinstance(exc, BudgetExceeded):
                return AI_BUDGET
            if isinstance(exc, CalendarProviderError):
                code = exc.error_code
                if code == "NOT_ORGANIZER":
                    return AI_NOT_ORGANIZER
                if code in {"TIMED_EVENTS_ONLY", "UNSUPPORTED_RECURRENCE"}:
                    return AI_TIMED_ONLY
                if code in {"CALENDAR_CONNECTION_CHANGED", "EVENT_CHANGED"}:
                    return AI_EVENT_CHANGED
            turn = self.store.turn(user_id, update_id)
            if turn and turn.get("response"):
                return str(turn["response"])
            if turn and turn.get("mutation"):
                return AI_UNCONFIRMED
            return AI_ERROR
        finally:
            with self._active_lock:
                self._active_users.discard(user_id)
            self._slots.release()

    def _respond(
        self, user_id: int, update_id: int, text: str, tz: ZoneInfo, *, now: datetime | None
    ) -> str:
        if len(text) > 6000:
            raise AiUnavailable("Message too long")
        now = now or datetime.now(tz)
        connection = self.calendar.connection_id(user_id)
        self.calendar.require_connection(user_id)
        conversation = self.store.conversation(user_id, connection, now)
        budget = TurnBudget(
            time.monotonic() + self.config.timeout_seconds, self.config.max_requests
        )
        tools = CalendarTools(
            self.calendar, self.store, user_id, update_id, conversation, tz, now, budget
        )
        previous_turn = self.store.turn(user_id, update_id)
        if previous_turn:
            if previous_turn["connection"] != connection:
                return AI_EVENT_CHANGED
            if previous_turn.get("response"):
                return str(previous_turn["response"])
            if previous_turn.get("mutation"):
                mutation = mutation_from_dict(previous_turn["mutation"])
                self.calendar.apply_mutation(
                    user_id, mutation, reconcile_only=True, deadline=budget.deadline
                )
                return tools.finish_mutation(mutation, previous_turn["calendar"])
        # Calendar titles/descriptions and generated prose NEVER enter the planner.
        # Only human messages, its own prior request, and numeric server context do.
        messages = conversation.get("messages", [])[-19:]
        human = [{"role": "user", "content": m["content"]} for m in messages if m["role"] == "user"]
        context = {
            "NOW": now.isoformat(),
            "timezone": str(tz),
            "previous_request": conversation.get("previous_request"),
            "previous_request_completed": conversation.get("completed", False),
            "option_kind": conversation.get("option_kind"),
            "option_count": len(conversation.get("options", [])),
            "conflict_disclosed": bool(conversation.get("conflict")),
        }
        response = self.provider.request(
            user_id,
            budget,
            instructions=PLANNER + "\n" + json.dumps(context),
            input_items=[*human, {"role": "user", "content": text}],
            tools=calendar_tools(),
        )
        calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        if len(calls) != 1 or calls[0]["name"] not in {t["name"] for t in calendar_tools()}:
            raise AiUnavailable("Invalid tool response")
        plan = {"name": calls[0]["name"], "arguments": json.loads(calls[0]["arguments"])}
        # Persist the exact interpreted request before executing; repeated delivery
        # after a completed write never goes back to the language model.
        self.store.save_turn(
            user_id, update_id, {"connection": connection, "plan": plan, "status": "planned"}
        )
        result = tools.execute(plan)
        conversation.update(
            connection=connection,
            updated=now.isoformat(),
            previous_request=plan,
            completed=bool((self.store.turn(user_id, update_id) or {}).get("mutation")),
        )
        if isinstance(result, str):
            answer = result
        else:
            try:
                explanation = self.provider.request(
                    user_id,
                    budget,
                    instructions=WRITER,
                    input_items=[
                        {"role": "user", "content": json.dumps(result, ensure_ascii=False)}
                    ],
                    optimize=plan["name"] == "optimize",
                )
                answer = "\n".join(
                    c["text"]
                    for item in explanation.get("output", [])
                    if item.get("type") == "message"
                    for c in item.get("content", [])
                    if c.get("type") == "output_text"
                )
                if not answer.strip():
                    raise AiUnavailable("Empty explanation")
            except Exception as exc:
                log.warning(
                    "AI explanation failed user_id=%s error_type=%s", user_id, type(exc).__name__
                )
                answer = AI_READ_FALLBACK
            answer = answer[:700] + "\n\n" + ai_report_text(result)
        conversation["messages"] = [
            *messages,
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer},
        ][-20:]
        self.store.save_conversation(user_id, conversation)
        turn = self.store.turn(user_id, update_id) or {"connection": connection}
        turn.update(response=answer, status="done", updated=now.isoformat())
        self.store.save_turn(user_id, update_id, turn)
        return answer
