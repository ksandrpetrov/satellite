"""Утилиты для работы со временем и интервалами в минутах от полуночи.

Чистые функции без зависимостей. Используются для расчёта статистики дня
без обращения к LLM: мерж пересекающихся интервалов, клиппинг к окнам,
парсинг HH:MM.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

Interval = tuple[int, int]
"""Полуоткрытый интервал [start, end) в минутах от полуночи."""

_MIN_PER_DAY = 24 * 60


def parse_hhmm(value: str) -> int:
    """Парсит время в минуты от полуночи.

    Принимает те же формы, что и ``normalize_hhmm_input`` (``9:30``, ``09 30``).
    Бросает ValueError, если формат не подходит или значения за диапазоном.
    """
    if not isinstance(value, str):
        raise ValueError(f"Expected HH:MM string, got {value!r}")
    normalized = normalize_hhmm_input(value)
    if normalized is None:
        raise ValueError(f"Expected HH:MM, got {value!r}")
    hour, minute = (int(part) for part in normalized.split(":"))
    return hour * 60 + minute


_HHMM_INPUT_PATTERN = r"^(?P<h>\d{1,2})(?::| +)(?P<m>\d{2})$"


def normalize_hhmm_input(value: str | None) -> str | None:
    """Нормализует пользовательский ввод времени к "HH:MM" или возвращает None.

    Разделитель — двоеточие или один и более пробелов: "9:00", "09:00",
    "8:30", "18 25", "17 30", "23:59", "00:00". Минута — всегда ровно две
    цифры. Любые «человеческие» формы вроде "утром", "9 утра", "900",
    "09-00", "25:00", "12:99" считаются невалидными.

    Возврат None означает «не получилось распарсить»; пользователю об этом
    отвечает вызывающий хендлер. Так держим валидацию отделимой от UI.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    match = re.fullmatch(_HHMM_INPUT_PATTERN, candidate)
    if match is None:
        return None
    try:
        hour = int(match.group("h"))
        minute = int(match.group("m"))
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def format_hhmm(minutes: int) -> str:
    """Форматирует минуты от полуночи в "HH:MM". Отрицательные клиппит в 0."""
    minutes = max(0, int(minutes))
    hours = (minutes // 60) % 24
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Объединяет пересекающиеся и смежные интервалы.

    Касающиеся интервалы (end == start следующего) тоже объединяются —
    это удобно для "склейки" встреч подряд при расчёте занятого времени.
    Пустые/инвертированные (end <= start) интервалы отбрасываются.
    """
    cleaned: list[Interval] = [(s, e) for s, e in intervals if e > s]
    cleaned.sort()
    merged: list[Interval] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def clip_interval(interval: Interval, lo: int, hi: int) -> Interval | None:
    """Пересечение интервала с окном [lo, hi). None если пересечения нет."""
    start, end = interval
    s = max(start, lo)
    e = min(end, hi)
    if e <= s:
        return None
    return (s, e)


def sum_minutes(intervals: Sequence[Interval]) -> int:
    """Сумма длительностей интервалов (без дедупликации — мерджи заранее)."""
    return sum(end - start for start, end in intervals)


def count_overlap_pairs(intervals: Sequence[Interval]) -> int:
    """Количество пар (i, j) с i<j, у которых интервалы пересекаются.

    Касание (end == start) пересечением не считается — полуоткрытые интервалы.
    """
    n = len(intervals)
    pairs = 0
    for i in range(n):
        ai_s, ai_e = intervals[i]
        for j in range(i + 1, n):
            aj_s, aj_e = intervals[j]
            if ai_s < aj_e and aj_s < ai_e:
                pairs += 1
    return pairs


def free_slots_within(
    merged: Sequence[Interval], window_start: int, window_end: int
) -> list[Interval]:
    """Свободные окна внутри [window_start, window_end), не покрытые `merged`.

    `merged` ожидается уже отсортированным и без пересечений.
    """
    slots: list[Interval] = []
    cursor = window_start
    for start, end in merged:
        if start > cursor:
            slots.append((cursor, min(start, window_end)))
        cursor = max(cursor, end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        slots.append((cursor, window_end))
    return [s for s in slots if s[1] > s[0]]
