"""Пользовательские тексты на русском (фасад).

Все строки и хелперы UI живут в подмодулях пакета. Корневой импорт:

    from satellite.messages_ru import BUTTON_TODAY, build_settings_hub_keyboard

Подмодули по сценариям: ``buttons``, ``identity``, ``access``,
``admin_messages``, ``calendar_ui``, ``settings_ui``, ``digest_ui``,
``meetings_ui``, ``plan_strings``, ``duration``, ``streaming_ui``.
"""

from .access import *  # noqa: F403
from .admin_messages import *  # noqa: F403
from .buttons import *  # noqa: F403
from .calendar_ui import *  # noqa: F403
from .digest_ui import *  # noqa: F403
from .duration import *  # noqa: F403
from .identity import *  # noqa: F403
from .meetings_ui import *  # noqa: F403
from .plan_strings import *  # noqa: F403
from .settings_ui import *  # noqa: F403
from .streaming_ui import *  # noqa: F403
