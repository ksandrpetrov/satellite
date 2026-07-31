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
    """Возвращает один и тот же striped-lock для одного ``chat_id``.

    Для отсутствующего `chat_id` (None) выдаётся одноразовый lock —
    последовательной обработки в этом случае не нужно.

    Фиксированный набор полос не растёт от количества когда-либо увиденных
    chat_id. Разные чаты изредка могут попасть на одну полосу; это безопасно и
    лишь кратковременно уменьшает параллелизм.
    """

    def __init__(self, stripes: int = 256) -> None:
        if stripes <= 0:
            raise ValueError("stripes must be positive")
        self._locks = tuple(threading.Lock() for _ in range(stripes))

    def acquire(self, chat_id: int | None) -> threading.Lock:
        if chat_id is None:
            return threading.Lock()
        return self._locks[chat_id % len(self._locks)]
