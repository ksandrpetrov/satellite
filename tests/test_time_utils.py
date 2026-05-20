import pytest

from satellite.calendar.time_utils import (
    clip_interval,
    count_overlap_pairs,
    format_hhmm,
    free_slots_within,
    merge_intervals,
    normalize_hhmm_input,
    parse_hhmm,
    sum_minutes,
)


def test_parse_hhmm_basic():
    assert parse_hhmm("00:00") == 0
    assert parse_hhmm("10:00") == 600
    assert parse_hhmm("13:30") == 810
    assert parse_hhmm("23:59") == 1439


@pytest.mark.parametrize(
    "raw,expected_minutes",
    [
        ("9:30", 9 * 60 + 30),
        ("09:30", 9 * 60 + 30),
        ("9 30", 9 * 60 + 30),
        ("09 30", 9 * 60 + 30),
    ],
)
def test_parse_hhmm_accepts_flexible_user_input(raw, expected_minutes):
    assert parse_hhmm(raw) == expected_minutes
    assert normalize_hhmm_input(raw) == "09:30"


def test_parse_hhmm_rejects_garbage():
    with pytest.raises(ValueError):
        parse_hhmm("nope")
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    with pytest.raises(ValueError):
        parse_hhmm("10:60")
    with pytest.raises(ValueError):
        parse_hhmm("")


def test_format_hhmm_round_trip():
    for s in ("00:00", "09:05", "13:30", "19:00", "23:59"):
        assert format_hhmm(parse_hhmm(s)) == s


def test_merge_intervals_overlapping_collapsed():
    # 10:00–11:00 и 10:30–11:30 → 10:00–11:30 (одна полоса 90 мин).
    merged = merge_intervals([(600, 660), (630, 690)])
    assert merged == [(600, 690)]
    assert sum_minutes(merged) == 90


def test_merge_intervals_touching_collapsed():
    # Касающиеся интервалы тоже объединяются: 13:00–14:00 ∪ 14:00–15:00 → 13:00–15:00.
    assert merge_intervals([(780, 840), (840, 900)]) == [(780, 900)]


def test_merge_intervals_disjoint_kept():
    assert merge_intervals([(600, 660), (780, 840)]) == [(600, 660), (780, 840)]


def test_merge_intervals_drops_empty():
    assert merge_intervals([(600, 600), (650, 640)]) == []


def test_clip_interval():
    assert clip_interval((540, 660), 600, 1140) == (600, 660)
    assert clip_interval((1100, 1200), 600, 1140) == (1100, 1140)
    assert clip_interval((400, 500), 600, 1140) is None
    assert clip_interval((1200, 1300), 600, 1140) is None


def test_count_overlap_pairs():
    # Два пересекающихся → 1 пара.
    assert count_overlap_pairs([(600, 660), (630, 690)]) == 1
    # Три попарно пересекающихся → 3 пары.
    assert count_overlap_pairs([(600, 700), (650, 750), (680, 800)]) == 3
    # Касание не считается пересечением.
    assert count_overlap_pairs([(600, 660), (660, 720)]) == 0
    # Непересекающиеся.
    assert count_overlap_pairs([(600, 660), (700, 760)]) == 0


def test_free_slots_within_basic():
    # Окно 10:00–19:00, занято 11:00–12:00 → свободно: 10:00–11:00, 12:00–19:00.
    merged = [(660, 720)]
    slots = free_slots_within(merged, 600, 1140)
    assert slots == [(600, 660), (720, 1140)]


def test_free_slots_within_no_meetings():
    assert free_slots_within([], 600, 1140) == [(600, 1140)]


def test_free_slots_within_meeting_outside_window():
    # Встреча до окна — окно остаётся целиком.
    assert free_slots_within([(540, 580)], 600, 1140) == [(600, 1140)]
