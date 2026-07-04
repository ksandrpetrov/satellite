"""Тесты на ``normalize_caldav_event`` — единственный production-путь
нормализации CalDAV-словаря в ``NormalizedEvent``.

Тесты ``calculate_day_stats`` работают со ``NormalizedEvent`` напрямую, без
проверки клиппинга по дню, часовых поясов и PARTSTAT. Эти аспекты живут
здесь.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from satellite.calendar.stats import NormalizedEvent, normalize_caldav_event

TZ = ZoneInfo("Europe/Moscow")


def _ev(start: datetime, end: datetime, **extra) -> dict:
    return {
        "summary": extra.pop("summary", "Daily"),
        "location": extra.pop("location", "A1"),
        "dtstart": start.isoformat(),
        "dtend": end.isoformat(),
        **extra,
    }


def test_basic_event_returns_minutes_relative_to_plan_date():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.start_minutes == 600 and ne.end_minutes == 660
    assert ne.title == "Daily" and ne.location == "A1"
    assert not ne.is_cancelled and not ne.is_pending and not ne.is_tentative


def test_event_outside_plan_date_returns_none():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 10, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 10, 11, 0, tzinfo=TZ),
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert ne is None


def test_multi_day_event_is_clipped_to_plan_date():
    """22:00 предыдущего дня → 03:00 целевого дня → видим только 00:00–03:00."""
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 10, 22, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 3, 0, tzinfo=TZ),
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.start_minutes == 0
    assert ne.end_minutes == 180


def test_event_with_utc_tz_is_converted_to_local():
    """CalDAV отдаёт UTC; нормализатор обязан переводить в локальный TZ."""
    utc = ZoneInfo("UTC")
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 7, 0, tzinfo=utc),  # 10:00 MSK
            datetime(2026, 5, 11, 8, 0, tzinfo=utc),  # 11:00 MSK
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.start_minutes == 600 and ne.end_minutes == 660


def test_cancelled_status_is_flagged():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 16, 30, tzinfo=TZ),
            datetime(2026, 5, 11, 18, 0, tzinfo=TZ),
            status="CANCELLED",
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.is_cancelled is True


def test_partstat_needs_action_marks_pending_when_login_known():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
            attendees=["mailto:me@mail.ru;PARTSTAT=NEEDS-ACTION"],
        ),
        date(2026, 5, 11),
        TZ,
        login="me@mail.ru",
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.is_pending is True
    assert ne.is_tentative is False


def test_partstat_tentative_marks_tentative_when_login_known():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
            attendees=["mailto:me@mail.ru;PARTSTAT=TENTATIVE"],
        ),
        date(2026, 5, 11),
        TZ,
        login="me@mail.ru",
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.is_pending is False
    assert ne.is_tentative is True


def test_partstat_ignored_without_login():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
            attendees=["mailto:me@mail.ru;PARTSTAT=NEEDS-ACTION"],
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.is_pending is False
    assert ne.is_tentative is False


def test_zero_duration_event_returns_none():
    same = datetime(2026, 5, 11, 10, 0, tzinfo=TZ)
    assert normalize_caldav_event(_ev(same, same), date(2026, 5, 11), TZ) is None


def test_conference_url_from_url_field():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
            url="https://meet.google.com/abc-defg-hij",
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.conference_url == "https://meet.google.com/abc-defg-hij"
    assert ne.location == "A1"


def test_location_as_meet_url_shows_online():
    meet = "https://meet.google.com/abc-defg-hij"
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
            location=meet,
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.conference_url == meet
    assert ne.location == "онлайн"


def test_conference_url_from_description():
    ne = normalize_caldav_event(
        _ev(
            datetime(2026, 5, 11, 10, 0, tzinfo=TZ),
            datetime(2026, 5, 11, 11, 0, tzinfo=TZ),
            location="A1",
            description="Ссылка: https://zoom.us/j/123456789",
        ),
        date(2026, 5, 11),
        TZ,
    )
    assert isinstance(ne, NormalizedEvent)
    assert ne.conference_url == "https://zoom.us/j/123456789"
    assert ne.location == "A1"
