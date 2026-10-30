"""Spending cannot escape the global cap, restarts, or a failed disk commit."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet

from satellite.assistant.config import USD_NANO
from satellite.assistant.store import AiStore, AiStoreError, BudgetExceeded
from satellite.json_store import JsonStoreLoadError


def test_global_reservations_are_atomic_and_survive_restart(tmp_path):
    key = Fernet.generate_key().decode()
    store = AiStore(tmp_path / "ai.json", key)

    def reserve(uid):
        try:
            return store.reserve(uid, "2026-10", USD_NANO, 50)
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(reserve, range(100)))
    assert len([r for r in accepted if r]) == 50
    restored = AiStore(tmp_path / "ai.json", key)
    assert restored.usage("2026-10")["cost"] == 50 * USD_NANO
    with pytest.raises(BudgetExceeded):
        restored.reserve(101, "2026-10", 1, 50)
    restored.reserve(101, "2026-11", 1, 50)
    assert restored.usage("2026-11")["cost"] == 1


def test_context_encrypted_expires_and_reset_keeps_journal(tmp_path):
    key = Fernet.generate_key().decode()
    store = AiStore(tmp_path / "ai.json", key)
    now = datetime(2026, 10, 30, 10, tzinfo=ZoneInfo("Europe/Moscow"))
    store.save_conversation(
        1,
        {
            "connection": "old",
            "updated": now.isoformat(),
            "messages": [{"role": "user", "content": "секретная встреча"}],
        },
    )
    store.save_turn(1, 7, {"connection": "old", "response": "секретная встреча", "mutation": {}})
    request_id = store.reserve(1, "2026-10", 100, 50)
    assert "секретная" not in (tmp_path / "ai.json").read_text()
    assert store.conversation(2, "old", now) == {}
    assert store.conversation(1, "old", now)["messages"]
    assert store.conversation(1, "old", now + timedelta(hours=24)) == {}
    store.reset(1)
    assert store.turn(1, 7)["response"] == "секретная встреча"
    store.settle(1, request_id, None, error=True)
    assert store.usage("2026-10")["cost"] == 100
    assert store.usage("2026-10")["errors"] == 1


def test_reconnection_clears_context(tmp_path):
    store = AiStore(tmp_path / "ai.json", Fernet.generate_key().decode())
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    store.save_conversation(1, {"connection": "a", "updated": now.isoformat(), "messages": []})
    assert store.conversation(1, "b", now) == {}


def test_corrupt_usage_never_resets_budget_and_failed_commit_does_not_publish(tmp_path):
    key = Fernet.generate_key().decode()
    path = tmp_path / "ai.json"
    path.write_text("{}")
    with pytest.raises(JsonStoreLoadError):
        AiStore(path, key)
    path.unlink()
    store = AiStore(path, key)
    store.reserve(1, "2026-10", 400, 50)
    before = path.read_bytes()
    store._persist_payload = MagicMock(side_effect=AiStoreError("disk full"))
    with pytest.raises(AiStoreError):
        store.reserve(2, "2026-10", 900, 50)
    assert store.usage("2026-10")["cost"] == 400
    assert path.read_bytes() == before
    with pytest.raises(JsonStoreLoadError):
        AiStore(path, Fernet.generate_key().decode())
