"""Парсеры request body / query / path для Web App сервера.

Все функции — без I/O за пределы чтения handler.rfile, чтобы тесты могли
проверять их без HTTP-сервера.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, tzinfo
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

MAX_BODY_BYTES = 64 * 1024

_CONNECT_TOKEN_PATH_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except ValueError:
        return {}
    if length <= 0 or length > MAX_BODY_BYTES:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def extract_init_data(
    handler: BaseHTTPRequestHandler,
    body: dict[str, Any] | None = None,
) -> str:
    """initData из заголовка, JSON-тела или query (nginx часто не проксирует кастомные headers)."""
    init_data = (handler.headers.get("X-Telegram-Init-Data") or "").strip()
    if init_data:
        return init_data
    if body is not None:
        from_body = str(body.get("initData") or "").strip()
        if from_body:
            return from_body
    qs = parse_qs(urlparse(handler.path).query)
    from_query = (qs.get("initData") or [""])[0].strip()
    return from_query


def connect_token_from_path(path: str) -> str | None:
    normalized = (path or "").rstrip("/")
    if not normalized.startswith("/connect/") or normalized == "/connect":
        return None
    token = normalized.split("/connect/", 1)[1].split("/", 1)[0].strip()
    if not token or not _CONNECT_TOKEN_PATH_RE.fullmatch(token):
        return None
    return token


def share_token_from_path(path: str) -> str | None:
    normalized = (path or "").rstrip("/")
    if not normalized.startswith("/share/") or normalized == "/share":
        return None
    token = normalized.split("/share/", 1)[1].split("/", 1)[0].strip()
    if not token or not _CONNECT_TOKEN_PATH_RE.fullmatch(token):
        return None
    return token


def extract_connect_token(
    handler: BaseHTTPRequestHandler,
    body: dict[str, Any] | None = None,
) -> str:
    token = (handler.headers.get("X-Connect-Token") or "").strip()
    if token:
        return token
    if body is not None:
        from_body = str(body.get("t") or body.get("connect_token") or "").strip()
        if from_body and _CONNECT_TOKEN_PATH_RE.fullmatch(from_body):
            return from_body
    parsed_path = urlparse(handler.path)
    from_path = connect_token_from_path(parsed_path.path) or ""
    if from_path:
        return from_path
    from_share = share_token_from_path(parsed_path.path) or ""
    if from_share:
        return from_share
    qs = parse_qs(parsed_path.query)
    from_query = (qs.get("t") or [""])[0].strip()
    if from_query and _CONNECT_TOKEN_PATH_RE.fullmatch(from_query):
        return from_query
    return ""


def parse_positive_int(value: str | None, *, default: int) -> int | None:
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value: str, tz: tzinfo) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt


def serialize_event(event: dict) -> dict:
    return {
        "uid": event.get("uid") or event.get("id"),
        "url": event.get("url"),
        "title": event.get("summary") or event.get("title") or "",
        "location": event.get("location") or "",
        "start": event.get("dtstart"),
        "end": event.get("dtend"),
        "status": event.get("status"),
        "all_day": bool(event.get("all_day")),
    }


def query_string(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    return parse_qs(urlparse(handler.path).query)


def request_path(handler: BaseHTTPRequestHandler) -> str:
    return urlparse(handler.path).path
