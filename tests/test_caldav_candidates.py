from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from caldav.lib.error import PutError

from satellite.calendar.caldav_client import (
    CalDAVError,
    CalDAVService,
    CalendarHandle,
    build_candidate_urls,
    calendar_matches,
    login_variants_for_caldav,
)
from satellite.calendar.events import is_pending_invitation_for_user


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
    handles = [CalendarHandle(name="Жуков Костя", obj=_CalendarSearchStub(), url="https://fake/")]
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
        cache_ttl_sec=300,
    )
    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=handles,
        cached_at=_time.monotonic(),
        auth_username="me",
    )

    captured: dict = {}

    class _Response:
        status_code = 200
        content = _ICS_WITH_ATTENDEE.encode("utf-8")

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["auth"] = kwargs.get("auth")
        return _Response()

    monkeypatch.setattr("satellite.calendar.caldav_client.requests.get", fake_get)

    events = service._search_events(handles, date(2026, 5, 12), ZoneInfo("Europe/Moscow"), None)

    assert captured["url"] == "https://fake/calendars/cal/abc.ics"
    assert captured["auth"] == ("me", "pw")
    assert len(events) == 1
    attendees = events[0]["attendees"]
    assert any("me@vk.team" in a and "PARTSTAT=TENTATIVE" in a for a in attendees)


# --- Регрессия: create_event обязан добавлять DTSTAMP (RFC 5545) ----------


class _StubCalendarObj:
    def __init__(self):
        self.saved_ical: bytes | None = None
        self.raise_on_save: Exception | None = None

    def add_event(self, ical: bytes) -> None:
        if self.raise_on_save is not None:
            raise self.raise_on_save
        self.saved_ical = ical


def _service_with_handle(url: str, stub: _StubCalendarObj) -> CalDAVService:
    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=300,
    )
    handle = CalendarHandle(name="primary", obj=stub, url=url)
    # подменяем discovery: cache hit без сетевого вызова
    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service._cache = _DiscoveryResult(
        endpoint=url,
        calendars=[handle],
        cached_at=_time.monotonic(),
        auth_username="me@vk.team",
    )
    return service


def test_create_event_serializes_dtstart_dtend_in_utc_with_dtstamp():
    """Mail.ru CalDAV отвергает VEVENT, если есть TZID без VTIMEZONE, или если
    нет DTSTAMP. Поэтому DTSTART/DTEND приводим к UTC (формат ``...Z``), а
    DTSTAMP добавляем явно — это RFC 5545-совместимо и принимается Mail.ru."""
    stub = _StubCalendarObj()
    service = _service_with_handle("https://fake/calendars/primary/", stub)
    tz = ZoneInfo("Europe/Moscow")
    uid, _url = service.create_event(
        calendar_url="https://fake/calendars/primary/",
        title="Test",
        start=datetime(2026, 5, 20, 10, 0, tzinfo=tz),
        end=datetime(2026, 5, 20, 11, 0, tzinfo=tz),
    )
    assert stub.saved_ical is not None
    body = stub.saved_ical.decode()
    assert "DTSTAMP" in body, "VEVENT должен содержать DTSTAMP (RFC 5545)"
    assert "TZID" not in body, (
        "DTSTART/DTEND с TZID без VTIMEZONE Mail.ru CalDAV отвергает; "
        "вместо TZID должен быть формат с явным UTC-суффиксом Z."
    )
    # Москва на 3 часа впереди UTC → 10:00 MSK == 07:00 UTC.
    assert "DTSTART:20260520T070000Z" in body
    assert "DTEND:20260520T080000Z" in body
    assert "ORGANIZER:mailto:me@vk.team" in body
    assert uid in body


def test_create_event_treats_naive_datetime_as_utc():
    """Если в datetime нет tzinfo — трактуем как UTC, не падаем."""
    stub = _StubCalendarObj()
    service = _service_with_handle("https://fake/calendars/primary/", stub)
    service.create_event(
        calendar_url="https://fake/calendars/primary/",
        title="Naive",
        start=datetime(2026, 5, 20, 10, 0),
        end=datetime(2026, 5, 20, 11, 0),
    )
    assert stub.saved_ical is not None
    body = stub.saved_ical.decode()
    assert "DTSTART:20260520T100000Z" in body
    assert "DTEND:20260520T110000Z" in body


def test_find_handle_matches_url_with_trailing_slash():
    stub = _StubCalendarObj()
    service = _service_with_handle("https://fake/calendars/primary/", stub)
    handle = service._find_handle("https://fake/calendars/primary")
    assert handle is not None
    assert handle.url.endswith("primary/")


def test_require_handle_invalidates_cache_on_miss():
    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=300,
    )
    import time as _time

    from satellite.calendar.caldav_client import CalendarHandle, _DiscoveryResult

    stale = CalendarHandle(name="old", obj=_StubCalendarObj(), url="https://fake/old/")
    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[stale],
        cached_at=_time.monotonic(),
        auth_username="me@vk.team",
    )
    discovery_calls = {"count": 0}
    real_discovery = service._do_discovery

    def counting_discovery():
        discovery_calls["count"] += 1
        return _DiscoveryResult(
            endpoint="https://fake/",
            calendars=[
                CalendarHandle(
                    name="new",
                    obj=_StubCalendarObj(),
                    url="https://fake/calendars/primary/",
                )
            ],
            cached_at=_time.monotonic(),
            auth_username="me@vk.team",
        )

    service._do_discovery = counting_discovery  # type: ignore[method-assign]
    handle = service._require_handle("https://fake/calendars/primary")
    assert handle.name == "new"
    assert discovery_calls["count"] == 1
    service._do_discovery = real_discovery  # type: ignore[method-assign]


def test_create_event_converts_dav_error_to_caldav_error():
    """DAVError (включая PutError при 400/415 от Mail.ru) должен подниматься
    как CalDAVError, чтобы провайдер вернул понятный CREATE_FAILED код, а
    `_run` не оборачивал его в общий «Календарь недоступен»."""
    stub = _StubCalendarObj()
    stub.raise_on_save = PutError("HTTP 400 Bad Request")
    service = _service_with_handle("https://fake/calendars/primary/", stub)
    tz = ZoneInfo("Europe/Moscow")
    with pytest.raises(CalDAVError):
        service.create_event(
            calendar_url="https://fake/calendars/primary/",
            title="Test",
            start=datetime(2026, 5, 20, 10, 0, tzinfo=tz),
            end=datetime(2026, 5, 20, 11, 0, tzinfo=tz),
        )


def test_partstat_refresh_does_not_cache_failed_get(monkeypatch):
    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=300,
    )
    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username="me",
    )

    calls = {"n": 0}

    def fail_get(*_args, **_kwargs):
        calls["n"] += 1
        raise requests.RequestException("timeout")

    import requests

    monkeypatch.setattr("satellite.calendar.caldav_client.requests.get", fail_get)

    url = "https://fake/calendars/cal/abc.ics"
    assert service._refresh_attendees_via_get(url) is None
    assert service._refresh_attendees_via_get(url) is None
    assert calls["n"] == 2


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

    monkeypatch.setattr("satellite.calendar.caldav_client.requests.get", fail_get)

    events = service._search_events(handles, date(2026, 5, 12), ZoneInfo("Europe/Moscow"), None)
    assert len(events) == 1


def test_enrich_invitations_prioritizes_upcoming_for_partstat_refresh(monkeypatch):
    """GET-бюджет PARTSTAT тратится сначала на ближайшие встречи, не на старые в REPORT."""
    tz = ZoneInfo("Europe/Moscow")
    target_url = "https://fake/calendars/cal/may26.ics"
    stale_accepted = {
        "summary": "Stale ACCEPTED in REPORT",
        "url": "https://fake/calendars/cal/old.ics",
        "dtstart": "2026-05-10T10:00:00+03:00",
        "dtend": "2026-05-10T11:00:00+03:00",
        "attendees": ["mailto:me@vk.team;PARTSTAT=ACCEPTED"],
    }
    may26 = {
        "summary": "May26 invite",
        "url": target_url,
        "dtstart": "2026-05-26T17:30:00+03:00",
        "dtend": "2026-05-26T18:30:00+03:00",
        "attendees": ["mailto:me@vk.team;PARTSTAT=ACCEPTED"],
    }
    events = [stale_accepted, may26]
    refreshed_urls: list[str] = []

    def fake_get(url, **_kwargs):
        refreshed_urls.append(str(url))
        from icalendar import Calendar as IcsCalendar
        from icalendar import Event as IcsEvent

        component = IcsEvent()
        component.add("uid", "u@test")
        component.add(
            "attendee",
            "mailto:me@vk.team",
            parameters={"PARTSTAT": "NEEDS-ACTION"},
        )
        component.add("dtstart", datetime(2026, 5, 26, 17, 30))
        component.add("dtend", datetime(2026, 5, 26, 18, 30))
        cal = IcsCalendar()
        cal.add_component(component)

        class _Resp:
            status_code = 200
            headers: dict = {}

            def __init__(self, content: bytes) -> None:
                self.content = content

        return _Resp(cal.to_ical())

    monkeypatch.setattr("satellite.calendar.caldav_client.requests.get", fake_get)

    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=300,
        partstat_refresh_limit=1,
        partstat_refresh_budget_sec=10.0,
    )
    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username="me@vk.team",
    )
    service._enrich_events_partstat(
        events,
        tz=tz,
        prioritize_from=date(2026, 5, 20),
        invitation_verify=True,
    )
    assert refreshed_urls == [target_url]
    assert is_pending_invitation_for_user(may26, "me@vk.team")


def test_enrich_invitations_refreshes_upcoming_before_older_false_accepted(monkeypatch):
    """Ложный ACCEPTED в REPORT: GET-бюджет не должен тратиться на старые дни до 26.05."""
    tz = ZoneInfo("Europe/Moscow")
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=tz)
    login = "alexandra@vk.team"
    target_url = "https://fake/calendars/cal/may26.ics"
    may26 = {
        "summary": "Кто есть кто",
        "url": target_url,
        "dtstart": "2026-05-26T17:30:00+03:00",
        "dtend": "2026-05-26T18:30:00+03:00",
        "attendees": [f"mailto:{login};PARTSTAT=ACCEPTED"],
    }
    fillers = [
        {
            "summary": f"Old {day}",
            "url": f"https://fake/calendars/cal/old{day}.ics",
            "dtstart": f"2026-05-{day:02d}T10:00:00+03:00",
            "dtend": f"2026-05-{day:02d}T11:00:00+03:00",
            "attendees": [f"mailto:{login};PARTSTAT=ACCEPTED"],
        }
        for day in range(8, 12)
    ]
    events = fillers + [may26]
    refreshed_urls: list[str] = []

    def fake_get(url, **_kwargs):
        refreshed_urls.append(str(url))
        from icalendar import Calendar as IcsCalendar
        from icalendar import Event as IcsEvent

        component = IcsEvent()
        component.add("uid", "u@test")
        component.add(
            "attendee",
            f"mailto:{login}",
            parameters={"PARTSTAT": "NEEDS-ACTION"},
        )
        component.add("dtstart", datetime(2026, 5, 26, 17, 30))
        component.add("dtend", datetime(2026, 5, 26, 18, 30))
        cal = IcsCalendar()
        cal.add_component(component)

        class _Resp:
            status_code = 200
            headers: dict = {}

            def __init__(self, content: bytes) -> None:
                self.content = content

        return _Resp(cal.to_ical())

    monkeypatch.setattr("satellite.calendar.caldav_client.requests.get", fake_get)

    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service = CalDAVService(
        caldav_url="https://fake/",
        login=login,
        app_password="pw",
        cache_ttl_sec=300,
        partstat_refresh_limit=2,
        partstat_refresh_budget_sec=10.0,
    )
    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username=login,
    )
    service._enrich_events_partstat(
        events,
        tz=tz,
        invitation_verify=True,
        moment=moment,
    )
    assert target_url in refreshed_urls
    assert is_pending_invitation_for_user(may26, login)


def test_enrich_invitations_skips_get_when_report_already_needs_action(monkeypatch):
    tz = ZoneInfo("Europe/Moscow")
    events = [
        {
            "summary": "Already pending",
            "url": "https://fake/calendars/cal/pending.ics",
            "dtstart": "2026-05-26T17:30:00+03:00",
            "dtend": "2026-05-26T18:30:00+03:00",
            "attendees": ["mailto:me@vk.team;PARTSTAT=NEEDS-ACTION"],
        }
    ]

    def fail_get(*_args, **_kwargs):
        raise AssertionError("GET should not run when REPORT already has NEEDS-ACTION")

    monkeypatch.setattr("satellite.calendar.caldav_client.requests.get", fail_get)

    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@vk.team",
        app_password="pw",
        cache_ttl_sec=0,
        partstat_refresh_limit=8,
    )
    service._enrich_events_partstat(
        events,
        tz=tz,
        prioritize_from=date(2026, 5, 20),
        invitation_verify=True,
    )
