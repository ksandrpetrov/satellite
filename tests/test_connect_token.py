"""Токены Web App connect без initData."""

from __future__ import annotations

import json

from satellite.web.connect_token import ConnectTokenStore


def test_issue_and_resolve() -> None:
    store = ConnectTokenStore(ttl_sec=60)
    token = store.issue(42)
    assert store.resolve(token) == 42


def test_expired_token_returns_none() -> None:
    now = {"t": 1000.0}

    def _now() -> float:
        return now["t"]

    store = ConnectTokenStore(ttl_sec=1, now_fn=_now)
    token = store.issue(7)
    now["t"] += 1.1
    assert store.resolve(token) is None


def test_persistence_round_trip(tmp_path) -> None:
    path = tmp_path / "connect-tokens.json"
    store1 = ConnectTokenStore(ttl_sec=900, storage_path=path)
    token = store1.issue(42)
    store2 = ConnectTokenStore(ttl_sec=900, storage_path=path)
    assert store2.resolve(token) == 42


def test_corrupt_file_recovery(tmp_path) -> None:
    path = tmp_path / "connect-tokens.json"
    path.write_text("{not json", encoding="utf-8")
    store = ConnectTokenStore(ttl_sec=60, storage_path=path)
    token = store.issue(99)
    assert store.resolve(token) == 99


def test_expired_purged_on_save(tmp_path) -> None:
    now = {"t": 2000.0}

    def _now() -> float:
        return now["t"]

    path = tmp_path / "connect-tokens.json"
    store = ConnectTokenStore(ttl_sec=1, storage_path=path, now_fn=_now)
    old = store.issue(1)
    now["t"] += 1.1
    store.issue(2)
    assert store.resolve(old) is None
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert old not in raw


def test_storage_path_none_means_no_file_io(tmp_path) -> None:
    store = ConnectTokenStore(storage_path=None)
    store.issue(5)
    assert not (tmp_path / "connect-tokens.json").exists()
