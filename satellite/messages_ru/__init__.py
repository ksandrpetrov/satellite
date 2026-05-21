"""Пользовательские тексты на русском (фасад).

Все строки и хелперы UI живут в подмодулях этого пакета. На корне — единая
точка импорта для существующего кода:

    from satellite.messages_ru import BUTTON_TODAY, build_settings_hub_keyboard

Когда понадобится разнести тексты по сценариям (calendar/digest/settings/...),
можно добавить рядом ``calendar.py``, ``digest.py`` и т.п. и
переэкспортировать их отсюда. Текущая фаза рефакторинга — только превращение
файла в пакет, без разбиения содержимого; импорты потребителей продолжают
работать как раньше.
"""

from . import _core as _core  # для отладки: satellite.messages_ru._core
from ._core import *  # noqa: F401,F403

__all__ = [name for name in dir(_core) if not name.startswith("_")]
