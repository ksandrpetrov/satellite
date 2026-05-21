"""REST-хендлер для PNG-карточек «Поделиться» (план / ближайшие / аналитика)."""

from __future__ import annotations

import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from ...calendar.providers.base import (
    CalendarNotConnectedError,
    CalendarProviderError,
)
from ...share_service import (
    SHARE_KIND_ANALYTICS,
    SHARE_KIND_PLAN,
    SHARE_KIND_UPCOMING,
    build_share_png,
)
from ..auth import validated_user
from ..parsing import parse_positive_int, query_string
from ..responses import AbortRequest, json_response, png_response
from ..routing import Deps

log = logging.getLogger(__name__)

_DEFAULT_UPCOMING_DAYS = 7

SHARE_KINDS = frozenset({SHARE_KIND_PLAN, SHARE_KIND_UPCOMING, SHARE_KIND_ANALYTICS})

_DOWNLOAD_NAMES = {
    SHARE_KIND_PLAN: "chaika-plan.png",
    SHARE_KIND_UPCOMING: "chaika-upcoming.png",
    SHARE_KIND_ANALYTICS: "chaika-analytics.png",
}


def handle_share_card(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    record = deps.users.get(user_id)
    if record is None or not record.has_calendar:
        json_response(handler, HTTPStatus.CONFLICT, {"error": "not_connected"})
        return
    qs = query_string(handler)
    kind = (qs.get("kind", [SHARE_KIND_PLAN])[0] or "").strip().lower()
    if kind not in SHARE_KINDS:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_kind"})
        return
    mode = (qs.get("mode", [""])[0] or "").strip().lower() or None
    days_raw = (qs.get("days", [""])[0] or "").strip()
    days = parse_positive_int(days_raw, default=_DEFAULT_UPCOMING_DAYS) if days_raw else None
    try:
        png = build_share_png(
            kind=kind,
            telegram_user_id=user_id,
            tz=deps.tz,
            calendar_service=deps.calendar,
            users=deps.users,
            plan_config=deps.plan_config,
            mode=mode,
            days=days,
        )
    except CalendarNotConnectedError:
        json_response(handler, HTTPStatus.CONFLICT, {"error": "not_connected"})
        return
    except CalendarProviderError as exc:
        json_response(
            handler,
            HTTPStatus.BAD_GATEWAY,
            {"error": exc.error_code, "message": str(exc)},
        )
        return
    except ValueError as exc:
        json_response(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": "invalid_request", "message": str(exc)},
        )
        return
    except Exception:  # noqa: BLE001
        log.exception("Share card build failed user_id=%s kind=%s", user_id, kind)
        json_response(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "build_failed"})
        return
    png_response(handler, png, filename=_DOWNLOAD_NAMES.get(kind, "chaika.png"))
