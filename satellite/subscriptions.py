"""Per-user настройки дайджеста: thread-safe JSON-store с атомарной записью.

Раньше тут жил минимальный SubscriptionStore (вкл/выкл), теперь — расширенная
модель ``DigestSettings`` с днями недели, временем по Москве и защитой от
повторной отправки в один день. Старый формат файла (только подписчики, без
явных полей настроек) совместим: при загрузке такие записи становятся
``digest_enabled=True`` с дефолтами.

Дизайн-решения:
- API класса ``SubscriptionStore`` (``subscribe``/``unsubscribe``/``is_subscribed``)
  сохранён, чтобы не ломать handlers и тесты. ``unsubscribe`` теперь не удаляет
  запись, а выключает ``digest_enabled`` — настройки пользователя переживают
  отписку и применяются при повторной подписке.
- ``list()`` возвращает только активных подписчиков (для шедулера это удобно
  и совместимо со старой семантикой). ``list_all()`` — все записи (для тестов
  и админских операций).
- ``Subscription`` оставлен как алиас для обратной совместимости импортов;
  у него те же поля (chat_id, username, subscribed_at), плюс новые с дефолтами.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from .calendar.time_utils import normalize_hhmm_input

log = logging.getLogger(__name__)


# Канонические значения digest_days. Сохраняются в JSON «как есть».
DIGEST_DAYS_WEEKDAYS = "weekdays"
DIGEST_DAYS_ALL = "all_days"
ALLOWED_DIGEST_DAYS = frozenset({DIGEST_DAYS_WEEKDAYS, DIGEST_DAYS_ALL})

DEFAULT_DIGEST_TIME = "09:00"
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
    subscribed_at: str = ""  # ISO8601 UTC момента первого включения подписки
    last_digest_sent_date: str | None = None  # "YYYY-MM-DD" или None


# Старое имя класса используется в тестах и шедулере. Оставляем как алиас.
Subscription = DigestSettings


class SubscriptionStore:
    """JSON-файл `{str(chat_id): { ...fields... }}`.

    Все мутации атомарны (tmp + os.replace) и потокобезопасны.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._items: dict[int, DigestSettings] = self._load()

    # --- подписка (back-compat) ------------------------------------------

    def is_subscribed(self, chat_id: int) -> bool:
        with self._lock:
            record = self._items.get(chat_id)
            return bool(record and record.digest_enabled)

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
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None or not existing.digest_enabled:
                return False
            self._items[chat_id] = replace(existing, digest_enabled=False)
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
        resolved_user_id = (
            int(telegram_user_id)
            if telegram_user_id is not None
            else int(chat_id)
        )
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None:
                created = DigestSettings(
                    chat_id=chat_id,
                    telegram_user_id=resolved_user_id,
                    username=normalized,
                )
                self._items[chat_id] = created
                self._save_locked()
                return created
            updated = existing
            if existing.username != normalized:
                updated = replace(updated, username=normalized)
            if existing.telegram_user_id != resolved_user_id:
                updated = replace(updated, telegram_user_id=resolved_user_id)
            if updated is not existing:
                self._items[chat_id] = updated
                self._save_locked()
            return updated

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
        resolved_user_id = (
            int(telegram_user_id)
            if telegram_user_id is not None
            else int(chat_id)
        )
        now_iso = self._now_iso()
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None:
                existing = DigestSettings(
                    chat_id=chat_id,
                    telegram_user_id=resolved_user_id,
                    username=normalized_user,
                )
            updated = existing
            if existing.username != normalized_user:
                updated = replace(updated, username=normalized_user)
            if existing.telegram_user_id != resolved_user_id:
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
            if updated != existing or chat_id not in self._items:
                self._items[chat_id] = updated
                self._save_locked()
            return updated

    def mark_digest_sent(self, chat_id: int, sent_date: date | str) -> None:
        """Записывает дату последней успешной автоотправки (YYYY-MM-DD)."""
        iso = sent_date.isoformat() if isinstance(sent_date, date) else str(sent_date)
        with self._lock:
            existing = self._items.get(chat_id)
            if existing is None:
                return
            if existing.last_digest_sent_date == iso:
                return
            self._items[chat_id] = replace(existing, last_digest_sent_date=iso)
            self._save_locked()

    def list(self) -> list[DigestSettings]:
        """Только активные подписчики (digest_enabled=True). Совместимо с прошлым API."""
        with self._lock:
            return [s for s in self._items.values() if s.digest_enabled]

    def list_all(self) -> list[DigestSettings]:
        """Все записи, включая отключённые — для админских операций и тестов."""
        with self._lock:
            return list(self._items.values())

    # --- internals --------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    def _load(self) -> dict[int, DigestSettings]:
        try:
            with self._path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load subscriptions from %s: %s", self._path, exc)
            return {}

        if not isinstance(raw, dict):
            log.warning("Subscriptions file %s is malformed (not an object)", self._path)
            return {}

        items: dict[int, DigestSettings] = {}
        for chat_key, value in raw.items():
            try:
                chat_id = int(chat_key)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict):
                continue
            username = str(value.get("username") or "").lower()
            if not username:
                continue
            subscribed_at = str(value.get("subscribed_at") or "")
            digest_days = str(value.get("digest_days") or DEFAULT_DIGEST_DAYS)
            if digest_days not in ALLOWED_DIGEST_DAYS:
                digest_days = DEFAULT_DIGEST_DAYS
            digest_time = _normalize_digest_time(value.get("digest_time"))
            digest_timezone = str(value.get("digest_timezone") or DEFAULT_DIGEST_TIMEZONE)
            # Старый формат не содержал явного `digest_enabled`: само присутствие
            # записи означало активную подписку. Сохраняем эту семантику миграцией.
            raw_enabled = value.get("digest_enabled")
            if raw_enabled is None:
                digest_enabled = True
            else:
                digest_enabled = _coerce_bool(raw_enabled, default=False)
            last_sent = value.get("last_digest_sent_date")
            last_sent_str: str | None
            if last_sent in (None, ""):
                last_sent_str = None
            else:
                last_sent_str = str(last_sent)
            uid_raw = value.get("telegram_user_id")
            if isinstance(uid_raw, int):
                telegram_user_id = uid_raw
            elif isinstance(uid_raw, str) and uid_raw.strip():
                try:
                    telegram_user_id = int(uid_raw)
                except ValueError:
                    telegram_user_id = chat_id
            else:
                telegram_user_id = chat_id
            items[chat_id] = DigestSettings(
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                username=username,
                digest_enabled=digest_enabled,
                digest_days=digest_days,
                digest_time=digest_time,
                digest_timezone=digest_timezone,
                subscribed_at=subscribed_at,
                last_digest_sent_date=last_sent_str,
            )
        return items

    def _save_locked(self) -> None:
        payload = {
            str(chat_id): {
                "telegram_user_id": rec.telegram_user_id,
                "username": rec.username,
                "digest_enabled": rec.digest_enabled,
                "digest_days": rec.digest_days,
                "digest_time": rec.digest_time,
                "digest_timezone": rec.digest_timezone,
                "subscribed_at": rec.subscribed_at,
                "last_digest_sent_date": rec.last_digest_sent_date,
            }
            for chat_id, rec in self._items.items()
        }
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
            log.error("Failed to persist subscriptions to %s: %s", self._path, exc)
