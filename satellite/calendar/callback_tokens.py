"""Короткие стабильные токены для Telegram ``callback_data`` (≤64 байт)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

_TOKEN_LEN = 12


def calendar_callback_token(url: str) -> str:
    normalized = (url or "").strip().rstrip("/")
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return digest[:_TOKEN_LEN]


def event_callback_token(event_url: str) -> str:
    normalized = (event_url or "").strip().rstrip("/")
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return digest[:_TOKEN_LEN]


def event_token(event: Mapping[str, Any]) -> str:
    url = str(event.get("url") or "")
    connection_id = str(event.get("_calendar_connection_id") or "")
    return event_callback_token(f"{connection_id}:{url}" if connection_id else url)
