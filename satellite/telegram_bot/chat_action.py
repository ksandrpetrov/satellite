"""Периодический ``sendChatAction`` (typing) на время долгой синхронной операции.

Проект использует синхронный ``TelegramClient`` и пул потоков, не aiogram/async.
Основная работа выполняется в текущем потоке, статус typing дублируется фоновым
потоком каждые ``interval_seconds`` секунд.

После возврата ``fn`` индикатор «печатает» может ещё несколько секунд висеть в
шапке чата (Telegram держит typing до ~5 с после последнего ``sendChatAction``),
но это деталь UI клиента — мы НЕ ждём её истечения, чтобы не задерживать выдачу
результата пользователю. Любое ``sendMessage`` гасит typing моментально; для
``editMessageText`` индикатор просто доживёт свой остаток после прихода итога.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TypeVar

from .api import TelegramClient

T = TypeVar("T")

logger = logging.getLogger(__name__)


def run_with_typing_action(
    telegram: TelegramClient,
    chat_id: int,
    fn: Callable[[], T],
    *,
    interval_seconds: float = 4.0,
) -> T:
    """Сразу шлёт typing, периодически обновляет его, выполняет ``fn``.

    Ошибки ``sendChatAction`` только логируются (warning), основная функция не
    прерывается. Исключения из ``fn`` пробрасываются; фоновый поток останавливается.

    ``sendChatAction`` — best-effort: короткий таймаут важнее ретраев, потому что
    медленный typing-индикатор не должен задерживать итоговое сообщение. По той же
    причине после ``fn`` мы не «досыпаем» остаток жизни typing — результат
    отдаётся вызывающему сразу, как только готов.
    """
    stop = threading.Event()
    lock = threading.Lock()
    send_timeout = min(max(0.5, float(interval_seconds)), 1.0)

    def _typing_once_locked() -> None:
        # Лок нужен ровно для одного: исключить ситуацию, когда фоновый поток
        # выходит из stop.wait по тайм-ауту ровно в тот момент, когда основной
        # поток уже выставил stop.set(). Без лока typing мог бы уйти Telegram'у
        # уже после возврата fn — и индикатор пережил бы итоговое сообщение
        # дольше, чем естественные ~5 с после последнего typing.
        with lock:
            if stop.is_set():
                return
            try:
                telegram.send_chat_action(chat_id, "typing", timeout=send_timeout)
            except Exception as error:
                logger.warning("Failed to send typing chat action: %s", error)

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
        join_budget = max(2.0, interval_seconds + 1.0)
        worker.join(timeout=join_budget)
        if worker.is_alive():
            logger.warning(
                "Typing worker thread did not finish within %.1fs after stop",
                join_budget,
            )
