"""Encrypted calendar accounts in a separate transactional store."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..json_store import JsonStoreBase, JsonStoreLoadError
from ..security.token_vault import ProviderCredentials, TokenVault


@dataclass(frozen=True)
class CalendarAccount:
    account_id: int
    credentials_blob: str
    primary_calendar_url: str
    calendar_urls: tuple[str, ...]

    @property
    def connection_id(self) -> str:
        return hashlib.sha256(self.credentials_blob.encode()).hexdigest()


class AccountPersistenceError(RuntimeError):
    pass


class AccountLoadError(JsonStoreLoadError):
    pass


class CalendarAccountStore(JsonStoreBase[CalendarAccount]):
    _PERSISTENCE_ERROR = AccountPersistenceError
    _LOAD_ERROR = AccountLoadError
    _STORE_LABEL = "MCP calendar accounts"

    def __init__(self, path: Path, vault: TokenVault) -> None:
        super().__init__(path)
        self.vault = vault
        root = self._load_json_root()
        if not root:
            return
        if root.get("version") != 1 or not isinstance(root.get("accounts"), dict):
            raise self._load_error("invalid schema")
        for key, raw in root["accounts"].items():
            try:
                if not isinstance(raw, dict):
                    raise ValueError("invalid account")
                urls = raw["calendar_urls"]
                if (
                    not isinstance(urls, list)
                    or not urls
                    or any(not isinstance(u, str) for u in urls)
                ):
                    raise ValueError("invalid calendar URLs")
                account = CalendarAccount(
                    account_id=int(key),
                    credentials_blob=raw["credentials_blob"],
                    primary_calendar_url=raw["primary_calendar_url"],
                    calendar_urls=tuple(urls),
                )
                if account.account_id <= 0 or account.primary_calendar_url not in urls:
                    raise ValueError("invalid account identity")
                if not isinstance(account.credentials_blob, str) or not account.credentials_blob:
                    raise ValueError("invalid encrypted credentials")
                self.vault.decrypt(account.credentials_blob)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                raise self._load_error("invalid account record") from exc
            self._items[account.account_id] = account

    def _build_snapshot_payload(self, items: Mapping[int, CalendarAccount]) -> dict[str, Any]:
        return {"version": 1, "accounts": {str(key): asdict(value) for key, value in items.items()}}

    def get(self, account_id: int) -> CalendarAccount:
        with self._lock:
            account = self._items.get(account_id)
        if account is None:
            raise ValueError("Calendar account is not connected")
        return account

    def connect(
        self, credentials: ProviderCredentials, primary: str, urls: tuple[str, ...]
    ) -> CalendarAccount:
        account_id = int.from_bytes(
            hashlib.sha256(credentials.login.strip().casefold().encode()).digest()[:8], "big"
        ) & ((1 << 63) - 1)
        account_id = account_id or 1
        account = CalendarAccount(account_id, self.vault.encrypt(credentials), primary, urls)
        with self._lock:
            existing = self._items.get(account_id)
            if (
                existing
                and self.vault.decrypt(existing.credentials_blob).login != credentials.login
            ):
                raise ValueError("Calendar identity collision")
            self._commit_items_locked({**self._items, account_id: account})
        return account
