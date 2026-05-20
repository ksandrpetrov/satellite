# -*- coding: utf-8 -*-
"""Пользовательские тексты на русском.

Меняй формулировки здесь — логика скриптов не требует правок.
Плейсхолдеры в фигурных скобках подставляются кодом, не удаляй их без необходимости.
"""

from __future__ import annotations

import unicodedata

# Реэкспорт доменных констант календаря: сами строки теперь живут в
# ``satellite.calendar.constants``, чтобы календарь не зависел от слоя UI.
from .calendar.constants import (
    LUNCH_EMOJI_MARKER,
    LUNCH_TEXT_MARKER,
    PLAN_ALL_DAY_LABEL,
)

# --- Telegram: подписи кнопок ---
BUTTON_TODAY = "📅 Сегодня"
BUTTON_TOMORROW = "➡️ Завтра"
BUTTON_DAY_AFTER = "⏭ Послезавтра"
BUTTON_UPCOMING = "🗓 Ближайшие события"
BUTTON_CREATE_EVENT = "➕ Создать событие"
BUTTON_SUBSCRIBE = "🔔 Подписаться на дайджест"
BUTTON_UNSUBSCRIBE = "🔕 Отключить дайджест"
BUTTON_UNSUBSCRIBE_LEGACY = "🔕 Отписаться от дайджеста"
BUTTON_SETTINGS = "⚙️ Настройки"
BUTTON_DIGEST_SETTINGS = "⚙️ Настройки дайджеста"  # legacy reply-кнопка
BUTTON_CONNECT_CALENDAR = "🔌 Подключить календарь"
BUTTON_RECONNECT_CALENDAR = "🔄 Переподключить календарь"
BUTTON_DISCONNECT_CALENDAR = "🗑 Отключить календарь"
BUTTON_CHECK_CALENDAR = "✅ Проверить подключение"
BUTTON_CALENDAR_SOURCES = "📚 Календари"
BUTTON_FOREIGN_CALENDARS = "👥 Чужие календари"

BUTTON_TO_PLAN_MODE: dict[str, str] = {
    BUTTON_TODAY: "today",
    BUTTON_TOMORROW: "tomorrow",
    BUTTON_DAY_AFTER: "day_after_tomorrow",
}


_VARIATION_SELECTORS_RANGE = (0xFE00, 0xFE0F)


def _is_invisible_combining(ch: str) -> bool:
    code = ord(ch)
    if _VARIATION_SELECTORS_RANGE[0] <= code <= _VARIATION_SELECTORS_RANGE[1]:
        return True
    return unicodedata.category(ch) == "Cf"


def normalize_button_text(text: str | None) -> str:
    """Нормализует текст кнопки: NFKC + strip + удаление variation selectors / ZWJ.

    Telegram иногда добавляет/убирает невидимые селекторы вариаций (U+FE0F и др.)
    у эмодзи, что ломает прямое сравнение строк.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).strip()
    return "".join(ch for ch in normalized if not _is_invisible_combining(ch))


_NORMALIZED_BUTTON_TO_MODE: dict[str, str] = {
    normalize_button_text(label): mode for label, mode in BUTTON_TO_PLAN_MODE.items()
}

_NORMALIZED_BUTTON_SUBSCRIBE = normalize_button_text(BUTTON_SUBSCRIBE)
_NORMALIZED_BUTTON_UNSUBSCRIBE = {
    normalize_button_text(BUTTON_UNSUBSCRIBE),
    normalize_button_text(BUTTON_UNSUBSCRIBE_LEGACY),
}
_NORMALIZED_BUTTON_SETTINGS = normalize_button_text(BUTTON_SETTINGS)
_NORMALIZED_BUTTON_DIGEST_SETTINGS = normalize_button_text(BUTTON_DIGEST_SETTINGS)
_NORMALIZED_BUTTON_UPCOMING = normalize_button_text(BUTTON_UPCOMING)
_NORMALIZED_BUTTON_CREATE_EVENT = normalize_button_text(BUTTON_CREATE_EVENT)
_NORMALIZED_BUTTON_CONNECT = normalize_button_text(BUTTON_CONNECT_CALENDAR)
_NORMALIZED_BUTTON_RECONNECT = normalize_button_text(BUTTON_RECONNECT_CALENDAR)
_NORMALIZED_BUTTON_DISCONNECT = normalize_button_text(BUTTON_DISCONNECT_CALENDAR)
_NORMALIZED_BUTTON_CHECK = normalize_button_text(BUTTON_CHECK_CALENDAR)
_NORMALIZED_BUTTON_CALENDAR_SOURCES = normalize_button_text(BUTTON_CALENDAR_SOURCES)
_NORMALIZED_BUTTON_FOREIGN_CALENDARS = normalize_button_text(BUTTON_FOREIGN_CALENDARS)


def button_text_to_mode(text: str | None) -> str | None:
    if not text:
        return None
    return _NORMALIZED_BUTTON_TO_MODE.get(normalize_button_text(text))


def button_text_is_subscribe(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_SUBSCRIBE


def button_text_is_unsubscribe(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) in _NORMALIZED_BUTTON_UNSUBSCRIBE


def button_text_is_settings(text: str | None) -> bool:
    if not text:
        return False
    normalized = normalize_button_text(text)
    return normalized in {
        _NORMALIZED_BUTTON_SETTINGS,
        _NORMALIZED_BUTTON_DIGEST_SETTINGS,
    }


def button_text_is_digest_settings(text: str | None) -> bool:
    """Legacy alias: старая кнопка «Настройки дайджеста» открывает общий экран настроек."""
    return button_text_is_settings(text)


def button_text_is_upcoming(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_UPCOMING


def button_text_is_create_event(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_CREATE_EVENT


def button_text_is_connect_calendar(text: str | None) -> bool:
    if not text:
        return False
    normalized = normalize_button_text(text)
    return normalized in {_NORMALIZED_BUTTON_CONNECT, _NORMALIZED_BUTTON_RECONNECT}


def button_text_is_disconnect_calendar(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_DISCONNECT


def button_text_is_check_calendar(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_CHECK


def button_text_is_calendar_sources(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_CALENDAR_SOURCES


def button_text_is_foreign_calendars(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_FOREIGN_CALENDARS


BOT_INPUT_PLACEHOLDER = "Выбери день, чтобы посмотреть встречи"

# Markup, который вычищает старую нижнюю Reply-клавиатуру у пользователей, у
# которых она ещё висит после миграции на меню команд Telegram. Передаётся
# в ``reply_markup`` обычных сообщений (например, на /start и /help).
REPLY_KEYBOARD_REMOVE: dict = {"remove_keyboard": True}

BOT_WELCOME_HTML = (
    "🪶 Привет. Чайка на связи.\n\n"
    "После одобрения администратором подключите свой календарь через кнопку "
    "«Подключить календарь» — каждый работает только со своим аккаунтом.\n\n"
    "Команды в меню Telegram:\n"
    "📅 /today — встречи на сегодня\n"
    "🗓 /upcoming — ближайшие события\n"
    "👥 «Чужие календари» — встречи в пошаренных календарях\n"
    "➕ /create — создать событие\n"
    "⚙️ /settings — дайджест, календари, подключение\n\n"
    "🍕 Чтобы чайка видела обед, добавь в календарь встречу с эмоджи 🍕 и словом «обед»."
)

BOT_HELP_HTML = (
    "🪶 Как пользоваться Чайкой\n\n"
    "Сначала администратор подтверждает доступ, затем вы подключаете свой "
    "календарь Mail.ru через Web App.\n\n"
    "Команды:\n"
    "📅 /today, /tomorrow, /aftertomorrow — план на день\n"
    "🗓 /upcoming — ближайшие события\n"
    "👥 «Чужие календари» или /foreign — пошаренные календари коллег\n"
    "➕ /create — создать событие\n"
    "⚙️ /settings — дайджест, календари, подключение\n"
    "🔌 /connect — подключить календарь (также в /settings)\n\n"
    "Короткие: <code>td</code>, <code>tm</code>, <code>dat</code>."
)

BOT_KEYBOARD_HINT = (
    "🪶 Не понял команду.\n"
    "Открой меню или используй /today, /upcoming, /create, /settings, /help"
)

# --- Access control ---
ACCESS_REQUEST_SENT_HTML = (
    "📝 Заявка на доступ отправлена администратору.\n"
    "После подтверждения вы сможете подключить календарь."
)
ACCESS_PENDING_HTML = (
    "⏳ Ваша заявка на доступ ещё на рассмотрении.\n"
    "Как только администратор одобрит её — пришлю уведомление."
)
ACCESS_REJECTED_HTML = (
    "🚫 Доступ к боту отклонён.\n"
    "Если это ошибка — свяжитесь с администратором."
)
ACCESS_BLOCKED_HTML = "🚫 Ваш доступ к боту заблокирован."
ACCESS_APPROVED_HTML = (
    "✅ Доступ открыт.\n"
    "Теперь подключите календарь — кнопка «Подключить календарь» ниже."
)
CALENDAR_NOT_CONNECTED_HTML = (
    "🔌 Календарь ещё не подключён.\n"
    "Нажмите «Подключить календарь», чтобы добавить свой сервисный токен."
)
CALENDAR_CONNECTED_HTML = "✅ Календарь подключён."
CALENDAR_DISCONNECTED_HTML = "Календарь отключён."
CALENDAR_CHECK_OK_HTML = "✅ Подключение к календарю работает."
CALENDAR_CHECK_FAIL_HTML = (
    "⚠️ Не удалось проверить подключение. Попробуйте переподключить календарь."
)

ERR_CALENDAR_TOKEN_INVALID = (
    "⚠️ Токен не подошёл. Проверьте, что он создан для календаря и не отозван."
)

# --- Admin ---
CB_ADMIN_APPROVE_PREFIX = "admin:approve:"
CB_ADMIN_REJECT_PREFIX = "admin:reject:"
CMD_PENDING = "/pending"

def admin_access_request_html(
    *, display_name: str | None, username: str | None, telegram_user_id: int
) -> str:
    name = display_name or "—"
    uname = f"@{username}" if username else "—"
    return (
        "👤 Новый пользователь хочет получить доступ:\n"
        f"Имя: {name}\n"
        f"Username: {uname}\n"
        f"Telegram ID: {telegram_user_id}"
    )


def build_admin_access_keyboard(*, telegram_user_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Разрешить",
                    "callback_data": f"{CB_ADMIN_APPROVE_PREFIX}{telegram_user_id}",
                },
                {
                    "text": "❌ Отклонить",
                    "callback_data": f"{CB_ADMIN_REJECT_PREFIX}{telegram_user_id}",
                },
            ]
        ]
    }


def admin_pending_list_html(lines: list[str]) -> str:
    if not lines:
        return "📋 Нет заявок на рассмотрении."
    body = "\n".join(f"• {line}" for line in lines)
    return f"📋 Заявки на доступ:\n{body}"


ADMIN_ACTION_FORBIDDEN_HTML = "⛔️ Эта команда доступна только администратору."

# --- Calendar list / create ---
UPCOMING_FETCH_STATUS = "🗓 Чайка собирает ближайшие события…"
UPCOMING_EMPTY_HTML = "🗓 На ближайшие дни встреч нет."
CREATE_EVENT_ASK_TITLE = "➕ Как назвать событие?"
CREATE_EVENT_ASK_DATE = "📅 На какую дату? Формат: ДД.ММ.ГГГГ или «сегодня» / «завтра»"
CREATE_EVENT_ASK_TIME = "🕘 Во сколько начать? Формат ЧЧ:ММ"
CREATE_EVENT_ASK_DURATION = "⏱ Сколько минут длится? Например: 30 или 60"
CREATE_EVENT_CONFIRM_HTML = (
    "Создать событие?\n"
    "<b>{title}</b>\n"
    "{date} {start}–{end}"
)
CREATE_EVENT_INVALID_DATE = "⚠️ Не понял дату. Пример: 20.05.2026 или «завтра»"
CREATE_EVENT_INVALID_TIME = "⚠️ Не понял время. Формат ЧЧ:ММ"
CREATE_EVENT_INVALID_DURATION = "⚠️ Укажите длительность в минутах, например 60"
CREATE_EVENT_CREATING_HTML = "⏳ Создаю событие в календаре…"
CREATE_EVENT_SUCCESS_HTML = "✅ Событие создано в вашем календаре."
CREATE_EVENT_FAILED_HTML = (
    "⚠️ Не удалось создать событие в календаре.\n"
    "Проверьте, что у пароля приложения есть право записи в календарь, "
    "и попробуйте ещё раз. Если не поможет — переподключите календарь."
)
CREATE_EVENT_CANCELLED_HTML = "Создание события отменено."

CB_CREATE_CONFIRM = "create:confirm"
CB_CREATE_CANCEL = "create:cancel"
CB_CREATE_DATE_TODAY = "create:date:today"
CB_CREATE_DATE_TOMORROW = "create:date:tomorrow"
CB_CREATE_DURATION_PREFIX = "create:dur:"
CREATE_EVENT_DURATION_PRESETS_MIN: tuple[int, ...] = (15, 30, 45, 60)
CB_MANAGE_DELETE_PREFIX = "manage:del:"


def build_create_date_keyboard() -> dict:
    """Inline-кнопки «сегодня/завтра» для шага выбора даты в /create.

    Пользователь всё ещё может ввести любую дату текстом — кнопки лишь
    ускоряют типичные сценарии. Поэтому клавиатуру отправляем под вопросом
    о дате, а text-handler в FSM не трогаем.
    """
    return {
        "inline_keyboard": [
            [
                {"text": "📅 Сегодня", "callback_data": CB_CREATE_DATE_TODAY},
                {"text": "➡️ Завтра", "callback_data": CB_CREATE_DATE_TOMORROW},
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
CB_CAL_TOGGLE_PREFIX = "cal:toggle:"
CB_CAL_CLOSE = "cal:close"

CALENDAR_SOURCES_SINGLE_HTML = (
    "📚 В аккаунте один календарь — отдельно выбирать нечего."
)
CALENDAR_SOURCES_LAST_ENABLED_TEXT = "Нужен хотя бы один календарь для плана."
CALENDAR_SOURCES_LOAD_FAIL_HTML = (
    "⚠️ Не удалось загрузить список календарей. Попробуйте позже."
)
CALENDAR_SOURCES_CLOSED_TEXT = "Настройка календарей закрыта."


def calendar_sources_screen_text(*, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "—"
    return (
        "📚 Какие календари учитывать в плане, дайджесте и «Ближайших»?\n\n"
        f"{body}\n\n"
        "Нажмите на строку, чтобы включить или выключить."
    )


def calendar_sources_toggle_notice(*, enabled: bool, name: str) -> str:
    state = "включён" if enabled else "выключен"
    return f"«{name}» {state}"


def build_calendar_sources_keyboard(
    *,
    calendars: list[tuple[str, str]],
    enabled_urls: set[str],
) -> dict:
    def _norm(url: str) -> str:
        return url.strip().rstrip("/")

    rows: list[list[dict[str, str]]] = []
    for idx, (name, url) in enumerate(calendars):
        mark = "✅" if _norm(url) in enabled_urls else "⬜️"
        label = f"{mark} {name}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([{"text": label, "callback_data": f"{CB_CAL_TOGGLE_PREFIX}{idx}"}])
    rows.append([{"text": "⬅️ Закрыть", "callback_data": CB_CAL_CLOSE}])
    return {"inline_keyboard": rows}


# --- чужие (пошаренные) календари ------------------------------------------

CB_FOREIGN_PICK_PREFIX = "foreign:p:"
CB_FOREIGN_DAY_PREFIX = "foreign:d:"
CB_FOREIGN_BACK = "foreign:back"
CB_FOREIGN_CLOSE = "foreign:close"

FOREIGN_CALENDARS_INTRO_HTML = (
    "👥 <b>Чужие календари</b>\n\n"
    "Здесь календари, которые вам открыли в Mail.ru или Яндексе. "
    "Выберите календарь, затем день."
)
FOREIGN_CALENDARS_EMPTY_HTML = (
    "👥 Пока нет чужих календарей.\n\n"
    "Попросите коллегу открыть доступ к календарю на вашу почту "
    "в настройках календаря Mail.ru или Яндекса — после этого он появится здесь."
)
FOREIGN_CALENDARS_LOAD_FAIL_HTML = (
    "⚠️ Не удалось загрузить список календарей. Попробуйте позже."
)
FOREIGN_CALENDARS_CLOSED_TEXT = "Просмотр чужих календарей закрыт."
FOREIGN_CALENDARS_FETCH_STATUS = "⏳ Загружаю события…"
FOREIGN_CALENDARS_DAY_EMPTY_HTML = "Встреч в этот день нет."


def foreign_calendars_pick_day_text(*, calendar_name: str) -> str:
    return (
        f"👥 <b>{calendar_name}</b>\n\n"
        "Выберите день:"
    )


def foreign_calendars_day_result_text(
    *, calendar_name: str, body_lines: list[str]
) -> str:
    body = "\n".join(body_lines)
    return f"👥 <b>{calendar_name}</b>\n\n{body}"


def build_foreign_calendars_keyboard(
    *,
    calendars: list[tuple[str, str]],
) -> dict:
    rows: list[list[dict[str, str]]] = []
    for idx, (name, _url) in enumerate(calendars):
        label = name if len(name) <= 60 else name[:57] + "…"
        rows.append(
            [{"text": label, "callback_data": f"{CB_FOREIGN_PICK_PREFIX}{idx}"}]
        )
    rows.append([{"text": "⬅️ Закрыть", "callback_data": CB_FOREIGN_CLOSE}])
    return {"inline_keyboard": rows}


def build_foreign_day_keyboard(*, calendar_idx: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": BUTTON_TODAY,
                    "callback_data": f"{CB_FOREIGN_DAY_PREFIX}{calendar_idx}:0",
                },
                {
                    "text": BUTTON_TOMORROW,
                    "callback_data": f"{CB_FOREIGN_DAY_PREFIX}{calendar_idx}:1",
                },
            ],
            [{"text": "⬅️ Назад", "callback_data": CB_FOREIGN_BACK}],
        ]
    }


def build_webapp_connect_keyboard(webapp_url: str, *, reconnect: bool = False) -> dict:
    label = BUTTON_RECONNECT_CALENDAR if reconnect else BUTTON_CONNECT_CALENDAR
    return {
        "keyboard": [[{"text": label, "web_app": {"url": webapp_url}}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_approved_main_keyboard() -> dict:
    """Компактная главная клавиатура: просмотр и создание событий + вход в настройки."""
    return {
        "keyboard": [
            [{"text": BUTTON_TODAY}, {"text": BUTTON_UPCOMING}],
            [{"text": BUTTON_FOREIGN_CALENDARS}],
            [{"text": BUTTON_CREATE_EVENT}],
            [{"text": BUTTON_SETTINGS}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": BOT_INPUT_PLACEHOLDER,
    }


# --- общий экран настроек (inline-хаб) ---------------------------------------

CB_SETTINGS_DIGEST = "settings_digest"
CB_SETTINGS_CALENDARS = "settings_calendars"
CB_SETTINGS_CHECK = "settings_check"
CB_SETTINGS_DISCONNECT = "settings_disconnect"
CB_SETTINGS_BACK = "settings_back"
CB_SETTINGS_CLOSE = "settings_close"

SETTINGS_HUB_TEXT = (
    "⚙️ Настройки\n\n"
    "Дайджест, календари в плане и подключение — всё здесь. Выбери раздел:"
)
SETTINGS_HUB_CLOSED_TEXT = "⚙️ Настройки закрыты. Кнопка «Настройки» на клавиатуре всегда рядом."


def build_settings_hub_keyboard(*, webapp_url: str, has_calendar: bool) -> dict:
    connect_label = (
        BUTTON_RECONNECT_CALENDAR if has_calendar else BUTTON_CONNECT_CALENDAR
    )
    rows: list[list[dict[str, str | dict[str, str]]]] = [
        [{"text": "🔔 Дайджест", "callback_data": CB_SETTINGS_DIGEST}],
    ]
    if has_calendar:
        rows.append(
            [{"text": BUTTON_CALENDAR_SOURCES, "callback_data": CB_SETTINGS_CALENDARS}]
        )
        rows.append(
            [
                {"text": BUTTON_CHECK_CALENDAR, "callback_data": CB_SETTINGS_CHECK},
                {
                    "text": BUTTON_DISCONNECT_CALENDAR,
                    "callback_data": CB_SETTINGS_DISCONNECT,
                },
            ]
        )
    if webapp_url:
        rows.append([{"text": connect_label, "web_app": {"url": webapp_url}}])
    rows.append([{"text": "⬅️ Закрыть", "callback_data": CB_SETTINGS_CLOSE}])
    return {"inline_keyboard": rows}


def subscribe_confirmation_text(time_str: str, weekdays_only: bool) -> str:
    """Текст подтверждения включения подписки в стиле «Чайки».

    Используется и старой кнопкой 🔔, и кнопкой «Включить дайджест» из настроек:
    параметры берутся из персональных настроек пользователя, а не из глобального
    DigestConfig. Глобальные дефолты остались только для самого первого нового
    пользователя (через get_or_create).
    """
    schedule = "по будням" if weekdays_only else "каждый день"
    return (
        "🔔 Чайка записала маршрут.\n"
        f"Дайджест будет прилетать в {time_str} МСК {schedule}."
    )


SUBSCRIBE_ALREADY_TEXT = (
    "🔔 Ты уже подписан(а). Чтобы выключить — /stopdigest или /settings."
)
UNSUBSCRIBE_CONFIRMATION_TEXT = (
    "🔕 Чайка сложила крылья.\n"
    "Дайджест больше не будет прилетать. Включить обратно можно через /digest или в /settings."
)
UNSUBSCRIBE_NOT_SUBSCRIBED_TEXT = "🔕 Ты и не был(а) подписан(а)."


# --- настройки дайджеста ---------------------------------------------------

# Callback data для inline-кнопок настроек. Длина каждой строки ≤ 64 байта (Telegram limit).
CB_DIGEST_SETTINGS = "digest_settings"
CB_DIGEST_TOGGLE = "digest_toggle"
CB_DIGEST_DAYS = "digest_days"
CB_DIGEST_DAYS_WEEKDAYS = "digest_days_weekdays"
CB_DIGEST_DAYS_ALL = "digest_days_all"
CB_DIGEST_TIME = "digest_time"
CB_DIGEST_BACK = "digest_back"
CB_DIGEST_CLOSE = "digest_close"

DIGEST_DAYS_LABEL = {
    "weekdays": "будни",
    "all_days": "все дни",
}


def digest_settings_screen_text(
    *, digest_enabled: bool, digest_days: str, digest_time: str
) -> str:
    status_emoji = "🔔" if digest_enabled else "🔕"
    status_text = "включён" if digest_enabled else "отключён"
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    return (
        "⚙️ Настройки дайджеста\n"
        f"{status_emoji} Статус: {status_text}\n"
        f"📆 Дни: {days_label}\n"
        f"🕘 Время: {digest_time} МСК\n"
        "Выбери, что изменить:"
    )


def digest_days_screen_text(digest_days: str) -> str:
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    return (
        "📆 Дни отправки дайджеста\n"
        f"Сейчас: {days_label}\n"
        "Когда присылать утренний облёт?"
    )


def digest_time_screen_text(digest_time: str) -> str:
    return (
        "🕘 Время отправки дайджеста\n"
        f"Сейчас: {digest_time} МСК\n"
        "Напиши новое время в формате ЧЧ:ММ.\n"
        "Например: 08:30 или 18:25."
    )


DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT = (
    "📆 Готово.\n"
    "Дайджест будет прилетать по будням: с понедельника по пятницу."
)
DIGEST_DAYS_ALL_APPLIED_TEXT = (
    "📆 Готово.\n"
    "Дайджест будет прилетать каждый день. Даже в выходные крылья будут на дежурстве."
)


def digest_time_applied_text(digest_time: str) -> str:
    return (
        "🕘 Готово.\n"
        f"Дайджест будет прилетать в {digest_time} МСК."
    )


DIGEST_TIME_INVALID_TEXT = (
    "⚠️ Не понял время.\n"
    "Напиши в формате ЧЧ:ММ.\n"
    "Например: 09:00 или 18:25."
)

DIGEST_SETTINGS_CLOSED_TEXT = "⚙️ Настройки закрыты. Возвращайся, когда понадобятся."


def build_digest_settings_keyboard(*, digest_enabled: bool) -> dict:
    toggle_label = "🔕 Отключить дайджест" if digest_enabled else "🔔 Включить дайджест"
    return {
        "inline_keyboard": [
            [{"text": "📆 Дни отправки", "callback_data": CB_DIGEST_DAYS}],
            [{"text": "🕘 Время отправки", "callback_data": CB_DIGEST_TIME}],
            [{"text": toggle_label, "callback_data": CB_DIGEST_TOGGLE}],
            [{"text": "⬅️ В настройки", "callback_data": CB_SETTINGS_BACK}],
        ]
    }


def build_digest_days_keyboard(*, digest_days: str) -> dict:
    weekdays_label = "✅ Только будни" if digest_days == "weekdays" else "Только будни"
    all_label = "✅ Все дни" if digest_days == "all_days" else "Все дни"
    return {
        "inline_keyboard": [
            [{"text": weekdays_label, "callback_data": CB_DIGEST_DAYS_WEEKDAYS}],
            [{"text": all_label, "callback_data": CB_DIGEST_DAYS_ALL}],
            [{"text": "⬅️ Назад к настройкам", "callback_data": CB_DIGEST_BACK}],
        ]
    }


def build_digest_time_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "⬅️ Назад к настройкам", "callback_data": CB_DIGEST_BACK}],
        ]
    }


PLAN_FETCH_STATUS_TEXT = {
    "today": (
        "📅 Чайка делает облёт календаря.\n\n"
        "Ищет твои встречи на сегодня и скоро принесёт сводку."
    ),
    "tomorrow": (
        "➡️ Чайка делает облёт завтрашнего дня.\n\n"
        "Ищет твои встречи и скоро принесёт сводку."
    ),
    "day_after_tomorrow": (
        "⏭ Чайка делает дальний облёт.\n\n"
        "Ищет твои встречи на послезавтра и скоро принесёт сводку."
    ),
}

ERR_CALDAV_UNAVAILABLE_TEXT = (
    "⚠️ Календарь сейчас недоступен. Попробуйте ещё раз через минуту."
)

ERR_DIGEST_BUILD_FAILED_TEXT = (
    "⚠️ Не удалось принести сводку.\n\n"
    "Крылья целы, но календарь сейчас не отвечает. Попробуй ещё раз позже."
)

# Универсальный текст для непредвиденных ошибок в диспетчере: пользователь
# должен получить какой-то ответ, чтобы не казалось, что бот «съел» команду.
# Никаких техдеталей — стек только в логе.
ERR_GENERIC_HANDLER_TEXT = (
    "⚠️ Что-то пошло не так. Чайка уже разбирается, попробуй ещё раз через минуту."
)


def digest_toggle_notice_text(*, enabled: bool) -> str:
    return "Дайджест включён" if enabled else "Дайджест отключён"


# --- Шаблоны строк дайджеста, использующиеся в seagull.render ---------------

PLAN_STATS_BREAKFAST = "🍕 Завтрак: {interval}"
PLAN_STATS_LUNCH = "🍕 Обед: {interval}"
PLAN_STATS_DINNER = "🍕 Ужин: {interval}"

DURATION_HOURS_AND_MINS = "{hours} ч {mins} мин"
DURATION_HOURS_ONLY = "{hours} ч"
DURATION_MINS_ONLY = "{mins} мин"


def format_duration_ru(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours = minutes // 60
    mins = minutes % 60
    if hours and mins:
        return DURATION_HOURS_AND_MINS.format(hours=hours, mins=mins)
    if hours:
        return DURATION_HOURS_ONLY.format(hours=hours)
    return DURATION_MINS_ONLY.format(mins=mins)


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по правилам gettext nplurals=3.

    one  — для 1, 21, 31, ... (mod 10 == 1 и mod 100 != 11);
    few  — для 2-4, 22-24, ... (mod 10 in 2..4 и mod 100 not in 12..14);
    many — для 0, 5-20, 25-30, ...
    """
    n = abs(int(n))
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def format_duration_long_ru(minutes: int) -> str:
    """Длинная форма длительности со склонением: «1 час», «2 часа 30 минут».

    Используется в заголовках групп `/upcoming` — там короткая форма «1 ч»
    выглядит куцо в круглых скобках.
    """
    minutes = max(0, int(minutes))
    hours = minutes // 60
    mins = minutes % 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}")
    if mins:
        parts.append(f"{mins} {_plural_ru(mins, 'минута', 'минуты', 'минут')}")
    if not parts:
        return "0 минут"
    return " ".join(parts)
