"""Re-export shim: canonical модуль теперь — ``handlers.digest_state``.

Старые импорты ``from satellite.telegram_bot.digest_state import ...``
продолжают работать. См. Фазу 9 рефакторинга.
"""

from .handlers import digest_state as _impl
from .handlers.digest_state import *  # noqa: F401,F403

__all__ = [name for name in dir(_impl) if not name.startswith("_")]
