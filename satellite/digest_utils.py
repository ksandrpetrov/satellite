"""Общие чистые хелперы для доменной логики дайджеста.

Используются и Telegram-хендлерами, и фоновым ``DigestScheduler``. Единое место
исключает дрифт между двумя реализациями одной и той же операции (целевая
дата по режиму, проверка дня недели).
"""

from __future__ import annotations

from datetime import date, timedelta

from .subscriptions import DIGEST_DAYS_ALL, DIGEST_DAYS_WEEKDAYS

DIGEST_DAYS_BITMASK_LEN = 7
DIGEST_DAYS_WEEKDAYS_MASK = "1111100"
DIGEST_DAYS_ALL_MASK = "1111111"
WEEKDAY_SHORT_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

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


def is_digest_days_bitmask(value: str) -> bool:
    """Маска из ровно 7 символов ``0``/``1`` (индекс 0 = понедельник)."""
    return len(value) == DIGEST_DAYS_BITMASK_LEN and all(ch in "01" for ch in value)


def digest_days_to_bitmask(digest_days: str) -> str:
    """Нормализует legacy ``weekdays``/``all_days`` и маску в 7-символьную строку."""
    if digest_days == DIGEST_DAYS_ALL:
        return DIGEST_DAYS_ALL_MASK
    if digest_days == DIGEST_DAYS_WEEKDAYS:
        return DIGEST_DAYS_WEEKDAYS_MASK
    if is_digest_days_bitmask(digest_days):
        return digest_days
    return DIGEST_DAYS_WEEKDAYS_MASK


def toggle_digest_days_bitmask(mask: str, weekday: int) -> str | None:
    """Переключает день в маске. ``None``, если после снятия галочки дней не останется."""
    if not (0 <= weekday < DIGEST_DAYS_BITMASK_LEN):
        return None
    bits = list(digest_days_to_bitmask(mask))
    bits[weekday] = "0" if bits[weekday] == "1" else "1"
    if "1" not in bits:
        return None
    return "".join(bits)


def format_digest_days_label(digest_days: str) -> str:
    """Человекочитаемая подпись для экрана настроек."""
    if digest_days == DIGEST_DAYS_ALL:
        return "все дни"
    if digest_days == DIGEST_DAYS_WEEKDAYS:
        return "будни"
    mask = digest_days_to_bitmask(digest_days)
    selected = [WEEKDAY_SHORT_RU[i] for i in range(DIGEST_DAYS_BITMASK_LEN) if mask[i] == "1"]
    if len(selected) == DIGEST_DAYS_BITMASK_LEN:
        return "все дни"
    if mask == DIGEST_DAYS_WEEKDAYS_MASK:
        return "будни"
    return ", ".join(selected)


def is_digest_day_allowed(digest_days: str, weekday: int) -> bool:
    """Разрешён ли запуск дайджеста сегодня (``weekday``: 0=Пн … 6=Вс).

    Неизвестное значение трактуем как «нет»: лучше пропустить день, чем
    спамить пользователя, если в JSON оказался мусор.
    """
    if digest_days == DIGEST_DAYS_ALL:
        return True
    if digest_days == DIGEST_DAYS_WEEKDAYS:
        return 0 <= weekday <= 4
    if is_digest_days_bitmask(digest_days) and 0 <= weekday < DIGEST_DAYS_BITMASK_LEN:
        return digest_days[weekday] == "1"
    return False
