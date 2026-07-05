"""Unit tests for satellite.calendar.duration_format."""

from __future__ import annotations

import pytest

from satellite.calendar.duration_format import format_duration_long_ru


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0 минут"),
        (1, "1 минута"),
        (2, "2 минуты"),
        (5, "5 минут"),
        (11, "11 минут"),
        (21, "21 минута"),
        (22, "22 минуты"),
        (25, "25 минут"),
        (42, "42 минуты"),
        (60, "1 час"),
        (61, "1 час 1 минута"),
        (90, "1 час 30 минут"),
        (120, "2 часа"),
        (121, "2 часа 1 минута"),
        (150, "2 часа 30 минут"),
    ],
)
def test_format_duration_long_ru_plural_edges(minutes: int, expected: str) -> None:
    assert format_duration_long_ru(minutes) == expected
