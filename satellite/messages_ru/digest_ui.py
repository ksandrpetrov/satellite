"""User-facing strings — настройки дайджестов: «на сегодня» и «непринятых встреч».

Вход в оба сценария — из хаба настроек (``settings_ui``): там живут
``CB_SETTINGS_DIGEST`` и ``CB_PENDING_DIGEST_SETTINGS``.
"""

from __future__ import annotations

from ..digest_utils import (
    WEEKDAY_SHORT_RU,
    digest_days_to_bitmask,
    format_digest_days_label,
)
from .buttons import styled_button
from .settings_ui import CB_SETTINGS_BACK, weather_in_plan_toggle_button_text

# --- подписка на дайджест (кнопка 🔔 / /digest) ------------------------------


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
CB_DIGEST_WEATHER_TOGGLE = "digest_weather_toggle"
CB_DIGEST_BACK = "digest_back"
CB_DIGEST_CLOSE = "digest_close"

DIGEST_DAYS_LABEL = {
    "weekdays": "будни",
    "all_days": "все дни",
}


def digest_settings_screen_text(
    *,
    digest_enabled: bool,
    digest_days: str,
    digest_time: str,
    weather_in_plan_enabled: bool,
) -> str:
    status_emoji = "🔔" if digest_enabled else "🔕"
    status_text = "включён" if digest_enabled else "отключён"
    weather_emoji = "🌤" if weather_in_plan_enabled else "🔕"
    weather_text = "включена" if weather_in_plan_enabled else "выключена"
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    return (
        "📅 <b>Настройки дайджеста на сегодня</b>\n\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n"
        f"📆 Дни: <b>{days_label}</b>\n"
        f"🕘 Время: <b>{digest_time} МСК</b>\n\n"
        f"{weather_emoji} Погода в дайджесте: <b>{weather_text}</b>\n\n"
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


def build_digest_settings_keyboard(*, digest_enabled: bool, weather_in_plan_enabled: bool) -> dict:
    toggle_label = (
        "🔕 Отключить дайджест на сегодня" if digest_enabled else "🔔 Включить дайджест на сегодня"
    )
    return {
        "inline_keyboard": [
            [{"text": "📆 Дни отправки", "callback_data": CB_DIGEST_DAYS}],
            [{"text": "🕘 Время отправки", "callback_data": CB_DIGEST_TIME}],
            [
                {
                    "text": weather_in_plan_toggle_button_text(enabled=weather_in_plan_enabled),
                    "callback_data": CB_DIGEST_WEATHER_TOGGLE,
                }
            ],
            [
                styled_button(
                    toggle_label,
                    CB_DIGEST_TOGGLE,
                    style="danger" if digest_enabled else "success",
                )
            ],
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


def digest_toggle_notice_text(*, enabled: bool) -> str:
    return "🔔 Дайджест на сегодня включён" if enabled else "🔕 Дайджест на сегодня отключён"


# --- настройки дайджеста непринятых встреч ---------------------------------

CB_PENDING_DIGEST_TOGGLE = "pending_digest_toggle"
CB_PENDING_DIGEST_DAYS = "pending_digest_days"
CB_PENDING_DIGEST_DAYS_WEEKDAYS = "pending_digest_days_weekdays"
CB_PENDING_DIGEST_DAYS_ALL = "pending_digest_days_all"
CB_PENDING_DIGEST_DAY_PREFIX = "pending_digest_d:"
CB_PENDING_DIGEST_TIME = "pending_digest_time"
CB_PENDING_DIGEST_BACK = "pending_digest_back"
CB_PENDING_DIGEST_CLOSE = "pending_digest_close"


def _pending_digest_days_label(digest_days: str) -> str:
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
            [
                styled_button(
                    toggle_label,
                    CB_PENDING_DIGEST_TOGGLE,
                    style="danger" if digest_enabled else "success",
                )
            ],
            [{"text": "⬅️ В настройки", "callback_data": CB_SETTINGS_BACK}],
        ]
    }


def build_pending_digest_days_keyboard(*, digest_days: str) -> dict:
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
