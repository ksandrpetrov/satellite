"""User-facing UI для персональных исключений встреч."""

from __future__ import annotations

from .settings_ui import CB_SETTINGS_CALENDAR_MENU

CB_MEX_PREFIX = "mex:"

MEX_CALLBACK_TOGGLE_PREFIX = f"{CB_MEX_PREFIX}t:"
MEX_CALLBACK_RESET_PREFIX = f"{CB_MEX_PREFIX}r:"
MEX_CALLBACK_PAGE_PREFIX = f"{CB_MEX_PREFIX}p:"
MEX_CALLBACK_REFRESH = f"{CB_MEX_PREFIX}refresh"
MEX_CALLBACK_CLEAR = f"{CB_MEX_PREFIX}clear"

MEETING_EXCLUSIONS_TITLE = "🚫 Исключения встреч"
MEETING_EXCLUSIONS_LOADING_HTML = "⏳ Собираю встречи ближайшей недели…"
MEETING_EXCLUSIONS_REFRESH_TOAST = "Обновляю список…"
MEETING_EXCLUSIONS_SAVED_TOAST = "Сохранено"
MEETING_EXCLUSIONS_RESET_TOAST = "Правило сброшено"
MEETING_EXCLUSIONS_CLEARED_TOAST = "Личные исключения сброшены"
MEETING_EXCLUSIONS_STALE_TEXT = (
    "Список встреч уже изменился. Чайка обновила его — выбери встречу ещё раз."
)
MEETING_EXCLUSIONS_CALENDAR_ERROR_TEXT = (
    "⚠️ Не удалось загрузить встречи недели.\n"
    "Проверь календарь или попробуй обновить список чуть позже."
)
MEETING_EXCLUSIONS_SETTINGS_ERROR_TEXT = (
    "⚠️ Не удалось прочитать настройки исключений.\n"
    "Чайка ничего не изменила — попробуй ещё раз чуть позже."
)
MEETING_EXCLUSIONS_SAVE_ERROR_TEXT = (
    "⚠️ Не удалось сохранить исключение.\nПрежние настройки остались без изменений."
)
MEETING_EXCLUSIONS_LIMIT_TEXT = (
    "Можно сохранить не больше 50 личных правил. Сбрось ненужное правило и попробуй снова."
)


def meeting_exclusions_screen_text(
    *,
    week_count: int,
    saved_outside_week_count: int,
    page: int,
    page_count: int,
    truncated: bool = False,
) -> str:
    """Fallback HTML экрана исключений."""
    if week_count:
        intro = (
            "Нажми встречу, чтобы учитывать её в дайджестах или исключить. "
            "🚫 — исключена, ✅ — учитывается."
        )
    else:
        intro = "В календарях нет подходящих встреч на ближайшие 7 дней."
    blocks = [f"<b>{MEETING_EXCLUSIONS_TITLE}</b>", intro]
    if saved_outside_week_count:
        blocks.append(
            "↩️ — сохранённое правило для встречи вне этой недели. "
            "Нажатие вернёт системное поведение."
        )
    if truncated:
        blocks.append("Показаны первые 200 уникальных названий.")
    if page_count > 1:
        blocks.append(f"Страница {page + 1} из {page_count}.")
    return "\n\n".join(blocks)


def _short_button_title(title: str, *, limit: int = 42) -> str:
    clean = " ".join((title or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1].rstrip()}…"


def build_meeting_exclusions_keyboard(
    *,
    rows: list[tuple[str, str, bool, bool]],
    page: int,
    page_count: int,
    has_overrides: bool,
) -> dict:
    """Клавиатура списка.

    ``rows``: ``(title, token, excluded, reset_only)``. Полное название
    используется только в подписи кнопки; callback содержит короткий token.
    """
    keyboard: list[list[dict[str, str]]] = []
    for title, token, excluded, reset_only in rows:
        marker = "🚫" if excluded else "✅"
        reset_marker = "↩️ " if reset_only else ""
        action = MEX_CALLBACK_RESET_PREFIX if reset_only else MEX_CALLBACK_TOGGLE_PREFIX
        keyboard.append(
            [
                {
                    "text": f"{reset_marker}{marker} {_short_button_title(title)}",
                    "callback_data": f"{action}{token}:{page}",
                }
            ]
        )

    if page_count > 1:
        nav: list[dict[str, str]] = []
        if page > 0:
            nav.append(
                {
                    "text": "←",
                    "callback_data": f"{MEX_CALLBACK_PAGE_PREFIX}{page - 1}",
                }
            )
        nav.append(
            {
                "text": f"{page + 1}/{page_count}",
                "callback_data": f"{MEX_CALLBACK_PAGE_PREFIX}{page}",
            }
        )
        if page + 1 < page_count:
            nav.append(
                {
                    "text": "→",
                    "callback_data": f"{MEX_CALLBACK_PAGE_PREFIX}{page + 1}",
                }
            )
        keyboard.append(nav)

    actions = [{"text": "🔄 Обновить", "callback_data": MEX_CALLBACK_REFRESH}]
    if has_overrides:
        actions.append({"text": "🧹 Сбросить личные", "callback_data": MEX_CALLBACK_CLEAR})
    keyboard.append(actions)
    keyboard.append([{"text": "⬅️ В календарь", "callback_data": CB_SETTINGS_CALENDAR_MENU}])
    return {"inline_keyboard": keyboard}


def build_meeting_exclusions_error_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🔄 Попробовать снова", "callback_data": MEX_CALLBACK_REFRESH}],
            [{"text": "⬅️ В календарь", "callback_data": CB_SETTINGS_CALENDAR_MENU}],
        ]
    }
