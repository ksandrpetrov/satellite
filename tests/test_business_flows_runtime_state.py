"""TokenVault, persistence hygiene, logging без секретов."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from satellite.security.token_vault import (
    InvalidEncryptionKeyError,
    ProviderCredentials,
    TokenDecryptError,
    TokenVault,
)
from satellite.users import UserStore


def test_token_vault_round_trip() -> None:
    key = Fernet.generate_key().decode("ascii")
    vault = TokenVault(key)
    creds = ProviderCredentials(login="user@mail.ru", secret="app-password-xyz")
    blob = vault.encrypt(creds)
    restored = vault.decrypt(blob)
    assert restored.login == creds.login
    assert restored.secret == creds.secret


def test_token_vault_rejects_empty_key() -> None:
    with pytest.raises(InvalidEncryptionKeyError):
        TokenVault("")


def test_token_vault_rejects_invalid_key_format() -> None:
    with pytest.raises(InvalidEncryptionKeyError):
        TokenVault("not-a-fernet-key")


def test_token_vault_decrypt_fails_on_wrong_key() -> None:
    key1 = Fernet.generate_key().decode("ascii")
    key2 = Fernet.generate_key().decode("ascii")
    blob = TokenVault(key1).encrypt(ProviderCredentials(login="a", secret="b"))
    with pytest.raises(TokenDecryptError):
        TokenVault(key2).decrypt(blob)


def test_users_json_never_contains_raw_password(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode("ascii")
    vault = TokenVault(key)
    users = UserStore(tmp_path / "users.json")
    users.upsert_from_telegram(
        telegram_user_id=1,
        chat_id=1,
        username="alice",
        display_name=None,
        default_status="approved",
    )
    secret = "RawPasswordMustNotAppear"
    blob = vault.encrypt(ProviderCredentials(login="u@mail.ru", secret=secret))
    users.set_calendar_connection(
        1,
        provider="mailru",
        encrypted_credentials=blob,
        primary_calendar_url="https://cal/",
    )
    raw = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert secret not in raw
    assert "RawPasswordMustNotAppear" not in raw


def test_subscription_store_atomic_write_failure_raises(tmp_path: Path, monkeypatch) -> None:
    """OSError при записи subscriptions.json не должен тихо проглатываться."""
    from satellite.subscriptions import SubscriptionStore

    store = SubscriptionStore(tmp_path / "subs.json")
    store.subscribe(1, "alice")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_locked", boom)
    with pytest.raises(OSError, match="disk full"):
        store.update_settings(1, "alice", digest_time="10:30")
