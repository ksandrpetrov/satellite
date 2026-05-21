"""Re-export shim: canonical модуль теперь — ``handlers.calendar_state``.

Старые импорты ``from satellite.telegram_bot.calendar_state import ...``
продолжают работать. См. также Фазу 9 рефакторинга — состояние FSM логически
принадлежит хендлерам, а не транспортному слою.
"""

from .handlers import calendar_state as _impl
from .handlers.calendar_state import *  # noqa: F401,F403

__all__ = [name for name in dir(_impl) if not name.startswith("_")]
