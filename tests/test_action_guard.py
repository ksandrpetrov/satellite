"""ActionGuard: дедуп длинных пользовательских действий.

Сценарии, ради которых guard существует (см. прод 2026-05-21 12:49 UTC —
два PNG аналитики с интервалом 7 c):

- Пока действие идёт — повтор по тому же ``(chat_id, action_key)`` не
  захватывает лок (``try_acquire`` → ``False``).
- После успешной отправки фиксируется cooldown — повтор внутри окна тоже
  отклоняется.
- ``release(sent=False)`` снимает лок без cooldown: пользователь увидел
  ошибку, ему незачем ждать перед повторной попыткой.
- Разные ``action_key`` или разные ``chat_id`` независимы (один пользователь
  может одновременно строить план и читать /upcoming в разных чатах).
"""

from __future__ import annotations

from satellite.telegram_bot.handlers.action_guard import ActionGuard


def test_concurrent_same_action_blocked():
    guard = ActionGuard(cooldown_sec=0.0)
    assert guard.try_acquire(1, "plan:today") is True
    assert guard.try_acquire(1, "plan:today") is False


def test_release_without_sent_allows_retry_immediately():
    guard = ActionGuard(cooldown_sec=60.0)
    assert guard.try_acquire(1, "plan:today") is True
    guard.release(1, "plan:today", sent=False)
    assert guard.try_acquire(1, "plan:today") is True


def test_release_with_sent_starts_cooldown():
    guard = ActionGuard(cooldown_sec=60.0)
    assert guard.try_acquire(1, "plan:today") is True
    guard.release(1, "plan:today", sent=True)
    assert guard.try_acquire(1, "plan:today") is False


def test_cooldown_expires():
    guard = ActionGuard(cooldown_sec=0.01)
    assert guard.try_acquire(1, "plan:today") is True
    guard.release(1, "plan:today", sent=True)
    import time

    time.sleep(0.02)
    assert guard.try_acquire(1, "plan:today") is True


def test_different_keys_independent():
    guard = ActionGuard(cooldown_sec=60.0)
    assert guard.try_acquire(1, "plan:today") is True
    assert guard.try_acquire(1, "upcoming") is True
    assert guard.try_acquire(2, "plan:today") is True


def test_reset_clears_state():
    guard = ActionGuard(cooldown_sec=60.0)
    assert guard.try_acquire(1, "plan:today") is True
    guard.release(1, "plan:today", sent=True)
    guard.reset()
    assert guard.try_acquire(1, "plan:today") is True
