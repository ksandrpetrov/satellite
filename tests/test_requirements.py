"""Контракт requirements.txt — ловим случайное снятие пинов."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"


def test_caldav_pinned_at_3() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"^caldav\s*>=\s*3\.\d+\s*,\s*<\s*4\s*$", text, re.MULTILINE), (
        "caldav must stay pinned as caldav>=3.x,<4 (requires Python 3.10+)"
    )


@pytest.mark.parametrize(
    "line",
    [
        "cryptography>=48.0",
        "icalendar>=7.1",
        "python-dotenv>=1.2",
        "requests>=2.34",
        "Pillow>=12.0",
    ],
)
def test_core_runtime_deps_present(line: str) -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert line in text
