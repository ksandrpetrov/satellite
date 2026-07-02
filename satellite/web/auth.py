"""Валидация Telegram ``initData`` и connect-token'а для Web App.

Авторизованный пользователь должен быть ``approved`` в ``UserStore``;
любой негативный исход — отправляет HTTP-ответ и поднимает :class:`AbortRequest`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

from ..users import USER_STATUS_APPROVED, UserStore
from .connect_token import ConnectTokenStore
from .errors import error_payload
from .init_data import InitDataError, validate_init_data
from .parsing import extract_connect_token, extract_init_data
from .responses import AbortRequest, json_response

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedWebUser:
    user_id: int
    source: str


class AuthResolver:
    """Single source of truth for Web App auth resolution."""

    def __init__(
        self,
        *,
        users: UserStore,
        bot_token: str,
        connect_tokens: ConnectTokenStore,
    ) -> None:
        self._users = users
        self._bot_token = bot_token
        self._connect_tokens = connect_tokens

    def resolve_user(
        self,
        handler: BaseHTTPRequestHandler,
        *,
        body: dict[str, Any] | None = None,
    ) -> ResolvedWebUser:
        init_data = extract_init_data(handler, body)
        if init_data:
            return self._resolve_init_data(handler, init_data)

        token = extract_connect_token(handler, body)
        if token:
            return self._resolve_connect_token(handler, token)

        log.info("Reject WebApp request: missing initData and connect token")
        json_response(
            handler,
            HTTPStatus.UNAUTHORIZED,
            error_payload(
                "no_init_data",
                message="Missing initData (open Web App from Telegram bot button)",
            ),
        )
        raise AbortRequest()

    def _resolve_init_data(
        self,
        handler: BaseHTTPRequestHandler,
        init_data: str,
    ) -> ResolvedWebUser:
        try:
            validated = validate_init_data(init_data, bot_token=self._bot_token)
        except InitDataError as exc:
            log.info("Reject WebApp request: source=init_data reason=%s", exc)
            json_response(
                handler,
                HTTPStatus.UNAUTHORIZED,
                error_payload(exc.code, message=str(exc)),
            )
            raise AbortRequest() from exc
        self._ensure_approved(handler, validated.user.id, source="init_data")
        return ResolvedWebUser(user_id=validated.user.id, source="init_data")

    def _resolve_connect_token(
        self,
        handler: BaseHTTPRequestHandler,
        token: str,
    ) -> ResolvedWebUser:
        user_id = self._connect_tokens.resolve(token)
        if user_id is None:
            log.info("Reject WebApp request: source=connect_token reason=invalid_or_expired")
            json_response(
                handler,
                HTTPStatus.UNAUTHORIZED,
                error_payload("connect_token_invalid", message="Connect link expired"),
            )
            raise AbortRequest()
        self._ensure_approved(handler, user_id, source="connect_token")
        return ResolvedWebUser(user_id=user_id, source="connect_token")

    def _ensure_approved(
        self,
        handler: BaseHTTPRequestHandler,
        user_id: int,
        *,
        source: str,
    ) -> None:
        record = self._users.get(user_id)
        if record is None or record.status != USER_STATUS_APPROVED:
            log.info(
                "Reject WebApp request: source=%s user_id=%s not approved (status=%s)",
                source,
                user_id,
                getattr(record, "status", None),
            )
            json_response(handler, HTTPStatus.FORBIDDEN, error_payload("not_approved"))
            raise AbortRequest()


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
    resolver = AuthResolver(users=users, bot_token=bot_token, connect_tokens=connect_tokens)
    return resolver.resolve_user(handler, body=body).user_id
