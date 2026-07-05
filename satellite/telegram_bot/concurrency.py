"""Маленькие потокобезопасные примитивы для бот-цикла.

Назначение:
- `ChatLockManager` — выдаёт по `chat_id` один и тот же lock, чтобы не
  обрабатывать сообщения одного пользователя параллельно (события из CalDAV
  и Telegram отвечают по очереди в правильном порядке).

Дедуп долгих команд — только через :mod:`handlers.action_guard`.
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
