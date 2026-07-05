"""Интеграционные тесты high-level дайджеста с CalDAV-словарями."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from satellite.seagull.digest import build_seagull_digest

TZ = ZoneInfo("Europe/Moscow")


def _ev(summary: str, start_h: int, start_m: int, end_h: int, end_m: int, *, location=""):
    return {
        "summary": summary,
        "location": location,
        "dtstart": datetime(2026, 5, 11, start_h, start_m, tzinfo=TZ).isoformat(),
        "dtend": datetime(2026, 5, 11, end_h, end_m, tzinfo=TZ).isoformat(),
    }


def test_digest_uses_today_label_when_plan_date_equals_reference():
    text = build_seagull_digest(
        [],
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert text.startswith("📬 <b>Прогноз на сегодня (11.05.2026)</b>\n")


def test_digest_uses_tomorrow_label_when_plan_date_is_next_day():
    text = build_seagull_digest(
        [],
        date(2026, 5, 12),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert text.startswith("📬 <b>Прогноз на завтра (12.05.2026)</b>\n")


def test_digest_uses_day_after_label_when_plan_date_is_plus_two():
    text = build_seagull_digest(
        [],
        date(2026, 5, 13),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert text.startswith("📬 <b>Прогноз на послезавтра (13.05.2026)</b>\n")


def test_digest_falls_back_to_date_label_for_other_days():
    text = build_seagull_digest(
        [],
        date(2026, 5, 20),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert text.startswith("📬 <b>Дайджест на 20.05.2026</b>\n")


def test_digest_renders_caldav_events_with_summary_field():
    text = build_seagull_digest(
        [_ev("Дейли", 10, 0, 10, 30, location="A1")],
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert "Первая встреча: 10:00" in text
    assert "Последняя встреча до 10:30" in text
    assert "Дейли" in text
    assert "🛖 A1" in text
    assert "👨\u200d💻 Занято: 30 мин" in text


def test_digest_ignores_events_not_on_the_target_date():
    events = [
        _ev("Today", 10, 0, 11, 0),  # 2026-05-11
        {
            "summary": "Tomorrow",
            "dtstart": datetime(2026, 5, 12, 10, 0, tzinfo=TZ).isoformat(),
            "dtend": datetime(2026, 5, 12, 11, 0, tzinfo=TZ).isoformat(),
        },
    ]
    text = build_seagull_digest(
        events,
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert "Today" in text
    assert "Tomorrow" not in text


def test_digest_marks_pending_meeting_parsed_from_real_ics():
    """End-to-end: ICS → парсер → digest. PARTSTAT не должен теряться по дороге."""
    from satellite.calendar.ical_parser import parse_calendar_events

    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:1@test\r\n"
        "SUMMARY:Pending\r\n"
        "DTSTART;TZID=Europe/Moscow:20260511T100000\r\n"
        "DTEND;TZID=Europe/Moscow:20260511T110000\r\n"
        "ATTENDEE;PARTSTAT=NEEDS-ACTION;CN=Me:mailto:me@mail.ru\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = parse_calendar_events(ics, "Test")
    text = build_seagull_digest(
        events,
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
        login="me@mail.ru",
    )
    assert "⚠️ <b>10:00–11:00</b> — Pending" in text


def test_digest_marks_pending_meeting_with_warning_when_login_given():
    pending_ev = _ev("Pending", 10, 0, 11, 0)
    pending_ev["attendees"] = ["mailto:me@mail.ru;PARTSTAT=NEEDS-ACTION"]
    accepted_ev = _ev("Accepted", 12, 0, 13, 0)
    accepted_ev["attendees"] = ["mailto:me@mail.ru;PARTSTAT=ACCEPTED"]
    text = build_seagull_digest(
        [pending_ev, accepted_ev],
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
        login="me@mail.ru",
    )
    assert "⚠️ <b>10:00–11:00</b> — Pending" in text
    assert "2️⃣ <b>12:00–13:00</b> — Accepted" in text


def test_digest_marks_tentative_meeting_with_scales():
    tentative_ev = _ev("Maybe", 10, 0, 11, 0)
    tentative_ev["attendees"] = ["mailto:me@mail.ru;PARTSTAT=TENTATIVE"]
    pending_ev = _ev("Pending", 12, 0, 13, 0)
    pending_ev["attendees"] = ["mailto:me@mail.ru;PARTSTAT=NEEDS-ACTION"]
    text = build_seagull_digest(
        [tentative_ev, pending_ev],
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
        login="me@mail.ru",
    )
    assert "⚖️ <b>10:00–11:00</b> — Maybe" in text
    assert "⚠️ <b>12:00–13:00</b> — Pending" in text


def test_digest_without_login_keeps_numbers_even_for_unaccepted():
    pending_ev = _ev("Pending", 10, 0, 11, 0)
    pending_ev["attendees"] = ["mailto:me@mail.ru;PARTSTAT=NEEDS-ACTION"]
    text = build_seagull_digest(
        [pending_ev],
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert "⚠️" not in text
    assert "1️⃣ <b>10:00–11:00</b> — Pending" in text


def test_digest_hidden_meal_events_show_footer_without_schedule_row():
    """Скрытые «🍕 Обед» не в расписании, но интервал внизу сообщения есть."""
    text = build_seagull_digest(
        [_ev("Дейли", 10, 0, 10, 30)],
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
        hidden_meal_events=[_ev("🍕 Обед", 13, 0, 14, 0)],
    )
    assert "Дейли" in text
    assert "🍕 Обед: 13:00 – 14:00" in text
    assert "10:00–10:30</b> — 🍕 Обед" not in text


def test_digest_drops_caldav_event_with_status_cancelled():
    # mail.ru CalDAV отдаёт отменённую встречу как обычный VEVENT с STATUS:CANCELLED.
    # Дайджест не должен её рисовать (регрессия фантомной [SMB] Delivery Demo).
    events = [
        _ev("Real", 10, 0, 10, 30),
        {
            "summary": "[SMB] Delivery Demo",
            "location": "ББ, 3 этаж, кубик Б20",
            "dtstart": datetime(2026, 5, 11, 16, 30, tzinfo=TZ).isoformat(),
            "dtend": datetime(2026, 5, 11, 18, 0, tzinfo=TZ).isoformat(),
            "status": "CANCELLED",
        },
    ]
    text = build_seagull_digest(
        events,
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    assert "Real" in text
    assert "[SMB] Delivery Demo" not in text
    assert "16:30" not in text


def test_digest_clips_multi_day_event_to_workday():
    events = [
        {
            "summary": "Marathon",
            "dtstart": datetime(2026, 5, 10, 23, 0, tzinfo=TZ).isoformat(),
            "dtend": datetime(2026, 5, 11, 11, 0, tzinfo=TZ).isoformat(),
        }
    ]
    text = build_seagull_digest(
        events,
        date(2026, 5, 11),
        tz=TZ,
        reference_date=date(2026, 5, 11),
    )
    # Внутри рабочего дня (10:00–19:00) попадает только 10:00–11:00 → 1ч.
    assert "👨\u200d💻 Занято: 1 ч" in text
