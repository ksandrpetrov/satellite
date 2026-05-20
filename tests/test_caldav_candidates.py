from datetime import date
from zoneinfo import ZoneInfo

from satellite.calendar.caldav_client import (
    build_candidate_urls,
    calendar_matches,
    login_variants_for_caldav,
)
from satellite.calendar.caldav_client import CalendarHandle, CalDAVService


def test_login_variants_for_caldav_includes_local_part():
    assert login_variants_for_caldav("alex@vk.team") == [
        "alex@vk.team",
        "alex",
    ]
    assert login_variants_for_caldav("user@mail.ru") == ["user@mail.ru", "user"]


def test_build_candidate_urls_includes_principal_and_calendars_paths():
    candidates = build_candidate_urls("https://calendar.mail.ru/", "alex@mail.ru")
    assert "https://calendar.mail.ru" in candidates
    assert any(c.endswith("/principals/mail.ru/alex") for c in candidates)
    assert any(c.endswith("/calendars/mail.ru/alex") for c in candidates)


def test_build_candidate_urls_handles_url_with_subpath():
    candidates = build_candidate_urls(
        "https://calendar.mail.ru/principals/vk.team/alex/", "alex@vk.team"
    )
    # Seed остаётся в начале списка
    assert candidates[0] == "https://calendar.mail.ru/principals/vk.team/alex"
    # Default root присутствует как fallback
    assert "https://calendar.mail.ru" in candidates


def test_build_candidate_urls_deduplicates():
    candidates = build_candidate_urls("https://calendar.mail.ru", "u@mail.ru")
    # Не должно быть дублей по rstrip("/")
    keys = [c.rstrip("/") for c in candidates]
    assert len(keys) == len(set(keys))


def test_build_candidate_urls_handles_empty_login():
    candidates = build_candidate_urls("https://calendar.mail.ru/", "")
    assert any("/principals/mail.ru/" in c for c in candidates)


def test_calendar_matches_case_insensitive_exact():
    assert calendar_matches("Александр Петров", "александр петров")
    assert calendar_matches("Александр Петров", "АЛЕКСАНДР ПЕТРОВ")
    assert not calendar_matches("Александра Качина", "Александр Петров")


def test_calendar_matches_empty_target_matches_all():
    assert calendar_matches("any", "")
    assert calendar_matches("any", None)


class _CalendarSearchStub:
    def search(self, **_kwargs):
        raise AssertionError("search should not be called when calendar does not match")


def test_search_events_logs_missing_target_calendar(caplog):
    handles = [
        CalendarHandle(name="Жуков Костя", obj=_CalendarSearchStub(), url="https://fake/")
    ]
    service = CalDAVService(
        caldav_url="https://fake/",
        login="x@y",
        app_password="z",
        cache_ttl_sec=0,
    )

    events = service._search_events(
        handles,
        date(2026, 5, 12),
        ZoneInfo("Europe/Moscow"),
        "Константин Жуков",
    )

    assert events == []
    assert "CalDAV target calendar not matched" in caplog.text
    assert "Жуков Костя" not in caplog.text


_ICS_NO_ATTENDEES = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:abc@x\r\n"
    "DTSTART:20260512T100000Z\r\nDTEND:20260512T110000Z\r\n"
    "SUMMARY:Empty\r\nSTATUS:TENTATIVE\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)
_ICS_WITH_ATTENDEE = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:abc@x\r\n"
    "DTSTART:20260512T100000Z\r\nDTEND:20260512T110000Z\r\n"
    "SUMMARY:Empty\r\nSTATUS:TENTATIVE\r\n"
    "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=TENTATIVE:mailto:me@vk.team\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)


class _StubRawEvent:
    def __init__(self, data: str, url: str):
        self.data = data
        self.url = url


class _StubCalendar:
    def __init__(self, raw_event: _StubRawEvent):
        self._raw = raw_event

    def search(self, **_kwargs):
        return [self._raw]


def test_search_events_enriches_missing_partstat_via_get(monkeypatch):
    raw = _StubRawEvent(
        data=_ICS_NO_ATTENDEES,
        url="https://fake/calendars/cal/abc.ics",
    )
    handles = [CalendarHandle(name="cal", obj=_StubCalendar(raw), url="https://fake/")]
    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=0,
    )

    captured: dict = {}

    class _Response:
        status_code = 200
        content = _ICS_WITH_ATTENDEE.encode("utf-8")

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["auth"] = kwargs.get("auth")
        return _Response()

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.get", fake_get
    )

    events = service._search_events(
        handles, date(2026, 5, 12), ZoneInfo("Europe/Moscow"), None
    )

    assert captured["url"] == "https://fake/calendars/cal/abc.ics"
    assert captured["auth"] == ("me@vk.team", "pw")
    assert len(events) == 1
    attendees = events[0]["attendees"]
    assert any("me@vk.team" in a and "PARTSTAT=TENTATIVE" in a for a in attendees)


def test_search_events_skips_get_when_partstat_already_present(monkeypatch):
    raw = _StubRawEvent(
        data=_ICS_WITH_ATTENDEE,
        url="https://fake/calendars/cal/abc.ics",
    )
    handles = [CalendarHandle(name="cal", obj=_StubCalendar(raw), url="https://fake/")]
    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=0,
    )

    def fail_get(*_args, **_kwargs):
        raise AssertionError("GET should not be issued when PARTSTAT is already present")

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.get", fail_get
    )

    events = service._search_events(
        handles, date(2026, 5, 12), ZoneInfo("Europe/Moscow"), None
    )
    assert len(events) == 1
