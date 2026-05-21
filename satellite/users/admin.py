"""Парсинг списка админов из env (``ADMIN_TELEGRAM_IDS``).

Здесь сознательно нет зависимостей от ``UserStore`` — это чистый парсинг
строки в кортеж ID. Использует ``config.py`` на этапе загрузки настроек.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

log = logging.getLogger(__name__)


def parse_admin_ids(raw: str | None) -> tuple[int, ...]:
    """Парсит ``ADMIN_TELEGRAM_IDS`` (`,`/`;` разделитель) в кортеж id."""
    if not raw:
        return ()
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            log.warning("Ignoring non-integer admin id: %r", token)
    return tuple(sorted(set(out)))


def admin_id_set(ids: Iterable[int]) -> frozenset[int]:
    return frozenset(int(i) for i in ids if int(i) > 0)
