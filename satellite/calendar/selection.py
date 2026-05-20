"""Выбор календарей для отображения плана, дайджеста и /upcoming."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..users import UserRecord


def _normalize_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/")


def effective_enabled_calendar_urls_from_parts(
    *,
    enabled_calendar_urls: tuple[str, ...],
    primary_calendar_url: str | None,
) -> tuple[str, ...]:
    """URL календарей, из которых читаем события."""
    if enabled_calendar_urls:
        return enabled_calendar_urls
    primary = _normalize_url(primary_calendar_url)
    if primary:
        return (primary,)
    return ()


def effective_enabled_calendar_urls(record: UserRecord) -> tuple[str, ...]:
    """URL календарей для ``UserRecord``."""
    return effective_enabled_calendar_urls_from_parts(
        enabled_calendar_urls=record.enabled_calendar_urls,
        primary_calendar_url=record.primary_calendar_url,
    )
