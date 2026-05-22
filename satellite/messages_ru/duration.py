"""User-facing strings — форматирование длительности на русском."""

from __future__ import annotations

from .plan_strings import DURATION_HOURS_AND_MINS, DURATION_HOURS_ONLY, DURATION_MINS_ONLY


def format_duration_ru(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours = minutes // 60
    mins = minutes % 60
    if hours and mins:
        return DURATION_HOURS_AND_MINS.format(hours=hours, mins=mins)
    if hours:
        return DURATION_HOURS_ONLY.format(hours=hours)
    return DURATION_MINS_ONLY.format(mins=mins)


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по правилам gettext nplurals=3.

    one  — для 1, 21, 31, ... (mod 10 == 1 и mod 100 != 11);
    few  — для 2-4, 22-24, ... (mod 10 in 2..4 и mod 100 not in 12..14);
    many — для 0, 5-20, 25-30, ...
    """
    n = abs(int(n))
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def format_duration_long_ru(minutes: int) -> str:
    """Длинная форма длительности со склонением: «1 час», «2 часа 30 минут».

    Используется в заголовках групп `/upcoming` — там короткая форма «1 ч»
    выглядит куцо в круглых скобках.
    """
    minutes = max(0, int(minutes))
    hours = minutes // 60
    mins = minutes % 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}")
    if mins:
        parts.append(f"{mins} {_plural_ru(mins, 'минута', 'минуты', 'минут')}")
    if not parts:
        return "0 минут"
    return " ".join(parts)
