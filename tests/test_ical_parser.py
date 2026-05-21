from satellite.calendar.ical_parser import parse_calendar_events

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
