from datetime import UTC, datetime

import pytest

from satellite.calendar.ical_parser import (
    CalendarParseError,
    parse_calendar_events,
    parse_calendar_events_in_range,
)

_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:1@test\r\n"
    "SUMMARY:Дейли\r\n"
    "DTSTART:20260511T070000Z\r\n"
    "DTEND:20260511T073000Z\r\n"
    "LOCATION:Room A\r\n"
    "ATTENDEE;PARTSTAT=DECLINED:mailto:me@mail.ru\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_parse_calendar_events_basic():
    events = parse_calendar_events(_ICS, "Test Cal")
    assert len(events) == 1
    ev = events[0]
    assert ev["calendar"] == "Test Cal"
    assert ev["summary"] == "Дейли"
    assert ev["location"] == "Room A"
    assert len(ev["attendees"]) == 1
    attendee = ev["attendees"][0]
    assert attendee.startswith("mailto:me@mail.ru")
    assert "PARTSTAT=DECLINED" in attendee
    assert ev["dtstart"].startswith("2026-05-11T07:00")
    assert ev["dtend"].startswith("2026-05-11T07:30")


def test_parse_calendar_events_preserves_partstat_for_pending_attendee():
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:2@test\r\n"
        "SUMMARY:Pending\r\n"
        "DTSTART:20260511T080000Z\r\n"
        "DTEND:20260511T083000Z\r\n"
        "ATTENDEE;PARTSTAT=NEEDS-ACTION;CN=Me:mailto:me@mail.ru\r\n"
        "ATTENDEE;PARTSTAT=ACCEPTED;CN=Other:mailto:other@mail.ru\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = parse_calendar_events(ics, "Test Cal")
    assert len(events) == 1
    attendees = events[0]["attendees"]
    assert any("mailto:me@mail.ru" in a and "PARTSTAT=NEEDS-ACTION" in a for a in attendees)
    assert any("mailto:other@mail.ru" in a and "PARTSTAT=ACCEPTED" in a for a in attendees)


def test_parse_calendar_events_garbage_input_returns_empty():
    assert parse_calendar_events("not an ical at all", "Test") == []


def test_parse_calendar_events_bytes_input():
    events = parse_calendar_events(_ICS.encode("utf-8"), "Test Cal")
    assert len(events) == 1


def test_parse_event_supports_duration_without_dtend():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:duration@test\r\nSUMMARY:Duration\r\n"
        "DTSTART:20260511T070000Z\r\nDURATION:PT45M\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    event = parse_calendar_events(ics, "Test")[0]

    assert event["dtstart"].startswith("2026-05-11T07:00")
    assert event["dtend"].startswith("2026-05-11T07:45")


def test_local_recurrence_expansion_keeps_occurrences_in_requested_range():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:weekly@test\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260504T070000Z\r\nDTEND:20260504T080000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=4\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    events = parse_calendar_events_in_range(
        ics,
        "Test",
        range_start=datetime(2026, 5, 11, tzinfo=UTC),
        range_end=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert len(events) == 1
    assert events[0]["dtstart"].startswith("2026-05-11T07:00")


def test_recurrence_exdates_rdates_and_moved_exception():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:series@test\r\nSUMMARY:Series\r\n"
        "DTSTART:20260511T070000Z\r\nDTEND:20260511T080000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20260512T070000Z\r\n"
        "RDATE:20260520T070000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:series@test\r\nSUMMARY:Moved\r\n"
        "RECURRENCE-ID:20260513T070000Z\r\n"
        "DTSTART:20260515T120000Z\r\nDTEND:20260515T130000Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    events = parse_calendar_events_in_range(
        ics,
        "Test",
        strict=True,
        range_start=datetime(2026, 5, 11, tzinfo=UTC),
        range_end=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert sorted(event["dtstart"] for event in events) == [
        "2026-05-11T07:00:00+00:00",
        "2026-05-14T07:00:00+00:00",
        "2026-05-15T12:00:00+00:00",
        "2026-05-20T07:00:00+00:00",
    ]
    assert next(event for event in events if event["summary"] == "Moved")["recurrence_id"] == (
        "2026-05-13T07:00:00+00:00"
    )


def test_recurrence_preserves_local_wall_clock_across_dst():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:dst@test\r\nSUMMARY:Weekly\r\n"
        "DTSTART;TZID=Europe/Berlin:20260322T100000\r\n"
        "DTEND;TZID=Europe/Berlin:20260322T110000\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    events = parse_calendar_events_in_range(
        ics,
        "Test",
        strict=True,
        range_start=datetime(2026, 3, 22, tzinfo=UTC),
        range_end=datetime(2026, 3, 30, tzinfo=UTC),
    )
    assert sorted(event["dtstart"] for event in events) == [
        "2026-03-22T10:00:00+01:00",
        "2026-03-29T10:00:00+02:00",
    ]


@pytest.mark.parametrize(
    "properties",
    [
        "DTSTART:20260511T100000Z\r\nDTEND:20260511T090000Z\r\n",
        "DTSTART:20260511T100000Z\r\nDURATION:-PT1H\r\n",
        "DTSTART;VALUE=DATE:20260511\r\nDTEND:20260512T090000Z\r\n",
    ],
)
def test_strict_parser_rejects_invalid_event_intervals(properties):
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:broken\r\n"
        + properties
        + "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    with pytest.raises(CalendarParseError):
        parse_calendar_events(ics, "Test", strict=True)


def test_strict_parser_does_not_replace_corrupted_utf8_with_plausible_title():
    with pytest.raises(CalendarParseError):
        parse_calendar_events(_ICS.encode().replace("Дейли".encode(), b"\xff"), "Test", strict=True)
