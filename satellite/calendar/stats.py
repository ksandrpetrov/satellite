"""Расчёт статистики дня для аналитики «чайки» (без LLM).

Чистые функции: получают список событий и параметры рабочего дня,
возвращают набор метрик. Не знают ничего про тексты и Telegram.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from .time_utils import (
    Interval,
    clip_interval,
    count_overlap_pairs,
    format_hhmm,
    merge_intervals,
    parse_hhmm,
    sum_minutes,
)

DEFAULT_WORKDAY_START = "10:00"
DEFAULT_WORKDAY_END = "19:00"
DEFAULT_LUNCH_START = "13:00"
DEFAULT_LUNCH_END = "14:00"


@dataclass(frozen=True)
class WorkdayOptions:
    """Окна рабочего дня и обеда в формате "HH:MM" (локальное время)."""

    workday_start: str = DEFAULT_WORKDAY_START
    workday_end: str = DEFAULT_WORKDAY_END
    lunch_start: str = DEFAULT_LUNCH_START
    lunch_end: str = DEFAULT_LUNCH_END

    def to_minutes(self) -> _WorkdayMinutes:
        ws = parse_hhmm(self.workday_start)
        we = parse_hhmm(self.workday_end)
        ls = parse_hhmm(self.lunch_start)
        le = parse_hhmm(self.lunch_end)
        if we <= ws:
            raise ValueError("Workday end must be after start")
        if le < ls:
            raise ValueError("Lunch end must be >= lunch start")
        return _WorkdayMinutes(ws, we, ls, le)


@dataclass(frozen=True)
class _WorkdayMinutes:
    workday_start: int
    workday_end: int
    lunch_start: int
    lunch_end: int

    @property
    def workday_total(self) -> int:
        return self.workday_end - self.workday_start

    @property
    def lunch_total(self) -> int:
        return self.lunch_end - self.lunch_start

    @property
    def effective_minutes(self) -> int:
        """Минуты рабочего дня вне обеда — база для расчёта свободного времени."""
        return max(0, self.workday_total - self.lunch_total)


@dataclass(frozen=True)
class NormalizedEvent:
    """Событие, приведённое к минутам от полуночи. Внутренний инвариант: end > start."""

    title: str
    start_minutes: int
    end_minutes: int
    location: str | None = None
    is_cancelled: bool = False
    is_pending: bool = False
    is_tentative: bool = False

    @property
    def start_hhmm(self) -> str:
        return format_hhmm(self.start_minutes)

    @property
    def end_hhmm(self) -> str:
        return format_hhmm(self.end_minutes)

    @property
    def interval(self) -> Interval:
        return (self.start_minutes, self.end_minutes)

    @property
    def duration_minutes(self) -> int:
        return max(0, self.end_minutes - self.start_minutes)


@dataclass(frozen=True)
class DayCalendarStats:
    """Метрики дня. Тексты не хранит — это задача ``seagull.rules``.

    Хранит только те поля, которые реально читаются в production-пути
    (rules → render → weather/analyzer). Метрики обеденного окна, фокус-слотов
    и back-to-back блоков были удалены вместе с соответствующими шаблонами
    «чайки» — если они когда-нибудь понадобятся снова, рассчитывать их следует
    в новой версии этой функции, а не оживлять из dead-полей.
    """

    date_label: str
    plan_date: date
    events: tuple[NormalizedEvent, ...]
    meetings_count: int
    first_meeting_start: str | None
    last_meeting_end: str | None
    busy_minutes: int
    free_minutes: int
    overlaps_count: int


# --- адаптер из CalDAV-словаря -----------------------------------------------


def _event_title(event: Mapping[str, object]) -> str:
    return str(event.get("title") or event.get("summary") or "")


def _event_location(event: Mapping[str, object]) -> str | None:
    loc = event.get("location")
    if loc is None:
        return None
    raw = str(loc).strip()
    return raw or None


def normalize_caldav_event(
    event: Mapping[str, object],
    plan_date: date,
    tz: tzinfo,
    *,
    login: str | None = None,
) -> NormalizedEvent | None:
    """Адаптер из CalDAV-словаря: учитывает зону, клипит к границам дня.

    Если событие выходит за пределы `plan_date`, оно обрезается до окна
    [00:00 plan_date, 00:00 plan_date+1). Возвращает None, если события
    нет на целевую дату или у него невалидные границы.

    Если задан `login`, проверяется attendee-список и проставляется
    `is_pending=True`, когда пользователь приглашён, но встречу не подтвердил.
    """
    from .events import event_datetime_bounds, is_cancelled_event  # late import to avoid cycle

    start_local, end_local = event_datetime_bounds(event, tz)
    if not start_local or not end_local or end_local <= start_local:
        return None

    day_start = datetime.combine(plan_date, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    if end_local <= day_start or start_local >= day_end:
        return None

    s = max(start_local, day_start)
    e = min(end_local, day_end)
    start_min = int((s - day_start).total_seconds() // 60)
    end_min = int((e - day_start).total_seconds() // 60)
    if end_min <= start_min:
        return None

    pending, tentative = _partstat_flags(event, login)
    return NormalizedEvent(
        title=_event_title(event),
        start_minutes=start_min,
        end_minutes=end_min,
        location=_event_location(event),
        is_cancelled=is_cancelled_event(event),
        is_pending=pending,
        is_tentative=tentative,
    )


def _partstat_flags(event: Mapping[str, object], login: str | None) -> tuple[bool, bool]:
    """Возвращает ``(is_pending, is_tentative)`` для пользователя в событии.

    Состояния взаимоисключающие: TENTATIVE → tentative, NEEDS-ACTION/DELEGATED
    → pending, остальное → оба False (рисуется как обычное подтверждённое).
    """
    if not login:
        return False, False
    from .events import user_partstat  # late import to avoid cycle

    status = user_partstat(event, login)
    if status == "TENTATIVE":
        return False, True
    if status in {"NEEDS-ACTION", "DELEGATED"}:
        return True, False
    return False, False


# --- основной расчёт --------------------------------------------------------


def calculate_day_stats(
    events: Sequence[NormalizedEvent],
    *,
    date_label: str,
    plan_date: date,
    options: WorkdayOptions | None = None,
) -> DayCalendarStats:
    """Считает метрики дня. Отменённые встречи отбрасываются.

    Принимает только уже нормализованные события (``NormalizedEvent``). Для
    CalDAV-словарей используется ``normalize_caldav_event`` или фасад
    ``seagull.digest.prepare_seagull_stats`` — один путь, без скрытых форматов.
    """
    opts = options or WorkdayOptions()
    win = opts.to_minutes()

    normalized = [ev for ev in events if not ev.is_cancelled and ev.end_minutes > ev.start_minutes]
    normalized.sort(key=lambda e: (e.start_minutes, e.end_minutes))

    raw_intervals: list[Interval] = [e.interval for e in normalized]

    # Занятое время: мерджим интервалы, клипим к рабочему дню.
    clipped_workday = [
        c
        for c in (clip_interval(iv, win.workday_start, win.workday_end) for iv in raw_intervals)
        if c
    ]
    merged_workday = merge_intervals(clipped_workday)
    busy_minutes = sum_minutes(merged_workday)

    # Свободное время: эффективный день минус занятое (lunch вычитается из дня).
    free_minutes = max(0, win.effective_minutes - busy_minutes)

    # Пересечения считаем по оригинальным интервалам, не клиппированным.
    overlaps_count = count_overlap_pairs(raw_intervals)

    first_start = normalized[0].start_hhmm if normalized else None
    last_end = format_hhmm(max(e.end_minutes for e in normalized)) if normalized else None

    return DayCalendarStats(
        date_label=date_label,
        plan_date=plan_date,
        events=tuple(normalized),
        meetings_count=len(normalized),
        first_meeting_start=first_start,
        last_meeting_end=last_end,
        busy_minutes=busy_minutes,
        free_minutes=free_minutes,
        overlaps_count=overlaps_count,
    )
