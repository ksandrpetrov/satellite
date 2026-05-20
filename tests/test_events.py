from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from satellite.calendar.events import (
    event_duration_minutes,
    event_occurs_on,
    filter_events_for_user,
    format_time_range,
    is_all_day_event,
    is_cancelled_event,
    is_declined_event_for_user,
    is_lunch_event,
    parse_iso,
    user_partstat,
)

TZ = ZoneInfo("Europe/Moscow")


def _ev(**fields):
    return {
        "summary": "",
        "location": "",
        "attendees": [],
        **fields,
    }


def test_parse_iso_round_trip_datetime():
    dt = datetime(2026, 5, 11, 10, 30, tzinfo=TZ)
    parsed = parse_iso(dt.isoformat())
    assert isinstance(parsed, datetime)
    assert parsed == dt


def test_parse_iso_date_only():
    parsed = parse_iso("2026-05-11")
    assert isinstance(parsed, date) and not isinstance(parsed, datetime)
    assert parsed == date(2026, 5, 11)


def test_parse_iso_handles_invalid():
    assert parse_iso(None) is None
    assert parse_iso("") is None
    assert parse_iso("not-a-date") is None


def test_event_occurs_on_simple():
    ev = _ev(
        dtstart=datetime(2026, 5, 11, 10, 0, tzinfo=TZ).isoformat(),
        dtend=datetime(2026, 5, 11, 11, 0, tzinfo=TZ).isoformat(),
    )
    assert event_occurs_on(ev, date(2026, 5, 11), TZ)
    assert not event_occurs_on(ev, date(2026, 5, 12), TZ)


def test_event_occurs_on_multi_day_all_day_with_exclusive_end():
    # iCal all-day многодневных: DTEND эксклюзивен.
    ev = _ev(dtstart="2026-05-11", dtend="2026-05-13")
    assert event_occurs_on(ev, date(2026, 5, 11), TZ)
    assert event_occurs_on(ev, date(2026, 5, 12), TZ)
    assert not event_occurs_on(ev, date(2026, 5, 13), TZ)


def test_is_all_day_event_for_date_value():
    ev = _ev(dtstart="2026-05-11", dtend="2026-05-12")
    assert is_all_day_event(ev, TZ)


def test_is_all_day_event_for_midnight_datetime():
    ev = _ev(
        dtstart="2026-05-11T00:00:00+03:00",
        dtend="2026-05-12T00:00:00+03:00",
    )
    assert is_all_day_event(ev, TZ)


def test_is_all_day_event_false_for_regular_meeting():
    ev = _ev(
        dtstart=datetime(2026, 5, 11, 10, 0, tzinfo=TZ).isoformat(),
        dtend=datetime(2026, 5, 11, 11, 0, tzinfo=TZ).isoformat(),
    )
    assert not is_all_day_event(ev, TZ)


def test_is_declined_for_user_case_insensitive():
    ev = _ev(
        attendees=[
            "mailto:You@Mail.Ru;PARTSTAT=DECLINED",
        ]
    )
    assert is_declined_event_for_user(ev, "you@mail.ru")
    assert not is_declined_event_for_user(ev, "other@mail.ru")


def test_user_partstat_returns_uppercase_or_none():
    ev = _ev(attendees=["mailto:me@mail.ru;PARTSTAT=tentative;CN=Me"])
    assert user_partstat(ev, "me@mail.ru") == "TENTATIVE"
    assert user_partstat(_ev(attendees=["mailto:me@mail.ru"]), "me@mail.ru") is None
    assert user_partstat(_ev(attendees=[]), "me@mail.ru") is None
    assert user_partstat(ev, "") is None


def test_user_partstat_prefers_accepted_over_tentative_when_duplicated():
    ev = _ev(
        attendees=[
            "mailto:me@mail.ru;PARTSTAT=TENTATIVE",
            "mailto:me@mail.ru;PARTSTAT=ACCEPTED",
        ]
    )
    assert user_partstat(ev, "me@mail.ru") == "ACCEPTED"


def test_is_lunch_event_requires_both_markers():
    assert is_lunch_event(_ev(summary="🍕 Обед с командой"))
    assert is_lunch_event(_ev(summary="ОБЕД 🍕"))
    assert is_lunch_event(_ev(summary="🍕 Завтрак команды"))
    assert is_lunch_event(_ev(summary="ужин 🍕"))
    assert not is_lunch_event(_ev(summary="🍕 Pizza party"))
    assert not is_lunch_event(_ev(summary="Просто обед без эмодзи"))


def test_format_time_range_timed_event():
    ev = _ev(
        dtstart=datetime(2026, 5, 11, 9, 0, tzinfo=TZ).isoformat(),
        dtend=datetime(2026, 5, 11, 10, 30, tzinfo=TZ).isoformat(),
    )
    assert format_time_range(ev, TZ) == "09:00–10:30"


def test_format_time_range_all_day_label():
    ev = _ev(dtstart="2026-05-11", dtend="2026-05-12")
    assert format_time_range(ev, TZ) == "весь день"


def test_event_duration_minutes():
    ev = _ev(
        dtstart=datetime(2026, 5, 11, 9, 0, tzinfo=TZ).isoformat(),
        dtend=datetime(2026, 5, 11, 10, 30, tzinfo=TZ).isoformat(),
    )
    assert event_duration_minutes(ev, TZ) == 90


def test_filter_events_for_user_removes_declined_lunch_allday():
    target = date(2026, 5, 11)
    events = [
        _ev(
            summary="Дейли",
            dtstart=datetime(2026, 5, 11, 10, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 11, 10, 30, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="🍕 Обед",
            dtstart=datetime(2026, 5, 11, 13, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 11, 14, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="Весь день",
            dtstart="2026-05-11",
            dtend="2026-05-12",
        ),
        _ev(
            summary="Я отказался",
            dtstart=datetime(2026, 5, 11, 15, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 11, 16, 0, tzinfo=TZ).isoformat(),
            attendees=["mailto:me@mail.ru;PARTSTAT=DECLINED"],
        ),
        _ev(
            summary="Не сегодня",
            dtstart=datetime(2026, 5, 12, 10, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 12, 11, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    visible, hidden_lunch = filter_events_for_user(
        events,
        target,
        tz=TZ,
        login="me@mail.ru",
        hide_all_day=True,
        hide_lunch=True,
    )
    assert [ev["summary"] for ev in visible] == ["Дейли"]
    assert [ev["summary"] for ev in hidden_lunch] == ["🍕 Обед"]


def test_is_cancelled_event_recognizes_status_cancelled():
    assert is_cancelled_event(_ev(status="CANCELLED"))
    assert is_cancelled_event(_ev(status="cancelled"))
    assert is_cancelled_event(_ev(isCancelled=True))
    assert is_cancelled_event(_ev(is_cancelled=True))
    assert not is_cancelled_event(_ev(status="CONFIRMED"))
    assert not is_cancelled_event(_ev())


def test_filter_events_for_user_drops_cancelled_status():
    # Регрессия: mail.ru CalDAV возвращает отменённые встречи как обычные
    # VEVENT с STATUS:CANCELLED — в плане их быть не должно.
    target = date(2026, 5, 19)
    events = [
        _ev(
            summary="Живая встреча",
            dtstart=datetime(2026, 5, 19, 10, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 19, 11, 0, tzinfo=TZ).isoformat(),
        ),
        _ev(
            summary="[SMB] Delivery Demo",
            dtstart=datetime(2026, 5, 19, 16, 30, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 19, 18, 0, tzinfo=TZ).isoformat(),
            status="CANCELLED",
        ),
    ]
    visible, hidden_lunch = filter_events_for_user(
        events,
        target,
        tz=TZ,
        login="me@mail.ru",
        hide_all_day=True,
        hide_lunch=True,
    )
    assert [ev["summary"] for ev in visible] == ["Живая встреча"]
    assert hidden_lunch == []


def test_filter_events_for_user_keeps_lunch_when_flag_off():
    target = date(2026, 5, 11)
    events = [
        _ev(
            summary="🍕 Обед",
            dtstart=datetime(2026, 5, 11, 13, 0, tzinfo=TZ).isoformat(),
            dtend=datetime(2026, 5, 11, 14, 0, tzinfo=TZ).isoformat(),
        ),
    ]
    visible, hidden_lunch = filter_events_for_user(
        events,
        target,
        tz=TZ,
        login="me@mail.ru",
        hide_all_day=False,
        hide_lunch=False,
    )
    assert len(visible) == 1
    assert hidden_lunch == []
