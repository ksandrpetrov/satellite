"""Русские сообщения для кодов ошибок Web App API."""

from __future__ import annotations

from ..messages_ru import WEBAPP_COPY

ERROR_MESSAGES: dict[str, str] = {
    "no_init_data": (
        "Не удалось подтвердить сессию. Закройте окно и снова нажмите "
        "«Подключить календарь» в чате с ботом."
    ),
    "bad_signature": WEBAPP_COPY["telegram_errors"]["bad_signature"],
    "expired": "Сессия устарела. Закройте окно и откройте снова из бота.",
    "connect_token_invalid": (
        "Ссылка устарела. Закройте окно и снова нажмите «Подключить календарь» в боте."
    ),
    "not_approved": "Доступ ещё не одобрен админом. Ожидайте сообщения от бота.",
    "not_found": "Страница не найдена.",
    "request_failed": "Не удалось выполнить запрос. Попробуйте ещё раз.",
    "unknown_provider": "Неизвестный провайдер календаря.",
    "PROVIDER_NOT_IMPLEMENTED": "Этот провайдер пока не поддерживается.",
    "missing_fields": "Заполните все обязательные поля.",
    "storage_unavailable": "Не удалось сохранить настройки. Попробуйте позже.",
    "invalid_days": "Некорректный диапазон дней.",
    "not_connected": "Сначала подключите календарь.",
    "invalid_range": "Некорректный диапазон дат.",
    "invalid_dates": "Некорректные даты события.",
    "invalid_duration": "Некорректная длительность события.",
    "missing_uid": "Не указан идентификатор события.",
}


def error_payload(code: str, *, message: str | None = None) -> dict[str, str]:
    """Стабильный ``error`` code + русский ``message`` для UI."""
    return {
        "error": code,
        "message": message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["request_failed"]),
    }
