"""Хранилище Telegram-пользователей и их подключений календаря.

JSON-store ``logs/users.json`` хранит per-user статус доступа и подключения к
календарному провайдеру. Файл — единственный источник правды по авторизации
в боте.

Структура записи (см. :class:`UserRecord`):

- ``telegram_user_id`` — ключ хранилища (int);
- ``chat_id`` — последний известный chat (для notify);
- ``username`` / ``display_name`` — справочно, для админских уведомлений;
- ``status`` — ``pending`` / ``approved`` / ``rejected`` / ``blocked``;
- ``access_request_status`` — состояние последней заявки на доступ;
- ``calendar_provider`` / ``encrypted_credentials`` — связка с провайдером
  (только зашифрованный blob, никаких сырых токенов);
- ``calendar_status`` — последнее известное состояние подключения;
- ``primary_calendar_url`` — служебный URL календаря (display name НЕ храним —
  это PII по событиям пользователя);
- ``enabled_calendar_urls`` — какие календари учитывать в плане/дайджесте
  (пусто = только ``primary_calendar_url``).

Этот ``__init__`` — фасад. Раньше всё жило в одном ``users.py``; сейчас
разнесено по ответственности:

- :mod:`.record` — ``UserRecord`` + enum-константы + helpers парсинга;
- :mod:`.store` — ``UserStore`` + ошибки загрузки/записи;
- :mod:`.admin` — парсинг ``ADMIN_TELEGRAM_IDS``.

Внешние импорты ``from satellite.users import …`` не меняются.
"""

from .admin import admin_id_set, parse_admin_ids
from .record import (
    ACCESS_REQUEST_APPROVED,
    ACCESS_REQUEST_NONE,
    ACCESS_REQUEST_PENDING,
    ACCESS_REQUEST_REJECTED,
    ALLOWED_ACCESS_REQUEST_STATES,
    ALLOWED_ANALYTICS_WORKDAYS,
    ALLOWED_CALENDAR_STATES,
    ALLOWED_USER_STATUSES,
    CALENDAR_CONNECTED,
    CALENDAR_DISCONNECTED,
    CALENDAR_ERROR,
    CALENDAR_INVALID,
    USER_STATUS_APPROVED,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
    USER_STATUS_REJECTED,
    UserRecord,
)
from .store import UserStore, UserStoreLoadError, UserStorePersistenceError

__all__ = [
    "ACCESS_REQUEST_APPROVED",
    "ACCESS_REQUEST_NONE",
    "ACCESS_REQUEST_PENDING",
    "ACCESS_REQUEST_REJECTED",
    "ALLOWED_ACCESS_REQUEST_STATES",
    "ALLOWED_ANALYTICS_WORKDAYS",
    "ALLOWED_CALENDAR_STATES",
    "ALLOWED_USER_STATUSES",
    "CALENDAR_CONNECTED",
    "CALENDAR_DISCONNECTED",
    "CALENDAR_ERROR",
    "CALENDAR_INVALID",
    "USER_STATUS_APPROVED",
    "USER_STATUS_BLOCKED",
    "USER_STATUS_PENDING",
    "USER_STATUS_REJECTED",
    "UserRecord",
    "UserStore",
    "UserStoreLoadError",
    "UserStorePersistenceError",
    "admin_id_set",
    "parse_admin_ids",
]
