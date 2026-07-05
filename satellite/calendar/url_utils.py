"""URL helpers без зависимостей от CalDAV/providers (избегаем циклов импорта)."""

from __future__ import annotations


def normalize_calendar_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/")
