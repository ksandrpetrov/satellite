"""Парсинг iCalendar VEVENT в dict-структуру, удобную для дальнейшей обработки."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from icalendar import Calendar


class CalendarParseError(ValueError):
    """The calendar response cannot be used as a complete source of events."""


def _to_serializable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if value is not None else None


def _attendees_to_list(raw: Any) -> list[str]:
    """Сериализует ATTENDEE-поле в строки вида ``mailto:user@host;PARTSTAT=...``.

    iCalendar отдаёт ATTENDEE как ``vCalAddress``, у которого ``str(...)``
    возвращает ТОЛЬКО mailto без параметров — PARTSTAT/CN живут в ``.params``.
    Если их не приклеить обратно, downstream-проверки (``is_declined_…`` /
    ``is_pending_…``) не находят PARTSTAT в строке и считают все встречи
    принятыми. Поэтому здесь явно ресериализуем "value;KEY=VALUE;…".
    """
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [_attendee_to_str(item) for item in items]


def _attendee_to_str(item: Any) -> str:
    value = str(item)
    params = getattr(item, "params", None)
    if not params:
        return value
    try:
        pairs = [f"{key}={params[key]}" for key in params]
    except Exception:  # noqa: BLE001 - редкие реализации params без iter
        return value
    if not pairs:
        return value
    return value + ";" + ";".join(pairs)


def _categories_to_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        return [str(item) for item in raw]
    except TypeError:
        return [str(raw)]


def _rrule_to_dict(rrule: Any) -> dict[str, list[str]] | None:
    if not rrule:
        return None
    return {key: [str(item) for item in values] for key, values in rrule.items()}


def parse_event(component: Any, calendar_name: str) -> dict[str, Any]:
    dtstart = component.get("DTSTART")
    dtend = component.get("DTEND")
    if dtend is None and dtstart is not None:
        duration = component.get("DURATION")
        try:
            duration_value = duration.dt if duration is not None else None
            if isinstance(duration_value, timedelta):
                dtend_value = dtstart.dt + duration_value
            else:
                dtend_value = None
        except (AttributeError, TypeError, ValueError):
            dtend_value = None
    else:
        dtend_value = dtend.dt if dtend else None
    recurrence_id = component.get("RECURRENCE-ID")
    created = component.get("CREATED")
    last_modified = component.get("LAST-MODIFIED")

    return {
        "calendar": calendar_name,
        "uid": _to_serializable(component.get("UID")),
        "summary": _to_serializable(component.get("SUMMARY")),
        "description": _to_serializable(component.get("DESCRIPTION")),
        "location": _to_serializable(component.get("LOCATION")),
        "status": _to_serializable(component.get("STATUS")),
        "url": _to_serializable(component.get("URL")),
        "organizer": _to_serializable(component.get("ORGANIZER")),
        "attendees": _attendees_to_list(component.get("ATTENDEE")),
        "categories": _categories_to_list(component.get("CATEGORIES")),
        "dtstart": _to_serializable(dtstart.dt if dtstart else None),
        "dtend": _to_serializable(dtend_value),
        "recurrence_id": _to_serializable(recurrence_id.dt if recurrence_id else None),
        "created": _to_serializable(created.dt if created else None),
        "last_modified": _to_serializable(last_modified.dt if last_modified else None),
        "rrule": _rrule_to_dict(component.get("RRULE")),
        "raw_keys": sorted(str(key) for key in component.keys()),
    }


def parse_calendar_events(
    ics_text: str | bytes, calendar_name: str, *, strict: bool = False
) -> list[dict[str, Any]]:
    """Парсит ICS-блок и возвращает список словарей по каждому VEVENT.

    По умолчанию сохраняет доступные события. Для пользовательских отчётов
    strict=True запрещает выдавать частичный результат при повреждённом ICS.
    """
    try:
        if isinstance(ics_text, bytes):
            ics_text = ics_text.decode("utf-8", errors="strict" if strict else "replace")
        calendar = Calendar.from_ical(ics_text)
        if strict and calendar.name != "VCALENDAR":
            raise CalendarParseError("Expected VCALENDAR")
        components = calendar.walk()
    except Exception as exc:  # noqa: BLE001 - icalendar бросает разное на битых данных
        if strict:
            raise CalendarParseError("Invalid calendar response") from exc
        return []

    events: list[dict[str, Any]] = []
    for component in components:
        if component.name == "VEVENT":
            try:
                if strict:
                    _validate_component(component)
                events.append(parse_event(component, calendar_name))
            except Exception as exc:  # noqa: BLE001 - non-strict callers allow partial data
                if strict:
                    raise CalendarParseError("Invalid calendar event") from exc
                continue
    return events


def parse_calendar_events_in_range(
    ics_text: str | bytes,
    calendar_name: str,
    *,
    range_start: datetime,
    range_end: datetime,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Expand a recurrence set locally when the CalDAV server cannot do it."""
    from recurring_ical_events import of

    try:
        if isinstance(ics_text, bytes):
            ics_text = ics_text.decode("utf-8", errors="strict" if strict else "replace")
        calendar = Calendar.from_ical(ics_text)
        if strict:
            if calendar.name != "VCALENDAR":
                raise CalendarParseError("Expected VCALENDAR")
            for component in calendar.walk("VEVENT"):
                _validate_component(component)
        components = of(calendar, skip_bad_series=False).between(range_start, range_end)
    except Exception as exc:  # noqa: BLE001 - strictness is decided by the range caller
        if strict:
            raise CalendarParseError("Invalid calendar recurrence") from exc
        return []
    events: list[dict[str, Any]] = []
    for component in components:
        try:
            events.append(parse_event(component, calendar_name))
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise CalendarParseError("Invalid calendar occurrence") from exc
            continue
    return events


def _validate_component(component: Any) -> None:
    """icalendar may retain invalid properties as errors instead of raising."""
    if component.errors:
        raise CalendarParseError("Invalid event properties")
    start = component.get("DTSTART")
    if start is None or not isinstance(start.dt, date):
        raise CalendarParseError("Missing event start")
    end = component.get("DTEND")
    duration = component.get("DURATION")
    if end is not None:
        if duration is not None or type(start.dt) is not type(end.dt):
            raise CalendarParseError("Inconsistent event interval")
        if end.dt <= start.dt:
            raise CalendarParseError("Event end must be after its start")
    if duration is not None:
        if not isinstance(duration.dt, timedelta) or duration.dt <= timedelta(0):
            raise CalendarParseError("Event duration must be positive")
        if not isinstance(start.dt, datetime) and duration.dt.seconds:
            raise CalendarParseError("All-day duration must use whole days")
    # Parsing the original components also catches malformed exceptions before
    # recurrence expansion can silently drop them.
    parse_event(component, "")
