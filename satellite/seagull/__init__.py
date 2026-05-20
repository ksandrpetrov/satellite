"""Локальная аналитика календаря в стиле «чайки» — без LLM.

Архитектура:
- `..calendar.stats` — расчёт метрик дня (чистые функции).
- `templates` — текстовые шаблоны.
- `rules` — выбор текстов по метрикам.
- `render` — сборка финального сообщения.
- `digest` — высокоуровневый API: события календаря → готовое сообщение.
"""

from .digest import build_seagull_digest, prepare_seagull_stats
from .render import render_daily_digest
from .rules import SeagullTexts, build_seagull_texts

__all__ = [
    "SeagullTexts",
    "build_seagull_digest",
    "build_seagull_texts",
    "prepare_seagull_stats",
    "render_daily_digest",
]
