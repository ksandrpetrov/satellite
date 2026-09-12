"""Corrupted bytes must follow each store's documented recovery policy."""

from __future__ import annotations

import json

import pytest

from satellite.subscriptions import SubscriptionStore, SubscriptionStoreLoadError
from satellite.telegram_bot.offset_store import OffsetStore
from satellite.users import UserStore, UserStoreLoadError


@pytest.mark.parametrize(
    "store,error",
    [(UserStore, UserStoreLoadError), (SubscriptionStore, SubscriptionStoreLoadError)],
)
def test_invalid_utf8_raises_public_load_error_without_rewriting_file(tmp_path, store, error):
    path = tmp_path / "state.json"
    original = b'{"broken": "\xff"}'
    path.write_bytes(original)
    with pytest.raises(error):
        store(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "payload", [None, [], "bad", {"offset": None}, {"offset": []}, {"offset": -1}]
)
def test_invalid_offset_shape_recovers_to_zero(tmp_path, payload):
    path = tmp_path / "offset.json"
    original = json.dumps(payload)
    path.write_text(original)
    assert OffsetStore(path).offset == 0
    assert path.read_text() == original
