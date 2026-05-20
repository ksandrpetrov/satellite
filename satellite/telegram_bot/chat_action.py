"""Периодический ``sendChatAction`` (typing) на время долгой синхронной операции.

Проект использует синхронный ``TelegramClient`` и пул потоков, не aiogram/async.
Логика соответствует описанному ``async def run_with_typing_action(..., coro)``:
основная работа выполняется в текущем потоке, статус typing дублируется фоновым
потоком каждые ``interval_seconds`` секунд.

Telegram держит индикатор «печатает» до ``TYPING_DISPLAY_SECONDS`` после
последнего ``sendChatAction``. Отменить его API не позволяет, и ``editMessageText``
(в отличие от ``sendMessage``) индикатор не сбрасывает. Чтобы пользователь не
видел «печатает» уже после того, как итоговое сообщение пришло в чат, после
завершения ``fn`` мы досыпаем оставшееся время жизни typing.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from .api import TelegramClient

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Bot API гарантирует «5 seconds or less», но это серверный контракт. На пути
# к клиенту прибавляется сетевая задержка push-уведомления «typing stopped»
# и фрейм-лаг самой анимации индикатора, поэтому впритык 5.0 не работает —
# typing успевает «моргнуть» уже после прихода итогового сообщения. Заклады-
# ваем запас: 5 c контракта + ~2 c на доставку до клиента и UI-обновление.
TYPING_DISPLAY_SECONDS = 7.0


def run_with_typing_action(
    telegram: TelegramClient,
    chat_id: int,
    fn: Callable[[], T],
    *,
    interval_seconds: float = 4.0,
    wait_for_typing_to_clear: bool = True,
    typing_display_seconds: float | None = None,
) -> T:
    """Сразу шлёт typing, периодически обновляет его, выполняет ``fn``.

    Ошибки ``sendChatAction`` только логируются (warning), основная функция не
    прерывается. Исключения из ``fn`` пробрасываются; фоновый поток останавливается.

    ``sendChatAction`` — best-effort: короткий таймаут важнее ретраев, потому что
    медленный typing-индикатор не должен задерживать итоговое сообщение.

    Если ``wait_for_typing_to_clear`` (по умолчанию True), после ``fn`` блокирующий
    поток досыпает время, оставшееся до истечения индикатора. Это гарантирует, что
    typing не «висит» в шапке чата уже после того, как итоговое сообщение
    отправлено или отредактировано. Когда финал — обычный ``sendMessage`` (Telegram
    сам гасит typing при приходе сообщения), вызывающий может выставить флаг в
    ``False`` и не платить за ожидание.
    """
    stop = threading.Event()
    lock = threading.Lock()
    send_timeout = min(max(0.5, float(interval_seconds)), 1.0)
    # Резолвим default в момент вызова, а не определения функции: позволяет
    # тестам подменять модульную константу через monkeypatch без переписывания
    # вызовов в продакшен-коде.
    display_seconds = (
        TYPING_DISPLAY_SECONDS if typing_display_seconds is None else typing_display_seconds
    )
    # ``last_typing_at`` — monotonic-время последнего УСПЕШНО отправленного typing.
    # 0.0 означает «ни один typing ещё не доехал до Telegram»; в этом случае ждать
    # на финале нечего. Лист — простой потокобезопасный bind: запись атомарна.
    last_typing_at: list[float] = [0.0]

    def _typing_once_locked() -> None:
        # Лок нужен ровно для одного: исключить ситуацию, когда фоновый поток
        # выходит из stop.wait по тайм-ауту ровно в тот момент, когда основной
        # поток уже завершил fn и собирается посчитать, сколько ещё ждать.
        # Без лока typing ушёл бы Telegram'у уже после расчёта ожидания, и
        # индикатор всё равно пережил бы итоговое сообщение.
        with lock:
            if stop.is_set():
                return
            try:
                telegram.send_chat_action(chat_id, "typing", timeout=send_timeout)
            except Exception as error:
                logger.warning("Failed to send typing chat action: %s", error)
                return
            # Запоминаем время уже после возврата HTTP. Это даёт неявную фору:
            # фактически Telegram включил индикатор раньше, чем мы здесь
            # отметили момент, — поэтому отсчёт display-окна заведомо
            # консервативнее реального.
            last_typing_at[0] = time.monotonic()

    def _periodic() -> None:
        while not stop.wait(interval_seconds):
            _typing_once_locked()

    _typing_once_locked()
    worker = threading.Thread(
        target=_periodic,
        name="satellite-typing-action",
        daemon=True,
    )
    worker.start()
    try:
        return fn()
    finally:
        with lock:
            stop.set()
            last_sent = last_typing_at[0]
        join_budget = max(2.0, interval_seconds + 1.0)
        worker.join(timeout=join_budget)
        if worker.is_alive():
            logger.warning(
                "Typing worker thread did not finish within %.1fs after stop",
                join_budget,
            )
        if wait_for_typing_to_clear and last_sent > 0.0:
            remaining = display_seconds - (time.monotonic() - last_sent)
            if remaining > 0:
                time.sleep(remaining)
