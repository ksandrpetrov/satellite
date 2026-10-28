"""Русские сообщения для кодов ошибок Web App API."""

from __future__ import annotations

from ..messages_ru import WEBAPP_COPY

ERROR_MESSAGES: dict[str, str] = {
    **WEBAPP_COPY["telegram_errors"],
    **WEBAPP_COPY["api_errors"],
}


def error_payload(code: str, *, message: str | None = None) -> dict[str, str]:
    """Стабильный ``error`` code + русский ``message`` для UI."""
    return {
        "error": code,
        "message": message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["request_failed"]),
    }
