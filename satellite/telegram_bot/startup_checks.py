"""Startup diagnostics and persistence checks for Telegram bot."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ..security.token_vault import TokenDecryptError, TokenVault
from ..subscriptions import SubscriptionStore
from ..users import USER_STATUS_APPROVED, UserStore

log = logging.getLogger(__name__)


def encryption_key_fingerprint(encryption_key: str) -> str:
    digest = hashlib.sha256(encryption_key.encode("utf-8")).hexdigest()
    return digest[:8]


def warn_if_users_lost(*, logs_dir: Path, users_total: int, subs_total: int) -> bool:
    if users_total > 0 or subs_total > 0:
        return False
    backups_dir = logs_dir / "backups"
    try:
        had_users_backups = any(
            item.name.startswith("users.json.") and item.name.endswith(".bak")
            for item in backups_dir.iterdir()
        )
    except OSError:
        had_users_backups = False
    if not had_users_backups:
        return False
    log.warning(
        "Persistence is empty (users=0, subs=0) but %s contains users.json.*.bak — "
        "store likely reset (legacy systemd → Docker volume migration?). "
        "Restore the latest snapshot or run scripts/migrate-legacy-logs.sh; "
        "see docs/troubleshooting.md.",
        backups_dir,
    )
    return True


def log_persistence_summary(
    *,
    users: UserStore,
    subscriptions: SubscriptionStore,
    users_path: Path,
    subscriptions_path: Path,
    encryption_key: str,
    startup_snapshots: list[Path],
) -> None:
    user_records = users.list_all()
    approved = sum(1 for rec in user_records if rec.status == USER_STATUS_APPROVED)
    with_calendar = sum(1 for rec in user_records if rec.has_calendar)
    subs_all = subscriptions.list_all()
    subs_active = sum(1 for sub in subs_all if sub.digest_enabled)
    snapshots = [str(path) for path in startup_snapshots]
    log.info(
        "Persistence loaded: users total=%d approved=%d calendar_connected=%d "
        "subscriptions total=%d active=%d users_path=%s subscriptions_path=%s "
        "key_fingerprint=%s snapshots=%s",
        len(user_records),
        approved,
        with_calendar,
        len(subs_all),
        subs_active,
        users_path,
        subscriptions_path,
        encryption_key_fingerprint(encryption_key),
        snapshots or "[]",
    )
    warn_if_users_lost(
        logs_dir=users_path.parent,
        users_total=len(user_records),
        subs_total=len(subs_all),
    )


def verify_encryption_key_against_existing_users(
    *,
    users: UserStore,
    token_vault: TokenVault,
    encryption_key: str,
) -> None:
    candidates = [
        rec
        for rec in users.list_all()
        if rec.encrypted_credentials and rec.status == USER_STATUS_APPROVED
    ]
    if not candidates:
        return
    for rec in candidates:
        try:
            token_vault.decrypt(rec.encrypted_credentials or "")
        except TokenDecryptError:
            continue
        return
    log.critical(
        "Encryption self-check failed: %d approved users have credentials, "
        "but none decrypt with current TOKEN_ENCRYPTION_KEY (fingerprint=%s). "
        "The key was likely rotated since users connected their calendars. "
        "Restore the previous .env (or logs/backups snapshot) to keep settings; "
        "see docs/troubleshooting.md.",
        len(candidates),
        encryption_key_fingerprint(encryption_key),
    )
