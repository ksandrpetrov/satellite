"""Снапшоты per-user стора на каждом старте бота.

`UserStore`/`SubscriptionStore` пишут JSON атомарно (tmp + os.replace), но это
защищает только от обрыва записи. От «человеческого» фактора — `rm -rf logs/`,
руками поправил файл и потерял запятую, сменил `TOKEN_ENCRYPTION_KEY` и
осиротил `encrypted_credentials` — атомарная запись не страхует.

Поэтому при каждом старте бота копируем актуальные `users.json` и
`subscriptions.json` в `logs/backups/`. Бэкапы стоят дёшево (двадцать
маленьких JSON-ов на пользователя), а восстановление — простое `cp`.

API минимальный:

- `snapshot(path)` — копирует файл в `path.parent / "backups"` с меткой времени
  в имени, удаляет старые копии за пределами окна `max_snapshots`.
- `snapshot_all(paths)` — то же для списка файлов; одна ошибка не валит весь
  список (например, если subscriptions.json ещё не создан).

Не используем сжатие: файлы маленькие, plain JSON удобнее для grep/diff на
сервере. Не пишем в `bot.log` — отдельный лог, чтобы видеть только ротацию
бэкапов.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_LIMIT = 20
SNAPSHOT_DIR_NAME = "backups"
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%SZ"


def snapshot(
    path: str | Path,
    *,
    snapshots_dir: str | Path | None = None,
    max_snapshots: int = DEFAULT_SNAPSHOT_LIMIT,
    now: datetime | None = None,
) -> Path | None:
    """Снимает копию ``path`` в `<parent>/backups/<name>.<timestamp>.bak`.

    Возвращает путь к созданному снапшоту или ``None``, если исходник отсутствует
    (первый запуск без данных — нечего бэкапить). Старые снапшоты с тем же
    префиксом обрезаются до ``max_snapshots`` штук (lexicographically — что
    эквивалентно сортировке по времени благодаря ISO-формату метки).
    """
    if max_snapshots < 1:
        raise ValueError("max_snapshots must be >= 1")
    source = Path(path)
    if not source.is_file():
        return None
    target_dir = Path(snapshots_dir) if snapshots_dir else source.parent / SNAPSHOT_DIR_NAME
    timestamp = (now or datetime.now(tz=timezone.utc)).strftime(_TIMESTAMP_FORMAT)
    target_name = f"{source.name}.{timestamp}.bak"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / target_name
        shutil.copy2(source, destination)
    except OSError as exc:
        log.warning("Failed to snapshot %s: %s", source, exc)
        return None
    _prune_old_snapshots(target_dir, prefix=source.name + ".", max_snapshots=max_snapshots)
    return destination


def snapshot_all(
    paths: Iterable[str | Path],
    *,
    snapshots_dir: str | Path | None = None,
    max_snapshots: int = DEFAULT_SNAPSHOT_LIMIT,
) -> list[Path]:
    """Снимает копии нескольких файлов; ошибки логируются и не прерывают цикл."""
    created: list[Path] = []
    now = datetime.now(tz=timezone.utc)
    for raw in paths:
        snap = snapshot(
            raw,
            snapshots_dir=snapshots_dir,
            max_snapshots=max_snapshots,
            now=now,
        )
        if snap is not None:
            created.append(snap)
    return created


def _prune_old_snapshots(directory: Path, *, prefix: str, max_snapshots: int) -> None:
    """Оставляет ``max_snapshots`` самых свежих бэкапов с указанным префиксом."""
    try:
        candidates = sorted(
            (item for item in directory.iterdir() if item.name.startswith(prefix) and item.name.endswith(".bak")),
            key=lambda item: item.name,
        )
    except OSError as exc:
        log.warning("Failed to list snapshot directory %s: %s", directory, exc)
        return
    overflow = len(candidates) - max_snapshots
    if overflow <= 0:
        return
    for victim in candidates[:overflow]:
        try:
            victim.unlink()
        except OSError as exc:
            log.warning("Failed to remove stale snapshot %s: %s", victim, exc)
