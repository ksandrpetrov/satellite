"""Выбор шаблонных текстов «чайки» по метрикам дня.

Все ветвления — простые if/elif. Никаких внешних сервисов или LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..calendar.stats import DayCalendarStats
from . import templates as t


@dataclass(frozen=True)
class SeagullTexts:
    """Готовые куски текста для последующей сборки сообщения."""

    main: str
    overlaps: str | None = None


def build_seagull_texts(stats: DayCalendarStats) -> SeagullTexts:
    return SeagullTexts(
        main=_main_text(stats),
        overlaps=_overlap_text(stats),
    )


def _main_text(stats: DayCalendarStats) -> str:
    busy = stats.busy_minutes
    if busy == 0:
        return t.MAIN_EMPTY
    if busy <= 120:
        return t.MAIN_LIGHT
    if busy <= 240:
        return t.MAIN_NORMAL
    if busy <= 360:
        return t.MAIN_DENSE
    return t.MAIN_STORM


def _overlap_text(stats: DayCalendarStats) -> str | None:
    if stats.meetings_count == 0:
        return None
    if stats.overlaps_count == 0:
        return t.OVERLAP_NONE
    if stats.overlaps_count == 1:
        return t.OVERLAP_ONE
    return t.OVERLAP_MANY
