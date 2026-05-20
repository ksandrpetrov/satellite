"""Append-only audit log календарных операций (без PII)."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)


class CalendarOperationLog:
    """Пишет одну JSON-строку на операцию в ``calendar_ops.jsonl``."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        user_id: int,
        provider: str,
        operation: str,
        status: str,
        error_code: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        cid = correlation_id or str(uuid4())
        entry = {
            "user_id": user_id,
            "provider": provider,
            "operation": operation,
            "status": status,
            "error_code": error_code,
            "correlation_id": cid,
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        }
        line = json.dumps(entry, ensure_ascii=False)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as file:
                    file.write(line + "\n")
                    file.flush()
                    os.fsync(file.fileno())
        except OSError as exc:
            log.warning("Failed to write calendar op log: %s", exc)
        return cid
