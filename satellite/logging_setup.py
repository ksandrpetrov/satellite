"""Базовая настройка логирования: один раз на процесс, идемпотентно."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _CalDAVNoiseFilter(logging.Filter):
    """Глушит INFO-уровневый шум caldav-библиотеки во время fallback-discovery.

    Библиотека caldav зовёт `logging.info()` напрямую (без именованного логгера),
    из-за чего настройка level для "caldav" не работает. Фильтруем по pathname.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        pathname = (record.pathname or "").lower()
        if "caldav" in pathname:
            return False
        return True


def setup_logging(
    *,
    level: str = "INFO",
    log_file: Path | str | None = None,
    quiet_loggers: tuple[str, ...] = ("caldav", "urllib3", "requests"),
) -> logging.Logger:
    """Настраивает root-логгер. Идемпотентно: повторный вызов не плодит хендлеры."""
    root = logging.getLogger()
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(resolved_level)

    noise_filter = _CalDAVNoiseFilter()

    if not any(getattr(handler, "_satellite_managed", False) for handler in root.handlers):
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        stderr_handler = logging.StreamHandler(stream=sys.stderr)
        stderr_handler.setFormatter(formatter)
        stderr_handler.addFilter(noise_filter)
        stderr_handler._satellite_managed = True
        root.addHandler(stderr_handler)

        if log_file:
            log_path = Path(log_file)
            os.makedirs(log_path.parent, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.addFilter(noise_filter)
            file_handler._satellite_managed = True
            root.addHandler(file_handler)

    for name in quiet_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    return root
