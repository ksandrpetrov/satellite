"""Re-export shim: canonical модуль теперь — ``analytics.service``.

Старые импорты ``from satellite.analytics_service import build_week_analytics``
продолжают работать; новый код пишет ``from satellite.analytics.service``.
"""

from .analytics import service as _impl
from .analytics.service import *  # noqa: F401,F403

__all__ = [name for name in dir(_impl) if not name.startswith("_")]
