"""Снимковые тесты на финальное сообщение «чайки» (раздел 6 и 12 ТЗ)."""

from __future__ import annotations

from datetime import date

from satellite.calendar.stats import calculate_day_stats
from satellite.seagull.render import MAX_DIGEST_MESSAGE_LEN, render_daily_digest
from satellite.seagull.rules import build_seagull_texts
from satellite.seagull.templates import MAIN_EMPTY, MAIN_LIGHT

from .conftest import make_event


def _ev(title, start, end, *, location=None):
    return make_event(title, start, end, location=location)


def _render(
    events,
    *,
    date_label="Сегодня",
    plan_date: date | None = None,
):
    pd = plan_date if plan_date is not None else date(2026, 9, 11)
    stats = calculate_day_stats(events, date_label=date_label, plan_date=pd)
    texts = build_seagull_texts(stats)
    return render_daily_digest(stats, texts)


def test_single_meeting_snapshot_matches_desired_formatting():
    """Формат как в примере пользователя (дата в заголовке 11.09.2026)."""
    text = _render(
        [_ev("SocServ | QA Captains Weekly", "11:00", "12:00")],
        plan_date=date(2026, 9, 11),
    )
    assert "Прогноз на сегодня (11.09.2026)" in text
    assert MAIN_LIGHT in text
    assert "Пересечений нет. Небо чистое." in text
    assert "<b>Первая встреча: 11:00</b>" in text
    assert "<b>Последняя встреча до 12:00</b>" in text
    assert "<b>Вот детальное расписание:</b>" in text
    assert "1️⃣ <b>11:00–12:00</b> — SocServ | QA Captains Weekly" in text
    assert 'expandable="true"' not in text


def test_empty_day_snapshot_matches_desired_formatting():
    text = _render([], plan_date=date(2026, 9, 11))
    assert MAIN_EMPTY in text
    assert "<b>Первая встреча: нет</b>" in text
    assert "Встреч нет. Чайка оставила календарь пустым." in text


def test_plain_date_header_when_not_relative_day():
    text = _render([], date_label="20.05.2026", plan_date=date(2026, 5, 20))
    assert "<b>Дайджест на 20.05.2026</b>" in text


def test_schedule_blockquote_when_four_or_more_meetings():
    """От 4 встреч расписание оборачивается в blockquote (развёрнутый)."""

    events = [_ev(f"M{i}", f"{10 + i:02d}:00", f"{10 + i:02d}:30") for i in range(4)]
    text = _render(events, plan_date=date(2026, 5, 11))
    assert "<blockquote>" in text
    assert 'expandable="true"' not in text
    assert "Вот детальное расписание" in text


def test_overlap_text_is_shown_when_meetings_overlap():
    text = _render(
        [
            _ev("A", "10:00", "11:00"),
            _ev("B", "10:30", "11:30"),
        ],
        plan_date=date(2026, 5, 11),
    )
    assert "Чайка заметила один календарный занос" in text


def test_lunch_commentary_lines_never_appear():
    """Удалены все три фразы про обед-комментарий (свободен/частично/захвачен)."""
    cases = [
        _render([_ev("L", "13:00", "14:00")], plan_date=date(2026, 5, 11)),
        _render([_ev("L", "12:30", "13:30")], plan_date=date(2026, 5, 11)),
        _render([_ev("M", "10:00", "10:30")], plan_date=date(2026, 5, 11)),
        _render([], plan_date=date(2026, 5, 11)),
    ]
    for text in cases:
        assert "🍕 Обед свободен" not in text
        assert "🍕 Обед частично" not in text
        assert "🍕 Обед захвачен" not in text
        assert "🍕 Обед:" not in text
        assert "🍕 Завтрак:" not in text
        assert "🍕 Ужин:" not in text


def test_meal_footer_lines_use_calendar_intervals():
    text = _render([_ev("🍕 Обед", "13:00", "14:00")], plan_date=date(2026, 5, 11))
    assert "🍕 Обед: 13:00 – 14:00" in text


def test_meal_lines_breakfast_lunch_dinner_when_present():
    text = _render(
        [
            _ev("🍕 Завтрак", "09:00", "09:30"),
            _ev("🍕 Обед", "13:00", "14:00"),
            _ev("🍕 Ужин", "18:00", "19:00"),
        ],
        plan_date=date(2026, 5, 11),
    )
    assert "🍕 Завтрак: 09:00 – 09:30" in text
    assert "🍕 Обед: 13:00 – 14:00" in text
    assert "🍕 Ужин: 18:00 – 19:00" in text


def test_meetings_count_commentary_lines_never_appear():
    """Удалены все фразы 5.6 — про количество встреч."""
    fragments = (
        "Всего одна встреча",
        "Встреч немного",
        "Встреч уже стая",
        "нашествие чаек",
        "Календарь молчит и машет крылом",
    )
    for n in (0, 1, 3, 6, 8):
        events = [_ev(f"M{i}", f"{10 + i:02d}:00", f"{10 + i:02d}:30") for i in range(n)]
        text = _render(events, plan_date=date(2026, 5, 11))
        for fragment in fragments:
            assert fragment not in text, (fragment, n)


def test_free_slot_commentary_lines_never_appear():
    """Удалены все фразы 5.7 — про большой остров / короткие окна / сцепку."""
    fragments = (
        "большой рабочий остров",
        "Свободное время рассыпано крошками",
        "плотная сцепка встреч",
    )
    text_long = _render([_ev("A", "10:00", "10:30")], plan_date=date(2026, 5, 11))
    text_short = _render(
        [_ev(f"M{i}", f"{10 + i:02d}:00", f"{10 + i:02d}:45") for i in range(9)],
        plan_date=date(2026, 5, 11),
    )
    text_b2b = _render(
        [
            _ev("A", "12:30", "13:00"),
            _ev("B", "13:00", "14:00"),
            _ev("C", "14:00", "15:00"),
        ],
        plan_date=date(2026, 5, 11),
    )
    for text in (text_long, text_short, text_b2b):
        for fragment in fragments:
            assert fragment not in text


def test_two_events_have_blank_line_between_blocks():
    text = _render(
        [
            _ev("A", "10:00", "10:30"),
            _ev("B", "11:00", "11:30"),
        ],
        plan_date=date(2026, 5, 11),
    )
    assert "Переговорная: без переговорной\n\n2️⃣" in text


def test_event_with_location_renders_room_line():
    text = _render([_ev("Daily", "10:00", "10:30", location="A1")], plan_date=date(2026, 5, 11))
    assert "Переговорная: A1" in text


def test_event_with_conference_url_renders_join_link():
    meet = "https://meet.google.com/abc-defg-hij"
    stats = calculate_day_stats(
        [
            make_event(
                "Weekly sync",
                "11:00",
                "12:00",
                location="A1",
                conference_url=meet,
            )
        ],
        date_label="Сегодня",
        plan_date=date(2026, 5, 11),
    )
    text = render_daily_digest(stats, build_seagull_texts(stats))
    assert 'href="https://meet.google.com/abc-defg-hij"' in text
    assert "Войти в Google Meet" in text
    assert "📹" in text
    assert "Переговорная: A1" in text


def test_online_location_does_not_duplicate_raw_url():
    meet = "https://meet.google.com/abc-defg-hij"
    stats = calculate_day_stats(
        [
            make_event(
                "Standup",
                "10:00",
                "10:30",
                location="онлайн",
                conference_url=meet,
            )
        ],
        date_label="Сегодня",
        plan_date=date(2026, 5, 11),
    )
    text = render_daily_digest(stats, build_seagull_texts(stats))
    assert "Переговорная: онлайн" in text
    assert meet not in text.replace(f'href="{meet}"', "")


def test_event_title_is_html_escaped_by_default():
    text = _render([_ev("<b>boom</b>", "10:00", "10:30")], plan_date=date(2026, 5, 11))
    assert "&lt;b&gt;boom&lt;/b&gt;" in text
    assert "<b>boom</b>" not in text


def test_render_without_escape_keeps_raw_title():
    stats = calculate_day_stats(
        [_ev("<b>raw</b>", "10:00", "10:30")],
        date_label="Сегодня",
        plan_date=date(2026, 5, 11),
    )
    text = render_daily_digest(stats, build_seagull_texts(stats), escape_html=False)
    assert "<b>raw</b>" in text


def test_long_digest_is_truncated_without_cutting_html_tags():
    events = [
        _ev(
            f"Very long meeting {i} " + ("<unsafe>&" * 80),
            f"{10 + (i % 8):02d}:00",
            f"{10 + (i % 8):02d}:30",
            location="Room " + ("<A&B>" * 80),
        )
        for i in range(80)
    ]

    text = _render(events, plan_date=date(2026, 5, 11))

    assert len(text) <= MAX_DIGEST_MESSAGE_LEN
    assert "Сообщение укорочено" in text
    assert text.count("<b>") == text.count("</b>")
    assert "<unsafe>" not in text
