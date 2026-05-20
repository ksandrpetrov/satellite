"""Краткоживущие токены для Web App, когда Telegram не передаёт initData.

Reply-клавиатура с ``web_app`` и menu button как обычный URL открывают Mini App
без ``initData``. Бот добавляет ``?t=…`` к URL кнопки; сервер принимает токен
вместо HMAC initData для того же пользователя.
"""

from __future__ import annotations

import secrets
import threading
import time

DEFAULT_TTL_SEC = 900


class ConnectTokenStore:
    def __init__(self, *, ttl_sec: int = DEFAULT_TTL_SEC) -> None:
        self._ttl = ttl_sec
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[int, float]] = {}

    def issue(self, telegram_user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_locked()
            self._tokens[token] = (telegram_user_id, time.time())
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
                return None
            return user_id

    def _purge_locked(self) -> None:
        cutoff = time.time() - self._ttl
        expired = [t for t, (_, ts) in self._tokens.items() if ts < cutoff]
        for t in expired:
            del self._tokens[t]
