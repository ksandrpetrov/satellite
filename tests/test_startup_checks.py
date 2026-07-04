"""Startup diagnostics: encryption self-check and persistence warnings."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

from satellite.security.token_vault import ProviderCredentials, TokenVault
from satellite.telegram_bot.startup_checks import (
    encryption_key_fingerprint,
    verify_encryption_key_against_existing_users,
    warn_if_users_lost,
)
from satellite.users import USER_STATUS_APPROVED, UserStore


def test_encryption_key_fingerprint_is_deterministic() -> None:
    key = Fernet.generate_key().decode("ascii")
    assert encryption_key_fingerprint(key) == encryption_key_fingerprint(key)
    assert len(encryption_key_fingerprint(key)) == 8


def test_verify_encryption_logs_critical_when_all_credentials_fail(tmp_path: Path, caplog) -> None:
    key = Fernet.generate_key().decode("ascii")
    vault = TokenVault(key)
    other_key = Fernet.generate_key().decode("ascii")
    blob = vault.encrypt(ProviderCredentials(login="u@mail.ru", secret="secret"))
    users = UserStore(tmp_path / "users.json")
    users.upsert_from_telegram(
        telegram_user_id=1,
        chat_id=1,
        username="u1",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        1,
        provider="mailru",
        encrypted_credentials=blob,
        primary_calendar_url="https://cal/",
    )
    caplog.set_level(logging.CRITICAL)
    verify_encryption_key_against_existing_users(
        users=users,
        token_vault=TokenVault(other_key),
        encryption_key=other_key,
    )
    matched = [rec for rec in caplog.records if "Encryption self-check failed" in rec.message]
    assert matched
    assert matched[0].levelno == logging.CRITICAL


def test_verify_encryption_silent_when_one_user_decrypts(tmp_path: Path, caplog) -> None:
    key = Fernet.generate_key().decode("ascii")
    vault = TokenVault(key)
    good_blob = vault.encrypt(ProviderCredentials(login="good@mail.ru", secret="ok"))
    bad_blob = vault.encrypt(ProviderCredentials(login="bad@mail.ru", secret="nope"))
    users = UserStore(tmp_path / "users.json")
    users.upsert_from_telegram(
        telegram_user_id=1,
        chat_id=1,
        username="u1",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        1,
        provider="mailru",
        encrypted_credentials=bad_blob,
        primary_calendar_url="https://cal/",
    )
    users.upsert_from_telegram(
        telegram_user_id=2,
        chat_id=2,
        username="u2",
        display_name=None,
        default_status=USER_STATUS_APPROVED,
    )
    users.set_calendar_connection(
        2,
        provider="mailru",
        encrypted_credentials=good_blob,
        primary_calendar_url="https://cal/",
    )

    def _decrypt_side_effect(blob: str) -> ProviderCredentials:
        if blob == bad_blob:
            from satellite.security.token_vault import TokenDecryptError

            raise TokenDecryptError("bad")
        return vault.decrypt(blob)

    mock_vault = MagicMock(spec=TokenVault)
    mock_vault.decrypt.side_effect = _decrypt_side_effect

    caplog.set_level(logging.CRITICAL)
    verify_encryption_key_against_existing_users(
        users=users,
        token_vault=mock_vault,
        encryption_key=key,
    )
    assert not any("Encryption self-check failed" in rec.message for rec in caplog.records)


def test_warn_if_users_lost_emits_warning_when_backups_exist(tmp_path: Path, caplog) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "users.json.20260520-150000Z.bak").write_text("{}", encoding="utf-8")
    caplog.set_level(logging.WARNING)
    emitted = warn_if_users_lost(logs_dir=tmp_path, users_total=0, subs_total=0)
    assert emitted is True
    assert any("Persistence is empty" in rec.message for rec in caplog.records)


def test_warn_if_users_lost_silent_when_store_populated(tmp_path: Path, caplog) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "users.json.20260520-150000Z.bak").write_text("{}", encoding="utf-8")
    caplog.set_level(logging.WARNING)
    emitted = warn_if_users_lost(logs_dir=tmp_path, users_total=1, subs_total=0)
    assert emitted is False
