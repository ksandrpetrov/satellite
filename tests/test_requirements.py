"""Контракт requirements.txt — ловим случайное снятие пинов."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"


def test_caldav_pinned_below_3() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"^caldav\s*>=\s*2\.2\s*,\s*<\s*3\s*$", text, re.MULTILINE), (
        "caldav must stay pinned as caldav>=2.2,<3 (3.x breaks mypy and runtime imports)"
    )


@pytest.mark.parametrize(
    "line",
    [
        "cryptography>=42.0",
        "icalendar>=5.0",
        "python-dotenv>=1.0",
        "requests>=2.31",
        "Pillow>=10.0",
    ],
)
def test_core_runtime_deps_present(line: str) -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert line in text
