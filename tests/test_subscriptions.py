import json
from pathlib import Path

from satellite.subscriptions import Subscription, SubscriptionStore


def test_subscribe_creates_entry(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    assert store.subscribe(123, "aleksanderpetrov") is True
    assert store.is_subscribed(123)
    assert not store.is_subscribed(999)
    sub = store.get(123)
    assert isinstance(sub, Subscription)
    assert sub.username == "aleksanderpetrov"


def test_subscribe_is_idempotent_for_same_user(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    assert store.subscribe(123, "alex") is True
    assert store.subscribe(123, "alex") is False  # уже подписан с тем же username
    assert store.is_subscribed(123)


def test_subscribe_overwrites_username(tmp_path: Path):
    """Если у того же chat_id поменялся username — обновляем запись."""
    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(123, "old_name")
    result = store.subscribe(123, "new_name")
    # вернуло False, потому что подписка не «новая» (chat_id уже был)
    assert result is False
    assert store.get(123).username == "new_name"


def test_unsubscribe_returns_false_if_not_subscribed(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    assert store.unsubscribe(123) is False


def test_unsubscribe_removes_entry(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(123, "alex")
    assert store.unsubscribe(123) is True
    assert not store.is_subscribed(123)
    assert store.unsubscribe(123) is False


def test_persistence_round_trip(tmp_path: Path):
    path = tmp_path / "subs.json"
    s1 = SubscriptionStore(path)
    s1.subscribe(1, "alex")
    s1.subscribe(2, "kostya")
    s1.unsubscribe(1)

    s2 = SubscriptionStore(path)
    assert not s2.is_subscribed(1)
    assert s2.is_subscribed(2)
    assert s2.get(2).username == "kostya"


def test_persistence_file_is_valid_json(tmp_path: Path):
    path = tmp_path / "subs.json"
    store = SubscriptionStore(path)
    store.subscribe(42, "Alex")  # lowercases username
    raw = json.loads(path.read_text())
    assert "42" in raw
    assert raw["42"]["username"] == "alex"


def test_load_from_corrupt_file_does_not_crash(tmp_path: Path):
    path = tmp_path / "subs.json"
    path.write_text("not valid json")
    store = SubscriptionStore(path)
    assert store.list() == []
    store.subscribe(7, "alex")
    assert store.is_subscribed(7)


def test_list_returns_all_subscriptions(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(1, "a")
    store.subscribe(2, "b")
    store.subscribe(3, "c")
    store.unsubscribe(2)
    chat_ids = {sub.chat_id for sub in store.list()}
    assert chat_ids == {1, 3}


def test_username_normalization(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(1, "AlexUser")
    assert store.get(1).username == "alexuser"
