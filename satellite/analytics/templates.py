"""Текстовые шаблоны недельной аналитики в стиле «чайки»."""

from __future__ import annotations

WEEK_LIGHT = "🪶 Чайка свела план недели: лёгкий маршрут — встреч мало, небо просторное."
WEEK_NORMAL = (
    "🪶 Чайка свела план недели: обычный рабочий ритм — встреч хватает, но воздуха ещё достаточно."
)
WEEK_DENSE = "🪶 Чайка свела план недели: плотный график — свободных окон мало."
WEEK_STORM = "🪶 Чайка свела план недели: календарный шторм — неделя почти съедена встречами."

TREND_UP = "За квартал встречи <b>набирают высоту</b> — небо плотнее."
TREND_DOWN = "За квартал встречи <b>ползут вниз</b> — небо светлеет."
TREND_FLAT = "За квартал нагрузка <b>держится на одной высоте</b>."

COMPARE_PREVIOUS_LIGHTER = "Прошлая неделя была легче на <b>{delta}</b> встреч."
COMPARE_PREVIOUS_DENSER = "Прошлая неделя была плотнее на <b>{delta}</b> встреч."
COMPARE_SAME = "Плановая нагрузка почти как на прошлой неделе."

OVERLAPS_LINE = "⚠️ <b>{count}</b>; больше всего — {day} ({day_count})."
QUALITY_UNVERIFIED = (
    "⚠️ Статус участия не удалось проверить для <b>{count}</b> за 13 недель; "
    "они учтены как календарные блоки."
)

SUMMARY_LINE = (
    "<b>{busy}</b> во встречах · <b>{free}</b> свободно · "
    "загрузка <b>{load}%</b> <i>(было {prev_load}%)</i>"
)
SCOPE_LINE = "<i>План Пн–Пт целиком, включая будущие встречи.</i>"

# Rich Message: таблица в подписи (``rich_caption``)
RICH_TABLE_HEADER_METRIC = ""
RICH_TABLE_HEADER_THIS_WEEK = "Эта неделя"
RICH_TABLE_HEADER_LAST_WEEK = "Прошлая"
RICH_TABLE_ROW_BUSY = "Занято"
RICH_TABLE_ROW_FREE = "Свободно"
RICH_TABLE_ROW_LOAD = "Загрузка"
RICH_WEEK_LABEL = "План недели {start}–{end}"
