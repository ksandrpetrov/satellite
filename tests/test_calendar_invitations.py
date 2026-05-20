"""Приглашения: фильтрация NEEDS-ACTION и CalDAV PARTSTAT update."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from icalendar import Calendar as IcsCalendar, Event as IcsEvent

from satellite.calendar.caldav_client import CalDAVService
from satellite.calendar.events import (
    collect_pending_invitations,
    is_pending_invitation_for_user,
)
from satellite.calendar.callback_tokens import event_callback_token
from satellite.telegram_bot.handlers.calendar_invitations import _find_event_by_token
from satellite.telegram_bot.handlers.routing import InvitationsCommand, recognize_message
from satellite.messages_ru import BUTTON_INVITATIONS

TZ = ZoneInfo("Europe/Moscow")
LOGIN = "me@mail.ru"


def _ev(
    *,
    summary: str = "Meet",
    partstat: str = "NEEDS-ACTION",
    url: str = "https://cal/e/1.ics",
    start: str = "2026-05-20T14:00:00+03:00",
    end: str = "2026-05-20T15:00:00+03:00",
) -> dict:
    return {
        "summary": summary,
        "url": url,
        "dtstart": start,
        "dtend": end,
        "attendees": [f"mailto:{LOGIN};PARTSTAT={partstat}"],
    }


def test_is_pending_invitation_for_user():
    assert is_pending_invitation_for_user(_ev(), LOGIN)
    assert not is_pending_invitation_for_user(
        _ev(partstat="ACCEPTED"), LOGIN
    )
    assert not is_pending_invitation_for_user(
        _ev(partstat="TENTATIVE"), LOGIN
    )


def test_collect_pending_invitations_skips_past_and_accepted():
    now = datetime(2026, 5, 20, 12, 0, tzinfo=TZ)
    events = [
        _ev(summary="Pending"),
        _ev(summary="Accepted", partstat="ACCEPTED"),
        _ev(
            summary="Past",
            start="2026-05-19T10:00:00+03:00",
            end="2026-05-19T11:00:00+03:00",
        ),
    ]
    pending = collect_pending_invitations(
        events, LOGIN, TZ, now=now, max_events=10
    )
    assert len(pending) == 1
    assert pending[0]["summary"] == "Pending"


def test_event_callback_token_stable():
    url = "https://calendar.mail.ru/cal/abc.ics"
    assert event_callback_token(url) == event_callback_token(url)
    assert len(event_callback_token(url)) == 12


def test_recognize_invitations_command():
    assert isinstance(recognize_message(BUTTON_INVITATIONS), InvitationsCommand)
    assert isinstance(recognize_message("/invitations"), InvitationsCommand)
    assert isinstance(recognize_message("/invites@Bot"), InvitationsCommand)


class _StubEventObj:
    """Имитирует ``caldav.Event`` в нужном объёме.

    ``data`` — property (getter/setter), ``save()`` — без аргументов. Это
    воспроизводит сигнатуру caldav>=2.x; передавать ICS позиционно в
    ``save()`` нельзя (там ``no_overwrite: bool``), новые данные кладутся
    через ``event_obj.data = ...``. ``load()`` обязателен до чтения ``data``
    у «пустого» объекта с сервера.
    """

    def __init__(self, data: bytes, *, unloaded: bool = False):
        self._data = None if unloaded else data
        self._loaded_data = data
        self.save_called = False
        self.load_called = False

    def load(self, only_if_unloaded: bool = False) -> "_StubEventObj":
        if only_if_unloaded and self._data is not None:
            return self
        self.load_called = True
        self._data = self._loaded_data
        return self

    @property
    def data(self) -> bytes | None:
        return self._data

    @data.setter
    def data(self, value: bytes) -> None:
        self._data = value

    def save(self) -> None:
        self.save_called = True


def test_set_attendee_partstat_updates_ics(monkeypatch):
    component = IcsEvent()
    component.add("uid", "u@test")
    component.add(
        "attendee",
        "mailto:me@mail.ru",
        parameters={"PARTSTAT": "NEEDS-ACTION", "CN": "Me"},
    )
    component.add("dtstart", datetime(2026, 5, 20, 10, 0))
    component.add("dtend", datetime(2026, 5, 20, 11, 0))
    cal = IcsCalendar()
    cal.add_component(component)
    ics_bytes = cal.to_ical()
    saved: dict = {}

    class _GetResp:
        status_code = 200
        content = ics_bytes
        headers = {"ETag": '"1"'}

    class _PutResp:
        status_code = 204

    def fake_get(url, **kwargs):
        return _GetResp()

    def fake_put(url, data=None, **kwargs):
        saved["body"] = data
        return _PutResp()

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.get", fake_get
    )
    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.put", fake_put
    )

    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@mail.ru",
        app_password="pw",
        cache_ttl_sec=300,
    )
    from satellite.calendar.caldav_client import _DiscoveryResult
    import time as _time

    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username="me@mail.ru",
    )

    service.set_attendee_partstat("https://fake/e.ics", "ACCEPTED")

    updated = IcsCalendar.from_ical(saved["body"])
    for vevent in updated.walk("vevent"):
        attendee = vevent.get("ATTENDEE")
        assert attendee.params["PARTSTAT"] == "ACCEPTED"


def test_set_attendee_partstat_adds_attendee_when_missing(monkeypatch):
    component = IcsEvent()
    component.add("uid", "u@test")
    component.add("dtstart", datetime(2026, 5, 20, 10, 0))
    component.add("dtend", datetime(2026, 5, 20, 11, 0))
    cal = IcsCalendar()
    cal.add_component(component)
    ics_bytes = cal.to_ical()
    saved: dict = {}

    class _GetResp:
        status_code = 200
        content = ics_bytes
        headers: dict = {}

    class _PutResp:
        status_code = 204

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.get",
        lambda *a, **k: _GetResp(),
    )

    def fake_put(*args, **kwargs):
        saved["body"] = kwargs.get("data") or (args[1] if len(args) > 1 else None)
        return _PutResp()

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.put", fake_put
    )

    service = CalDAVService(
        caldav_url="https://fake/",
        login="me@mail.ru",
        app_password="pw",
        cache_ttl_sec=300,
    )
    from satellite.calendar.caldav_client import _DiscoveryResult
    import time as _time

    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username="me@mail.ru",
    )

    service.set_attendee_partstat("https://fake/e.ics", "ACCEPTED")

    updated = IcsCalendar.from_ical(saved["body"])
    for vevent in updated.walk("vevent"):
        attendee = vevent.get("ATTENDEE")
        assert attendee is not None
        assert attendee.params["PARTSTAT"] == "ACCEPTED"
        assert "me@mail.ru" in str(attendee).casefold()


def test_event_callback_token_ignores_trailing_slash():
    url = "https://calendar.mail.ru/cal/abc.ics"
    assert event_callback_token(url) == event_callback_token(url + "/")


def test_find_event_by_token_when_not_pending():
    """Кнопка привязана к URL; при ответе событие может выпасть из pending без PARTSTAT в REPORT."""
    url = "https://calendar.mail.ru/calendars/vk.team/u/evt.ics"
    token = event_callback_token(url)
    events = [
        {
            "summary": "SocServ| Техно check up",
            "url": url,
            "dtstart": "2026-06-26T15:00:00+03:00",
            "dtend": "2026-06-26T16:00:00+03:00",
            "attendees": [f"mailto:{LOGIN}"],
        },
    ]
    assert not is_pending_invitation_for_user(events[0], LOGIN)
    found = _find_event_by_token(events, token)
    assert found is not None
    assert found["summary"] == "SocServ| Техно check up"


def test_set_attendee_partstat_updates_pending_attendee_without_login_match(monkeypatch):
    """Если mailto в ICS не совпал с логином, обновляем строку с NEEDS-ACTION."""
    component = IcsEvent()
    component.add("uid", "u@test")
    component.add(
        "attendee",
        "mailto:other.alias@vk.team",
        parameters={"PARTSTAT": "NEEDS-ACTION", "CN": "Alex"},
    )
    component.add("dtstart", datetime(2026, 5, 20, 10, 0))
    component.add("dtend", datetime(2026, 5, 20, 11, 0))
    cal = IcsCalendar()
    cal.add_component(component)
    ics_bytes = cal.to_ical()
    saved: dict = {}

    class _GetResp:
        status_code = 200
        content = ics_bytes
        headers: dict = {}

    class _PutResp:
        status_code = 204

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.get",
        lambda *a, **k: _GetResp(),
    )

    def fake_put(*args, **kwargs):
        saved["body"] = kwargs.get("data") or (args[1] if len(args) > 1 else None)
        return _PutResp()

    monkeypatch.setattr(
        "satellite.calendar.caldav_client.requests.put", fake_put
    )

    service = CalDAVService(
        caldav_url="https://fake/",
        login="alex@vk.team",
        app_password="pw",
        cache_ttl_sec=300,
    )
    from satellite.calendar.caldav_client import _DiscoveryResult
    import time as _time

    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username="alex",
    )

    service.set_attendee_partstat("https://fake/e.ics", "DECLINED")

    updated = IcsCalendar.from_ical(saved["body"])
    for vevent in updated.walk("vevent"):
        assert vevent.get("ATTENDEE").params["PARTSTAT"] == "DECLINED"
