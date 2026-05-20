"""Краткоживущие токены для Web App, когда Telegram не передаёт initData."""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_TTL_SEC = 900


class ConnectTokenStore:
    def __init__(
        self,
        *,
        ttl_sec: int = DEFAULT_TTL_SEC,
        storage_path: Path | None = None,
    ) -> None:
        self._ttl = ttl_sec
        self._storage_path = storage_path
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[int, float]] = {}
        if storage_path is not None:
            self._load()

    def issue(self, telegram_user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_locked()
            self._tokens[token] = (telegram_user_id, time.time())
            self._save_locked()
        return token

    def resolve(self, token: str) -> int | None:
        raw = (token or "").strip()
        if not raw:
            return None
        with self._lock:
            self._purge_locked()
            entry = self._tokens.get(raw)
            if entry is None:
                return None
            user_id, issued_at = entry
            if time.time() - issued_at > self._ttl:
                del self._tokens[raw]
                self._save_locked()
                return None
            return user_id

    def _purge_locked(self) -> None:
        cutoff = time.time() - self._ttl
        expired = [t for t, (_, ts) in self._tokens.items() if ts < cutoff]
        for t in expired:
            del self._tokens[t]

    def _load(self) -> None:
        path = self._storage_path
        if path is None or not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load connect tokens from %s: %s", path, exc)
            return
        if not isinstance(raw, dict):
            return
        loaded: dict[str, tuple[int, float]] = {}
        for token, entry in raw.items():
            if not isinstance(token, str) or not isinstance(entry, list) or len(entry) != 2:
                continue
            try:
                loaded[token] = (int(entry[0]), float(entry[1]))
            except (TypeError, ValueError):
                continue
        self._tokens = loaded
        self._purge_locked()

    def _save_locked(self) -> None:
        path = self._storage_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {t: [uid, ts] for t, (uid, ts) in self._tokens.items()}
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            log.warning("Failed to persist connect tokens to %s", path, exc_info=True)
