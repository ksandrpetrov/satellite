"""Дедуп длинных пользовательских действий (per chat + action key).

Зачем нужно: типичный хендлер делает CalDAV-fetch (1–10 с) и затем отправляет
новое сообщение (``sendMessage`` / ``sendPhoto``). Если пользователь дважды
тапает кнопку или дважды отправляет команду, ``ChatLockManager`` сериализует
их по ``chat_id`` — но второй callback всё равно отработает и пользователь
получит дубликат (см. прод-инцидент 2026-05-21 12:49 UTC: два PNG аналитики
с интервалом 7 секунд).

Дизайн:

- ``try_acquire(chat_id, action_key)`` берёт лок per ``(chat_id, action_key)``;
  если действие сейчас идёт ИЛИ только что успешно завершилось в пределах
  ``cooldown_sec`` — возвращает ``False``.
- ``release(chat_id, action_key, sent=True)`` снимает «running» и фиксирует
  момент успеха для cooldown'а. ``sent=False`` — снимает лок, но без cooldown
  (короткий путь: пользователь увидит ту же ошибку, ему нет смысла ждать).

``action_key`` — произвольная строка: ``"plan:today"``, ``"upcoming"``,
``f"partstat:{token}"``. Это позволяет независимо ограничивать разные
действия в том же чате.

Дублирует семантику ``DigestStateStore.claim_callback`` (по ``callback_query_id``),
но защищает от другого класса повторов: новый клик / новая команда от
пользователя, который сначала не дождался ответа. ``claim_callback`` спасает
только от переотдачи **того же** update'а Telegram'ом.

Все таймеры — ``time.monotonic()``: устойчиво к скачкам системного времени.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class _Key:
    chat_id: int
    action_key: str


class ActionGuard:
    """Потокобезопасный пер-чат дедуп долгих действий с cooldown'ом."""

    def __init__(self, *, cooldown_sec: float = 30.0) -> None:
        self._lock = threading.Lock()
        self._running: set[_Key] = set()
        self._last_success_at: dict[_Key, float] = {}
        self._cooldown_sec = max(0.0, float(cooldown_sec))

    def try_acquire(self, chat_id: int, action_key: str) -> bool:
        """``True``, если действие можно запускать; ``False`` — занято/cooldown."""
        if chat_id is None or not action_key:
            return True
        key = _Key(chat_id=chat_id, action_key=action_key)
        now = time.monotonic()
        with self._lock:
            if key in self._running:
                return False
            last = self._last_success_at.get(key)
            if last is not None and (now - last) < self._cooldown_sec:
                return False
            self._running.add(key)
            return True

    def release(self, chat_id: int, action_key: str, *, sent: bool = False) -> None:
        """Снять лок. ``sent=True`` — фиксирует cooldown после успешной отправки."""
        if chat_id is None or not action_key:
            return
        key = _Key(chat_id=chat_id, action_key=action_key)
        with self._lock:
            self._running.discard(key)
            if sent:
                self._last_success_at[key] = time.monotonic()
            else:
                self._last_success_at.pop(key, None)

    def reset(self) -> None:
        """Полный сброс — для изоляции в тестах между прогонами."""
        with self._lock:
            self._running.clear()
            self._last_success_at.clear()
