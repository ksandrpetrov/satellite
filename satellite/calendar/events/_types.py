"""Базовые типы и константы для пакета ``calendar.events``.

Держим отдельно от _time/_partstat/_filters, чтобы их можно было импортировать
не таща за собой остальное (избегаем циклов внутри пакета).

``Event`` — read-only ``Mapping`` (а не ``dict``), потому что все функции
пакета только читают поля события и принимают как сырые CalDAV-dict'ы, так и
``Mapping[str, object]`` (например, из ``calendar.stats``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

PizzaMealKind = Literal["breakfast", "lunch", "dinner"]

Event = Mapping[str, Any]

NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
