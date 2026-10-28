"""User-facing strings — план дня: статусы загрузки и шаблоны строк для seagull."""

from __future__ import annotations

PLAN_FETCH_STATUS_TEXT = {
    "today": "📅 Собираю план на сегодня…",
    "tomorrow": "➡️ Собираю план на завтра…",
    "day_after_tomorrow": "⏭ Собираю план на послезавтра…",
}

PLAN_BUSY_TEXT = "📅 Уже собираю план. Подожди немного."

# --- Шаблоны строк дайджеста, использующиеся в seagull.render ---------------

PLAN_STATS_BREAKFAST = "🍕 Завтрак: {interval}"
PLAN_STATS_LUNCH = "🍕 Обед: {interval}"
PLAN_STATS_DINNER = "🍕 Ужин: {interval}"

DURATION_HOURS_AND_MINS = "{hours} ч {mins} мин"
DURATION_HOURS_ONLY = "{hours} ч"
DURATION_MINS_ONLY = "{mins} мин"
