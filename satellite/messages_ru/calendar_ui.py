"""User-facing strings — календарные сценарии: upcoming, create, sources, foreign, invitations, manage."""

from __future__ import annotations

from .buttons import (
    BUTTON_CONNECT_CALENDAR,
    BUTTON_CREATE_CANCEL,
    BUTTON_CREATE_CONFIRM,
    BUTTON_CREATE_EVENT,
    BUTTON_DAY_AFTER,
    BUTTON_FOREIGN_CALENDARS,
    BUTTON_INVITATIONS,
    BUTTON_MANAGE_EVENTS,
    BUTTON_RECONNECT_CALENDAR,
    BUTTON_SETTINGS,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    BUTTON_UPCOMING,
    styled_button,
)
from .identity import BOT_INPUT_PLACEHOLDER

UPCOMING_FETCH_STATUS = "🗓 Чайка обходит ближайшую неделю…"
UPCOMING_BUSY_TEXT = "🗓 Уже собираю список — секунду."
UPCOMING_EMPTY_HTML = (
    "🗓 На ближайшие дни встреч нет.\nНебо чистое — самое время для глубокой работы."
)


CREATE_EVENT_ASK_TITLE = "➕ Как назвать встречу? Напиши одной строкой."
CREATE_EVENT_ASK_DATE = (
    "📅 На какой день? Жми кнопку ниже или напиши:\n"
    "<i>20.05.2026</i> · <i>«сегодня»</i> · <i>«завтра»</i>"
)
CREATE_EVENT_ASK_TIME = (
    "🕘 Во сколько начинаем? Можно так: <i>09:30</i>, <i>9:30</i> или <i>9 30</i>."
)
CREATE_EVENT_ASK_DURATION = (
    "⏱ Сколько минут? Жми пресет ниже или напиши число — например, <i>45</i>."
)
CREATE_EVENT_CONFIRM_HTML = (
    "🪶 Чайка готова занести в календарь:\n<b>{title}</b>\n{date} · {start}–{end}\n\nВсё верно?"
)
CREATE_EVENT_INVALID_DATE = (
    "⚠️ Чайка не разобрала дату.\n"
    "Попробуй ещё раз: <i>20.05.2026</i>, <i>«сегодня»</i> или <i>«завтра»</i>."
)
CREATE_EVENT_INVALID_TIME = (
    "⚠️ Чайка не разобрала время.\nФормат: <i>09:30</i>, <i>9:30</i> или <i>9 30</i>."
)
CREATE_EVENT_INVALID_DURATION = "⚠️ Длительность — числом минут. Например, <i>30</i> или <i>60</i>."
CREATE_EVENT_CREATING_HTML = "⏳ Чайка заносит событие в календарь…"
CREATE_EVENT_SUCCESS_HTML = "✅ Чайка занесла встречу в календарь. Готово."
CREATE_EVENT_FAILED_HTML = (
    "⚠️ Не получилось создать встречу.\n"
    "Чайка просит проверить: у пароля приложения должно быть право на запись в календарь. "
    "Если не помогло — попробуй переподключить календарь в настройках."
)
CREATE_EVENT_CANCELLED_HTML = "🪶 Чайка сложила черновик. Встреча не создана."
CREATE_EVENT_CREATING_TOAST = "Создаю…"
CREATE_EVENT_ALREADY_CREATING_TOAST = "Уже создаём…"
CREATE_EVENT_DONE_TOAST = "Готово"
CREATE_EVENT_DONE_SHORT = "✅ Готово."

CB_CREATE_CONFIRM = "create:confirm"
CB_CREATE_CANCEL = "create:cancel"
CB_CREATE_DATE_TODAY = "create:date:today"
CB_CREATE_DATE_TOMORROW = "create:date:tomorrow"
CB_CREATE_DURATION_PREFIX = "create:dur:"
CREATE_EVENT_DURATION_PRESETS_MIN: tuple[int, ...] = (15, 30, 45, 60)
CREATE_DATE_ALIAS_TODAY = frozenset({"сегодня", "today"})
CREATE_DATE_ALIAS_TOMORROW = frozenset({"завтра", "tomorrow"})


def build_create_date_keyboard() -> dict:
    """Inline-кнопки «сегодня/завтра» для шага выбора даты в /create.

    Пользователь всё ещё может ввести любую дату текстом — кнопки лишь
    ускоряют типичные сценарии. Поэтому клавиатуру отправляем под вопросом
    о дате, а text-handler в FSM не трогаем.
    """
    return {
        "inline_keyboard": [
            [
                {"text": BUTTON_TODAY, "callback_data": CB_CREATE_DATE_TODAY},
                {"text": BUTTON_TOMORROW, "callback_data": CB_CREATE_DATE_TOMORROW},
            ]
        ]
    }


def build_create_confirm_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                styled_button(BUTTON_CREATE_CONFIRM, CB_CREATE_CONFIRM, style="success"),
                styled_button(BUTTON_CREATE_CANCEL, CB_CREATE_CANCEL, style="danger"),
            ]
        ]
    }


def build_create_duration_keyboard() -> dict:
    """Inline-кнопки 15/30/45/60 минут для шага длительности в /create.

    Подписи в callback_data — числа в минутах, что упрощает парсинг. Длина
    каждой callback_data короче 64 байт, как требует Telegram. Ввод текстом
    остаётся валидным каналом для любых нестандартных длительностей.
    """
    row = [
        {
            "text": f"{minutes} мин",
            "callback_data": f"{CB_CREATE_DURATION_PREFIX}{minutes}",
        }
        for minutes in CREATE_EVENT_DURATION_PRESETS_MIN
    ]
    return {"inline_keyboard": [row]}


# --- выбор календарей для плана --------------------------------------------

CB_CAL_SOURCES = "cal_sources"
CB_CAL_TOGGLE_PREFIX = "cal:t:"
CB_CAL_CLOSE = "cal:close"

CALENDAR_SOURCES_SINGLE_HTML = "📚 В аккаунте всего один календарь — выбирать тут пока нечего."
CALENDAR_SOURCES_LAST_ENABLED_TEXT = (
    "Нужен хотя бы один календарь — иначе плану неоткуда брать встречи."
)
CALENDAR_SOURCES_LOAD_FAIL_HTML = (
    "⚠️ Чайка не смогла принести список календарей.\nПопробуй ещё раз через минуту."
)
CALENDAR_SOURCES_UNAVAILABLE_TEXT = "Календари не отвечают"
CALENDAR_SOURCES_UPDATE_FAIL_TEXT = "Не удалось обновить список"
CALENDAR_SOURCES_FETCH_STATUS = "📚 Чайка собирает календари…"
CALENDAR_SOURCES_CLOSED_TEXT = "📚 Закрыли список календарей. Возвращайся, когда понадобится."


def calendar_sources_screen_text(*, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "—"
    return (
        "📚 <b>Календари в плане</b>\n\n"
        "Чайка учитывает встречи только из отмеченных календарей. "
        "Это касается плана дня, утреннего дайджеста и «Ближайших».\n\n"
        f"{body}\n\n"
        "<i>Тапни строку, чтобы включить или выключить.</i>"
    )


def calendar_sources_toggle_notice(*, enabled: bool, name: str) -> str:
    state = "в плане" if enabled else "выключен"
    return f"«{name}» {state}"


def build_calendar_sources_keyboard(
    *,
    calendars: list[tuple[str, str]],
    enabled_urls: set[str],
    url_tokens: list[str],
) -> dict:
    # Lazy: реальный цикл calendar.events._collectors → messages_ru →
    # calendar_ui → calendar.selection → providers → caldav_client → events.
    from ..calendar.selection import normalize_calendar_url

    rows: list[list[dict[str, str]]] = []
    for (name, url), token in zip(calendars, url_tokens):
        mark = "✅" if normalize_calendar_url(url) in enabled_urls else "⬜️"
        label = f"{mark} {name}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([{"text": label, "callback_data": f"{CB_CAL_TOGGLE_PREFIX}{token}"}])
    rows.append([{"text": "⬅️ В Календарь", "callback_data": CB_CAL_CLOSE}])
    return {"inline_keyboard": rows}


# --- чужие (пошаренные) календари ------------------------------------------

CB_FOREIGN_PICK_PREFIX = "foreign:p:"
CB_FOREIGN_DAY_PREFIX = "foreign:d:"
CB_FOREIGN_BACK = "foreign:back"
CB_FOREIGN_CLOSE = "foreign:close"

FOREIGN_CALENDARS_LOADING_TOAST = "Загружаю…"
FOREIGN_CALENDARS_INTRO_HTML = (
    "👥 <b>Чужие календари</b>\n\n"
    "Календари коллег, которые открыты на твою почту в Mail.ru или Яндексе. "
    "Чайка может посмотреть в них одним глазом — выбери календарь, потом день."
)
FOREIGN_CALENDARS_EMPTY_HTML = (
    "👥 Пока ни одного чужого календаря.\n\n"
    "Попроси коллегу открыть доступ к своему календарю на твою почту "
    "(в настройках Mail.ru или Яндекс Календаря) — после этого он появится в этом списке."
)
FOREIGN_CALENDARS_LOAD_FAIL_HTML = (
    "⚠️ Чайка не смогла принести список чужих календарей.\nПопробуй ещё раз через минуту."
)
FOREIGN_CALENDARS_REFRESH_FAIL_TEXT = "Не удалось обновить список"
FOREIGN_CALENDARS_CLOSED_TEXT = "👥 Закрыли чужие календари. Возвращайся, когда понадобится."
FOREIGN_CALENDARS_FETCH_STATUS = "⏳ Чайка облетает чужой календарь…"
FOREIGN_CALENDARS_DAY_EMPTY_HTML = "🪶 В этот день встреч у коллеги нет."


def foreign_calendars_pick_day_text(*, calendar_name: str) -> str:
    return f"👥 <b>{calendar_name}</b>\n\nКакой день посмотреть?"


def foreign_calendars_day_result_text(*, calendar_name: str, body_lines: list[str]) -> str:
    body = "\n".join(body_lines)
    return f"👥 <b>{calendar_name}</b>\n\n{body}"


def build_foreign_calendars_keyboard(
    *,
    calendars: list[tuple[str, str]],
    url_tokens: list[str],
) -> dict:
    rows: list[list[dict[str, str]]] = []
    for (name, _url), token in zip(calendars, url_tokens):
        label = name if len(name) <= 60 else name[:57] + "…"
        rows.append([{"text": label, "callback_data": f"{CB_FOREIGN_PICK_PREFIX}{token}"}])
    rows.append([{"text": "⬅️ Закрыть", "callback_data": CB_FOREIGN_CLOSE}])
    return {"inline_keyboard": rows}


def build_foreign_day_keyboard(*, calendar_token: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": BUTTON_TODAY,
                    "callback_data": f"{CB_FOREIGN_DAY_PREFIX}{calendar_token}:0",
                },
                {
                    "text": BUTTON_TOMORROW,
                    "callback_data": f"{CB_FOREIGN_DAY_PREFIX}{calendar_token}:1",
                },
            ],
            [
                {
                    "text": BUTTON_DAY_AFTER,
                    "callback_data": f"{CB_FOREIGN_DAY_PREFIX}{calendar_token}:2",
                },
            ],
            [{"text": "⬅️ К списку", "callback_data": CB_FOREIGN_BACK}],
        ]
    }


def build_webapp_connect_keyboard(webapp_url: str, *, reconnect: bool = False) -> dict:
    """Inline-кнопка Web App для подключения календаря.

    Reply-клавиатура с ``web_app`` не передаёт ``initData`` (см. Telegram
    WebAppInitData) — API календаря в connect.html не сможет авторизовать
    запрос. Inline и menu button передают сессию; настройки уже используют
    inline — здесь тот же формат.
    """
    label = BUTTON_RECONNECT_CALENDAR if reconnect else BUTTON_CONNECT_CALENDAR
    return {
        "inline_keyboard": [[{"text": label, "web_app": {"url": webapp_url}}]],
    }


def build_approved_main_keyboard() -> dict:
    """Главная клавиатура.

    Сгруппирована по смыслу: верхний ряд — план дня (сегодня/завтра),
    второй ряд — расширенные виды, третий — действия с встречами,
    четвёртый — создание встречи и настройки в одном ряду.
    """
    return {
        "keyboard": [
            [{"text": BUTTON_TODAY}, {"text": BUTTON_TOMORROW}],
            [{"text": BUTTON_UPCOMING}, {"text": BUTTON_INVITATIONS}],
            [{"text": BUTTON_MANAGE_EVENTS}, {"text": BUTTON_FOREIGN_CALENDARS}],
            [{"text": BUTTON_CREATE_EVENT}, {"text": BUTTON_SETTINGS}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": BOT_INPUT_PLACEHOLDER,
    }
