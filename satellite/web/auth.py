"""Валидация Telegram ``initData`` и connect-token'а для Web App.

Авторизованный пользователь должен быть ``approved`` в ``UserStore``;
любой негативный исход — отправляет HTTP-ответ и поднимает :class:`AbortRequest`.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

from ..users import USER_STATUS_APPROVED, UserStore
from .connect_token import ConnectTokenStore
from .init_data import InitDataError, validate_init_data
from .parsing import extract_connect_token, extract_init_data
from .responses import AbortRequest, json_response

log = logging.getLogger(__name__)


def _user_id_from_connect_token(
    handler: BaseHTTPRequestHandler,
    users: UserStore,
    connect_tokens: ConnectTokenStore,
    *,
    body: dict[str, Any] | None = None,
) -> int | None:
    token = extract_connect_token(handler, body)
    if not token:
        return None
    user_id = connect_tokens.resolve(token)
    if user_id is None:
        log.info("Reject WebApp request: invalid or expired connect token")
        json_response(
            handler,
            HTTPStatus.UNAUTHORIZED,
            {"error": "connect_token_invalid", "message": "Connect link expired"},
        )
        raise AbortRequest()
    record = users.get(user_id)
    if record is None or record.status != USER_STATUS_APPROVED:
        log.info(
            "Reject WebApp request: connect token user_id=%s not approved (status=%s)",
            user_id,
            getattr(record, "status", None),
        )
        json_response(handler, HTTPStatus.FORBIDDEN, {"error": "not_approved"})
        raise AbortRequest()
    return user_id


def validated_user(
    handler: BaseHTTPRequestHandler,
    users: UserStore,
    bot_token: str,
    connect_tokens: ConnectTokenStore,
    *,
    body: dict[str, Any] | None = None,
) -> int:
    """Возвращает telegram_user_id, если initData валидна и пользователь approved.

    Без approved-статуса возвращает HTTP 403 и поднимает ``AbortRequest``,
    чтобы хендлер сразу завершился. Web App доступен только тем, кому
    одобрили заявку на доступ через админский флоу.
    """
    init_data = extract_init_data(handler, body)
    if init_data:
        try:
            validated = validate_init_data(init_data, bot_token=bot_token)
        except InitDataError as exc:
            log.info("Reject WebApp request: %s", exc)
            json_response(
                handler,
                HTTPStatus.UNAUTHORIZED,
                {"error": exc.code, "message": str(exc)},
            )
            raise AbortRequest()
        record = users.get(validated.user.id)
        if record is None or record.status != USER_STATUS_APPROVED:
            log.info(
                "Reject WebApp request: user_id=%s not approved (status=%s)",
                validated.user.id,
                getattr(record, "status", None),
            )
            json_response(handler, HTTPStatus.FORBIDDEN, {"error": "not_approved"})
            raise AbortRequest()
        return validated.user.id

    user_id = _user_id_from_connect_token(handler, users, connect_tokens, body=body)
    if user_id is not None:
        return user_id

    log.info("Reject WebApp request: missing initData and connect token")
    json_response(
        handler,
        HTTPStatus.UNAUTHORIZED,
        {
            "error": "no_init_data",
            "message": "Missing initData (open Web App from Telegram bot button)",
        },
    )
    raise AbortRequest()
