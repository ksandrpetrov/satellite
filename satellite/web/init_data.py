"""Telegram Web App initData validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    """initData не прошла проверку подписи или устарела."""

    def __init__(self, message: str, *, code: str = "unauthorized") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InitDataUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True)
class ValidatedInitData:
    user: InitDataUser
    auth_date: int
    raw: Mapping[str, str]


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_sec: int = 86400,
) -> ValidatedInitData:
    """HMAC-SHA256 validation per Telegram WebApp docs."""
    if not bot_token:
        raise InitDataError("Missing bot token", code="server_misconfigured")
    if not init_data:
        raise InitDataError("Missing initData", code="no_init_data")
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise InitDataError(
            "Missing hash in initData (open Web App from Telegram, not browser)",
            code="no_init_data",
        )
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError(
            "Invalid initData signature (TELEGRAM_BOT_TOKEN mismatch?)",
            code="bad_signature",
        )
    auth_date_raw = parsed.get("auth_date")
    try:
        auth_date = int(auth_date_raw or "0")
    except ValueError as exc:
        raise InitDataError("Invalid auth_date") from exc
    if auth_date <= 0:
        raise InitDataError("Missing auth_date")
    if time.time() - auth_date > max_age_sec:
        raise InitDataError("initData expired", code="expired")
    user_raw = parsed.get("user")
    if not user_raw:
        raise InitDataError("Missing user in initData")
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("Invalid user JSON") from exc
    if not isinstance(user_obj, dict):
        raise InitDataError("Invalid user object")
    user_id = user_obj.get("id")
    if not isinstance(user_id, int):
        raise InitDataError("Invalid user id")
    user = InitDataUser(
        id=user_id,
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
        last_name=user_obj.get("last_name"),
    )
    return ValidatedInitData(user=user, auth_date=auth_date, raw=parsed)
