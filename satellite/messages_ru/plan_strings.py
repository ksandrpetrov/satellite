"""User-facing strings — план дня: статусы загрузки и шаблоны строк для seagull."""

from __future__ import annotations

PLAN_FETCH_STATUS_TEXT = {
    "today": ("📅 Чайка делает облёт сегодняшнего дня.\n\nСейчас принесу сводку."),
    "tomorrow": ("➡️ Чайка летит на завтрашний день.\n\nСейчас принесу сводку."),
    "day_after_tomorrow": (
        "⏭ Чайка ушла в дальний облёт — послезавтра.\n\nСкоро вернусь со сводкой."
    ),
}

PLAN_BUSY_TEXT = "📅 Уже в облёте — секунду, сейчас принесу сводку."

# --- Шаблоны строк дайджеста, использующиеся в seagull.render ---------------

PLAN_STATS_BREAKFAST = "🍕 Завтрак: {interval}"
PLAN_STATS_LUNCH = "🍕 Обед: {interval}"
PLAN_STATS_DINNER = "🍕 Ужин: {interval}"

DURATION_HOURS_AND_MINS = "{hours} ч {mins} мин"
DURATION_HOURS_ONLY = "{hours} ч"
DURATION_MINS_ONLY = "{mins} мин"
