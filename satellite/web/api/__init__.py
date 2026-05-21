"""REST-хендлеры Web App (``/api/calendar/*``).

Каждый хендлер принимает ``BaseHTTPRequestHandler`` и :class:`..routing.Deps`,
сам себе отправляет HTTP-ответ. Боль и обёртки авторизации/маппинга
ошибок — в общих модулях ``web.auth`` / ``web.responses``.
"""

from .calendar import (
    handle_connect,
    handle_create_event,
    handle_delete_event,
    handle_disconnect,
    handle_list_events,
    handle_status,
)
__all__ = [
    "handle_connect",
    "handle_create_event",
    "handle_delete_event",
    "handle_disconnect",
    "handle_list_events",
    "handle_status",
]
