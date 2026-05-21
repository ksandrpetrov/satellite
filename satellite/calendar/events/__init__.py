"""Чистые функции над словарём события: парсинг времени, фильтры, сортировка.

Пакет разбит по ответственности:

- :mod:`._types` — типовые алиасы (``Event``, ``PizzaMealKind``) и константы.
- :mod:`._time` — парсинг dtstart/dtend и базовые операции с диапазонами.
- :mod:`._partstat` — работа с ATTENDEE/PARTSTAT (declined, pending, ranking).
- :mod:`._filters` — предикаты «отбраковки» события (cancelled, all-day, lunch).
- :mod:`._collectors` — прикладные сборщики списков (/upcoming, приглашения,
  фильтрация дня).

Этот ``__init__`` — фасад: все потребители (handlers, scheduler, plan, тесты)
импортируют публичный API одинаково — ``from satellite.calendar.events import …``.
Внутренняя раскладка может меняться без правок снаружи.
"""

from ._collectors import (
    build_upcoming_events_groups,
    collect_manageable_events,
    collect_pending_invitations,
    event_relevant_for_invitations,
    filter_events_for_user,
    format_invitation_list_lines,
    format_single_day_events_lines,
    format_upcoming_day_header,
    format_upcoming_events_lines,
)
from ._filters import (
    event_index_marker,
    is_all_day_event,
    is_cancelled_event,
    is_lunch_event,
    pizza_meal_kind,
)
from ._partstat import (
    is_declined_event_for_user,
    is_pending_invitation_for_user,
    user_partstat,
)
from ._time import (
    day_bounds,
    event_datetime_bounds,
    event_duration_minutes,
    event_ends_after,
    event_local_start_date,
    event_occurs_on,
    format_time_range,
    parse_iso,
    sort_key,
)
from ._types import NUMBER_EMOJI, Event, PizzaMealKind

__all__ = [
    "Event",
    "NUMBER_EMOJI",
    "PizzaMealKind",
    "build_upcoming_events_groups",
    "collect_manageable_events",
    "collect_pending_invitations",
    "day_bounds",
    "event_datetime_bounds",
    "event_duration_minutes",
    "event_ends_after",
    "event_index_marker",
    "event_local_start_date",
    "event_occurs_on",
    "event_relevant_for_invitations",
    "filter_events_for_user",
    "format_invitation_list_lines",
    "format_single_day_events_lines",
    "format_time_range",
    "format_upcoming_day_header",
    "format_upcoming_events_lines",
    "is_all_day_event",
    "is_cancelled_event",
    "is_declined_event_for_user",
    "is_lunch_event",
    "is_pending_invitation_for_user",
    "parse_iso",
    "pizza_meal_kind",
    "sort_key",
    "user_partstat",
]
