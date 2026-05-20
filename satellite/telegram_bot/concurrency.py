"""Маленькие потокобезопасные примитивы для бот-цикла.

Назначение:
- `ChatLockManager` — выдаёт по `chat_id` один и тот же lock, чтобы не
  обрабатывать сообщения одного пользователя параллельно (события из CalDAV
  и Telegram отвечают по очереди в правильном порядке).
- `InflightTracker` — гасит дубли распознанных команд (например, двойной тап
  по кнопке): пока для чата идёт обработка распознанной команды, повторные
  такие же команды отбрасываются.

Обе сущности — самодостаточные, без зависимостей на остальной бот; их легко
проверять юнит-тестами.
"""

from __future__ import annotations

import threading


class ChatLockManager:
    """Возвращает один и тот же `threading.Lock` для одного `chat_id`.

    Для отсутствующего `chat_id` (None) выдаётся одноразовый lock —
    последовательной обработки в этом случае не нужно.
    """

    def __init__(self) -> None:
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    def acquire(self, chat_id: int | None) -> threading.Lock:
        if chat_id is None:
            return threading.Lock()
        with self._guard:
            lock = self._locks.get(chat_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[chat_id] = lock
            return lock


class InflightTracker:
    """Отслеживает, идёт ли сейчас распознанная команда от данного чата.

    Используется как defensive-механика против двойных тапов по reply-кнопке.
    Применяется ТОЛЬКО к распознанным командам (`add_if_absent` вызывается
    только когда команда узнана); неопознанный текст не блокируется.
    """

    def __init__(self) -> None:
        self._items: set[int] = set()
        self._lock = threading.Lock()

    def add_if_absent(self, chat_id: int | None) -> bool:
        """Возвращает True, если чат был добавлен; False, если уже был."""
        if chat_id is None:
            return True
        with self._lock:
            if chat_id in self._items:
                return False
            self._items.add(chat_id)
            return True

    def discard(self, chat_id: int | None) -> None:
        if chat_id is None:
            return
        with self._lock:
            self._items.discard(chat_id)
