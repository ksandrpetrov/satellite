"""User-facing copy для Web App (/connect)."""

from __future__ import annotations

import json
from typing import Any

WEBAPP_COPY: dict[str, Any] = {
    "page_title": "Чайка — календарь",
    "heading": "Календарь",
    "user_hint_default": "Подключите Mail.ru, чтобы Чайка собирала ваш день.",
    "tab_connection": "Подключение",
    "tab_events": "События",
    "tab_create": "Создать",
    "status_checking": "проверяем…",
    "status_ready": "готов к подключению",
    "status_connected_prefix": "подключено: ",
    "status_reconnect": "требует переподключения",
    "status_disconnected": "не подключено",
    "status_not_approved": "доступ не одобрен",
    "status_check_error": "ошибка проверки",
    "hint_connect": "Введите логин и пароль приложения, затем нажмите «Подключить».",
    "hint_connected": "Календарь подключён. Можно создавать события прямо отсюда.",
    "hint_not_approved": "Доступ ещё не одобрен админом. Ожидайте сообщения от бота.",
    "events_hint": "Как в боте: ближайшие 7 дней, сгруппировано по дням.",
    "events_refresh": "Обновить",
    "events_empty_open": "Откройте вкладку или нажмите «Обновить».",
    "events_loading": "Чайка собирает ближайшие события…",
    "events_not_connected": "Сначала подключите календарь.",
    "events_not_approved": "Доступ не одобрен.",
    "events_load_fail": "Не удалось загрузить события.",
    "events_empty": "На ближайшие дни встреч нет.",
    "events_heading": "Ближайшие события",
    "events_delete": "Удалить",
    "connect_btn": "Подключить",
    "check_btn": "Проверить подключение",
    "disconnect_btn": "Отключить календарь",
    "create_confirm_title": "Создать событие?",
    "create_cancel": "❌ Отмена",
    "create_confirm": "✅ Создать",
    "duration_min_suffix": " мин",
    "telegram_errors": {
        "no_init_data": (
            "Не удалось подтвердить сессию. Закройте окно и снова нажмите "
            "«Подключить календарь» в чате с ботом."
        ),
        "bad_signature": (
            "На сервере другой TELEGRAM_BOT_TOKEN. Проверьте .env и перезапустите бота."
        ),
        "expired": "Сессия устарела. Закройте окно и откройте снова из бота.",
        "connect_token_invalid": (
            "Ссылка устарела. Закройте окно и снова нажмите «Подключить календарь» в боте."
        ),
        "default": "Не удалось войти. Закройте окно и откройте снова из бота.",
    },
}


def webapp_copy_json() -> str:
    """JSON для инжекта в ``window.__SATELLITE_COPY__``."""
    return json.dumps(WEBAPP_COPY, ensure_ascii=False)
