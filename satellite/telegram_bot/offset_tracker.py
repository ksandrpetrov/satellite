"""Отслеживание прогресса обработки update'ов с двумя offset'ами.

В Telegram-семантике offset, который мы передаём в ``getUpdates``, имеет два
очень разных назначения, и держать их как одно значение — рецепт дубликатов:

- **Polling offset** — то, что мы шлём в ``getUpdates``: «всё до этого id я уже
  получил, не переотдавай». Должен продвигаться **сразу при получении** апдейта,
  иначе следующий long-poll вернёт тот же самый update_id снова, пока воркер
  ещё его обрабатывает (см. ниже). Telegram переотдаёт каждые ~30 секунд (или
  моментально, если timeout=0).
- **Persisted offset** — «низкий водяной знак»: до какого update_id мы уже
  обработали ВСЕ предыдущие. Используется только для восстановления после
  рестарта: если процесс упал между ``mark_dispatched`` и ``mark_completed``,
  на старте мы перепоштилем недоделанное.

Сценарий, который раньше вызывал спам:
1. Пользователь шлёт «10:45», update_id=N. Polling offset = persisted = N.
2. Поллер получает [N], отдаёт воркеру. Persisted offset = N (не двигается).
3. Воркер ещё бежит. Поллер идёт на следующий long-poll с offset=N → Telegram
   мгновенно возвращает [N] снова.
4. Бот дважды диспатчит один и тот же update_id; для «10:45» первая копия
   попадает в FSM (state waiting → корректный ответ), вторая — в
   ``_handle_unknown`` (state уже очищен предыдущей копией) и присылает
   «🪶 Не понял команду».

С разделением offset'ов polling сдвигается сразу до N+1, и Telegram больше N
не отдаёт. Plus belt-and-suspenders: ``mark_dispatched`` теперь возвращает
``False`` для уже-pending update_id (на случай гонки между потоками или
между instances на том же токене).

Stale-updates:
- Если приходит ``update_id < persisted_offset`` (Telegram переотдаёт уже
  подтверждённый update — типично при гонке с другим инстансом или после
  ручного сдвига), мы такие молча дропаем. Polling offset всё равно подтягиваем
  вверх — это «вежливое» уведомление Telegram: всё, что меньше нашего polling,
  переотдавать больше не нужно.
"""

from __future__ import annotations

import logging
import threading

from .offset_store import OffsetStore

log = logging.getLogger(__name__)

# Лог стейлов любим, но без флуда: один INFO раз в N штук подряд.
_STALE_LOG_EVERY = 50


class OffsetTracker:
    def __init__(self, store: OffsetStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._pending: dict[int, bool] = {}  # update_id -> completed?
        self._stale_counter = 0
        # Polling offset стартует с persisted: на холодном старте у нас нет
        # in-flight задач, и Telegram отдаст всё начиная с этой точки.
        self._polling_offset = store.offset

    @property
    def offset(self) -> int:
        """Persisted offset — низкий водяной знак для восстановления после рестарта.

        Сдвигается только когда контигуозный префикс pending-id'шников завершён.
        Тесты и старый код, читавшие «offset», получают именно это значение.
        """
        return self._store.offset

    @property
    def polling_offset(self) -> int:
        """Offset для следующего ``getUpdates`` — «не переотдавай ниже этого».

        Сдвигается мгновенно при получении любого update_id, даже если воркер
        ещё бежит. Это и есть ключ к тому, чтобы Telegram не возвращал нам
        один и тот же update снова в течение pending-окна.
        """
        with self._lock:
            return self._polling_offset

    def mark_dispatched(self, update_id: int) -> bool:
        """Возвращает ``True``, если update нужно обработать; ``False`` — пропуск.

        ``False`` возвращается в трёх случаях:
        - ``update_id <= 0`` — мусор.
        - ``update_id < persisted_offset`` — stale (Telegram переотдал
          уже подтверждённый); polling offset всё равно подтягиваем вверх.
        - ``update_id`` уже в pending — параллельная переотдача того же
          update'а Telegram'ом (другой поток / другой long-poll цикл) пока
          мы ещё его обрабатываем. Без этого guard'а мы бы дважды
          выполнили побочные эффекты.

        В любом случае polling offset подтягивается до ``update_id + 1``: даже
        для stale это полезный сигнал Telegram'у «давай уже двигайся».
        """
        if update_id <= 0:
            return False
        log_message: str | None = None
        with self._lock:
            current_offset = self._store.offset
            next_polling = update_id + 1
            if next_polling > self._polling_offset:
                self._polling_offset = next_polling
            if update_id < current_offset:
                self._stale_counter += 1
                if self._stale_counter == 1 or self._stale_counter % _STALE_LOG_EVERY == 0:
                    log_message = (
                        f"Dropping stale update_id={update_id} "
                        f"(offset={current_offset}, count={self._stale_counter})"
                    )
                return_value = False
            elif update_id in self._pending:
                # Уже диспатчили в этом процессе — Telegram переотдал, потому
                # что воркер ещё не завершился. Это безопасно и тихо
                # пропускаем; первая копия доделает работу.
                return_value = False
            else:
                self._pending[update_id] = False
                self._stale_counter = 0
                return_value = True
        if log_message is not None:
            log.info(log_message)
        return return_value

    def mark_completed(self, update_id: int) -> None:
        if update_id <= 0:
            return
        with self._lock:
            if update_id in self._pending:
                self._pending[update_id] = True
            advance_to = self._compute_next_offset_locked()
        if advance_to is not None:
            self._store.update(advance_to)

    def _compute_next_offset_locked(self) -> int | None:
        if not self._pending:
            return None
        advance_to: int | None = None
        for uid in sorted(self._pending):
            if self._pending[uid]:
                advance_to = uid + 1
                del self._pending[uid]
            else:
                break
        return advance_to
