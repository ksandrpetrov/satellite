"""Персональная политика исключения событий по точному названию."""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import LUNCH_EMOJI_MARKER, SYSTEM_EVENT_TITLE_PHRASES

_MEAL_TITLE_WORDS = ("завтрак", "обед", "ужин")
_NORMALIZED_SYSTEM_EVENT_TITLE_PHRASES = tuple(
    " ".join(phrase.split()).casefold() for phrase in SYSTEM_EVENT_TITLE_PHRASES
)


def normalize_event_title(title: str) -> str:
    """Нормализует title для точного сопоставления пользовательского правила."""
    return " ".join(str(title or "").split()).casefold()


def _is_pizza_meal_title(normalized_title: str) -> bool:
    return LUNCH_EMOJI_MARKER in normalized_title and any(
        word in normalized_title for word in _MEAL_TITLE_WORDS
    )


def _is_system_title(normalized_title: str) -> bool:
    return any(phrase in normalized_title for phrase in _NORMALIZED_SYSTEM_EVENT_TITLE_PHRASES)


def default_is_excluded(title: str) -> bool:
    """Возвращает встроенное состояние при стандартном скрытии приёмов пищи."""
    normalized = normalize_event_title(title)
    if not normalized:
        return False
    return _is_pizza_meal_title(normalized) or _is_system_title(normalized)


@dataclass(frozen=True)
class EventTitleOverride:
    """Явное пользовательское состояние для одного точного названия."""

    title: str
    excluded: bool


@dataclass(frozen=True)
class EventExclusionPolicy:
    """Эффективные правила пользователя поверх встроенных исключений."""

    overrides: tuple[EventTitleOverride, ...] = ()
    exclude_meals_by_default: bool = True
    _override_states: dict[str, bool] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        ordered: dict[str, EventTitleOverride] = {}
        for override in self.overrides:
            normalized = normalize_event_title(override.title)
            if not normalized:
                continue
            ordered[normalized] = EventTitleOverride(
                title=override.title,
                excluded=bool(override.excluded),
            )
        normalized_overrides = tuple(ordered.values())
        object.__setattr__(self, "overrides", normalized_overrides)
        object.__setattr__(
            self,
            "_override_states",
            {
                normalize_event_title(override.title): override.excluded
                for override in normalized_overrides
            },
        )

    def default_is_excluded(self, title: str) -> bool:
        """Встроенное состояние title с учётом настройки meal-фильтра."""
        normalized = normalize_event_title(title)
        if not normalized:
            return False
        if _is_system_title(normalized):
            return True
        return self.exclude_meals_by_default and _is_pizza_meal_title(normalized)

    def is_excluded(self, title: str) -> bool:
        """Возвращает эффективное состояние после точного пользовательского override."""
        normalized = normalize_event_title(title)
        if not normalized:
            return False
        override = self._override_states.get(normalized)
        if override is not None:
            return override
        return self.default_is_excluded(title)


__all__ = [
    "EventExclusionPolicy",
    "EventTitleOverride",
    "default_is_excluded",
    "normalize_event_title",
]
