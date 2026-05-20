from __future__ import annotations

import sys
from pathlib import Path

from satellite.calendar.stats import NormalizedEvent
from satellite.calendar.time_utils import parse_hhmm

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def make_event(
    title: str,
    start: str,
    end: str,
    *,
    location: str | None = None,
    is_cancelled: bool = False,
    is_pending: bool = False,
    is_tentative: bool = False,
) -> NormalizedEvent:
    """Удобный конструктор NormalizedEvent из ``HH:MM`` для тестов.

    Production-путь строит NormalizedEvent через ``normalize_caldav_event``;
    в юнит-тестах метрик мы пропускаем CalDAV-словарь и сразу собираем
    нормализованное событие — это устраняет второй путь нормализации.
    """
    return NormalizedEvent(
        title=title,
        start_minutes=parse_hhmm(start),
        end_minutes=parse_hhmm(end),
        location=location,
        is_cancelled=is_cancelled,
        is_pending=is_pending,
        is_tentative=is_tentative,
    )
