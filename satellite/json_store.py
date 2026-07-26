"""Общая транзакционная persistence-логика для JSON-сторов."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

log = logging.getLogger(__name__)

RecordT = TypeVar("RecordT")


class JsonStoreLoadError(RuntimeError):
    """Durable JSON-store нельзя безопасно загрузить."""


class JsonStoreBase(Generic[RecordT]):
    """Один lock и commit ``candidate -> disk -> memory``.

    Подклассы задают типы публичных ошибок, парсят записи в ``_load`` и
    сериализуют candidate-состояние в ``_build_snapshot_payload``.
    """

    _PERSISTENCE_ERROR: type[RuntimeError]
    _LOAD_ERROR: type[JsonStoreLoadError]
    _STORE_LABEL: str

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._items: dict[int, RecordT] = {}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=UTC).isoformat(timespec="seconds")

    def _load_json_root(self) -> dict[str, Any]:
        try:
            with self._path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            raise self._load_error(f"cannot read valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise self._load_error("root value must be a JSON object")
        return raw

    def _load_error(self, detail: str) -> JsonStoreLoadError:
        return self._LOAD_ERROR(f"Failed to load {self._STORE_LABEL} from {self._path}: {detail}")

    def _build_snapshot_payload(
        self,
        items: Mapping[int, RecordT],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _commit_items_locked(self, candidate: dict[int, RecordT]) -> None:
        """Записывает candidate и публикует его только после успешного replace.

        Caller обязан держать ``self._lock``: так read-modify-write и файловая
        запись образуют одну сериализованную транзакцию.
        """
        payload = self._build_snapshot_payload(candidate)
        self._persist_payload(payload)
        self._items = candidate

    def _persist_payload(self, payload: dict[str, Any]) -> None:
        try:
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
        except (OSError, TypeError, ValueError) as exc:
            log.error(
                "Failed to persist %s to %s: %s",
                self._STORE_LABEL,
                self._path,
                exc,
            )
            raise self._PERSISTENCE_ERROR(
                f"Failed to persist {self._STORE_LABEL} to {self._path}: {exc}"
            ) from exc
