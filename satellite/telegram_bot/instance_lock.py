"""Single-instance guard через эксклюзивный `fcntl.flock` на файле.

Гарантирует, что одновременно работает только один процесс бота. Без этого
параллельные инстансы попадают в гонку на long-polling'е Telegram: оба читают
один и тот же update до того, как кто-то успеет подтвердить offset, и
пользователь получает дублирующиеся ответы (например, два welcome на /start).

Контракт:

- Lock берётся неблокирующе. Если уже занят — кидаем `InstanceLockError`,
  чтобы caller мог упасть с понятной диагностикой вместо тихой работы рядом
  с другим инстансом.
- В файл пишется PID владельца — это нужно только для человекочитаемой
  диагностики, проверка занятости делается через `flock`, а не через PID.
- На `release` снимаем lock, но файл намеренно НЕ удаляем: гонка на удаление
  плохо дружит с многократным release/re-acquire, а сам по себе lock-файл
  ничего не «портит».
- POSIX-only (используется `fcntl`). Этого достаточно для прод-окружения
  (Linux) и локальной разработки на macOS.
"""

from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from types import TracebackType

log = logging.getLogger(__name__)


class InstanceLockError(RuntimeError):
    """Lock уже занят другим процессом."""


class InstanceLock:
    """Эксклюзивный файловый lock через `fcntl.flock(LOCK_EX | LOCK_NB)`."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            owner_pid = self._read_owner_pid()
            owner_hint = f" (PID {owner_pid})" if owner_pid else ""
            raise InstanceLockError(
                f"lock file {self._path} is held by another process{owner_hint}"
            ) from exc
        except OSError:
            os.close(fd)
            raise
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(fd)
        except OSError as exc:
            # PID — диагностический, не критичный: жить без него можно.
            log.warning("Failed to write PID to lock file %s: %s", self._path, exc)
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd = self._fd
        self._fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as exc:
            log.warning("Failed to release lock %s: %s", self._path, exc)
        try:
            os.close(fd)
        except OSError:
            pass

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def _read_owner_pid(self) -> int | None:
        try:
            content = self._path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            return None
        if not content or not content.isdigit():
            return None
        try:
            return int(content)
        except ValueError:
            return None
