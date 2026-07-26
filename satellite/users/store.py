"""Транзакционный JSON-store пользователей."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..json_store import JsonStoreBase, JsonStoreLoadError
from .record import (
    ACCESS_REQUEST_APPROVED,
    ACCESS_REQUEST_PENDING,
    ACCESS_REQUEST_REJECTED,
    ALLOWED_ANALYTICS_WORKDAYS,
    ALLOWED_CALENDAR_STATES,
    CALENDAR_CONNECTED,
    CALENDAR_DISCONNECTED,
    USER_STATUS_APPROVED,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
    USER_STATUS_REJECTED,
    UserRecord,
    _normalize_calendar_url_list,
)


class UserStorePersistenceError(RuntimeError):
    """Не удалось записать ``users.json``; прежнее состояние сохранено."""


class UserStoreLoadError(JsonStoreLoadError):
    """``users.json`` повреждён или недоступен."""


class UserStore(JsonStoreBase[UserRecord]):
    """Thread-safe JSON-store пользователей.

    См. модульный docstring выше.
    """

    _PERSISTENCE_ERROR = UserStorePersistenceError
    _LOAD_ERROR = UserStoreLoadError
    _STORE_LABEL = "users"

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self._items: dict[int, UserRecord] = self._load()

    # --- queries ---------------------------------------------------------

    def get(self, telegram_user_id: int) -> UserRecord | None:
        with self._lock:
            return self._items.get(telegram_user_id)

    def list_all(self) -> list[UserRecord]:
        with self._lock:
            return list(self._items.values())

    def list_by_status(self, status: str) -> list[UserRecord]:
        with self._lock:
            return [rec for rec in self._items.values() if rec.status == status]

    def list_pending_requests(self) -> list[UserRecord]:
        with self._lock:
            return [
                rec
                for rec in self._items.values()
                if rec.access_request_status == ACCESS_REQUEST_PENDING
            ]

    def find_by_username(self, username: str) -> UserRecord | None:
        normalized = (username or "").strip().lower()
        if not normalized:
            return None
        with self._lock:
            for rec in self._items.values():
                if (rec.username or "").lower() == normalized:
                    return rec
        return None

    # --- mutators --------------------------------------------------------

    def upsert_from_telegram(
        self,
        *,
        telegram_user_id: int,
        chat_id: int | None,
        username: str | None,
        display_name: str | None,
        default_status: str = USER_STATUS_PENDING,
    ) -> UserRecord:
        """Создаёт или обновляет запись по сигналам Telegram-апдейта.

        Username/display_name могут поменяться: обновляем, но статус не
        трогаем. Используется в access-gating и admin-уведомлениях.
        """
        if telegram_user_id <= 0:
            raise ValueError("telegram_user_id must be positive")
        normalized_user = (username or "").strip().lower() or None
        normalized_name = (display_name or "").strip() or None
        now_iso = self._now_iso()
        with self._lock:
            existing = self._items.get(telegram_user_id)
            if existing is None:
                record = UserRecord(
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    username=normalized_user,
                    display_name=normalized_name,
                    status=default_status,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            else:
                updated = existing
                if chat_id is not None and existing.chat_id != chat_id:
                    updated = replace(updated, chat_id=chat_id)
                if normalized_user is not None and existing.username != normalized_user:
                    updated = replace(updated, username=normalized_user)
                if normalized_name is not None and existing.display_name != normalized_name:
                    updated = replace(updated, display_name=normalized_name)
                if updated is not existing:
                    updated = replace(updated, updated_at=now_iso)
                record = updated
                if updated is existing:
                    return record
            candidate = dict(self._items)
            candidate[telegram_user_id] = record
            self._commit_items_locked(candidate)
        return record

    def submit_access_request(self, telegram_user_id: int) -> tuple[UserRecord, bool]:
        """Помечает заявку как ``pending`` (если не уже).

        Возвращает ``(record, was_new_request)``. ``was_new_request=False``
        для уже существующей pending — anti-spam: повторный ``/start`` не
        создаёт новую заявку и не дёргает админа второй раз.
        """
        now_iso = self._now_iso()
        with self._lock:
            existing = self._items.get(telegram_user_id)
            if existing is None:
                raise ValueError(f"submit_access_request: user {telegram_user_id} is unknown")
            if existing.access_request_status == ACCESS_REQUEST_PENDING:
                return existing, False
            if existing.status in (USER_STATUS_APPROVED, USER_STATUS_BLOCKED):
                return existing, False
            updated = replace(
                existing,
                status=USER_STATUS_PENDING,
                access_request_status=ACCESS_REQUEST_PENDING,
                access_request_created_at=now_iso,
                access_resolved_at=None,
                resolved_by_admin_id=None,
                updated_at=now_iso,
            )
            candidate = dict(self._items)
            candidate[telegram_user_id] = updated
            self._commit_items_locked(candidate)
        return updated, True

    def approve(self, telegram_user_id: int, *, admin_telegram_id: int) -> UserRecord:
        return self._resolve_request(
            telegram_user_id,
            admin_telegram_id=admin_telegram_id,
            new_status=USER_STATUS_APPROVED,
            new_request_status=ACCESS_REQUEST_APPROVED,
        )

    def reject(self, telegram_user_id: int, *, admin_telegram_id: int) -> UserRecord:
        return self._resolve_request(
            telegram_user_id,
            admin_telegram_id=admin_telegram_id,
            new_status=USER_STATUS_REJECTED,
            new_request_status=ACCESS_REQUEST_REJECTED,
        )

    def block(self, telegram_user_id: int, *, admin_telegram_id: int) -> UserRecord:
        return self._update_locked_with(
            telegram_user_id,
            change=lambda _existing, now_iso: {
                "status": USER_STATUS_BLOCKED,
                "calendar_provider": None,
                "encrypted_credentials": None,
                "calendar_status": CALENDAR_DISCONNECTED,
                "primary_calendar_url": None,
                "enabled_calendar_urls": (),
                "resolved_by_admin_id": admin_telegram_id,
                "access_resolved_at": now_iso,
            },
        )

    def set_calendar_connection(
        self,
        telegram_user_id: int,
        *,
        provider: str,
        encrypted_credentials: str,
        primary_calendar_url: str | None,
    ) -> UserRecord:
        if not provider.strip():
            raise ValueError("provider is required")
        if not encrypted_credentials.strip():
            raise ValueError("encrypted_credentials is required")
        return self._update_locked_with(
            telegram_user_id,
            change=lambda existing, now_iso: {
                "calendar_provider": provider.strip(),
                "encrypted_credentials": encrypted_credentials,
                "primary_calendar_url": (primary_calendar_url or "").strip() or None,
                "enabled_calendar_urls": (),
                "calendar_status": CALENDAR_CONNECTED,
                "calendar_connected_at": existing.calendar_connected_at or now_iso,
                "calendar_last_checked_at": now_iso,
            },
        )

    def set_enabled_calendar_urls(
        self,
        telegram_user_id: int,
        *,
        calendar_urls: Iterable[str],
    ) -> UserRecord:
        normalized = _normalize_calendar_url_list(calendar_urls)
        if not normalized:
            raise ValueError("At least one calendar URL is required")
        return self._update_locked(
            telegram_user_id,
            enabled_calendar_urls=normalized,
        )

    def mark_calendar_status(self, telegram_user_id: int, *, status: str) -> UserRecord | None:
        if status not in ALLOWED_CALENDAR_STATES:
            raise ValueError(f"Unknown calendar status: {status!r}")
        try:
            return self._update_locked_with(
                telegram_user_id,
                change=lambda _existing, now_iso: {
                    "calendar_status": status,
                    "calendar_last_checked_at": now_iso,
                },
            )
        except KeyError:
            return None

    def set_analytics_workday(self, telegram_user_id: int, *, preset: str) -> UserRecord:
        if preset not in ALLOWED_ANALYTICS_WORKDAYS:
            raise ValueError(f"Unknown analytics workday preset: {preset!r}")
        with self._lock:
            existing = self._items.get(telegram_user_id)
            if existing is None:
                raise KeyError(telegram_user_id)
            if existing.analytics_workday == preset:
                return existing
        return self._update_locked(telegram_user_id, analytics_workday=preset)

    def set_weather_in_plan_enabled(self, telegram_user_id: int, *, enabled: bool) -> UserRecord:
        with self._lock:
            existing = self._items.get(telegram_user_id)
            if existing is None:
                raise KeyError(telegram_user_id)
            if existing.weather_in_plan_enabled == enabled:
                return existing
        return self._update_locked(telegram_user_id, weather_in_plan_enabled=enabled)

    def clear_calendar_connection(self, telegram_user_id: int) -> UserRecord:
        return self._update_locked_with(
            telegram_user_id,
            change=lambda _existing, now_iso: {
                "calendar_provider": None,
                "encrypted_credentials": None,
                "primary_calendar_url": None,
                "enabled_calendar_urls": (),
                "calendar_status": CALENDAR_DISCONNECTED,
                "calendar_connected_at": None,
                "calendar_last_checked_at": now_iso,
            },
        )

    def ensure_admin_record(
        self,
        *,
        telegram_user_id: int,
        chat_id: int | None = None,
        username: str | None = None,
        display_name: str | None = None,
    ) -> UserRecord:
        """Гарантирует, что админ заведён и сразу ``approved``.

        Нужно для бутстрапа: первый запуск с пустым ``logs/users.json`` —
        админ должен сразу получить доступ, без процедуры одобрения.
        """
        record = self.upsert_from_telegram(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            username=username,
            display_name=display_name,
            default_status=USER_STATUS_APPROVED,
        )
        if record.status == USER_STATUS_APPROVED:
            return record
        return self.approve(telegram_user_id, admin_telegram_id=telegram_user_id)

    # --- internals -------------------------------------------------------

    def _resolve_request(
        self,
        telegram_user_id: int,
        *,
        admin_telegram_id: int,
        new_status: str,
        new_request_status: str,
    ) -> UserRecord:
        return self._update_locked_with(
            telegram_user_id,
            change=lambda _existing, now_iso: {
                "status": new_status,
                "access_request_status": new_request_status,
                "access_resolved_at": now_iso,
                "resolved_by_admin_id": admin_telegram_id,
            },
        )

    def _update_locked(self, telegram_user_id: int, **fields: Any) -> UserRecord:
        """Атомарно применяет статические поля поверх существующей записи.

        Подходит, когда новые значения не зависят от текущих. Всегда
        обновляет ``updated_at``. KeyError, если запись отсутствует.
        """
        return self._update_locked_with(
            telegram_user_id,
            change=lambda _existing, _now_iso: dict(fields),
        )

    def _update_locked_with(
        self,
        telegram_user_id: int,
        *,
        change: Callable[[UserRecord, str], dict[str, Any]],
    ) -> UserRecord:
        """Атомарно применяет поля, зависящие от существующей записи / времени.

        ``change(existing, now_iso) -> dict`` — какие поля заменить.
        ``updated_at`` всегда обновляется на ``now_iso``.
        """
        now_iso = self._now_iso()
        with self._lock:
            existing = self._items.get(telegram_user_id)
            if existing is None:
                raise KeyError(telegram_user_id)
            fields = change(existing, now_iso)
            updated = replace(existing, **fields, updated_at=now_iso)
            candidate = dict(self._items)
            candidate[telegram_user_id] = updated
            self._commit_items_locked(candidate)
        return updated

    def _load(self) -> dict[int, UserRecord]:
        raw = self._load_json_root()
        items: dict[int, UserRecord] = {}
        for key, value in raw.items():
            try:
                user_id = int(key)
            except (TypeError, ValueError) as exc:
                raise self._load_error(f"record key {key!r} is not an integer") from exc
            if not isinstance(value, dict):
                raise self._load_error(f"record {key!r} must be a JSON object")
            try:
                items[user_id] = UserRecord.from_json(user_id, value)
            except Exception as exc:  # noqa: BLE001 - переводим в публичную load-ошибку
                raise self._load_error(f"record {key!r} is structurally invalid: {exc}") from exc
        return items

    def _build_snapshot_payload(
        self,
        items: Mapping[int, UserRecord],
    ) -> dict[str, Any]:
        return {str(rec.telegram_user_id): rec.to_json() for rec in items.values()}
