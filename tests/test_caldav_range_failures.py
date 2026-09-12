"""Range REPORT boundaries: selection, partial failure and real ICS parsing."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from satellite.calendar.caldav_client import CalDAVError, CalDAVService, CalendarHandle
from satellite.calendar.caldav_shared import _DiscoveryResult

DAY = date(2026, 9, 12)


def event(uid: str, hour: int):
    data = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        f"UID:{uid}\r\nSUMMARY:{uid}\r\n"
        f"DTSTART:20260912T{hour:02d}0000Z\r\nDTEND:20260912T{hour + 1:02d}0000Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    return SimpleNamespace(data=data, url=f"https://cal/{uid}.ics")


@pytest.fixture
def calendar_service(monkeypatch):
    service = CalDAVService(
        caldav_url="https://cal/", login="test@example.com", app_password="test"
    )
    handles = [CalendarHandle(name, Mock(), f"https://cal/{name}/") for name in ("one", "two")]
    discovery = Mock(return_value=_DiscoveryResult("https://cal/", handles, 0, "test@example.com"))
    monkeypatch.setattr(service, "_ensure_discovery", discovery)
    try:
        yield service, handles, discovery
    finally:
        service.close()


def test_range_uses_only_selected_calendar_and_inclusive_date_bounds(calendar_service):
    service, handles, _ = calendar_service
    handles[1].obj.search.return_value = [event("late", 15), event("early", 9)]
    events = service.fetch_events_in_range(
        DAY, DAY, tz=UTC, calendar_urls=["https://cal/two"], strict=True
    )
    assert [item["uid"] for item in events] == ["early", "late"]
    assert [item["url"] for item in events] == ["https://cal/early.ics", "https://cal/late.ics"]
    handles[0].obj.search.assert_not_called()
    handles[1].obj.search.assert_called_once_with(
        start=datetime(2026, 9, 12, tzinfo=UTC),
        end=datetime(2026, 9, 13, tzinfo=UTC),
        event=True,
        expand=True,
    )


def test_unknown_selected_calendar_does_not_fall_back_to_other_calendars(calendar_service):
    service, handles, _ = calendar_service
    with pytest.raises(CalDAVError, match="not found"):
        service.fetch_events_in_range(DAY, DAY, tz=UTC, calendar_urls=["https://cal/missing/"])
    for handle in handles:
        handle.obj.search.assert_not_called()


def test_reversed_range_does_not_contact_discovery(calendar_service):
    service, _, discovery = calendar_service
    assert service.fetch_events_in_range(date(2026, 9, 13), DAY, tz=UTC) == []
    discovery.assert_not_called()


@pytest.mark.parametrize("strict", [False, True])
def test_one_failed_calendar_is_partial_only_in_non_strict_mode(calendar_service, strict):
    service, handles, _ = calendar_service
    handles[0].obj.search.return_value = [event("available", 9)]
    handles[1].obj.search.side_effect = RuntimeError("REPORT unavailable")
    if strict:
        with pytest.raises(CalDAVError, match="range search failed"):
            service.fetch_events_in_range(DAY, DAY, tz=UTC, strict=True)
    else:
        events = service.fetch_events_in_range(DAY, DAY, tz=UTC, strict=False)
        assert [item["uid"] for item in events] == ["available"]
    for handle in handles:
        handle.obj.search.assert_called_once()


@pytest.mark.parametrize("strict", [False, True])
def test_iterator_failure_does_not_masquerade_as_complete_result(calendar_service, strict):
    service, handles, _ = calendar_service

    def interrupted_response():
        yield event("first", 9)
        raise OSError("connection dropped while reading events")

    handles[0].obj.search.return_value = interrupted_response()
    if strict:
        with pytest.raises(CalDAVError, match="response could not be read"):
            service.fetch_events_in_range(
                DAY, DAY, tz=UTC, calendar_url=handles[0].url, strict=True
            )
    else:
        events = service.fetch_events_in_range(DAY, DAY, tz=UTC, calendar_url=handles[0].url)
        assert [item["uid"] for item in events] == ["first"]


@pytest.mark.parametrize("as_bytes", [False, True])
def test_strict_mode_rejects_unparseable_event_instead_of_empty_calendar(
    calendar_service, as_bytes
):
    service, handles, _ = calendar_service
    broken = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:broken\r\n"
    handles[0].obj.search.return_value = [
        SimpleNamespace(data=broken.encode() if as_bytes else broken)
    ]
    with pytest.raises(CalDAVError, match="could not be parsed"):
        service.fetch_events_in_range(DAY, DAY, tz=UTC, calendar_url=handles[0].url, strict=True)
