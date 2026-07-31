"""Парсинг iCalendar VEVENT в dict-структуру, удобную для дальнейшей обработки."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from icalendar import Calendar


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
        "created": _to_serializable(created.dt if created else None),
        "last_modified": _to_serializable(last_modified.dt if last_modified else None),
        "rrule": _rrule_to_dict(component.get("RRULE")),
        "raw_keys": sorted(str(key) for key in component.keys()),
    }


def parse_calendar_events(ics_text: str | bytes, calendar_name: str) -> list[dict[str, Any]]:
    """Парсит ICS-блок и возвращает список словарей по каждому VEVENT.

    На некорректных ICS возвращает пустой список (вместо падения), чтобы один
    битый ивент не валил отправку плана целиком.
    """
    if isinstance(ics_text, bytes):
        ics_text = ics_text.decode("utf-8", errors="replace")
    try:
        calendar = Calendar.from_ical(ics_text)
    except Exception:  # noqa: BLE001 - icalendar бросает разное на битых данных
        return []

    events: list[dict[str, Any]] = []
    for component in _walk_components(calendar):
        if component.name == "VEVENT":
            try:
                events.append(parse_event(component, calendar_name))
            except Exception:  # noqa: BLE001 - один битый VEVENT не должен валить всё
                continue
    return events


def parse_calendar_events_in_range(
    ics_text: str | bytes,
    calendar_name: str,
    *,
    range_start: datetime,
    range_end: datetime,
) -> list[dict[str, Any]]:
    """Expand a recurrence set locally when the CalDAV server cannot do it."""
    from recurring_ical_events import of

    if isinstance(ics_text, bytes):
        ics_text = ics_text.decode("utf-8", errors="replace")
    try:
        calendar = Calendar.from_ical(ics_text)
        components = of(calendar, skip_bad_series=False).between(range_start, range_end)
    except Exception:  # noqa: BLE001 - strictness is decided by the range caller
        return []
    events: list[dict[str, Any]] = []
    for component in components:
        try:
            events.append(parse_event(component, calendar_name))
        except Exception:  # noqa: BLE001
            continue
    return events


def _walk_components(calendar: Any) -> Iterable[Any]:
    try:
        yield from calendar.walk()
    except Exception:  # noqa: BLE001
        return
