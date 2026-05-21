"""Пользовательские тексты на русском.

Меняй формулировки здесь — логика скриптов не требует правок.
Плейсхолдеры в фигурных скобках подставляются кодом, не удаляй их без необходимости.
"""

from __future__ import annotations

import unicodedata

# Реэкспорт доменных констант календаря: сами строки теперь живут в
# ``satellite.calendar.constants``, чтобы календарь не зависел от слоя UI.

# --- Telegram: подписи кнопок ---
BUTTON_TODAY = "📅 Сегодня"
BUTTON_TOMORROW = "➡️ Завтра"
BUTTON_DAY_AFTER = "⏭ Послезавтра"
BUTTON_UPCOMING = "🗓 Ближайшие события"
BUTTON_INVITATIONS = "📨 Приглашения"
BUTTON_MANAGE_EVENTS = "🛠 Изменить статус"
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
_NORMALIZED_BUTTON_INVITATIONS = normalize_button_text(BUTTON_INVITATIONS)
_NORMALIZED_BUTTON_MANAGE_EVENTS = normalize_button_text(BUTTON_MANAGE_EVENTS)
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


def button_text_is_invitations(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_INVITATIONS


def button_text_is_manage_events(text: str | None) -> bool:
    if not text:
        return False
    return normalize_button_text(text) == _NORMALIZED_BUTTON_MANAGE_EVENTS


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


BOT_INPUT_PLACEHOLDER = "Куда летим? Жми кнопку или напиши команду"

BOT_NAME_RU = "🪶 Чайка"
BOT_SHORT_DESCRIPTION_RU = (
    "Сводка дня из календаря: план, дайджест, приглашения и аналитика недели."
)
BOT_DESCRIPTION_RU = (
    "Чайка подключается к Mail.ru или Яндекс Календарю и приносит:\n"
    "• план на сегодня, завтра и послезавтра;\n"
    "• утренний дайджест по расписанию;\n"
    "• ближайшие события, приглашения и смену статуса встреч;\n"
    "• недельную аналитику с графиком.\n\n"
    "Команды — в меню рядом с полем ввода. Настройки — /settings."
)


def _build_bot_welcome_html() -> str:
    from ..telegram_bot.html_format import blockquote, replace_first_char_with_tg_emoji

    tip = blockquote(
        "Подсказка: добавь в встречу эмоджи 🍕 и слово «обед» — чайка засчитает её "
        "обедом и подскажет окно."
    )
    head = replace_first_char_with_tg_emoji("🪶 С возвращением. Чайка на связи.\n\n", "🪶")
    return (
        f"{head}"
        "Нижние кнопки — это твой штурвал:\n"
        "📅 <b>Сегодня</b> / ➡️ <b>Завтра</b> — план на день\n"
        "🗓 <b>Ближайшие</b> — события на неделю вперёд\n"
        "📨 <b>Приглашения</b> — встречи, где нужно принять решение\n"
        "🛠 <b>Изменить статус</b> — поменять решение по любой ближайшей встрече\n"
        "👥 <b>Чужие календари</b> — что у коллег\n"
        "➕ <b>Создать</b> — новая встреча в твой календарь\n"
        "⚙️ <b>Настройки</b> — дайджест, аналитика, подключение\n\n"
        f"{tip}"
    )


def _build_bot_help_html() -> str:
    from ..telegram_bot.html_format import expandable_blockquote, replace_first_char_with_tg_emoji

    commands_block = expandable_blockquote(
        "/today, /tomorrow, /aftertomorrow — план дня\n"
        "/upcoming — ближайшие события\n"
        "/invitations — ответить на приглашения\n"
        "/manage — изменить статус встречи на неделе\n"
        "/foreign — чужие календари\n"
        "/create — создать встречу\n"
        "/settings — настройки\n"
        "/digest, /stopdigest — включить или выключить утренний дайджест",
        threshold=2,
    )
    head = replace_first_char_with_tg_emoji("🪶 <b>Как летать с Чайкой</b>\n\n", "🪶")
    return (
        f"{head}"
        "Чайка собирает встречи из твоего календаря и приносит сводку дня.\n\n"
        "<b>Кнопки внизу:</b>\n"
        "📅 Сегодня, ➡️ Завтра — план на день\n"
        "🗓 Ближайшие — события на 7 дней\n"
        "📨 Приглашения — принять, отклонить или «может быть»\n"
        "🛠 Изменить статус — поменять решение по любой встрече на неделе\n"
        "👥 Чужие календари — пошаренные от коллег\n"
        "➕ Создать событие — добавить встречу\n"
        "⚙️ Настройки — дайджест, аналитика, подключение\n\n"
        "<b>Команды:</b>\n"
        f"{commands_block}\n\n"
        "<i>Короткие алиасы: <code>td</code>, <code>tm</code>, <code>dat</code>.</i>"
    )


BOT_WELCOME_HTML = _build_bot_welcome_html()
BOT_HELP_HTML = _build_bot_help_html()

# Markup, который вычищает старую нижнюю Reply-клавиатуру у пользователей, у
# которых она ещё висит после миграции на меню команд Telegram. Передаётся
# в ``reply_markup`` обычных сообщений (например, на /start и /help).
REPLY_KEYBOARD_REMOVE: dict = {"remove_keyboard": True}


BOT_KEYBOARD_HINT = (
    "🪶 Чайка не узнала команду.\nЖми кнопку внизу или открой меню — там все основные действия."
)

# --- Access control ---
ACCESS_REQUEST_SENT_HTML = (
    "📝 Заявка улетела администратору.\n"
    "Как только одобрит — Чайка сразу даст знать, и можно будет подключить календарь."
)
ACCESS_PENDING_HTML = (
    "⏳ Заявка ещё в полёте — администратор её увидит.\n"
    "Как только одобрит, Чайка постучится первой."
)
ACCESS_REJECTED_HTML = (
    "🚫 Доступ закрыт.\nЕсли это недоразумение — напиши администратору, Чайка подождёт."
)
ACCESS_BLOCKED_HTML = "🚫 Доступ заблокирован. Чайка пока на берегу."
ACCESS_APPROVED_HTML = (
    "✅ Доступ открыт, можно лететь.\n"
    "Жми «🔌 Подключить календарь» под этим сообщением — Чайка свяжется "
    "с твоим Mail.ru или Яндексом и будет приносить сводку."
)
ACCESS_APPROVED_KEYBOARD_HINT = "⌨️ Команды плана — на клавиатуре ниже."
CALENDAR_NOT_CONNECTED_HTML = (
    "🔌 Календарь ещё не подключён.\n"
    "Жми «Подключить календарь» под сообщением — Чайка откроет защищённое окно, "
    "там нужно ввести логин и пароль приложения для CalDAV."
)
CALENDAR_RECONNECT_INTRO_HTML = (
    "🔄 Откроем окно подключения заново — Чайка подменит сохранённые ключи "
    "на свежие, без потери настроек."
)
CALENDAR_CONNECTED_HTML = "✅ Календарь на месте. Чайка готова к облёту."
CALENDAR_DISCONNECTED_HTML = (
    "🪶 Чайка отвязала календарь.\n"
    "Настройки дайджеста и аналитики сохранены — подключи заново, и всё вернётся."
)
CALENDAR_CHECK_OK_HTML = "✅ Чайка достучалась до календаря — всё на связи."
CALENDAR_CHECK_FAIL_HTML = (
    "⚠️ Чайка не достучалась до календаря.\n"
    "Попробуй переподключить: «⚙️ Настройки» → «📅 Календарь» → «🔄 Переподключить»."
)

ERR_CALENDAR_TOKEN_INVALID = (
    "⚠️ Чайка не смогла войти с этими ключами.\n"
    "Проверь логин и пароль приложения для календаря — возможно, он отозван или скопирован с пробелом."
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
        "👤 Новый пользователь стучится к Чайке:\n"
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
UPCOMING_FETCH_STATUS = "🗓 Чайка обходит ближайшую неделю…"
UPCOMING_EMPTY_HTML = (
    "🗓 На ближайшие дни встреч нет.\nНебо чистое — самое время для глубокой работы."
)
# Минимум строк событий в дне, чтобы обернуть их в blockquote.
# Блок всегда показывается развёрнутым (без атрибута ``expandable``):
# пользователь свернёт цитату вручную, если захочет.
# Одиночная встреча остаётся обычным текстом под заголовком.
UPCOMING_DAY_EXPANDABLE_MIN_LINES = 2


def upcoming_events_day_sections(
    events,
    tz,
    reference_date,
    *,
    days: int = 7,
    max_events: int = 30,
) -> list[str]:
    """Секции «Ближайшие события» по одному дню (заголовок + события)."""
    from html import escape

    from ..calendar.events import build_upcoming_events_groups
    from ..telegram_bot.html_format import expandable_blockquote

    sections: list[str] = []
    for group in build_upcoming_events_groups(
        events, tz, reference_date, days=days, max_events=max_events
    ):
        header = f"<b>{group['header']}</b>"
        event_lines: list[str] = []
        for item in group["events"]:
            title = escape(str(item["title"]))
            event_lines.append(f"{item['marker']} {item['time_range']} — {title}")
        if not event_lines:
            sections.append(header)
            continue
        body = "\n".join(event_lines)
        wrapped = expandable_blockquote(body, threshold=UPCOMING_DAY_EXPANDABLE_MIN_LINES)
        sections.append(f"{header}\n{wrapped}")
    return sections


def upcoming_events_html(
    events,
    tz,
    reference_date,
    *,
    days: int = 7,
    max_events: int = 30,
) -> str:
    """HTML тела «Ближайшие события» со сворачиванием по дням."""
    return "\n\n".join(
        upcoming_events_day_sections(events, tz, reference_date, days=days, max_events=max_events)
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

CB_CREATE_CONFIRM = "create:confirm"
CB_CREATE_CANCEL = "create:cancel"
CB_CREATE_DATE_TODAY = "create:date:today"
CB_CREATE_DATE_TOMORROW = "create:date:tomorrow"
CB_CREATE_DURATION_PREFIX = "create:dur:"
CREATE_EVENT_DURATION_PRESETS_MIN: tuple[int, ...] = (15, 30, 45, 60)


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


# --- общий экран настроек (inline-хаб) ---------------------------------------

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

CB_ANALYTICS_RUN = "analytics:run"
CB_ANALYTICS_WORKDAY_9 = "analytics:wd:9-18"
CB_ANALYTICS_WORKDAY_10 = "analytics:wd:10-19"
CB_ANALYTICS_BACK = "analytics:back"

CALENDAR_DISCONNECT_TOAST = "Отключено"
ANALYTICS_SAVED_TOAST = "Сохранено"
FOREIGN_CALENDARS_LOADING_TOAST = "Загружаю…"

BUTTON_ANALYTICS = "📊 Аналитика недели"
BUTTON_CALENDAR_MENU = "📅 Календарь"


def settings_hub_text(*, digest_enabled: bool | None = None, has_calendar: bool = True) -> str:
    from ..telegram_bot.html_format import blockquote

    status_bits: list[str] = []
    if digest_enabled is not None:
        status_bits.append("🔔 Дайджест включён" if digest_enabled else "🔕 Дайджест выключен")
    if has_calendar:
        status_bits.append("📅 Календарь подключён")
    else:
        status_bits.append("🔌 Календарь не подключён")
    summary = blockquote(" · ".join(status_bits)) if status_bits else ""
    base = (
        "⚙️ <b>Настройки Чайки</b>\n\n"
        "Здесь живут три раздела: дайджест, аналитика и календарь. Выбери, что настроить."
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


def build_settings_hub_keyboard(
    *,
    webapp_url: str,
    has_calendar: bool,
    calendar_login: str | None = None,
) -> dict:
    """Главный экран настроек.

    Структура: три раздела (Дайджест, Аналитика, Календарь). Управление
    подключением и календарями в плане спрятано во вложенный экран
    «Календарь» — это уменьшает число кнопок на главном экране и убирает
    деструктивный «Отключить» из зоны случайного нажатия.
    """
    from ..telegram_bot.html_format import build_copy_text_button

    rows: list[list[dict[str, str | dict[str, str]]]] = [
        [{"text": "🔔 Дайджест", "callback_data": CB_SETTINGS_DIGEST}],
    ]
    if has_calendar:
        rows.append([{"text": BUTTON_ANALYTICS, "callback_data": CB_SETTINGS_ANALYTICS}])
        rows.append([{"text": BUTTON_CALENDAR_MENU, "callback_data": CB_SETTINGS_CALENDAR_MENU}])
        if calendar_login:
            rows.append(
                [
                    build_copy_text_button(
                        "📋 Скопировать e-mail",
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

# --- приглашения (PARTSTAT) --------------------------------------------------

CB_INV_CLOSE = "inv:close"
CB_INV_BACK = "inv:back"
CB_INV_REFRESH = "inv:refresh"
CB_INV_RESPOND_PREFIX = "inv:r:"

INVITATIONS_FETCH_STATUS = "📨 Чайка собирает приглашения…"
INVITATIONS_EMPTY_HTML = (
    "📨 <b>Приглашения</b>\n\nВсё разобрано — встреч, где нужно принять решение, сейчас нет."
)
INVITATIONS_INTRO_HTML = (
    "📨 <b>Приглашения</b>\n\n"
    "Встречи, где тебя ждут как участника. Нажми кнопку под событием — "
    "ответ улетит в календарь."
)
INVITATIONS_RESPOND_ACCEPTED = "Принято"
INVITATIONS_RESPOND_DECLINED = "Отклонено"
INVITATIONS_RESPOND_TENTATIVE = "Может быть"
INVITATIONS_RESPOND_FAIL_TEXT = "Не удалось обновить ответ. Попробуйте позже."
INVITATIONS_CLOSED_TEXT = "📨 Чайка свернула список приглашений."
SETTINGS_DISCONNECT_CONFIRM_TEXT = (
    "🪶 Точно отключить календарь?\n\n"
    "Чайка забудет логин и пароль, но настройки дайджеста и аналитики сохранятся. "
    "Заново подключить можно одной кнопкой."
)
SETTINGS_DISCONNECT_CANCEL_TEXT = "🪶 Отбой — календарь на месте."
BUTTON_DISCONNECT_CALENDAR_CONFIRM = "⚠️ Да, отключить"
BUTTON_DISCONNECT_CALENDAR_CANCEL = "⬅️ Отмена"


def build_invitations_keyboard(
    events: list[tuple[str, str]],
) -> dict:
    """Inline-клавиатура: по строке кнопок на каждое событие (token, label index)."""
    rows: list[list[dict[str, str]]] = []
    for token, label in events:
        rows.append(
            [
                {
                    "text": f"✅ {label}",
                    "callback_data": f"{CB_INV_RESPOND_PREFIX}{token}:a",
                },
                {
                    "text": f"❌ {label}",
                    "callback_data": f"{CB_INV_RESPOND_PREFIX}{token}:d",
                },
                {
                    "text": f"🤔 {label}",
                    "callback_data": f"{CB_INV_RESPOND_PREFIX}{token}:t",
                },
            ]
        )
    rows.append([{"text": "🔄 Обновить", "callback_data": CB_INV_REFRESH}])
    rows.append(
        [
            {"text": "⬅️ В календарь", "callback_data": CB_INV_BACK},
            {"text": "⬅️ Закрыть", "callback_data": CB_INV_CLOSE},
        ]
    )
    return {"inline_keyboard": rows}


def invitations_list_html(*, body_lines: list[str], truncated: bool) -> str:
    from ..telegram_bot.html_format import expandable_blockquote

    parts = [INVITATIONS_INTRO_HTML]
    if body_lines:
        parts.append("")
        body = "\n".join(body_lines)
        parts.append(expandable_blockquote(body, threshold=4))
    if truncated:
        parts.append("")
        parts.append("<i>Показаны первые встречи — обновите список после ответов.</i>")
    return "\n".join(parts)


# --- изменение статуса встречи (PARTSTAT) ----------------------------------

CB_MANAGE_CLOSE = "mng:close"
CB_MANAGE_BACK = "mng:back"
CB_MANAGE_REFRESH = "mng:refresh"
CB_MANAGE_PICK_PREFIX = "mng:p:"
CB_MANAGE_RESPOND_PREFIX = "mng:r:"

MANAGE_FETCH_STATUS = "🛠 Чайка собирает встречи на неделе…"
MANAGE_INTRO_HTML = (
    "🛠 <b>Изменить статус встречи</b>\n\n"
    "Встречи на ближайшие 7 дней, где ты участник. Тапни строку — Чайка покажет, "
    "что можно поменять: ✅ принять, 🤔 может быть, ❌ отклонить.\n\n"
    "<i>Отклонённые встречи Чайка не показывает в плане и дайджесте.</i>"
)
MANAGE_EMPTY_HTML = (
    "🛠 <b>Изменить статус встречи</b>\n\n"
    "На ближайшую неделю встреч, где ты участник, не нашлось — менять статус нечему."
)
MANAGE_CLOSED_TEXT = "🛠 Чайка свернула список встреч."
MANAGE_NOT_FOUND_TEXT = "Встреча не нашлась — обновите список."
MANAGE_RESPOND_FAIL_TEXT = "Не удалось обновить статус. Попробуйте позже."
MANAGE_RESPOND_ACCEPTED = "✅ Принято"
MANAGE_RESPOND_DECLINED = "❌ Отклонено"
MANAGE_RESPOND_TENTATIVE = "🤔 Может быть"

_MANAGE_PARTSTAT_LABEL_RU = {
    "ACCEPTED": "✅ принято",
    "TENTATIVE": "🤔 может быть",
    "DECLINED": "❌ отклонено",
    "NEEDS-ACTION": "📨 ждёт ответа",
    "DELEGATED": "↪️ делегировано",
}


def manage_partstat_label(partstat: str | None) -> str | None:
    if not partstat:
        return None
    return _MANAGE_PARTSTAT_LABEL_RU.get(partstat.strip().upper())


def manage_detail_html(*, title: str, when: str, partstat: str | None) -> str:
    label = manage_partstat_label(partstat) or "—"
    return (
        f"🛠 <b>{title}</b>\n"
        f"{when}\n\n"
        f"📌 Сейчас: <b>{label}</b>\n\n"
        "<i>Поменять решение можно сколько угодно — Чайка пошлёт ответ в календарь.</i>"
    )


def build_manage_list_keyboard(rows: list[tuple[str, str]]) -> dict:
    """rows: [(token, label like '1️⃣ 14:00 — Standup')]."""
    inline: list[list[dict[str, str]]] = []
    for token, label in rows:
        clipped = label if len(label) <= 60 else label[:57] + "…"
        inline.append([{"text": clipped, "callback_data": f"{CB_MANAGE_PICK_PREFIX}{token}"}])
    inline.append([{"text": "🔄 Обновить", "callback_data": CB_MANAGE_REFRESH}])
    inline.append([{"text": "⬅️ Закрыть", "callback_data": CB_MANAGE_CLOSE}])
    return {"inline_keyboard": inline}


def build_manage_detail_keyboard(token: str, *, partstat: str | None) -> dict:
    cur = (partstat or "").strip().upper()
    mark = lambda code, label: f"{label} ✓" if cur == code else label  # noqa: E731
    return {
        "inline_keyboard": [
            [
                {
                    "text": mark("ACCEPTED", "✅ Принять"),
                    "callback_data": f"{CB_MANAGE_RESPOND_PREFIX}{token}:a",
                },
                {
                    "text": mark("TENTATIVE", "🤔 Может быть"),
                    "callback_data": f"{CB_MANAGE_RESPOND_PREFIX}{token}:t",
                },
            ],
            [
                {
                    "text": mark("DECLINED", "❌ Отклонить"),
                    "callback_data": f"{CB_MANAGE_RESPOND_PREFIX}{token}:d",
                },
            ],
            [{"text": "⬅️ К списку", "callback_data": CB_MANAGE_BACK}],
        ]
    }


def manage_list_html(*, body_lines: list[str], truncated: bool) -> str:
    from ..telegram_bot.html_format import expandable_blockquote

    parts = [MANAGE_INTRO_HTML]
    if body_lines:
        parts.append("")
        body = "\n".join(body_lines)
        parts.append(expandable_blockquote(body, threshold=4))
    if truncated:
        parts.append("")
        parts.append("<i>Показаны первые встречи — обновите список после изменений.</i>")
    return "\n".join(parts)


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
        f"Утренний дайджест будет прилетать в <b>{time_str} МСК</b> {schedule}.\n\n"
        "Поменять время или дни — /settings → «Дайджест»."
    )


SUBSCRIBE_ALREADY_TEXT = (
    "🔔 Дайджест уже включён.\nЧтобы выключить — /stopdigest, изменить время — /settings."
)
UNSUBSCRIBE_CONFIRMATION_TEXT = (
    "🔕 Чайка сложила крылья.\n"
    "Утренний дайджест больше не будет прилетать. Включить обратно — /digest или /settings."
)
UNSUBSCRIBE_NOT_SUBSCRIBED_TEXT = "🔕 Дайджест и так был выключен — Чайка просто кивнула."


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


def digest_settings_screen_text(*, digest_enabled: bool, digest_days: str, digest_time: str) -> str:
    status_emoji = "🔔" if digest_enabled else "🔕"
    status_text = "включён" if digest_enabled else "отключён"
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    return (
        "🔔 <b>Настройки дайджеста</b>\n\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n"
        f"📆 Дни: <b>{days_label}</b>\n"
        f"🕘 Время: <b>{digest_time} МСК</b>\n\n"
        "Что меняем?"
    )


def digest_days_screen_text(digest_days: str) -> str:
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    return (
        "📆 <b>Дни отправки</b>\n\n"
        f"Сейчас: <b>{days_label}</b>.\n"
        "Когда Чайке делать утренний облёт?"
    )


def digest_time_screen_text(digest_time: str) -> str:
    return (
        "🕘 <b>Время отправки</b>\n\n"
        f"Сейчас: <b>{digest_time} МСК</b>.\n"
        "Напиши новое время одной строкой:\n"
        "<i>09:30</i> · <i>9 30</i> · <i>8:00</i> · <i>18:25</i>"
    )


DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT = (
    "📆 Готово. Утренний дайджест — по будням, с понедельника по пятницу."
)
DIGEST_DAYS_ALL_APPLIED_TEXT = (
    "📆 Готово. Дайджест будет прилетать каждый день — даже в выходные Чайка на дежурстве."
)


def digest_time_applied_text(digest_time: str) -> str:
    return f"🕘 Готово.\nУтренний дайджест будет прилетать в <b>{digest_time} МСК</b>."


DIGEST_TIME_INVALID_TEXT = (
    "⚠️ Чайка не разобрала время.\n"
    "Напиши так: <i>09:30</i>, <i>9 30</i>, <i>9:30</i> или <i>18:25</i>."
)

DIGEST_SETTINGS_CLOSED_TEXT = (
    "🪶 Чайка свернула настройки дайджеста. Возвращайся, когда понадобятся."
)


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
    "today": ("📅 Чайка делает облёт сегодняшнего дня.\n\nСейчас принесу сводку."),
    "tomorrow": ("➡️ Чайка летит на завтрашний день.\n\nСейчас принесу сводку."),
    "day_after_tomorrow": (
        "⏭ Чайка ушла в дальний облёт — послезавтра.\n\nСкоро вернусь со сводкой."
    ),
}

ERR_CALDAV_UNAVAILABLE_TEXT = (
    "⚠️ Календарь не отвечает.\nЧайка попробует снова через минуту — попытайся ещё раз."
)

ERR_DIGEST_BUILD_FAILED_TEXT = (
    "⚠️ Чайка вернулась без сводки.\n\n"
    "Крылья целы, но календарь сейчас не отвечает. Попробуй ещё раз чуть позже."
)

ERR_USERS_SAVE_FAILED_TEXT = (
    "⚠️ Не удалось сохранить настройки.\nЧайка попробует снова при следующем действии."
)

# Универсальный текст для непредвиденных ошибок в диспетчере: пользователь
# должен получить какой-то ответ, чтобы не казалось, что бот «съел» команду.
# Никаких техдеталей — стек только в логе.
ERR_GENERIC_HANDLER_TEXT = (
    "⚠️ Что-то пошло не так. Чайка уже разбирается — попробуй ещё раз через минуту."
)


def digest_toggle_notice_text(*, enabled: bool) -> str:
    return "🔔 Дайджест включён" if enabled else "🔕 Дайджест отключён"


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
