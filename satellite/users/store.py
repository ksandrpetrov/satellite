"""Thread-safe JSON-store пользователей.

Атомарные записи (``tmp + fsync + os.replace``); все читающие/пишущие методы
синхронизированы через один lock. Загрузка устойчива к битому файлу:
невалидная запись игнорируется, остальные подгружаются.

Все мутаторы — тонкие обёртки над ``_update_locked`` / ``_update_locked_with``;
единственное место, где меняется ``updated_at`` и идёт ``_save_locked``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

log = logging.getLogger(__name__)


class UserStorePersistenceError(RuntimeError):
    """Не удалось записать ``users.json`` на диск.

    Пробрасывается из ``UserStore._save_locked`` вместо тихого логирования —
    in-memory состояние при этом уже обновлено и будет сохранено при следующей
    успешной записи (мы сериализуем весь словарь, а не дельту). Caller должен
    показать пользователю безопасный текст из ``messages_ru``.
    """


class UserStore:
    """Thread-safe JSON-store пользователей.

    См. модульный docstring выше.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
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
                self._items[telegram_user_id] = record
                self._save_locked()
                return record
            updated = existing
            if chat_id is not None and existing.chat_id != chat_id:
                updated = replace(updated, chat_id=chat_id)
            if normalized_user is not None and existing.username != normalized_user:
                updated = replace(updated, username=normalized_user)
            if normalized_name is not None and existing.display_name != normalized_name:
                updated = replace(updated, display_name=normalized_name)
            if updated is not existing:
                updated = replace(updated, updated_at=now_iso)
                self._items[telegram_user_id] = updated
                self._save_locked()
            return updated

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
            self._items[telegram_user_id] = updated
            self._save_locked()
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
            self._items[telegram_user_id] = updated
            self._save_locked()
            return updated

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    def _load(self) -> dict[int, UserRecord]:
        try:
            with self._path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load users from %s: %s", self._path, exc)
            return {}
        if not isinstance(raw, dict):
            log.warning("Users file %s is malformed (not an object)", self._path)
            return {}
        items: dict[int, UserRecord] = {}
        for key, value in raw.items():
            try:
                user_id = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict):
                continue
            try:
                items[user_id] = UserRecord.from_json(user_id, value)
            except Exception:  # noqa: BLE001 - не валим бот из-за одной битой записи
                log.warning("Skipping malformed user record %r", key, exc_info=True)
        return items

    def _save_locked(self) -> None:
        payload = {str(rec.telegram_user_id): rec.to_json() for rec in self._items.values()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=self._path.name + ".",
                suffix=".tmp",
                dir=self._path.parent,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(tmp_path, self._path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            log.error("Failed to persist users to %s: %s", self._path, exc)
            raise UserStorePersistenceError(
                f"Failed to persist users to {self._path}: {exc}"
            ) from exc
