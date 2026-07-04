"""User-facing strings — хаб настроек, аналитика, подэкран «Календарь», ошибки handler.

Сценарии дайджестов — в ``digest_ui``, ответы на встречи — в ``meetings_ui``.
"""

from __future__ import annotations

from ..presentation.html import blockquote, build_copy_text_button
from .buttons import (
    BUTTON_CALENDAR_SOURCES,
    BUTTON_CHECK_CALENDAR,
    BUTTON_CONNECT_CALENDAR,
    BUTTON_COPY_EMAIL,
    BUTTON_DISCONNECT_CALENDAR,
    BUTTON_INVITATIONS,
    BUTTON_RECONNECT_CALENDAR,
)

CB_SETTINGS_DIGEST = "settings_digest"
CB_SETTINGS_ANALYTICS = "settings_analytics"
# Подэкран «Календарь» — группирует управление подключением и календарями в плане
CB_SETTINGS_CALENDAR_MENU = "settings_calendar_menu"
CB_SETTINGS_CALENDARS = "settings_calendars"
CB_SETTINGS_INVITATIONS = "settings_invitations"
CB_SETTINGS_CHECK = "settings_check"
CB_SETTINGS_RECONNECT = "settings_reconnect"
# Двухшаговое отключение календаря: сначала подтверждение, потом сам disconnect
CB_SETTINGS_DISCONNECT = "settings_disconnect"
CB_SETTINGS_DISCONNECT_CONFIRM = "settings_disconnect_confirm"
CB_SETTINGS_BACK = "settings_back"
CB_SETTINGS_CLOSE = "settings_close"
CB_SETTINGS_WEATHER_TOGGLE = "settings_weather_toggle"
# Вход в настройки pending-дайджеста с хаба; остальные CB_PENDING_* — в digest_ui.
CB_PENDING_DIGEST_SETTINGS = "pending_digest_settings"

WEATHER_IN_PLAN_SAVED_TOAST = "Сохранено"

CB_ANALYTICS_RUN = "analytics:run"
CB_ANALYTICS_WORKDAY_9 = "analytics:wd:9-18"
CB_ANALYTICS_WORKDAY_10 = "analytics:wd:10-19"
CB_ANALYTICS_BACK = "analytics:back"

CALENDAR_DISCONNECT_TOAST = "Отключено"
CALENDAR_DISCONNECT_LOADING_HTML = "⏳ Отключаю календарь…"
ANALYTICS_SAVED_TOAST = "Сохранено"
ANALYTICS_BUSY_TOAST = "Уже строю отчёт — подожди немного"

BUTTON_ANALYTICS = "📊 Аналитика недели"
BUTTON_CALENDAR_MENU = "📅 Календарь"


def settings_hub_text(
    *,
    digest_enabled: bool | None = None,
    pending_digest_enabled: bool | None = None,
    weather_in_plan_enabled: bool | None = None,
    has_calendar: bool = True,
) -> str:
    status_bits: list[str] = []
    if digest_enabled is not None:
        status_bits.append(
            "🔔 Дайджест на сегодня включён"
            if digest_enabled
            else "🔕 Дайджест на сегодня выключен"
        )
    if pending_digest_enabled is not None:
        status_bits.append(
            "📨 Дайджест непринятых включён"
            if pending_digest_enabled
            else "📨 Дайджест непринятых выключен"
        )
    if weather_in_plan_enabled is not None:
        status_bits.append(
            "🌤 Погода в плане включена"
            if weather_in_plan_enabled
            else "🔕 Погода в плане выключена"
        )
    if has_calendar:
        status_bits.append("📅 Календарь подключён")
    else:
        status_bits.append("🔌 Календарь не подключён")
    summary = blockquote(" · ".join(status_bits)) if status_bits else ""
    base = (
        "⚙️ <b>Настройки Чайки</b>\n\n"
        "Здесь живут дайджесты, погода в плане, аналитика и календарь. Выбери, что настроить."
    )
    if summary:
        return f"{base}\n\n{summary}"
    return base


SETTINGS_HUB_TEXT = settings_hub_text()
SETTINGS_HUB_NO_CALENDAR_HINT = (
    "🔌 Календарь ещё не подключён — без него Чайке нечего показывать.\n"
    "Жми «Подключить календарь» ниже — откроется защищённое окно."
)

ANALYTICS_FETCH_STATUS = "📊 Чайка сводит неделю по календарю…"
ANALYTICS_OPTIONS_TEXT = (
    "📊 <b>Аналитика недели</b>\n\n"
    "Рабочий день для расчёта занятости: <b>{workday}</b>.\n"
    "Жми «Построить отчёт» — Чайка пришлёт картинку с графиком и сводкой по последним семи дням."
)
ANALYTICS_WORKDAY_APPLIED_TEXT = (
    "📊 Рабочий день для аналитики обновлён.\n"
    "Жми «Построить отчёт» — Чайка пересчитает по новым границам."
)


def analytics_options_screen_text(*, workday_preset: str) -> str:
    label = "9:00–18:00" if workday_preset == "9-18" else "10:00–19:00"
    return ANALYTICS_OPTIONS_TEXT.format(workday=label)


def build_analytics_options_keyboard(*, workday_preset: str) -> dict:
    wd9 = "✅ 9:00–18:00" if workday_preset == "9-18" else "9:00–18:00"
    wd10 = "✅ 10:00–19:00" if workday_preset == "10-19" else "10:00–19:00"
    return {
        "inline_keyboard": [
            [{"text": "📊 Построить отчёт", "callback_data": "analytics:run"}],
            [
                {"text": wd9, "callback_data": "analytics:wd:9-18"},
                {"text": wd10, "callback_data": "analytics:wd:10-19"},
            ],
            [{"text": "⬅️ В настройки", "callback_data": "analytics:back"}],
        ]
    }


SETTINGS_HUB_CLOSED_TEXT = (
    "🪶 Чайка свернула настройки. Кнопка «Настройки» всегда рядом — на главной клавиатуре."
)


def weather_in_plan_toggle_button_text(*, enabled: bool) -> str:
    return "🔕 Выключить погоду в плане" if enabled else "🌤 Включить погоду в плане"


def weather_in_plan_toggle_notice_text(*, enabled: bool) -> str:
    if enabled:
        return "🌤 Погода снова будет в плане и дайджесте на сегодня."
    return "🔕 Погоду в плане и дайджесте на сегодня отключил — только календарь."


def build_settings_hub_keyboard(
    *,
    webapp_url: str,
    has_calendar: bool,
    weather_in_plan_enabled: bool = True,
    calendar_login: str | None = None,
) -> dict:
    """Главный экран настроек.

    Структура: три раздела (Дайджест, Аналитика, Календарь). Управление
    подключением и календарями в плане спрятано во вложенный экран
    «Календарь» — это уменьшает число кнопок на главном экране и убирает
    деструктивный «Отключить» из зоны случайного нажатия.
    """
    rows: list[list[dict[str, object]]] = [
        [{"text": "🔔 Дайджест на сегодня", "callback_data": CB_SETTINGS_DIGEST}],
        [{"text": "📨 Дайджест непринятых встреч", "callback_data": CB_PENDING_DIGEST_SETTINGS}],
        [
            {
                "text": weather_in_plan_toggle_button_text(enabled=weather_in_plan_enabled),
                "callback_data": CB_SETTINGS_WEATHER_TOGGLE,
            }
        ],
    ]
    if has_calendar:
        rows.append([{"text": BUTTON_ANALYTICS, "callback_data": CB_SETTINGS_ANALYTICS}])
        rows.append([{"text": BUTTON_CALENDAR_MENU, "callback_data": CB_SETTINGS_CALENDAR_MENU}])
        if calendar_login:
            rows.append(
                [
                    build_copy_text_button(
                        BUTTON_COPY_EMAIL,
                        calendar_login,
                    )
                ]
            )
    elif webapp_url:
        rows.append([{"text": BUTTON_CONNECT_CALENDAR, "web_app": {"url": webapp_url}}])
    rows.append([{"text": "⬅️ Закрыть", "callback_data": CB_SETTINGS_CLOSE}])
    return {"inline_keyboard": rows}


# --- подэкран «Календарь» ---------------------------------------------------

SETTINGS_CALENDAR_MENU_TEXT = (
    "📅 <b>Календарь</b>\n\nУправление подключением, приглашения и выбор календарей для плана."
)

SETTINGS_DISCONNECT_CONFIRM_TEXT = (
    "🪶 Точно отключить календарь?\n\n"
    "Чайка забудет логин и пароль, но настройки дайджеста и аналитики сохранятся. "
    "Заново подключить можно одной кнопкой."
)
SETTINGS_DISCONNECT_CANCEL_TEXT = "🪶 Отбой — календарь на месте."
BUTTON_DISCONNECT_CALENDAR_CONFIRM = "⚠️ Да, отключить"
BUTTON_DISCONNECT_CALENDAR_CANCEL = "⬅️ Отмена"


def build_settings_calendar_menu_keyboard(*, webapp_url: str) -> dict:
    rows: list[list[dict[str, str | dict[str, str]]]] = [
        [{"text": BUTTON_INVITATIONS, "callback_data": CB_SETTINGS_INVITATIONS}],
        [{"text": BUTTON_CALENDAR_SOURCES, "callback_data": CB_SETTINGS_CALENDARS}],
        [{"text": BUTTON_CHECK_CALENDAR, "callback_data": CB_SETTINGS_CHECK}],
    ]
    if webapp_url:
        rows.append([{"text": BUTTON_RECONNECT_CALENDAR, "web_app": {"url": webapp_url}}])
    rows.append([{"text": BUTTON_DISCONNECT_CALENDAR, "callback_data": CB_SETTINGS_DISCONNECT}])
    rows.append([{"text": "⬅️ В настройки", "callback_data": CB_SETTINGS_BACK}])
    return {"inline_keyboard": rows}


def build_settings_disconnect_confirm_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": BUTTON_DISCONNECT_CALENDAR_CONFIRM,
                    "callback_data": CB_SETTINGS_DISCONNECT_CONFIRM,
                }
            ],
            [
                {
                    "text": BUTTON_DISCONNECT_CALENDAR_CANCEL,
                    "callback_data": CB_SETTINGS_CALENDAR_MENU,
                }
            ],
        ]
    }


# --- ошибки handler'ов -------------------------------------------------------

ERR_CALDAV_UNAVAILABLE_TEXT = (
    "⚠️ Календарь не отвечает.\nЧайка попробует снова через минуту — попытайся ещё раз."
)

ERR_DIGEST_BUILD_FAILED_TEXT = (
    "⚠️ Чайка вернулась без сводки.\n\n"
    "Крылья целы, но календарь сейчас не отвечает. Попробуй ещё раз чуть позже."
)

ERR_SETTINGS_SAVE_FAILED_TEXT = (
    "⚠️ Не удалось сохранить настройки.\nЧайка попробует снова при следующем действии."
)
ERR_USERS_SAVE_FAILED_TEXT = ERR_SETTINGS_SAVE_FAILED_TEXT

# Универсальный текст для непредвиденных ошибок в диспетчере: пользователь
# должен получить какой-то ответ, чтобы не казалось, что бот «съел» команду.
# Никаких техдеталей — стек только в логе.
ERR_GENERIC_HANDLER_TEXT = (
    "⚠️ Что-то пошло не так. Чайка уже разбирается — попробуй ещё раз через минуту."
)
