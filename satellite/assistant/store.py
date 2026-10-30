"""Encrypted conversation, durable action journal and atomic global spending cap."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from ..json_store import JsonStoreBase, JsonStoreLoadError
from .config import USD_NANO


class AiStoreError(RuntimeError):
    pass


class BudgetExceeded(AiStoreError):
    pass


def _empty() -> dict[str, Any]:
    return {"conversation": {}, "turns": {}, "requests": {}}


class AiStore(JsonStoreBase[dict[str, Any]]):
    _PERSISTENCE_ERROR = AiStoreError
    _LOAD_ERROR = JsonStoreLoadError
    _STORE_LABEL = "AI state"

    def __init__(self, path: str | Path, encryption_key: str) -> None:
        super().__init__(path)
        self._cipher = Fernet(encryption_key.encode("ascii"))
        raw = self._load_json_root()
        if not raw and not self._path.exists():
            return
        try:
            if raw.get("version") != 1 or not isinstance(raw.get("users"), dict):
                raise ValueError("Invalid state envelope")
            for user_id, blob in raw["users"].items():
                record = json.loads(self._cipher.decrypt(blob.encode("ascii")))
                self._validate(record)
                self._items[int(user_id)] = record
        except (InvalidToken, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise self._load_error("invalid or undecryptable AI state") from exc

    @staticmethod
    def _validate(record: Any) -> None:
        if not isinstance(record, dict) or set(record) != {"conversation", "turns", "requests"}:
            raise ValueError("Invalid AI record")
        if any(not isinstance(record[key], dict) for key in record):
            raise ValueError("Invalid AI record fields")
        for req in record["requests"].values():
            if (
                not isinstance(req, dict)
                or not isinstance(req.get("month"), str)
                or type(req.get("cost")) is not int
                or req["cost"] < 0
                or req.get("status") not in {"reserved", "settled", "error"}
            ):
                raise ValueError("Invalid usage record")
        for turn in record["turns"].values():
            if not isinstance(turn, dict) or not isinstance(turn.get("connection"), str):
                raise ValueError("Invalid operation journal")

    def _build_snapshot_payload(self, items: Mapping[int, dict[str, Any]]) -> dict[str, Any]:
        return {
            "version": 1,
            "users": {
                str(uid): self._cipher.encrypt(
                    json.dumps(record, ensure_ascii=False).encode()
                ).decode()
                for uid, record in items.items()
            },
        }

    def _save(self, user_id: int, record: dict[str, Any]) -> None:
        self._commit_items_locked({**self._items, user_id: record})

    def conversation(self, user_id: int, connection: str, now: datetime) -> dict[str, Any]:
        with self._lock:
            record = copy.deepcopy(self._items.get(user_id, _empty()))
            expired = [
                key
                for key, turn in record["turns"].items()
                if not turn.get("mutation")
                and turn.get("updated")
                and datetime.fromisoformat(turn["updated"]) + timedelta(hours=24) <= now
            ]
            for key in expired:
                del record["turns"][key]
            conversation = record["conversation"]
            if conversation and (
                conversation.get("connection") != connection
                or datetime.fromisoformat(conversation["updated"]) + timedelta(hours=24) <= now
            ):
                record["conversation"] = {}
                self._save(user_id, record)
            elif expired:
                self._save(user_id, record)
            return record["conversation"]

    def save_conversation(self, user_id: int, conversation: dict[str, Any]) -> None:
        with self._lock:
            record = copy.deepcopy(self._items.get(user_id, _empty()))
            record["conversation"] = copy.deepcopy(conversation)
            record["conversation"]["messages"] = conversation.get("messages", [])[-20:]
            self._save(user_id, record)

    def reset(self, user_id: int) -> None:
        self.save_conversation(user_id, {})

    def turn(self, user_id: int, update_id: int) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._items.get(user_id, _empty())["turns"].get(str(update_id)))

    def save_turn(self, user_id: int, update_id: int, turn: dict[str, Any]) -> None:
        with self._lock:
            record = copy.deepcopy(self._items.get(user_id, _empty()))
            record["turns"][str(update_id)] = copy.deepcopy(turn)
            self._save(user_id, record)

    def reserve(self, user_id: int, month: str, cost: int, limit_usd: int) -> str:
        if cost < 0:
            raise ValueError("Negative reservation")
        with self._lock:
            spent = sum(
                req["cost"]
                for user in self._items.values()
                for req in user["requests"].values()
                if req["month"] == month
            )
            if spent + cost > limit_usd * USD_NANO:
                raise BudgetExceeded("AI monthly cap reached")
            request_id = uuid4().hex
            record = copy.deepcopy(self._items.get(user_id, _empty()))
            record["requests"][request_id] = {"month": month, "cost": cost, "status": "reserved"}
            self._save(user_id, record)
            return request_id

    def settle(
        self, user_id: int, request_id: str, cost: int | None, *, error: bool = False
    ) -> None:
        with self._lock:
            record = copy.deepcopy(self._items[user_id])
            req = record["requests"][request_id]
            if cost is not None:
                if cost < 0:
                    raise ValueError("Negative usage")
                req["cost"] = cost
                req["status"] = "settled"
            if error:
                req["status"] = "error"
            self._save(user_id, record)

    def usage(self, month: str) -> dict[str, Any]:
        with self._lock:
            users = {}
            for uid, record in self._items.items():
                reqs = [r for r in record["requests"].values() if r["month"] == month]
                if reqs:
                    users[str(uid)] = {
                        "cost": sum(r["cost"] for r in reqs),
                        "requests": len(reqs),
                        "errors": sum(r["status"] == "error" for r in reqs),
                        "reserved": sum(r["status"] == "reserved" for r in reqs),
                    }
            return {
                "month": month,
                "users": users,
                "cost": sum(u["cost"] for u in users.values()),
                "requests": sum(u["requests"] for u in users.values()),
                "errors": sum(u["errors"] for u in users.values()),
                "reserved": sum(u["reserved"] for u in users.values()),
            }
