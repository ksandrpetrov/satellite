"""REST-хендлеры календаря: connect / disconnect / status / events CRUD."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from ..auth import validated_user
from ..calendar_api_service import CalendarApiService
from ..parsing import query_string, read_json, request_path
from ..responses import AbortRequest, json_response
from ..routing import Deps


def handle_connect(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    body = read_json(handler)
    try:
        user_id = validated_user(
            handler, deps.users, deps.bot_token, deps.connect_tokens, body=body
        )
    except AbortRequest:
        return
    result = CalendarApiService(calendar=deps.calendar, users=deps.users, tz=deps.tz).connect(
        user_id, body
    )
    json_response(handler, result.status, result.payload)


def handle_disconnect(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    result = CalendarApiService(calendar=deps.calendar, users=deps.users, tz=deps.tz).disconnect(
        user_id
    )
    json_response(handler, result.status, result.payload)


def handle_status(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    result = CalendarApiService(calendar=deps.calendar, users=deps.users, tz=deps.tz).status(
        user_id
    )
    json_response(handler, result.status, result.payload)


def handle_list_events(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    query = {key: values[0] if values else None for key, values in query_string(handler).items()}
    result = CalendarApiService(calendar=deps.calendar, users=deps.users, tz=deps.tz).list_events(
        user_id, query
    )
    json_response(handler, result.status, result.payload)


def handle_create_event(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    body = read_json(handler)
    try:
        user_id = validated_user(
            handler, deps.users, deps.bot_token, deps.connect_tokens, body=body
        )
    except AbortRequest:
        return
    result = CalendarApiService(calendar=deps.calendar, users=deps.users, tz=deps.tz).create_event(
        user_id, body
    )
    json_response(handler, result.status, result.payload)


def handle_delete_event(handler: BaseHTTPRequestHandler, deps: Deps) -> None:
    try:
        user_id = validated_user(handler, deps.users, deps.bot_token, deps.connect_tokens)
    except AbortRequest:
        return
    path = request_path(handler)
    uid = path[len("/api/calendar/events/") :].strip("/")
    url = query_string(handler).get("url", [None])[0]
    result = CalendarApiService(calendar=deps.calendar, users=deps.users, tz=deps.tz).delete_event(
        user_id, uid, url
    )
    json_response(handler, result.status, result.payload)
