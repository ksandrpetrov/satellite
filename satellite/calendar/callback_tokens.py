"""Короткие стабильные токены для Telegram ``callback_data`` (≤64 байт)."""

from __future__ import annotations

import hashlib

_TOKEN_LEN = 12


def calendar_callback_token(url: str) -> str:
    normalized = (url or "").strip().rstrip("/")
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return digest[:_TOKEN_LEN]


def event_callback_token(event_url: str) -> str:
    digest = hashlib.sha256((event_url or "").strip().encode()).hexdigest()
    return digest[:_TOKEN_LEN]
