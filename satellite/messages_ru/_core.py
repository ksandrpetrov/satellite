"""Совместимость: реэкспорт всех подмодулей messages_ru.

Новый код может импортировать из ``satellite.messages_ru.buttons`` и т.д.;
фасад ``satellite.messages_ru`` по-прежнему отдаёт полный API.
"""

from __future__ import annotations

from .access import *  # noqa: F403
from .admin_messages import *  # noqa: F403
from .buttons import *  # noqa: F403
from .calendar_ui import *  # noqa: F403
from .duration import *  # noqa: F403
from .identity import *  # noqa: F403
from .plan_strings import *  # noqa: F403
from .settings_ui import *  # noqa: F403
