"""Форматирование длительности на русском (домен, без UI-текстов)."""

from __future__ import annotations


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по правилам gettext nplurals=3."""
    n = abs(int(n))
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def format_duration_long_ru(minutes: int) -> str:
    """Длинная форма длительности со склонением: «1 час», «2 часа 30 минут»."""
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
