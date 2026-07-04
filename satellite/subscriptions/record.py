"""Digest settings model and validation helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..calendar.time_utils import normalize_hhmm_input

log = logging.getLogger(__name__)


DIGEST_DAYS_WEEKDAYS = "weekdays"
DIGEST_DAYS_ALL = "all_days"
ALLOWED_DIGEST_DAYS = frozenset({DIGEST_DAYS_WEEKDAYS, DIGEST_DAYS_ALL})
PENDING_DIGEST_DAYS_MASK_LEN = 7


def is_valid_pending_digest_days(value: str) -> bool:
    """Legacy ``weekdays``/``all_days`` или 7-битная маска с хотя бы одним днём."""
    if value in ALLOWED_DIGEST_DAYS:
        return True
    return (
        len(value) == PENDING_DIGEST_DAYS_MASK_LEN
        and all(ch in "01" for ch in value)
        and "1" in value
    )


DEFAULT_DIGEST_TIME = "09:00"
DEFAULT_PENDING_DIGEST_TIME = "10:00"
DEFAULT_DIGEST_TIMEZONE = "Europe/Moscow"
DEFAULT_DIGEST_DAYS = DIGEST_DAYS_WEEKDAYS


def _normalize_digest_time(value: object) -> str:
    normalized = normalize_hhmm_input(str(value)) if value is not None else None
    return normalized or DEFAULT_DIGEST_TIME


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on", "y"}:
            return True
        if raw in {"0", "false", "no", "off", "n"}:
            return False
    return default


@dataclass(frozen=True)
class DigestSettings:
    """Настройки дайджеста одного пользователя.

    Все времена хранятся как нормализованный ``HH:MM`` (zero-padded), часовой
    пояс — IANA-имя ("Europe/Moscow"). Это позволяет не таскать tz-объект в
    JSON и облегчает миграции.
    """

    chat_id: int
    telegram_user_id: int
    username: str
    digest_enabled: bool = False
    digest_days: str = DEFAULT_DIGEST_DAYS
    digest_time: str = DEFAULT_DIGEST_TIME
    digest_timezone: str = DEFAULT_DIGEST_TIMEZONE
    subscribed_at: str = ""
    last_digest_sent_date: str | None = None
    pending_digest_enabled: bool = False
    pending_digest_days: str = DEFAULT_DIGEST_DAYS
    pending_digest_time: str = DEFAULT_PENDING_DIGEST_TIME
    pending_digest_timezone: str = DEFAULT_DIGEST_TIMEZONE
    last_pending_digest_sent_date: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "telegram_user_id": self.telegram_user_id,
            "username": self.username,
            "digest_enabled": self.digest_enabled,
            "digest_days": self.digest_days,
            "digest_time": self.digest_time,
            "digest_timezone": self.digest_timezone,
            "subscribed_at": self.subscribed_at,
            "last_digest_sent_date": self.last_digest_sent_date,
            "pending_digest_enabled": self.pending_digest_enabled,
            "pending_digest_days": self.pending_digest_days,
            "pending_digest_time": self.pending_digest_time,
            "pending_digest_timezone": self.pending_digest_timezone,
            "last_pending_digest_sent_date": self.last_pending_digest_sent_date,
        }

    @classmethod
    def from_json(cls, chat_id: int, raw: dict) -> DigestSettings | None:
        """Парсит запись JSON. ``None`` — если запись непригодна (нет username).

        Старый формат файла (без явного ``digest_enabled``) считается активной
        подпиской: само присутствие записи раньше означало «подписан».
        """
        username = str(raw.get("username") or "").lower()
        if not username:
            return None
        subscribed_at = str(raw.get("subscribed_at") or "")
        digest_days = str(raw.get("digest_days") or DEFAULT_DIGEST_DAYS)
        if digest_days not in ALLOWED_DIGEST_DAYS:
            digest_days = DEFAULT_DIGEST_DAYS
        digest_time = _normalize_digest_time(raw.get("digest_time"))
        digest_timezone = str(raw.get("digest_timezone") or DEFAULT_DIGEST_TIMEZONE)
        raw_enabled = raw.get("digest_enabled")
        digest_enabled = True if raw_enabled is None else _coerce_bool(raw_enabled, default=False)
        last_sent = raw.get("last_digest_sent_date")
        last_sent_str = None if last_sent in (None, "") else str(last_sent)
        pending_days = str(raw.get("pending_digest_days") or DEFAULT_DIGEST_DAYS)
        if not is_valid_pending_digest_days(pending_days):
            pending_days = DEFAULT_DIGEST_DAYS
        pending_time_raw = raw.get("pending_digest_time")
        if pending_time_raw is None:
            pending_time = DEFAULT_PENDING_DIGEST_TIME
        else:
            pending_time = _normalize_digest_time(pending_time_raw)
        pending_timezone = str(raw.get("pending_digest_timezone") or DEFAULT_DIGEST_TIMEZONE)
        pending_enabled = _coerce_bool(raw.get("pending_digest_enabled"), default=False)
        last_pending = raw.get("last_pending_digest_sent_date")
        last_pending_str = None if last_pending in (None, "") else str(last_pending)
        uid_raw = raw.get("telegram_user_id")
        if isinstance(uid_raw, int):
            telegram_user_id = uid_raw
        elif isinstance(uid_raw, str) and uid_raw.strip():
            try:
                telegram_user_id = int(uid_raw)
            except ValueError:
                telegram_user_id = chat_id
        else:
            telegram_user_id = chat_id
        return cls(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            username=username,
            digest_enabled=digest_enabled,
            digest_days=digest_days,
            digest_time=digest_time,
            digest_timezone=digest_timezone,
            subscribed_at=subscribed_at,
            last_digest_sent_date=last_sent_str,
            pending_digest_enabled=pending_enabled,
            pending_digest_days=pending_days,
            pending_digest_time=pending_time,
            pending_digest_timezone=pending_timezone,
            last_pending_digest_sent_date=last_pending_str,
        )


Subscription = DigestSettings
