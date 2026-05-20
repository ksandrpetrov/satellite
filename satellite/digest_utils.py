"""Общие чистые хелперы для доменной логики дайджеста.

Используются и Telegram-хендлерами, и фоновым ``DigestScheduler``. Единое место
исключает дрифт между двумя реализациями одной и той же операции (целевая
дата по режиму, проверка дня недели).
"""

from __future__ import annotations

from datetime import date, timedelta

from .subscriptions import DIGEST_DAYS_ALL, DIGEST_DAYS_WEEKDAYS

DIGEST_MODE_TODAY = "today"
DIGEST_MODE_TOMORROW = "tomorrow"
DIGEST_MODE_DAY_AFTER = "day_after_tomorrow"


def resolve_target_date(mode: str, today: date) -> date:
    """День, на который строится дайджест, по глобальному режиму.

    Неизвестный режим трактуем как ``tomorrow`` — историческое поведение
    scheduler. Сохраняем, чтобы опечатка в env не меняла поведение бота.
    """
    if mode == DIGEST_MODE_TODAY:
        return today
    if mode == DIGEST_MODE_DAY_AFTER:
        return today + timedelta(days=2)
    return today + timedelta(days=1)


def is_digest_day_allowed(digest_days: str, weekday: int) -> bool:
    """Разрешён ли запуск дайджеста сегодня (``weekday``: 0=Пн … 6=Вс).

    Неизвестное значение трактуем как «нет»: лучше пропустить день, чем
    спамить пользователя, если в JSON оказался мусор.
    """
    if digest_days == DIGEST_DAYS_ALL:
        return True
    if digest_days == DIGEST_DAYS_WEEKDAYS:
        return 0 <= weekday <= 4
    return False
