"""Регрессии /invitations: Mail.ru REPORT без ATTENDEE и урезанный GET-бюджет.

Сценарий Александры Качиной (май 2026): встреча 26.05 «Кто есть кто» есть в
календаре, но пропадает из приглашений, если:
- в REPORT нет ATTENDEE (только STATUS=TENTATIVE);
- GET-бюджет PARTSTAT слишком мал и очередь не доходит до 26.05.

Эти тесты должны падать при откате на короткий бюджет (5s) или отказе от фазы 1.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent

from satellite.calendar.caldav_client import (
    _INVITATION_MISSING_ATTENDEES_BUDGET_SEC,
    _INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT,
    CalDAVService,
)
from satellite.calendar.events import is_pending_invitation_for_user
from satellite.calendar.providers.base import UserCalendarContext
from satellite.calendar.providers.mailru import (
    INVITATIONS_PARTSTAT_REFRESH_KWARGS,
    MailruCalendarProvider,
)
from satellite.invitations_view import collect_pending_from_events
from satellite.security.token_vault import ProviderCredentials

TZ = ZoneInfo("Europe/Moscow")
LOGIN = "alexandra@vk.team"

# Значения, при которых на проде снова пропала встреча 26.05 (2026-05-21).
_KNOWN_BAD_INVITATIONS_REFRESH = {
    "partstat_refresh_limit": 20,
    "partstat_refresh_timeout_sec": 1.0,
    "partstat_refresh_budget_sec": 5.0,
}

_MIN_INVITATIONS_REFRESH = {
    "partstat_refresh_limit": 24,
    "partstat_refresh_timeout_sec": 2.0,
    "partstat_refresh_budget_sec": 18.0,
}


def _mailru_context() -> UserCalendarContext:
    return UserCalendarContext(
        user_id=250796939,
        provider_id="mailru",
        credentials=ProviderCredentials(login=LOGIN, secret="pw"),
        primary_calendar_url="https://cal/primary",
        enabled_calendar_urls=("https://cal/primary",),
        login=LOGIN,
    )


def _kto_est_kto_may26(*, attendees: list[str] | None = None) -> dict:
    return {
        "summary": "«Кто есть кто»: команды модерации, редакторской разметки и проектов",
        "url": "https://fake/calendars/cal/may26-kto.ics",
        "dtstart": "2026-05-26T17:30:00+03:00",
        "dtend": "2026-05-26T18:30:00+03:00",
        "attendees": list(attendees) if attendees is not None else [],
        "status": "TENTATIVE",
    }


def _accepted_fillers(login: str, *, count: int = 12) -> list[dict]:
    return [
        {
            "summary": f"Filler ACCEPTED {i}",
            "url": f"https://fake/calendars/cal/filler{i}.ics",
            "dtstart": f"2026-05-{day:02d}T10:00:00+03:00",
            "dtend": f"2026-05-{day:02d}T11:00:00+03:00",
            "attendees": [f"mailto:{login};PARTSTAT=ACCEPTED"],
        }
        for i, day in enumerate(range(22, 22 + count), start=1)
    ]


def _ics_with_needs_action(login: str) -> bytes:
    component = IcsEvent()
    component.add("uid", "u-kto-est-kto")
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


@pytest.mark.parametrize("key,min_value", list(_MIN_INVITATIONS_REFRESH.items()))
def test_mailru_invitations_partstat_refresh_contract(key: str, min_value: float) -> None:
    """Контракт: _service_for_invitations не должен снова стать «5s / 20 GET / 1s timeout»."""
    provider = MailruCalendarProvider()
    service = provider._service_for_invitations(_mailru_context().credentials)
    actual = getattr(service, f"_{key}")
    assert actual >= min_value, (
        f"INVITATIONS_PARTSTAT_REFRESH_KWARGS[{key!r}]={actual} < minimum {min_value}. "
        f"Не откатывайте бюджет GET для /invitations — см. _KNOWN_BAD_* в этом файле."
    )
    assert INVITATIONS_PARTSTAT_REFRESH_KWARGS[key] == actual


def test_mailru_invitations_config_must_not_match_known_bad_values() -> None:
    assert INVITATIONS_PARTSTAT_REFRESH_KWARGS != _KNOWN_BAD_INVITATIONS_REFRESH


def test_caldav_missing_attendees_phase_has_dedicated_budget() -> None:
    assert _INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT >= 24
    assert _INVITATION_MISSING_ATTENDEES_BUDGET_SEC >= 10.0


def test_kto_est_kto_not_pending_without_attendees_in_report() -> None:
    """До GET: пустые attendees → не pending (почему встреча «пропадала» из списка)."""
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=TZ)
    ev = _kto_est_kto_may26()
    assert not is_pending_invitation_for_user(ev, LOGIN)
    pending, _ = collect_pending_from_events([ev], LOGIN, TZ, now=moment)
    assert pending == []


def test_kto_est_kto_in_pending_after_enrich_phase1(monkeypatch: pytest.MonkeyPatch) -> None:
    """После фазы 1 GET: NEEDS-ACTION → встреча в collect_pending (регрессия 26.05)."""
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=TZ)
    may26 = _kto_est_kto_may26()
    events = _accepted_fillers(LOGIN, count=15) + [may26]
    refreshed_urls: list[str] = []

    def fake_get(self: CalDAVService, url: str, **_kwargs: object) -> object:
        refreshed_urls.append(url)
        payload = _ics_with_needs_action(LOGIN)

        class _Resp:
            status_code = 200
            headers: dict = {}

            def __init__(self, content: bytes) -> None:
                self.content = content

        return _Resp(payload)

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)

    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service = CalDAVService(
        caldav_url="https://fake/",
        login=LOGIN,
        app_password="pw",
        cache_ttl_sec=300,
        partstat_refresh_limit=0,
        partstat_refresh_budget_sec=0.0,
    )
    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username=LOGIN,
    )
    service._enrich_events_partstat(
        events,
        tz=TZ,
        invitation_verify=True,
        moment=moment,
    )

    assert may26["url"] in refreshed_urls
    assert is_pending_invitation_for_user(may26, LOGIN)
    pending, truncated = collect_pending_from_events(events, LOGIN, TZ, now=moment)
    summaries = [str(e.get("summary") or "") for e in pending]
    assert any("Кто есть кто" in s for s in summaries)
    assert not truncated or len(pending) <= 12


def test_enrich_invitation_verify_calls_missing_attendees_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """invitation_verify=True всегда запускает фазу 1 (_enrich_invitation_missing_attendees)."""
    calls = {"missing_phase": 0}

    original = CalDAVService._enrich_invitation_missing_attendees

    def tracked(self: CalDAVService, *args: object, **kwargs: object) -> int:
        calls["missing_phase"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        CalDAVService,
        "_enrich_invitation_missing_attendees",
        tracked,
    )
    monkeypatch.setattr(
        CalDAVService,
        "_refresh_attendees_via_get",
        lambda self, url: None,
    )

    service = CalDAVService(
        caldav_url="https://fake/",
        login=LOGIN,
        app_password="pw",
        cache_ttl_sec=0,
        partstat_refresh_limit=8,
    )
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=TZ)
    service._enrich_events_partstat(
        [_kto_est_kto_may26()],
        tz=TZ,
        invitation_verify=True,
        moment=moment,
    )
    assert calls["missing_phase"] == 1


def test_mailru_list_events_for_invitations_enables_partstat_verify() -> None:
    provider = MailruCalendarProvider()
    ctx = _mailru_context()
    captured: dict = {}

    def fake_fetch(*args: object, **kwargs: object) -> list:
        captured.update(kwargs)
        return []

    mock_service = MagicMock()
    mock_service.fetch_events_in_range.side_effect = fake_fetch

    with patch.object(provider, "_service_for_invitations", return_value=mock_service):
        provider.list_events_for_invitations(
            ctx,
            start_date=date(2026, 5, 7),
            end_date=date(2026, 7, 20),
            tz=TZ,
        )

    assert captured.get("enrich_partstat") is True
    assert captured.get("invitation_partstat_verify") is True


def test_mailru_list_events_for_analytics_is_enriched_and_strict() -> None:
    provider = MailruCalendarProvider()
    ctx = _mailru_context()
    captured: dict = {}

    def fake_fetch(*args: object, **kwargs: object) -> list:
        captured.update(kwargs)
        return []

    mock_service = MagicMock()
    mock_service.fetch_events_in_range.side_effect = fake_fetch

    with patch.object(provider, "_service_for_invitations", return_value=mock_service):
        provider.list_events_for_analytics(
            ctx,
            start_date=date(2026, 2, 16),
            end_date=date(2026, 5, 17),
            tz=TZ,
        )

    assert captured.get("enrich_partstat") is True
    assert captured.get("invitation_partstat_verify") is True
    assert captured.get("strict") is True


def test_many_accepted_fillers_do_not_block_kto_est_kto_with_short_phase2_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """15 ложных ACCEPTED + phase2 limit=1: фаза 1 всё равно подтягивает 26.05."""
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=TZ)
    may26 = _kto_est_kto_may26()
    events = _accepted_fillers(LOGIN, count=15) + [may26]
    get_order: list[str] = []

    def fake_get(self: CalDAVService, url: str, **_kwargs: object) -> object:
        get_order.append(str(url))
        if "may26-kto" not in str(url):
            payload = _ics_with_needs_action("other@vk.team")
        else:
            payload = _ics_with_needs_action(LOGIN)

        class _Resp:
            status_code = 200
            headers: dict = {}

            def __init__(self, content: bytes) -> None:
                self.content = content

        return _Resp(payload)

    monkeypatch.setattr(CalDAVService, "_http_get", fake_get)

    import time as _time

    from satellite.calendar.caldav_client import _DiscoveryResult

    service = CalDAVService(
        caldav_url="https://fake/",
        login=LOGIN,
        app_password="pw",
        cache_ttl_sec=300,
        partstat_refresh_limit=1,
        partstat_refresh_budget_sec=22.0,
        partstat_refresh_timeout_sec=2.5,
    )
    service._cache = _DiscoveryResult(
        endpoint="https://fake/",
        calendars=[],
        cached_at=_time.monotonic(),
        auth_username=LOGIN,
    )
    service._enrich_events_partstat(
        events,
        tz=TZ,
        invitation_verify=True,
        moment=moment,
    )

    assert is_pending_invitation_for_user(may26, LOGIN)
    assert get_order and get_order[0] == may26["url"]
