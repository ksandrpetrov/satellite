"""Тексты и хелперы потоковой доставки (``sendRichMessageDraft``)."""

from __future__ import annotations

from ..presentation.rich import escape_rich, thinking_block

DEFAULT_THINKING_TEXT = "Чайка думает…"

PLAN_PROGRESS_COMPUTING = "📊 Считаю метрики дня…"
PLAN_PROGRESS_WEATHER = "🌤 Уточняю погоду…"
SETTINGS_OPEN_THINKING = "⚙️ Открываю настройки…"


def rich_thinking_status(text: str) -> str:
    """Rich draft-кадр со статусом (``<tg-thinking>``)."""
    return thinking_block(escape_rich(text))
