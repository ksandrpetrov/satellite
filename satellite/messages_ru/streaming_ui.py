"""Тексты и хелперы потоковой доставки (``sendRichMessageDraft``)."""

from __future__ import annotations

from ..telegram_bot.rich_message import escape_rich, thinking_block

DEFAULT_THINKING_TEXT = "Чайка думает…"

PLAN_PROGRESS_COMPUTING = "📊 Считаю метрики дня…"
PLAN_PROGRESS_WEATHER = "🌤 Уточняю погоду…"

UPCOMING_PROGRESS_LOADING = "🗓 Загружаю события на неделю…"
INVITATIONS_PROGRESS_LOADING = "📨 Сверяю приглашения в календаре…"
MANAGE_PROGRESS_LOADING = "🛠 Собираю встречи на неделе…"
ANALYTICS_THINKING = "📊 Чайка сводит неделю по календарю…"


def rich_thinking_status(text: str) -> str:
    """Rich draft-кадр со статусом (``<tg-thinking>``)."""
    return thinking_block(escape_rich(text))
