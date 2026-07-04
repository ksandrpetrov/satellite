"""Thread-safe JSON store for per-user digest subscriptions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from ..calendar.time_utils import normalize_hhmm_input
from ..json_store import JsonStoreBase
from .record import (
    ALLOWED_DIGEST_DAYS,
    DigestSettings,
    is_valid_pending_digest_days,
)

log = logging.getLogger(__name__)


class SubscriptionStorePersistenceError(RuntimeError):
    """Не удалось записать ``subscriptions.json`` на диск."""


class SubscriptionStore(JsonStoreBase):
    """JSON-файл `{str(chat_id): { ...fields... }}`.

    Все мутации атомарны (tmp + os.replace) и потокобезопасны.
    """

    _PERSISTENCE_ERROR = SubscriptionStorePersistenceError
    _STORE_LABEL = "subscriptions"

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self._items: dict[int, DigestSettings] = self._load()

    # --- подписка (back-compat) ------------------------------------------

    def is_subscribed(self, chat_id: int) -> bool:
        with self._lock:
            record = self._items.get(chat_id)
            return bool(record and (record.digest_enabled or record.pending_digest_enabled))

    def subscribe(
        self,
        chat_id: int,
        username: str,
        *,
        telegram_user_id: int | None = None,
    ) -> bool:
        """Тонкая обёртка над ``update_settings(digest_enabled=True)``.

        Возвращает ``True``, если запись была создана или ``digest_enabled``
        действительно переключился c ``False`` на ``True``. Используется только
        тестами и внешними скриптами; production-handlers (см.
        ``handlers/subscription.py``) вызывают ``update_settings`` напрямую,
        чтобы был один путь включения подписки.
        """
        with self._lock:
            existed = self._items.get(chat_id)
            was_enabled = bool(existed and existed.digest_enabled)
        updated = self.update_settings(
            chat_id,
            username,
            telegram_user_id=telegram_user_id,
            digest_enabled=True,
        )
        return not was_enabled and updated.digest_enabled

    def unsubscribe(self, chat_id: int) -> bool:
        """Выключает digest_enabled. True — если состояние действительно изменилось.

        Запись НЕ удаляется: настройки (дни/время) переживают отписку, чтобы
        при повторном включении пользователь не настраивал всё заново.
        """
        changed = False
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None or not existing.digest_enabled:
                return False
            self._items[chat_id] = replace(existing, digest_enabled=False)
            changed = True
        if changed:
            self._save_locked()
        return True

    # --- per-user settings ------------------------------------------------

    def get(self, chat_id: int) -> DigestSettings | None:
        """Возвращает запись, если есть. None — если пользователь ни разу не трогал бота."""
        with self._lock:
            return self._items.get(chat_id)

    def get_or_create(
        self,
        chat_id: int,
        username: str,
        *,
        telegram_user_id: int | None = None,
    ) -> DigestSettings:
        """Гарантирует запись с дефолтами; обновляет username, если поменялся.

        Полезно для экрана настроек: открытие меню должно показать корректное
        состояние, даже если пользователь ни разу не нажимал «подписаться».
        Подписка при этом не активируется — ``digest_enabled`` остаётся ``False``.
        """
        if chat_id is None:
            raise ValueError("chat_id is required")
        if not username:
            raise ValueError("username is required")
        normalized = username.lower()
        resolved_user_id = int(telegram_user_id) if telegram_user_id is not None else int(chat_id)

        def _change(existing: DigestSettings | None) -> DigestSettings:
            if existing is None:
                return DigestSettings(
                    chat_id=chat_id,
                    telegram_user_id=resolved_user_id,
                    username=normalized,
                )
            updated = existing
            if existing.username != normalized:
                updated = replace(updated, username=normalized)
            if existing.telegram_user_id != resolved_user_id:
                updated = replace(updated, telegram_user_id=resolved_user_id)
            return updated

        return self._upsert_locked(chat_id, build=_change)

    def update_settings(
        self,
        chat_id: int,
        username: str,
        *,
        telegram_user_id: int | None = None,
        digest_enabled: bool | None = None,
        digest_days: str | None = None,
        digest_time: str | None = None,
        digest_timezone: str | None = None,
        pending_digest_enabled: bool | None = None,
        pending_digest_days: str | None = None,
        pending_digest_time: str | None = None,
        pending_digest_timezone: str | None = None,
    ) -> DigestSettings:
        """Точечное обновление полей. Создаёт запись, если её ещё нет.

        Невалидные значения (digest_days вне белого списка) игнорируются,
        чтобы случайный мусор из callback_data не портил файл.
        """
        if chat_id is None:
            raise ValueError("chat_id is required")
        if not username:
            raise ValueError("username is required")
        normalized_user = username.lower()
        resolved_user_id = int(telegram_user_id) if telegram_user_id is not None else int(chat_id)
        now_iso = self._now_iso()

        def _change(existing: DigestSettings | None) -> DigestSettings:
            current = existing or DigestSettings(
                chat_id=chat_id,
                telegram_user_id=resolved_user_id,
                username=normalized_user,
            )
            updated = current
            if current.username != normalized_user:
                updated = replace(updated, username=normalized_user)
            if current.telegram_user_id != resolved_user_id:
                updated = replace(updated, telegram_user_id=resolved_user_id)
            if digest_enabled is not None and digest_enabled != updated.digest_enabled:
                if digest_enabled:
                    updated = replace(
                        updated,
                        digest_enabled=True,
                        subscribed_at=updated.subscribed_at or now_iso,
                    )
                else:
                    updated = replace(updated, digest_enabled=False)
            if digest_days is not None and digest_days in ALLOWED_DIGEST_DAYS:
                updated = replace(updated, digest_days=digest_days)
            if digest_time is not None and digest_time:
                normalized_time = normalize_hhmm_input(digest_time)
                if normalized_time is not None:
                    updated = replace(updated, digest_time=normalized_time)
                else:
                    log.info(
                        "Ignored invalid digest_time for chat_id=%s: %r",
                        chat_id,
                        digest_time,
                    )
            if digest_timezone is not None and digest_timezone:
                updated = replace(updated, digest_timezone=digest_timezone)
            if (
                pending_digest_enabled is not None
                and pending_digest_enabled != updated.pending_digest_enabled
            ):
                updated = replace(updated, pending_digest_enabled=pending_digest_enabled)
            if pending_digest_days is not None and is_valid_pending_digest_days(
                pending_digest_days
            ):
                updated = replace(updated, pending_digest_days=pending_digest_days)
            if pending_digest_time is not None and pending_digest_time:
                normalized_pending_time = normalize_hhmm_input(pending_digest_time)
                if normalized_pending_time is not None:
                    updated = replace(updated, pending_digest_time=normalized_pending_time)
                else:
                    log.info(
                        "Ignored invalid pending_digest_time for chat_id=%s: %r",
                        chat_id,
                        pending_digest_time,
                    )
            if pending_digest_timezone is not None and pending_digest_timezone:
                updated = replace(updated, pending_digest_timezone=pending_digest_timezone)
            return updated

        return self._upsert_locked(chat_id, build=_change)

    def mark_digest_sent(self, chat_id: int, sent_date: date | str) -> None:
        """Записывает дату последней успешной автоотправки (YYYY-MM-DD)."""
        iso = sent_date.isoformat() if isinstance(sent_date, date) else str(sent_date)
        changed = False
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None:
                return
            if existing.last_digest_sent_date == iso:
                return
            self._items[chat_id] = replace(existing, last_digest_sent_date=iso)
            changed = True
        if changed:
            self._save_locked()

    def mark_pending_digest_sent(self, chat_id: int, sent_date: date | str) -> None:
        """Дата последней успешной автоотправки дайджеста непринятых встреч."""
        iso = sent_date.isoformat() if isinstance(sent_date, date) else str(sent_date)
        changed = False
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None:
                return
            if existing.last_pending_digest_sent_date == iso:
                return
            self._items[chat_id] = replace(existing, last_pending_digest_sent_date=iso)
            changed = True
        if changed:
            self._save_locked()

    def list_active(self) -> list[DigestSettings]:
        """Подписчики с хотя бы одним включённым дайджестом.

        Раньше назывался ``list()``, но это shadow'ит builtin ``list`` в
        типовых аннотациях класса, из-за чего mypy ломался на ``list_all() ->
        list[DigestSettings]``. Переименовано без back-compat: внутри проекта
        вызовы обновлены, тесты — тоже.
        """
        with self._lock:
            return [s for s in self._items.values() if s.digest_enabled or s.pending_digest_enabled]

    def list_all(self) -> list[DigestSettings]:
        """Все записи, включая отключённые — для админских операций и тестов."""
        with self._lock:
            return list(self._items.values())

    # --- internals --------------------------------------------------------

    def _upsert_locked(
        self,
        chat_id: int,
        *,
        build: Callable[[DigestSettings | None], DigestSettings],
    ) -> DigestSettings:
        """Атомарно применяет ``build(existing|None) -> новая запись``.

        Сохраняет только если что-то реально поменялось или запись только что
        появилась. Возвращает финальную запись.
        """
        changed = False
        with self._lock:
            existing = self._items.get(chat_id)
            updated = build(existing)
            if updated != existing or chat_id not in self._items:
                self._items[chat_id] = updated
                changed = True
        if changed:
            self._save_locked()
        return updated

    def _load(self) -> dict[int, DigestSettings]:
        raw = self._load_json_root()
        items: dict[int, DigestSettings] = {}
        for chat_key, value in raw.items():
            try:
                chat_id = int(chat_key)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict):
                continue
            record = DigestSettings.from_json(chat_id, value)
            if record is not None:
                items[chat_id] = record
        return items

    def _build_snapshot_payload(self) -> dict[str, Any]:
        return {str(chat_id): rec.to_json() for chat_id, rec in self._items.items()}
