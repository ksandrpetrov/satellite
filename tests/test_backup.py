"""Тесты для ``satellite.backup``: ротация снапшотов на старте бота."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from satellite import backup


def test_snapshot_creates_copy_with_timestamp(tmp_path: Path) -> None:
    source = tmp_path / "users.json"
    source.write_text('{"42": {}}', encoding="utf-8")

    fixed = datetime(2026, 5, 20, 18, 30, 0, tzinfo=UTC)
    snap = backup.snapshot(source, now=fixed)

    assert snap is not None
    assert snap.parent == tmp_path / "backups"
    assert snap.name == "users.json.20260520-183000Z.bak"
    assert snap.read_text(encoding="utf-8") == '{"42": {}}'


def test_snapshot_missing_source_returns_none(tmp_path: Path) -> None:
    assert backup.snapshot(tmp_path / "users.json") is None
    assert not (tmp_path / "backups").exists()


def test_snapshot_prunes_oldest(tmp_path: Path) -> None:
    source = tmp_path / "subscriptions.json"
    source.write_text("{}", encoding="utf-8")

    start = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    for offset in range(5):
        backup.snapshot(
            source,
            max_snapshots=3,
            now=start + timedelta(minutes=offset),
        )

    backups_dir = tmp_path / "backups"
    surviving = sorted(p.name for p in backups_dir.iterdir())
    assert surviving == [
        "subscriptions.json.20260520-120200Z.bak",
        "subscriptions.json.20260520-120300Z.bak",
        "subscriptions.json.20260520-120400Z.bak",
    ]


def test_snapshot_prune_only_touches_same_prefix(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    subs = tmp_path / "subscriptions.json"
    users.write_text("{}", encoding="utf-8")
    subs.write_text("{}", encoding="utf-8")

    fixed = datetime(2026, 5, 20, 9, 0, 0, tzinfo=UTC)
    backup.snapshot(users, max_snapshots=1, now=fixed)
    backup.snapshot(subs, max_snapshots=1, now=fixed + timedelta(seconds=1))

    backups_dir = tmp_path / "backups"
    names = sorted(p.name for p in backups_dir.iterdir())
    assert names == [
        "subscriptions.json.20260520-090001Z.bak",
        "users.json.20260520-090000Z.bak",
    ]


def test_snapshot_all_collects_existing_paths(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    users.write_text("{}", encoding="utf-8")
    missing = tmp_path / "subscriptions.json"

    created = backup.snapshot_all([users, missing])

    assert len(created) == 1
    assert created[0].parent == tmp_path / "backups"


def test_snapshot_max_snapshots_must_be_positive(tmp_path: Path) -> None:
    source = tmp_path / "users.json"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        backup.snapshot(source, max_snapshots=0)
