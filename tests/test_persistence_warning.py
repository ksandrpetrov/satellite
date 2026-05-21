"""Регрессия: warning, когда users/subs пустые, а снапшоты есть.

Реальный сценарий — миграция systemd → Docker без переноса /opt/satellite/logs/
в именованный volume: контейнер видит пустой /app/logs и тихо стартует, забыв
всех approved-юзеров. Это уже один раз отстрелило прод; не дать снова.
"""

from __future__ import annotations

import logging
from pathlib import Path

from satellite.telegram_bot.bot import warn_if_users_lost


def _make_backup(logs_dir: Path, name: str) -> None:
    backups = logs_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    (backups / name).write_text("{}", encoding="utf-8")


def test_no_warning_when_store_is_populated(tmp_path: Path, caplog) -> None:
    _make_backup(tmp_path, "users.json.20260520-150000Z.bak")
    caplog.set_level(logging.WARNING)
    emitted = warn_if_users_lost(logs_dir=tmp_path, users_total=3, subs_total=0)
    assert emitted is False
    assert not any("Persistence is empty" in rec.message for rec in caplog.records)


def test_no_warning_when_first_ever_start(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.WARNING)
    emitted = warn_if_users_lost(logs_dir=tmp_path, users_total=0, subs_total=0)
    assert emitted is False
    assert not any("Persistence is empty" in rec.message for rec in caplog.records)


def test_warning_when_store_empty_but_backups_exist(tmp_path: Path, caplog) -> None:
    _make_backup(tmp_path, "users.json.20260520-150000Z.bak")
    _make_backup(tmp_path, "users.json.20260521-141200Z.bak")
    caplog.set_level(logging.WARNING)
    emitted = warn_if_users_lost(logs_dir=tmp_path, users_total=0, subs_total=0)
    assert emitted is True
    matched = [rec for rec in caplog.records if "Persistence is empty" in rec.message]
    assert matched, "ждали WARNING Persistence is empty"
    record = matched[0]
    assert record.levelno == logging.WARNING
    assert "migrate-legacy-logs.sh" in record.getMessage()


def test_warning_ignores_non_users_backups(tmp_path: Path, caplog) -> None:
    _make_backup(tmp_path, "subscriptions.json.20260520-150000Z.bak")
    caplog.set_level(logging.WARNING)
    emitted = warn_if_users_lost(logs_dir=tmp_path, users_total=0, subs_total=0)
    assert emitted is False
