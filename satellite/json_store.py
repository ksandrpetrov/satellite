"""Общая атомарная persistence-логика для JSON-сторов (users, subscriptions)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class JsonStoreBase:
    """Блокировки, версионирование снапшотов и атомарная запись (tmp + fsync + replace).

    Подклассы задают ``_PERSISTENCE_ERROR`` и ``_STORE_LABEL``, реализуют
    парсинг записей в ``_load`` и собирают payload в ``_build_snapshot_payload``.
    """

    _PERSISTENCE_ERROR: type[RuntimeError]
    _STORE_LABEL: str

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._version = 0

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    def _load_json_root(self) -> dict[str, Any]:
        try:
            with self._path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning(
                "Failed to load %s from %s: %s",
                self._STORE_LABEL,
                self._path,
                exc,
            )
            return {}
        if not isinstance(raw, dict):
            log.warning(
                "%s file %s is malformed (not an object)",
                self._STORE_LABEL.capitalize(),
                self._path,
            )
            return {}
        return raw

    def _snapshot_locked(self) -> tuple[dict[str, Any], int]:
        self._version += 1
        payload = self._build_snapshot_payload()
        return payload, self._version

    def _build_snapshot_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def _save_locked(self) -> None:
        with self._lock:
            payload, version = self._snapshot_locked()
        self._save_snapshot(payload, version)

    def _save_snapshot(self, payload: dict[str, Any], version: int) -> None:
        try:
            with self._write_lock:
                with self._lock:
                    if version < self._version:
                        return
                self._path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(
                    prefix=self._path.name + ".",
                    suffix=".tmp",
                    dir=self._path.parent,
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as file:
                        json.dump(payload, file, ensure_ascii=False, indent=2)
                        file.flush()
                        os.fsync(file.fileno())
                    os.replace(tmp_path, self._path)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
        except OSError as exc:
            log.error(
                "Failed to persist %s to %s: %s",
                self._STORE_LABEL,
                self._path,
                exc,
            )
            raise self._PERSISTENCE_ERROR(
                f"Failed to persist {self._STORE_LABEL} to {self._path}: {exc}"
            ) from exc
