"""High-level startup failure handling."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from satellite.services import run_bot
from satellite.users import UserStoreLoadError


def test_run_bot_reports_store_recovery_and_releases_instance_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MagicMock()
    settings.project_root = tmp_path
    settings.log_level = logging.INFO
    lock = MagicMock()
    monkeypatch.setattr("satellite.services.setup_logging", MagicMock())
    monkeypatch.setattr("satellite.services.InstanceLock", MagicMock(return_value=lock))
    monkeypatch.setattr(
        "satellite.services.TelegramBot",
        MagicMock(side_effect=UserStoreLoadError("broken users.json")),
    )

    with caplog.at_level(logging.CRITICAL, logger="satellite.services"):
        with pytest.raises(SystemExit) as exc_info:
            run_bot(settings=settings)

    assert exc_info.value.code == 1
    lock.acquire.assert_called_once_with()
    lock.release.assert_called_once_with()
    assert "Restore the latest valid snapshot" in caplog.text
    assert str(tmp_path / "logs" / "backups") in caplog.text
