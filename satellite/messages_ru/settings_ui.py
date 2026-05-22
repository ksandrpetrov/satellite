"""User-facing strings — хаб настроек, дайджест, pending digest, ошибки handler."""

from __future__ import annotations

from .buttons import (
    BUTTON_CALENDAR_SOURCES,
    BUTTON_CHECK_CALENDAR,
    BUTTON_CONNECT_CALENDAR,
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

CB_ANALYTICS_RUN = "analytics:run"
CB_ANALYTICS_WORKDAY_9 = "analytics:wd:9-18"
CB_ANALYTICS_WORKDAY_10 = "analytics:wd:10-19"
CB_ANALYTICS_BACK = "analytics:back"

CALENDAR_DISCONNECT_TOAST = "Отключено"
ANALYTICS_SAVED_TOAST = "Сохранено"
ANALYTICS_BUSY_TOAST = "Уже строю отчёт — подожди немного"
FOREIGN_CALENDARS_LOADING_TOAST = "Загружаю…"

BUTTON_ANALYTICS = "📊 Аналитика недели"
BUTTON_CALENDAR_MENU = "📅 Календарь"


def settings_hub_text(
    *,
    digest_enabled: bool | None = None,
    pending_digest_enabled: bool | None = None,
    has_calendar: bool = True,
) -> str:
    from ..telegram_bot.html_format import blockquote

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

    rows: list[list[dict[str, object]]] = [
        [{"text": "🔔 Дайджест на сегодня", "callback_data": CB_SETTINGS_DIGEST}],
        [{"text": "📨 Дайджест непринятых встреч", "callback_data": CB_PENDING_DIGEST_SETTINGS}],
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
        f"Дайджест на сегодня будет прилетать в <b>{time_str} МСК</b> {schedule}.\n\n"
        "Поменять время или дни — /settings → «Дайджест на сегодня»."
    )


SUBSCRIBE_ALREADY_TEXT = (
    "🔔 Дайджест на сегодня уже включён.\n"
    "Чтобы выключить — /stopdigest, изменить время — /settings."
)
UNSUBSCRIBE_CONFIRMATION_TEXT = (
    "🔕 Чайка сложила крылья.\n"
    "Дайджест на сегодня больше не будет прилетать. Включить обратно — /digest или /settings."
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
        "📅 <b>Настройки дайджеста на сегодня</b>\n\n"
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
        "Когда Чайке присылать сводку на сегодня?"
    )


def digest_time_screen_text(digest_time: str) -> str:
    return (
        "🕘 <b>Время отправки</b>\n\n"
        f"Сейчас: <b>{digest_time} МСК</b>.\n"
        "Напиши новое время одной строкой:\n"
        "<i>09:30</i> · <i>9 30</i> · <i>8:00</i> · <i>18:25</i>"
    )


DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT = (
    "📆 Готово. Дайджест на сегодня — по будням, с понедельника по пятницу."
)
DIGEST_DAYS_ALL_APPLIED_TEXT = (
    "📆 Готово. Дайджест на сегодня будет прилетать каждый день — "
    "даже в выходные Чайка на дежурстве."
)


def digest_time_applied_text(digest_time: str) -> str:
    return f"🕘 Готово.\nДайджест на сегодня будет прилетать в <b>{digest_time} МСК</b>."


DIGEST_TIME_INVALID_TEXT = (
    "⚠️ Чайка не разобрала время.\n"
    "Напиши так: <i>09:30</i>, <i>9 30</i>, <i>9:30</i> или <i>18:25</i>."
)

DIGEST_SETTINGS_CLOSED_TEXT = (
    "🪶 Чайка свернула настройки дайджеста на сегодня. Возвращайся, когда понадобятся."
)


def build_digest_settings_keyboard(*, digest_enabled: bool) -> dict:
    toggle_label = (
        "🔕 Отключить дайджест на сегодня" if digest_enabled else "🔔 Включить дайджест на сегодня"
    )
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
    return "🔔 Дайджест на сегодня включён" if enabled else "🔕 Дайджест на сегодня отключён"


# --- настройки дайджеста непринятых встреч ---------------------------------

CB_PENDING_DIGEST_SETTINGS = "pending_digest_settings"
CB_PENDING_DIGEST_TOGGLE = "pending_digest_toggle"
CB_PENDING_DIGEST_DAYS = "pending_digest_days"
CB_PENDING_DIGEST_DAYS_WEEKDAYS = "pending_digest_days_weekdays"
CB_PENDING_DIGEST_DAYS_ALL = "pending_digest_days_all"
CB_PENDING_DIGEST_DAY_PREFIX = "pending_digest_d:"
CB_PENDING_DIGEST_TIME = "pending_digest_time"
CB_PENDING_DIGEST_BACK = "pending_digest_back"
CB_PENDING_DIGEST_CLOSE = "pending_digest_close"


def _pending_digest_days_label(digest_days: str) -> str:
    from ..digest_utils import format_digest_days_label

    return format_digest_days_label(digest_days)


def pending_digest_day_callback_data(weekday: int) -> str:
    return f"{CB_PENDING_DIGEST_DAY_PREFIX}{weekday}"


def pending_digest_settings_screen_text(
    *, digest_enabled: bool, digest_days: str, digest_time: str
) -> str:
    status_emoji = "📨" if digest_enabled else "🔕"
    status_text = "включён" if digest_enabled else "отключён"
    days_label = _pending_digest_days_label(digest_days)
    return (
        "📨 <b>Настройки дайджеста непринятых встреч</b>\n\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n"
        f"📆 Дни: <b>{days_label}</b>\n"
        f"🕘 Время: <b>{digest_time} МСК</b>\n\n"
        "По расписанию Чайка напомнит принять встречи — как в «Входящие»."
    )


def pending_digest_days_screen_text(digest_days: str) -> str:
    days_label = _pending_digest_days_label(digest_days)
    return (
        "📆 <b>Дни отправки</b>\n\n"
        f"Сейчас: <b>{days_label}</b>.\n"
        "Отметь дни недели — можно один или несколько.\n"
        "Снять последнюю галочку нельзя: нужен хотя бы один день."
    )


PENDING_DIGEST_LAST_DAY_TEXT = "Нужен хотя бы один день отправки."


def pending_digest_time_screen_text(digest_time: str) -> str:
    return (
        "🕘 <b>Время отправки</b>\n\n"
        f"Сейчас: <b>{digest_time} МСК</b>.\n"
        "Напиши новое время одной строкой:\n"
        "<i>10:00</i> · <i>10 30</i> · <i>9:00</i> · <i>18:25</i>"
    )


PENDING_DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT = (
    "📆 Готово. Напоминания о непринятых встречах — по будням."
)
PENDING_DIGEST_DAYS_ALL_APPLIED_TEXT = (
    "📆 Готово. Напоминания будут прилетать каждый день, включая выходные."
)


def pending_digest_time_applied_text(digest_time: str) -> str:
    return f"🕘 Готово.\nДайджест непринятых встреч будет прилетать в <b>{digest_time} МСК</b>."


PENDING_DIGEST_TIME_INVALID_TEXT = (
    "⚠️ Чайка не разобрала время.\n"
    "Напиши так: <i>10:00</i>, <i>10 30</i>, <i>9:30</i> или <i>18:25</i>."
)

PENDING_DIGEST_SETTINGS_CLOSED_TEXT = (
    "🪶 Чайка свернула настройки дайджеста непринятых встреч. Возвращайся, когда понадобятся."
)


def build_pending_digest_settings_keyboard(*, digest_enabled: bool) -> dict:
    toggle_label = (
        "🔕 Отключить дайджест непринятых" if digest_enabled else "📨 Включить дайджест непринятых"
    )
    return {
        "inline_keyboard": [
            [{"text": "📆 Дни отправки", "callback_data": CB_PENDING_DIGEST_DAYS}],
            [{"text": "🕘 Время отправки", "callback_data": CB_PENDING_DIGEST_TIME}],
            [{"text": toggle_label, "callback_data": CB_PENDING_DIGEST_TOGGLE}],
            [{"text": "⬅️ В настройки", "callback_data": CB_SETTINGS_BACK}],
        ]
    }


def build_pending_digest_days_keyboard(*, digest_days: str) -> dict:
    from ..digest_utils import WEEKDAY_SHORT_RU, digest_days_to_bitmask

    mask = digest_days_to_bitmask(digest_days)
    rows: list[list[dict[str, str]]] = []
    for weekday, short_name in enumerate(WEEKDAY_SHORT_RU):
        prefix = "✅ " if mask[weekday] == "1" else ""
        rows.append(
            [
                {
                    "text": f"{prefix}{short_name}",
                    "callback_data": pending_digest_day_callback_data(weekday),
                }
            ]
        )
    rows.append(
        [
            {"text": "Все дни", "callback_data": CB_PENDING_DIGEST_DAYS_ALL},
            {"text": "Будни", "callback_data": CB_PENDING_DIGEST_DAYS_WEEKDAYS},
        ]
    )
    rows.append([{"text": "⬅️ Назад к настройкам", "callback_data": CB_PENDING_DIGEST_BACK}])
    return {"inline_keyboard": rows}


def build_pending_digest_time_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "⬅️ Назад к настройкам", "callback_data": CB_PENDING_DIGEST_BACK}],
        ]
    }


def pending_digest_toggle_notice_text(*, enabled: bool) -> str:
    return "📨 Дайджест непринятых включён" if enabled else "🔕 Дайджест непринятых отключён"
