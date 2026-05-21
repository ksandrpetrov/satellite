from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


@pytest.fixture(autouse=True)
def _reset_action_guards():
    """Сбрасывает module-level ``ActionGuard``-синглтоны между тестами.

    Назначение: guard-ы (analytics/plan/upcoming/invitations/manage/partstat)
    держат cooldown per ``(chat_id, action)``. Без сброса cooldown с прошлого
    теста ловит повторный вызов команды (``/td`` и т.п.) в текущем тесте, и
    тот видит 0 ``send`` вместо ожидаемого 1 (с логом
    ``Plan run skipped (duplicate within cooldown)``).

    Импорты внутри фикстуры — чтобы collect-time не падал, если кто-то
    переименует/удалит соответствующие модули.
    """
    from satellite.telegram_bot.handlers import analytics as _analytics
    from satellite.telegram_bot.handlers import calendar_invitations as _invitations
    from satellite.telegram_bot.handlers import calendar_list as _upcoming
    from satellite.telegram_bot.handlers import calendar_manage as _manage
    from satellite.telegram_bot.handlers import partstat_flow as _partstat
    from satellite.telegram_bot.handlers import plan as _plan

    for guard in (
        _analytics._analytics_run_guard,
        _plan._plan_run_guard,
        _upcoming._upcoming_guard,
        _invitations._invitations_open_guard,
        _manage._manage_open_guard,
        _partstat._partstat_respond_guard,
    ):
        guard.reset()
    yield
