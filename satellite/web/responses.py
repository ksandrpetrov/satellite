"""HTTP-ответы и общий ``_AbortRequest`` для embedded Web App сервера."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any


class AbortRequest(Exception):
    """Сигнал хендлеру: ответ уже отправлен, надо тихо выйти."""


# Алиас для обратной совместимости со старым API внутри пакета.
_AbortRequest = AbortRequest


def json_response(
    handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any]
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def png_response(handler: BaseHTTPRequestHandler, body: bytes, *, filename: str) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", f'inline; filename="{filename}"')
    handler.end_headers()
    handler.wfile.write(body)
