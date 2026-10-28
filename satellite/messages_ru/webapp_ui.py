"""User-facing copy для Web App (/connect)."""

from __future__ import annotations

import json
from typing import Any

from .calendar_ui import CALENDAR_CONNECTION_CHANGED_TEXT, CREATE_EVENT_UNCONFIRMED_HTML
from .meetings_ui import PARTSTAT_UNCONFIRMED_TEXT

WEBAPP_COPY: dict[str, Any] = {
    "page_title": "Чайка — календарь",
    "heading": "Календарь",
    "user_hint_default": "Подключи календарь Mail.ru, чтобы Чайка собирала твой день.",
    "tab_connection": "Подключение",
    "tab_events": "События",
    "tab_create": "Создать",
    "status_checking": "проверяю…",
    "status_ready": "можно подключить",
    "status_connected_prefix": "подключён: ",
    "status_reconnect": "подключи заново",
    "status_disconnected": "не подключён",
    "status_not_approved": "ожидает одобрения",
    "status_check_error": "не удалось проверить",
    "hint_connect": "Введи почту и пароль приложения, затем нажми «Подключить».",
    "hint_connected": "Календарь подключён. Здесь можно посмотреть встречи и создать новые.",
    "hint_not_approved": "Администратор ещё не открыл доступ. Чайка сообщит, когда можно будет "
    "подключить календарь.",
    "events_hint": "События на ближайшие 7 дней, по дням.",
    "events_refresh": "Обновить",
    "events_empty_open": "Нажми «Обновить», чтобы загрузить события.",
    "events_loading": "Собираю события на ближайшие 7 дней…",
    "events_not_connected": "Сначала подключи календарь.",
    "events_not_approved": "Администратор ещё не открыл доступ.",
    "events_load_fail": "Не удалось загрузить события.",
    "events_empty": "На ближайшие 7 дней встреч нет.",
    "events_heading": "Ближайшие события",
    "events_delete": "Удалить",
    "connect_btn": "Подключить",
    "check_btn": "Проверить подключение",
    "disconnect_btn": "Отключить календарь",
    "create_confirm_title": "Создать событие?",
    "create_cancel": "❌ Отмена",
    "create_confirm": "✅ Создать",
    "connection_pending": "Проверяю подключение…",
    "create_saving": "Добавляю событие в календарь…",
    "request_failed": "Не удалось получить ответ. Проверь соединение и попробуй ещё раз.",
    "write_unconfirmed": "Не удалось подтвердить результат. Изменение могло сохраниться. Проверь "
    "календарь перед повторной попыткой, чтобы не выполнить действие "
    "дважды.",
    "request_timeout": "Ответ занимает слишком много времени. Попробуй ещё раз позже.",
    "create_invalid_local_time": "Такого местного времени нет из-за перевода часов. Выбери "
    "другое время.",
    "duration_min_suffix": " мин",
    "telegram_errors": {
        "no_init_data": "Не удалось подтвердить вход. Закрой окно и снова нажми "
        "«Подключить календарь» в чате с Чайкой.",
        "bad_signature": "Не удалось подтвердить вход. Закрой окно и открой его "
        "снова из чата с Чайкой.",
        "expired": "Срок доступа к этому окну истёк. Закрой его и открой снова из чата с Чайкой.",
        "connect_token_invalid": "Ссылка устарела. Закрой окно и снова нажми "
        "«Подключить календарь» в чате с Чайкой.",
        "default": "Не удалось войти. Закрой окно и открой его снова из чата с Чайкой.",
    },
    "disconnection_pending": "Отключаю календарь…",
    "status_label": "Статус:",
    "provider_label": "Сервис календаря",
    "provider_yandex": "Яндекс — пока недоступен",
    "login_label": "Почта календаря",
    "password_label": "Пароль приложения",
    "password_placeholder": "Введи пароль",
    "provider_mailru": "Mail.ru",
    "caldav_url_placeholder": "https://…",
    "credentials_hint_html": "В настройках Mail.ru открой «Пароли для внешних приложений» и "
    "создай пароль с доступом <strong>«Календарь»</strong>. Это не "
    "пароль от почты. Подойдёт адрес @mail.ru или корпоративная почта "
    "на calendar.mail.ru.",
    "caldav_url_label": "Адрес календаря (CalDAV, необязательно)",
    "caldav_url_hint": "Оставь поле пустым, если у тебя есть только адрес calendar.mail.ru. "
    "Чайка сама найдёт календари. Полный адрес учётной записи (principal URL) "
    "укажи, только если его дал почтовый клиент.",
    "create_title_label": "➕ Как назвать событие?",
    "create_title_placeholder": "Встреча команды",
    "create_date_label": "📅 На какой день?",
    "create_today": "📅 Сегодня",
    "create_tomorrow": "➡️ Завтра",
    "create_date_hint": "Или выбери дату в календаре.",
    "create_time_label": "🕘 Во сколько начнётся?",
    "create_time_hint": "Например, 09:30",
    "create_duration_label": "⏱ Сколько минут продлится?",
    "create_next": "Далее",
    "create_back": "Назад",
    "connect_missing_fields": "Введи почту и пароль приложения.",
    "connect_sent_to_bot": "Данные отправлены. Посмотри результат в чате с Чайкой.",
    "connect_open_from_bot": "Открой окно снова: отправь /connect в чате с Чайкой и нажми кнопку "
    "под сообщением.",
    "connect_success": "Календарь подключён.",
    "connect_failed": "Не удалось подключить календарь. Попробуй ещё раз позже.",
    "connect_auth_failed": "Не удалось войти в календарь. Проверь почту, пароль приложения с "
    "доступом «Календарь» и адрес CalDAV, если ты его указал.",
    "connect_before_check_chat": "Сначала нажми «Подключить». Результат проверки появится в чате "
    "с Чайкой.",
    "connect_before_check": "Сначала подключи календарь кнопкой «Подключить».",
    "connection_active": "Подключение работает.",
    "connection_inactive": "Календарь не подключён.",
    "connection_check_failed": "Не удалось проверить подключение. Попробуй ещё раз позже.",
    "disconnect_success": "Календарь отключён.",
    "disconnect_failed": "Не удалось отключить календарь. Попробуй ещё раз позже.",
    "delete_confirm": "Удалить событие из календаря?",
    "delete_success": "Событие удалено.",
    "delete_failed": "Не удалось удалить событие. Обнови список и попробуй ещё раз.",
    "create_title_required": "Напиши название события.",
    "create_date_invalid": "Выбери дату в календаре или нажми «Сегодня» либо «Завтра».",
    "create_time_invalid": "Укажи время начала, например 09:30.",
    "create_duration_invalid": "Укажи длительность целым числом минут от 1 до 1440, например 60.",
    "create_success": "✅ Событие добавлено в твой календарь.",
    "create_failed": "Не удалось создать событие. Попробуй ещё раз позже.",
    "create_write_failed": "Не удалось создать событие. Проверь право на запись в календарь.",
    "api_errors": {
        "not_approved": "Администратор ещё не открыл доступ. Чайка сообщит, когда "
        "можно будет подключить календарь.",
        "not_found": "Страница не найдена.",
        "request_failed": "Не удалось выполнить действие. Попробуй ещё раз позже.",
        "unknown_provider": "Этот сервис календаря не распознан. Выбери Mail.ru.",
        "PROVIDER_NOT_IMPLEMENTED": "Этот сервис календаря пока недоступен. Сейчас "
        "можно подключить Mail.ru.",
        "missing_fields": "Заполни обязательные поля.",
        "storage_unavailable": "Не удалось сохранить настройки. Попробуй ещё раз позже.",
        "invalid_days": "Выбери от 1 до 31 дня.",
        "not_connected": "Сначала подключи календарь.",
        "invalid_range": "Проверь даты: конец периода не должен быть раньше начала.",
        "invalid_dates": "Проверь дату и время события. Оно должно заканчиваться "
        "позже, чем начинается.",
        "invalid_duration": "Укажи длительность целым числом минут от 1 до 1440, например 60.",
        "missing_uid": "Не удалось определить событие. Обнови список и выбери его снова.",
        "AUTH_FAILED": "Не удалось войти в календарь. Проверь почту, пароль "
        "приложения с доступом «Календарь» и адрес CalDAV, если ты его "
        "указал.",
        "CALENDAR_NOT_CONNECTED": "Сначала подключи календарь.",
        "CALDAV_UNAVAILABLE": "Не удалось получить данные календаря. Попробуй ещё раз позже.",
        "CALENDAR_ERROR": "Не удалось выполнить действие с календарём. Попробуй ещё раз позже.",
        "NO_CALENDAR": "Не удалось найти календарь. Проверь его в Mail.ru и подключи заново.",
        "MISSING_EVENT_URL": "Не удалось найти адрес встречи. Обнови список и выбери её снова.",
        "PARTSTAT_UPDATE_FAILED": "Не удалось сохранить ответ на приглашение. Обнови "
        "список и попробуй ещё раз.",
        "CREATE_FAILED": "Не удалось создать событие. Проверь право на запись в календарь.",
        "UPDATE_FAILED": "Не удалось изменить событие. Обнови список и попробуй ещё раз.",
        "DELETE_FAILED": "Не удалось удалить событие. Обнови список и попробуй ещё раз.",
    },
}


WEBAPP_COPY["api_errors"].update(
    {
        "unauthorized": WEBAPP_COPY["telegram_errors"]["default"],
        "server_misconfigured": "Не удалось открыть подключение. Попробуй ещё раз позже.",
        "CALENDAR_CONNECTION_CHANGED": CALENDAR_CONNECTION_CHANGED_TEXT,
        "CREATE_UNCONFIRMED": CREATE_EVENT_UNCONFIRMED_HTML,
        "PARTSTAT_UPDATE_UNCONFIRMED": PARTSTAT_UNCONFIRMED_TEXT,
    }
)


def webapp_copy_json() -> str:
    """JSON для инжекта в ``window.__SATELLITE_COPY__``."""
    return json.dumps(WEBAPP_COPY, ensure_ascii=False)
