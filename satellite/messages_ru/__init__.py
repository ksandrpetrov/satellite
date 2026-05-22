"""Пользовательские тексты на русском (фасад).

Все строки и хелперы UI живут в подмодулях пакета. Корневой импорт:

    from satellite.messages_ru import BUTTON_TODAY, build_settings_hub_keyboard

Подмодули по сценариям: ``buttons``, ``identity``, ``access``,
``admin_messages``, ``calendar_ui``, ``settings_ui``, ``plan_strings``,
``duration``.
"""

from . import _core as _core  # для отладки: satellite.messages_ru._core
from ._core import *  # noqa: F401,F403

__all__ = [name for name in dir(_core) if not name.startswith("_")]
