"""Атомарное хранилище offset для long-polling Telegram-бота."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class OffsetStore:
    """Хранит offset на диске. Запись атомарна (tmp + os.replace), потокобезопасна."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._offset = self._load()

    @property
    def offset(self) -> int:
        with self._lock:
            return self._offset

    def update(self, new_offset: int) -> None:
        """Записывает новое значение, если оно больше текущего. Атомарно."""
        with self._lock:
            if new_offset <= self._offset:
                return
            self._offset = new_offset
            self._save_locked(new_offset)

    def reset(self, new_offset: int) -> None:
        """Принудительно выставляет offset (в т.ч. вниз). Используется, когда
        обнаружено, что сохранённое значение не соответствует реальности
        (например, поменялся бот-токен, и старый offset из файла не сходится
        с update_id, которые присылает Telegram).
        """
        if new_offset < 0:
            new_offset = 0
        with self._lock:
            if new_offset == self._offset:
                return
            self._offset = new_offset
            self._save_locked(new_offset)

    def _load(self) -> int:
        try:
            with self._path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return int(data.get("offset", 0))
        except FileNotFoundError:
            return 0
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load offset from %s: %s; starting from 0", self._path, exc)
            return 0

    def _save_locked(self, value: int) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=self._path.name + ".",
                suffix=".tmp",
                dir=self._path.parent,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump({"offset": value}, file, ensure_ascii=False)
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
            log.error("Failed to persist offset to %s: %s", self._path, exc)
