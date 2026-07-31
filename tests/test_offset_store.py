import json
import os
import threading
from pathlib import Path

from satellite.telegram_bot.offset_store import OffsetStore
from satellite.telegram_bot.offset_tracker import OffsetTracker


def test_offset_store_persists_atomically(tmp_path: Path):
    path = tmp_path / "offset.json"
    store = OffsetStore(path)
    assert store.offset == 0

    store.update(5)
    assert store.offset == 5
    assert json.loads(path.read_text())["offset"] == 5

    # Регресс не должен переписывать
    store.update(3)
    assert store.offset == 5

    store.update(10)
    assert store.offset == 10


def test_offset_store_write_failure_keeps_memory_and_disk_unchanged(tmp_path: Path, monkeypatch):
    path = tmp_path / "offset.json"
    store = OffsetStore(path)
    assert store.update(5) is True

    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk")))

    assert store.update(10) is False
    assert store.offset == 5
    assert json.loads(path.read_text())["offset"] == 5
    assert store.reset(1) is False
    assert store.offset == 5


def test_offset_tracker_retries_completed_prefix_after_write_failure(tmp_path: Path, monkeypatch):
    path = tmp_path / "offset.json"
    store = OffsetStore(path)
    tracker = OffsetTracker(store)
    real_replace = os.replace
    fail_once = True

    def flaky_replace(src, dst):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("disk")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    assert tracker.mark_dispatched(1) is True
    assert tracker.mark_dispatched(2) is True

    tracker.mark_completed(1)
    assert tracker.offset == 0

    tracker.mark_completed(2)
    assert tracker.offset == 3
    assert json.loads(path.read_text())["offset"] == 3


def test_offset_store_load_from_corrupt_file(tmp_path: Path):
    path = tmp_path / "offset.json"
    path.write_text("definitely not json")
    store = OffsetStore(path)
    assert store.offset == 0


def test_offset_store_threadsafe(tmp_path: Path):
    path = tmp_path / "offset.json"
    store = OffsetStore(path)

    def bump(value):
        for i in range(value, value + 50):
            store.update(i)

    threads = [threading.Thread(target=bump, args=(i * 100,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.offset == 449
    assert json.loads(path.read_text())["offset"] == 449


def test_offset_tracker_advances_only_after_contiguous_completion(tmp_path: Path):
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)

    assert tracker.mark_dispatched(100) is True
    assert tracker.mark_dispatched(101) is True
    assert tracker.mark_dispatched(102) is True
    assert tracker.offset == 0

    # Завершился 101 — пока offset не двигаем (есть незавершённый 100)
    tracker.mark_completed(101)
    assert tracker.offset == 0

    # Завершился 100 — продвигаемся до 102 (но не дальше)
    tracker.mark_completed(100)
    assert tracker.offset == 102

    # Завершился 102 — продвинулись до 103
    tracker.mark_completed(102)
    assert tracker.offset == 103


def test_offset_tracker_ignores_completion_for_unknown_id(tmp_path: Path):
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)
    tracker.mark_completed(999)
    assert tracker.offset == 0


def test_offset_store_reset_can_move_offset_down(tmp_path: Path):
    path = tmp_path / "offset.json"
    store = OffsetStore(path)
    store.update(500)
    assert store.offset == 500

    store.reset(100)
    assert store.offset == 100
    assert json.loads(path.read_text())["offset"] == 100

    store.reset(-5)
    assert store.offset == 0


def test_offset_tracker_drops_stale_updates_silently(tmp_path: Path):
    """Stale (update_id < offset) — Telegram переотдал уже подтверждённый update.

    Раньше tracker «откатывал offset вниз», что в проде создавало бесконечный
    цикл reset→dispatch→complete→reset при гонке двух инстансов на тот же токен.
    Теперь такие update'ы молча дропаются: ``mark_dispatched`` возвращает False,
    offset остаётся как был, побочных эффектов в обработчиках нет.
    """
    path = tmp_path / "offset.json"
    store = OffsetStore(path)
    store.update(274_977_811)
    tracker = OffsetTracker(store)

    incoming = 132_193_405
    assert tracker.mark_dispatched(incoming) is False, "stale → дроп"
    assert tracker.offset == 274_977_811, "offset вниз не уезжает"

    # mark_completed на stale-id — no-op, потому что он не в pending
    tracker.mark_completed(incoming)
    assert tracker.offset == 274_977_811


def test_offset_tracker_fresh_update_after_stale_still_works(tmp_path: Path):
    """После дропа stale свежие update'ы продвигают offset как обычно."""
    store = OffsetStore(tmp_path / "offset.json")
    store.update(1000)
    tracker = OffsetTracker(store)

    # сначала стейл
    assert tracker.mark_dispatched(500) is False
    # потом свежий
    assert tracker.mark_dispatched(1001) is True
    tracker.mark_completed(1001)
    assert tracker.offset == 1002


def test_polling_offset_advances_on_dispatch_before_completion(tmp_path: Path):
    """Главный фикс: polling_offset уезжает вперёд сразу при mark_dispatched.

    Это и есть то, что говорит Telegram'у «не переотдавай мне этот update»,
    пока worker всё ещё его обрабатывает. Без этого long-poll возвращал
    тот же update снова и снова → дубль ответов в чате.
    """
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)

    assert tracker.polling_offset == 0

    assert tracker.mark_dispatched(100) is True
    assert tracker.polling_offset == 101, "polling offset должен сразу уехать вперёд"
    # persisted offset (низкий водяной знак) пока не двигается — worker не закончил
    assert tracker.offset == 0

    # Параллельный апдейт — polling offset уезжает дальше
    assert tracker.mark_dispatched(101) is True
    assert tracker.polling_offset == 102
    assert tracker.offset == 0

    # Когда worker для 100 наконец-то закончит — persisted догоняет до 101
    # (101 ещё в pending → дальше не идём).
    tracker.mark_completed(100)
    assert tracker.offset == 101
    tracker.mark_completed(101)
    assert tracker.offset == 102
    assert tracker.polling_offset == 102


def test_polling_offset_initialized_from_persisted_on_startup(tmp_path: Path):
    """На холодном старте polling = persisted: Telegram не присылает ничего ниже."""
    path = tmp_path / "offset.json"
    store = OffsetStore(path)
    store.update(500)
    tracker = OffsetTracker(store)

    assert tracker.polling_offset == 500
    assert tracker.offset == 500


def test_mark_dispatched_returns_false_for_duplicate_pending(tmp_path: Path):
    """Belt-and-suspenders: если Telegram переотдал update пока worker ещё бежит,
    второй mark_dispatched возвращает False — побочные эффекты не дублируются.

    Регресс на баг: «10:45» → «🕘 Готово.» + «🪶 Не понял команду.»
    Первая копия попадала в FSM-ветку и чистила state; вторая видела
    очищенный state и валилась в _handle_unknown.
    """
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)

    assert tracker.mark_dispatched(100) is True
    # Тот же update_id ещё раз — Telegram любит переотдавать в long-poll
    assert tracker.mark_dispatched(100) is False, "уже в pending — пропуск"
    # polling offset не регрессирует
    assert tracker.polling_offset == 101

    # После завершения — stale (101 > 100, offset уже 101)
    tracker.mark_completed(100)
    assert tracker.offset == 101
    assert tracker.mark_dispatched(100) is False


def test_polling_offset_advances_even_for_stale_updates(tmp_path: Path):
    """Stale update'ы тоже подтягивают polling offset вверх.

    Это вежливое уведомление Telegram'у: «всё что меньше — больше не присылай».
    Иначе при гонке двух процессов на тот же токен polling мог застрять.
    """
    store = OffsetStore(tmp_path / "offset.json")
    store.update(1000)
    tracker = OffsetTracker(store)

    # persisted=1000, polling=1000
    # Stale update приходит после рестарта (offset поднимался вне нашего знания)
    assert tracker.mark_dispatched(800) is False
    # polling всё равно подтянулся (но не выше 1000, потому что 800<1000)
    assert tracker.polling_offset == 1000

    # Если приходит stale с update_id > polling, polling подтянется
    # (но это редкий случай — обычно stale ниже всего)


def test_polling_offset_does_not_regress(tmp_path: Path):
    """polling offset монотонен — никогда не идёт назад."""
    store = OffsetStore(tmp_path / "offset.json")
    tracker = OffsetTracker(store)

    assert tracker.mark_dispatched(200) is True
    assert tracker.polling_offset == 201

    # Меньший id — polling не регрессирует
    assert tracker.mark_dispatched(150) is True
    assert tracker.polling_offset == 201
