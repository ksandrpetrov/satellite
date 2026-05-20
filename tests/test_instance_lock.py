import multiprocessing
import os
import time
from pathlib import Path

import pytest

from satellite.telegram_bot.instance_lock import InstanceLock, InstanceLockError


def test_acquire_succeeds_when_lock_is_free(tmp_path: Path):
    lock = InstanceLock(tmp_path / "bot.lock")
    lock.acquire()
    try:
        assert lock.is_held is True
        assert (tmp_path / "bot.lock").exists()
    finally:
        lock.release()
    assert lock.is_held is False


def test_acquire_writes_owner_pid_to_lock_file(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    with InstanceLock(lock_path):
        content = lock_path.read_text(encoding="ascii").strip()
    assert content == str(os.getpid())


def test_acquire_is_idempotent_within_same_holder(tmp_path: Path):
    lock = InstanceLock(tmp_path / "bot.lock")
    lock.acquire()
    try:
        lock.acquire()  # no-op
        assert lock.is_held is True
    finally:
        lock.release()


def test_release_is_idempotent(tmp_path: Path):
    lock = InstanceLock(tmp_path / "bot.lock")
    lock.acquire()
    lock.release()
    lock.release()
    assert lock.is_held is False


def test_release_allows_reacquire(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    first = InstanceLock(lock_path)
    first.acquire()
    first.release()

    second = InstanceLock(lock_path)
    second.acquire()
    try:
        assert second.is_held is True
    finally:
        second.release()


def test_second_acquire_raises_while_first_is_held(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    holder = InstanceLock(lock_path)
    holder.acquire()
    try:
        contender = InstanceLock(lock_path)
        with pytest.raises(InstanceLockError) as exc_info:
            contender.acquire()
        # Подсказка про PID в сообщении помогает диагностике.
        assert str(os.getpid()) in str(exc_info.value)
        assert contender.is_held is False
    finally:
        holder.release()


def test_context_manager_releases_lock_on_exit(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    with InstanceLock(lock_path):
        pass
    # Можно перезахватить, значит освободили
    with InstanceLock(lock_path) as second:
        assert second.is_held is True


def test_context_manager_releases_on_exception(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with InstanceLock(lock_path):
            raise RuntimeError("boom")
    # Лок должен быть свободен после выхода
    with InstanceLock(lock_path) as second:
        assert second.is_held is True


def test_creates_parent_directory(tmp_path: Path):
    lock_path = tmp_path / "nested" / "dir" / "bot.lock"
    with InstanceLock(lock_path):
        assert lock_path.exists()


def _hold_lock_in_child(path: str, ready_path: str, exit_path: str) -> None:
    """Захватывает lock в дочернем процессе и ждёт сигнала на выход."""
    from satellite.telegram_bot.instance_lock import InstanceLock as _Lock

    with _Lock(path):
        Path(ready_path).write_text("ok", encoding="ascii")
        for _ in range(200):  # ждём до 20 секунд
            if Path(exit_path).exists():
                return
            time.sleep(0.1)


def test_cross_process_exclusion(tmp_path: Path):
    """Главное свойство: другой процесс не может взять lock, пока первый держит."""
    lock_path = tmp_path / "bot.lock"
    ready_path = tmp_path / "child_ready"
    exit_path = tmp_path / "child_exit"

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(
        target=_hold_lock_in_child,
        args=(str(lock_path), str(ready_path), str(exit_path)),
    )
    child.start()
    try:
        deadline = time.monotonic() + 10.0
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready_path.exists(), "child did not acquire the lock in time"

        with pytest.raises(InstanceLockError):
            InstanceLock(lock_path).acquire()

        # PID в файле должен быть пайдом ребёнка, а не нашего процесса.
        pid_in_file = int(lock_path.read_text(encoding="ascii").strip())
        assert pid_in_file == child.pid
    finally:
        exit_path.write_text("go", encoding="ascii")
        child.join(timeout=10)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)

    # После выхода ребёнка lock должен освободиться.
    with InstanceLock(lock_path) as final:
        assert final.is_held is True
