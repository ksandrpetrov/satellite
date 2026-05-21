"""Сервинг статических HTML-страниц Web App (``/connect``).

Telegram-клиент открывает страницы во встроенном WebView; страницы
получают токен подключения, инжектируемый в начало ``<script>``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .responses import json_response


@dataclass(frozen=True)
class StaticPage:
    """Описание SPA-страницы, отдаваемой Web App-сервером."""

    path: Path
    csp_img_src: str = "'self' data:"

    def csp(self) -> str:
        return (
            "default-src 'self'; "
            "script-src 'self' https://telegram.org 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            f"img-src {self.csp_img_src}; connect-src 'self'; "
            "frame-ancestors 'self' https://web.telegram.org https://*.web.telegram.org "
            "https://telegram.org https://*.telegram.org"
        )


def serve_html(
    handler: BaseHTTPRequestHandler,
    page: StaticPage,
    *,
    path_token: str | None = None,
) -> None:
    """Отдаёт SPA-страницу с инжектом ``window.__SATELLITE_CONNECT_TOKEN__``.

    Параметры безопасности: ``X-Content-Type-Options: nosniff``,
    ``Referrer-Policy: no-referrer``, ``Cache-Control: no-store``,
    CSP с фрейм-предками для Telegram WebView. Не ставим ``X-Frame-Options``:
    ломает WebView Telegram Desktop/Web.
    """
    if not page.path.is_file():
        json_response(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        return
    body = page.path.read_bytes()
    if path_token:
        inject = (
            "<script>window.__SATELLITE_CONNECT_TOKEN__="
            + json.dumps(path_token, ensure_ascii=False)
            + ";</script>\n  "
        )
        marker = b"<script>"
        if marker in body:
            body = body.replace(marker, inject.encode("utf-8") + marker, 1)
        else:
            body = inject.encode("utf-8") + body
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Content-Security-Policy", page.csp())
    handler.end_headers()
    handler.wfile.write(body)
