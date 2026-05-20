"""Токены Web App connect без initData."""

from __future__ import annotations

import time

from satellite.web.connect_token import ConnectTokenStore


def test_issue_and_resolve() -> None:
    store = ConnectTokenStore(ttl_sec=60)
    token = store.issue(42)
    assert store.resolve(token) == 42


def test_expired_token_returns_none() -> None:
    store = ConnectTokenStore(ttl_sec=1)
    token = store.issue(7)
    time.sleep(1.1)
    assert store.resolve(token) is None
