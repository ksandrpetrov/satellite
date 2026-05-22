"""``UserRecord`` (dataclass) и связанные enum-константы.

Не зависит ни от чего, кроме stdlib и ``calendar.constants``. Это «модельный
слой» пакета :mod:`satellite.users` — может импортироваться откуда угодно
без риска зацепить I/O или CalDAV.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..calendar.constants import (
    ANALYTICS_WORKDAY_9_18,
    ANALYTICS_WORKDAY_10_19,
    DEFAULT_ANALYTICS_WORKDAY,
)

ALLOWED_ANALYTICS_WORKDAYS = frozenset({ANALYTICS_WORKDAY_9_18, ANALYTICS_WORKDAY_10_19})


USER_STATUS_PENDING = "pending"
USER_STATUS_APPROVED = "approved"
USER_STATUS_REJECTED = "rejected"
USER_STATUS_BLOCKED = "blocked"

ALLOWED_USER_STATUSES = frozenset(
    {USER_STATUS_PENDING, USER_STATUS_APPROVED, USER_STATUS_REJECTED, USER_STATUS_BLOCKED}
)


ACCESS_REQUEST_NONE = "none"
ACCESS_REQUEST_PENDING = "pending"
ACCESS_REQUEST_APPROVED = "approved"
ACCESS_REQUEST_REJECTED = "rejected"

ALLOWED_ACCESS_REQUEST_STATES = frozenset(
    {
        ACCESS_REQUEST_NONE,
        ACCESS_REQUEST_PENDING,
        ACCESS_REQUEST_APPROVED,
        ACCESS_REQUEST_REJECTED,
    }
)


CALENDAR_DISCONNECTED = "disconnected"
CALENDAR_CONNECTED = "connected"
CALENDAR_INVALID = "invalid"
CALENDAR_ERROR = "error"

ALLOWED_CALENDAR_STATES = frozenset(
    {CALENDAR_DISCONNECTED, CALENDAR_CONNECTED, CALENDAR_INVALID, CALENDAR_ERROR}
)


@dataclass(frozen=True)
class UserRecord:
    """Один Telegram-пользователь.

    Не хранит PII календаря: ни названий событий, ни email участников, ни
    самого токена (только зашифрованный blob). ``primary_calendar_url`` —
    технический URL CalDAV-календаря, нужен, чтобы CRUD-операции не делали
    discovery на каждый чих.
    """

    telegram_user_id: int
    chat_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    status: str = USER_STATUS_PENDING
    access_request_status: str = ACCESS_REQUEST_NONE
    access_request_created_at: str | None = None
    access_resolved_at: str | None = None
    resolved_by_admin_id: int | None = None
    calendar_provider: str | None = None
    encrypted_credentials: str | None = None
    calendar_status: str = CALENDAR_DISCONNECTED
    primary_calendar_url: str | None = None
    enabled_calendar_urls: tuple[str, ...] = ()
    calendar_connected_at: str | None = None
    calendar_last_checked_at: str | None = None
    analytics_workday: str = DEFAULT_ANALYTICS_WORKDAY
    weather_in_plan_enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_approved(self) -> bool:
        return self.status == USER_STATUS_APPROVED

    @property
    def has_calendar(self) -> bool:
        return (
            self.is_approved
            and self.calendar_provider is not None
            and self.encrypted_credentials is not None
            and self.calendar_status == CALENDAR_CONNECTED
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "username": self.username,
            "display_name": self.display_name,
            "status": self.status,
            "access_request_status": self.access_request_status,
            "access_request_created_at": self.access_request_created_at,
            "access_resolved_at": self.access_resolved_at,
            "resolved_by_admin_id": self.resolved_by_admin_id,
            "calendar_provider": self.calendar_provider,
            "encrypted_credentials": self.encrypted_credentials,
            "calendar_status": self.calendar_status,
            "primary_calendar_url": self.primary_calendar_url,
            "enabled_calendar_urls": list(self.enabled_calendar_urls),
            "calendar_connected_at": self.calendar_connected_at,
            "calendar_last_checked_at": self.calendar_last_checked_at,
            "analytics_workday": self.analytics_workday,
            "weather_in_plan_enabled": self.weather_in_plan_enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, telegram_user_id: int, raw: dict) -> UserRecord:
        status = str(raw.get("status") or USER_STATUS_PENDING)
        if status not in ALLOWED_USER_STATUSES:
            status = USER_STATUS_PENDING
        access_request_status = str(raw.get("access_request_status") or ACCESS_REQUEST_NONE)
        if access_request_status not in ALLOWED_ACCESS_REQUEST_STATES:
            access_request_status = ACCESS_REQUEST_NONE
        calendar_status = str(raw.get("calendar_status") or CALENDAR_DISCONNECTED)
        if calendar_status not in ALLOWED_CALENDAR_STATES:
            calendar_status = CALENDAR_DISCONNECTED
        return cls(
            telegram_user_id=telegram_user_id,
            chat_id=_coerce_optional_int(raw.get("chat_id")),
            username=(
                (raw.get("username") or None) and str(raw.get("username") or "").lower() or None
            ),
            display_name=(raw.get("display_name") or None),
            status=status,
            access_request_status=access_request_status,
            access_request_created_at=raw.get("access_request_created_at") or None,
            access_resolved_at=raw.get("access_resolved_at") or None,
            resolved_by_admin_id=_coerce_optional_int(raw.get("resolved_by_admin_id")),
            calendar_provider=(raw.get("calendar_provider") or None),
            encrypted_credentials=(raw.get("encrypted_credentials") or None),
            calendar_status=calendar_status,
            primary_calendar_url=(raw.get("primary_calendar_url") or None),
            enabled_calendar_urls=_parse_enabled_calendar_urls(raw.get("enabled_calendar_urls")),
            calendar_connected_at=raw.get("calendar_connected_at") or None,
            calendar_last_checked_at=raw.get("calendar_last_checked_at") or None,
            analytics_workday=_parse_analytics_workday(raw.get("analytics_workday")),
            weather_in_plan_enabled=_parse_weather_in_plan_enabled(
                raw.get("weather_in_plan_enabled")
            ),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )


def _coerce_optional_int(raw: object) -> int | None:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _normalize_calendar_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _normalize_calendar_url_list(urls: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        normalized = _normalize_calendar_url(str(raw))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return tuple(out)


def _parse_weather_in_plan_enabled(raw: object) -> bool:
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return True


def _parse_analytics_workday(raw: object) -> str:
    preset = str(raw or DEFAULT_ANALYTICS_WORKDAY).strip()
    if preset in ALLOWED_ANALYTICS_WORKDAYS:
        return preset
    return DEFAULT_ANALYTICS_WORKDAY


def _parse_enabled_calendar_urls(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return _normalize_calendar_url_list([raw])
    if isinstance(raw, (list, tuple)):
        return _normalize_calendar_url_list(str(item) for item in raw)
    return ()
