"""Быстрое PARTSTAT-обогащение /invitations: параллельные GET, дедуп, multiget.

Регрессии на оптимизацию июля 2026: до неё до 80 GET шли строго последовательно
(wall-clock бюджеты 14с/22с выедались целиком) и /invitations занимал ~40с.
Эти тесты должны падать при откате на последовательный цикл, потере дедупа по
URL или отказе от multiget-fallback'а.
"""

from __future__ import annotations

import threading
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

from caldav.lib.url import URL as CaldavURL
from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent

from satellite.calendar.caldav_client import (
    CalDAVService,
    CalendarHandle,
    _DiscoveryResult,
)
from satellite.calendar.events import is_pending_invitation_for_user

TZ = ZoneInfo("Europe/Moscow")
LOGIN = "me@vk.team"
MOMENT = datetime(2026, 5, 21, 12, 0, tzinfo=TZ)


def _ics_needs_action(login: str = LOGIN) -> bytes:
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
    return cal.to_ical()


def _ics_without_attendees() -> bytes:
    component = IcsEvent()
    component.add("uid", "u@test")
    component.add("dtstart", datetime(2026, 5, 26, 17, 30))
    component.add("dtend", datetime(2026, 5, 26, 18, 30))
    cal = IcsCalendar()
    cal.add_component(component)
    return cal.to_ical()


def _event(url: str, *, day: int = 26, attendees: list[str] | None = None) -> dict:
    return {
        "summary": f"Event {url.rsplit('/', 1)[-1]}",
        "url": url,
        "dtstart": f"2026-05-{day:02d}T17:30:00+03:00",
        "dtend": f"2026-05-{day:02d}T18:30:00+03:00",
        "attendees": list(attendees or []),
    }


class _Resp:
    status_code = 200
    headers: dict = {}

    def __init__(self, content: bytes) -> None:
        self.content = content


def _service(**kwargs) -> CalDAVService:
    return CalDAVService(
        caldav_url="https://fake/",
        login=LOGIN,
        app_password="pw",
        cache_ttl_sec=300,
        **kwargs,
    )


def _prime_discovery(service: CalDAVService, calendars: list[CalendarHandle] | None = None) -> None:
    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=list(calendars or []),
        cached_at=_time.monotonic(),
        auth_username=LOGIN,
    )


# --- параллельный refresh ---------------------------------------------------


def test_parallel_refresh_dedupes_shared_url(monkeypatch):
    """Occurrence'ы recurring-встречи делят один ресурс: один GET, результат у всех."""
    shared = "https://fake/calendars/cal/recurring.ics"
    events = [_event(shared, day=22), _event(shared, day=23), _event(shared, day=24)]
    calls: list[str] = []

    def fake_get(self, url, **_kwargs):
        calls.append(str(url))
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)
    service = _service()
    _prime_discovery(service)

    done = service._refresh_events_partstat_parallel(
        events, limit=10, deadline=_time.monotonic() + 5.0
    )

    assert calls == [shared]
    assert done == 1
    for ev in events:
        assert is_pending_invitation_for_user(ev, LOGIN)


def test_parallel_refresh_limit_counts_unique_urls(monkeypatch):
    events = [_event(f"https://fake/calendars/cal/e{i}.ics") for i in range(5)]
    calls: list[str] = []

    def fake_get(self, url, **_kwargs):
        calls.append(str(url))
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)
    service = _service()
    _prime_discovery(service)

    done = service._refresh_events_partstat_parallel(
        events, limit=2, deadline=_time.monotonic() + 5.0
    )

    assert done == 2
    # Приоритет сохраняется: в очередь идут первые уникальные URL списка.
    assert sorted(calls) == sorted([events[0]["url"], events[1]["url"]])


def test_parallel_refresh_expired_deadline_skips_gets(monkeypatch):
    def fail_get(*_args, **_kwargs):
        raise AssertionError("GET must not run after deadline")

    monkeypatch.setattr(CalDAVService, "_http_get", fail_get)
    service = _service()

    done = service._refresh_events_partstat_parallel(
        [_event("https://fake/calendars/cal/e.ics")],
        limit=10,
        deadline=_time.monotonic() - 0.1,
    )

    assert done == 0


def test_parallel_refresh_runs_concurrently(monkeypatch):
    """GET'ы выполняются в несколько потоков, а не последовательно."""
    in_flight = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow_get(self, url, **_kwargs):
        with lock:
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
        _time.sleep(0.15)
        with lock:
            in_flight["now"] -= 1
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", slow_get)
    service = _service()
    _prime_discovery(service)
    events = [_event(f"https://fake/calendars/cal/p{i}.ics") for i in range(4)]

    done = service._refresh_events_partstat_parallel(
        events, limit=10, deadline=_time.monotonic() + 10.0
    )

    assert done == 4
    assert in_flight["max"] >= 2, "GET'ы должны идти параллельно (ThreadPoolExecutor)"
    for ev in events:
        assert is_pending_invitation_for_user(ev, LOGIN)


# --- calendar-multiget (фаза 0) ----------------------------------------------


class _MultigetResponse:
    def __init__(self, url: str, data: bytes) -> None:
        self.url = CaldavURL.objectify(url)
        self.data = data


class _MultigetCalendarStub:
    """Имитирует ``caldav.Calendar.multiget``: yield объектов с ``.url`` и ``.data``."""

    def __init__(
        self,
        payload_by_url: dict[str, bytes] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._payload_by_url = payload_by_url or {}
        self._error = error

    def multiget(self, urls, raise_notfound: bool = False):
        materialized = [str(u) for u in urls]
        self.calls.append(materialized)
        if self._error is not None:
            raise self._error
        for url in materialized:
            payload = self._payload_by_url.get(url)
            if payload is not None:
                yield _MultigetResponse(url, payload)


def test_multiget_satisfies_candidates_without_per_event_gets(monkeypatch):
    """Multiget с ATTENDEE закрывает URL: per-event GET не выполняется вовсе."""
    cal_url = "https://fake/calendars/cal/"
    event_url = cal_url + "kto.ics"
    ev = _event(event_url)
    stub = _MultigetCalendarStub({event_url: _ics_needs_action()})
    handle = CalendarHandle(name="cal", obj=stub, url=cal_url)

    def fail_get(*_args, **_kwargs):
        raise AssertionError("per-event GET must not run when multiget satisfied the URL")

    monkeypatch.setattr(CalDAVService, "_http_get", fail_get)
    service = _service(partstat_refresh_limit=8)
    _prime_discovery(service, [handle])

    stats = service._enrich_events_partstat([ev], tz=TZ, invitation_verify=True, moment=MOMENT)

    assert stub.calls == [[event_url]]
    assert stats.multiget_satisfied == 1
    assert stats.phase1_gets == 0
    assert stats.phase2_gets == 0
    assert is_pending_invitation_for_user(ev, LOGIN)


def test_multiget_without_attendees_falls_back_to_get(monkeypatch):
    """Если сервер режет ATTENDEE и в multiget — URL остаётся кандидатом GET-фаз."""
    cal_url = "https://fake/calendars/cal/"
    event_url = cal_url + "stripped.ics"
    ev = _event(event_url)
    stub = _MultigetCalendarStub({event_url: _ics_without_attendees()})
    handle = CalendarHandle(name="cal", obj=stub, url=cal_url)
    get_calls: list[str] = []

    def fake_get(self, url, **_kwargs):
        get_calls.append(str(url))
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)
    service = _service(partstat_refresh_limit=8)
    _prime_discovery(service, [handle])

    stats = service._enrich_events_partstat([ev], tz=TZ, invitation_verify=True, moment=MOMENT)

    assert stats.multiget_satisfied == 0
    assert get_calls == [event_url]
    assert is_pending_invitation_for_user(ev, LOGIN)


def test_multiget_error_falls_back_to_get(monkeypatch):
    """Сервер без поддержки multiget: warning + полный fallback на per-event GET."""
    cal_url = "https://fake/calendars/cal/"
    event_url = cal_url + "kto.ics"
    ev = _event(event_url)
    stub = _MultigetCalendarStub(error=RuntimeError("REPORT not supported"))
    handle = CalendarHandle(name="cal", obj=stub, url=cal_url)
    get_calls: list[str] = []

    def fake_get(self, url, **_kwargs):
        get_calls.append(str(url))
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)
    service = _service(partstat_refresh_limit=8)
    _prime_discovery(service, [handle])

    stats = service._enrich_events_partstat([ev], tz=TZ, invitation_verify=True, moment=MOMENT)

    assert stats.multiget_satisfied == 0
    assert get_calls == [event_url]
    assert is_pending_invitation_for_user(ev, LOGIN)


def test_multiget_skipped_without_discovery_cache(monkeypatch):
    """Enrich без готового discovery-кэша не инициирует discovery ради multiget."""
    ev = _event("https://fake/calendars/cal/kto.ics")
    get_calls: list[str] = []

    def fake_get(self, url, **_kwargs):
        get_calls.append(str(url))
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)
    # GET-фаза берёт auth-username из discovery — изолируем от сети;
    # multiget-фаза при пустом _cache должна отвалиться сама, до discovery.
    monkeypatch.setattr(CalDAVService, "_auth_username", lambda self: LOGIN)
    service = _service(partstat_refresh_limit=8)
    assert service._cache is None

    stats = service._enrich_events_partstat([ev], tz=TZ, invitation_verify=True, moment=MOMENT)

    assert stats.multiget_satisfied == 0
    assert get_calls == [ev["url"]]
    assert is_pending_invitation_for_user(ev, LOGIN)


def test_multiget_skips_urls_outside_known_calendars(monkeypatch):
    """URL вне известных календарей не попадает в multiget, но обогащается GET'ом."""
    cal_url = "https://fake/calendars/cal/"
    foreign_url = "https://other/calendars/x/ev.ics"
    ev = _event(foreign_url)
    stub = _MultigetCalendarStub()
    handle = CalendarHandle(name="cal", obj=stub, url=cal_url)
    get_calls: list[str] = []

    def fake_get(self, url, **_kwargs):
        get_calls.append(str(url))
        return _Resp(_ics_needs_action())

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)
    service = _service(partstat_refresh_limit=8)
    _prime_discovery(service, [handle])

    stats = service._enrich_events_partstat([ev], tz=TZ, invitation_verify=True, moment=MOMENT)

    assert stub.calls == []
    assert stats.multiget_satisfied == 0
    assert get_calls == [foreign_url]
    assert is_pending_invitation_for_user(ev, LOGIN)
