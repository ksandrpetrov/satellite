"""Очень лёгкий FSM поверх chat_id и dedup для callback_query.

Назначение:

- Сценарий FSM: пользователь нажал inline-кнопку «🕘 Время отправки», после
  чего следующий текстовый ввод должен трактоваться как новое время. Полный
  aiogram FSM здесь избыточен — достаточно потокобезопасной мапы
  ``chat_id -> {state, message_id, digest_kind}``.

- Dedup callback_query_id: Telegram иногда переотдаёт один и тот же
  callback_query (offset-рассинхрон при рестарте, гонки с другими процессами
  на тот же токен и т.п.). Без защиты повторная обработка приводит к
  фантомному «спаму» — каждый дубль пробует ``editMessageText``, получает
  «message is not modified» и в прошлой версии шёл в send_message-фоллбэк.
  Хранение последних 1024 cb_id в bounded-кольце достаточно: callback expires
  на стороне Telegram через ~30 минут, мы заведомо переживём это окно.

In-memory store сбрасывается при рестарте процесса бота. Это сознательный
компромисс: пользователь, который ничего не успел ввести до рестарта, повторит
шаг через интерфейс настроек.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

STATE_WAITING_FOR_DIGEST_TIME = "waiting_for_digest_time"

DigestKind = Literal["daily", "pending"]
DIGEST_KIND_DAILY: DigestKind = "daily"
DIGEST_KIND_PENDING: DigestKind = "pending"

# Размер кольцевого dedup-буфера. ~1k — потолок «одной активной сессии» с запасом.
_DEDUP_CAPACITY = 1024


@dataclass(frozen=True)
class WaitingState:
    state: str
    message_id: int | None  # id «исходного» inline-сообщения, чтобы вернуться на него
    digest_kind: DigestKind = DIGEST_KIND_DAILY


class DigestStateStore:
    """Потокобезопасный per-chat state + LRU-dedup для callback_query_id."""

    def __init__(self, dedup_capacity: int = _DEDUP_CAPACITY) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, WaitingState] = {}
        self._seen_callbacks: OrderedDict[str, None] = OrderedDict()
        self._dedup_capacity = max(1, int(dedup_capacity))

    def set_waiting_for_time(
        self,
        chat_id: int,
        message_id: int | None,
        *,
        digest_kind: DigestKind = DIGEST_KIND_DAILY,
    ) -> None:
        with self._lock:
            self._items[chat_id] = WaitingState(
                state=STATE_WAITING_FOR_DIGEST_TIME,
                message_id=message_id,
                digest_kind=digest_kind,
            )

    def get(self, chat_id: int) -> WaitingState | None:
        with self._lock:
            return self._items.get(chat_id)

    def clear(self, chat_id: int) -> WaitingState | None:
        """Атомарно достаёт и удаляет state. Возвращает прошлое состояние или None."""
        with self._lock:
            return self._items.pop(chat_id, None)

    def is_waiting_for_time(self, chat_id: int) -> bool:
        with self._lock:
            current = self._items.get(chat_id)
            return current is not None and current.state == STATE_WAITING_FOR_DIGEST_TIME

    def claim_callback(self, callback_id: str) -> bool:
        """True — этот callback_id мы видим впервые и берём в работу.

        False — уже обрабатывали (Telegram переотдал тот же update); вызывающий
        должен молча выйти. LRU-семантика: при переполнении вытесняется самый
        старый id.
        """
        if not callback_id:
            return True
        with self._lock:
            if callback_id in self._seen_callbacks:
                # обновим «возраст» — теперь самый свежий
                self._seen_callbacks.move_to_end(callback_id)
                return False
            self._seen_callbacks[callback_id] = None
            while len(self._seen_callbacks) > self._dedup_capacity:
                self._seen_callbacks.popitem(last=False)
            return True
