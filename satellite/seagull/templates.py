"""Текстовые шаблоны «чайки». Меняй фразы здесь — алгоритм не правится.

Все строки русскоязычные. Жирное оформление для Telegram HTML (`<b>`)
добавляет `satellite/seagull/render.py` для заголовка прогноза, строк
«Первая/Последняя встреча» (только время), заголовка расписания и интервала
времени в строке события.
"""

from __future__ import annotations

from ..presentation.html import replace_first_char_with_tg_emoji


def _seagull_line(text: str) -> str:
    """Премиум ``<tg-emoji>`` для 🪶 — fallback в ``api/client.py`` при отказе Telegram."""
    return replace_first_char_with_tg_emoji(text, "🪶")


# --- основной текст по busyMinutes (раздел 5.1) -----------------------------

MAIN_EMPTY = _seagull_line(
    "🪶 Чайка принесла редкую добычу: день без встреч. Это чистый пляж для фокуса."
)
MAIN_LIGHT = _seagull_line(
    "🪶 Чайка докладывает: день лёгкий. Встреч мало, воздуха много. "
    "Можно спокойно закрывать важные задачи."
)
MAIN_NORMAL = _seagull_line(
    "🪶 Чайка видит обычный рабочий маршрут: встреч хватает, но небо ещё не забито."
)
MAIN_DENSE = _seagull_line(
    "🪶 Чайка напрягла крылья: день плотный. Встреч много, свободных окон мало."
)
MAIN_STORM = _seagull_line(
    "🪶 Чайка кричит с мачты: календарный шторм. День почти съеден встречами."
)

# --- пересечения (раздел 5.4) -----------------------------------------------

OVERLAP_NONE = "Пересечений нет. Небо чистое."
OVERLAP_ONE = (
    "Чайка заметила один календарный занос: есть пересечение. "
    "Лучше заранее выбрать, куда реально лететь."
)
OVERLAP_MANY = (
    "Календарь устроил драку чаек за один пирожок: несколько пересечений. "
    "День надо чинить до старта."
)

# --- метки даты и оформление сообщения --------------------------------------

LABEL_TODAY = "Сегодня"
LABEL_TOMORROW = "Завтра"
LABEL_DAY_AFTER = "Послезавтра"

# Заголовок дайджеста: «📬 Прогноз на сегодня (11.09.2026)».
# 📬 добавляется в `render._forecast_header` снаружи HTML-жирного,
# а текстовая часть оборачивается в <b>...</b>.
FORECAST_HEADER_RELATIVE = "Прогноз на {rel} ({date})"
FORECAST_HEADER_PLAIN_DATE = "Дайджест на {date}"

NO_VALUE = "нет"
SCHEDULE_TITLE = "Вот детальное расписание:"
EMPTY_SCHEDULE = "Встреч нет. Чайка оставила календарь пустым."

FIRST_LINE = "Первая встреча: {value}"
LAST_LINE = "Последняя встреча до {value}"
LAST_LINE_EMPTY = "Последняя встреча: {value}"

BUSY_LINE = "👨‍💻 Занято: {value}"
FREE_LINE = "🧘 Свободно: {value}"

# Rich Message: таблица времени дня (``render_rich``). Эмодзи — те же, что
# в legacy-строках BUSY_LINE / FREE_LINE, чтобы оба рендера читались одинаково.
RICH_STATS_HEADER_TYPE = "Тип"
RICH_STATS_HEADER_TIME = "Время"
RICH_STATS_ROW_BUSY = "👨‍💻 Занято"
RICH_STATS_ROW_FREE = "🧘 Свободно"
SCHEDULE_TITLE_WITH_COUNT = "{title} — {count} встреч"

ROOM_LINE = "🛖 {location}"
ROOM_NONE = "без переговорной"
ROOM_ONLINE = "онлайн"

CONFERENCE_JOIN_MEET = "Войти в Google Meet"
CONFERENCE_JOIN_ZOOM = "Войти в Zoom"
CONFERENCE_JOIN_TEAMS = "Войти в Microsoft Teams"
CONFERENCE_JOIN_VK_TEAMS = "Войти в VK Teams"
CONFERENCE_JOIN_JITSI = "Войти в Jitsi"
CONFERENCE_JOIN_WEBEX = "Войти в Webex"
CONFERENCE_JOIN_GENERIC = "Войти в видеозвонок"

EVENT_NO_TITLE = "(без названия)"
