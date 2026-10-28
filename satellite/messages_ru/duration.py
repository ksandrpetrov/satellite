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


def format_meeting_count_ru(count: int) -> str:
    value = max(0, int(count))
    if 11 <= value % 100 <= 19:
        word = "встреч"
    elif value % 10 == 1:
        word = "встреча"
    elif 2 <= value % 10 <= 4:
        word = "встречи"
    else:
        word = "встреч"
    return f"{value} {word}"
