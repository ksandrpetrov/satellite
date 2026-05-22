"""Контрактные тесты команд / callback'ов / Web routes.

Цель — поймать рассинхрон между документацией (``docs/telegram-ux.md``,
``messages_ru/_core.py``) и кодом маршрутизации:

- каждый documented alias возвращает правильный ``RecognizedCommand``;
- каждый класс из union ``RecognizedCommand`` обрабатывается dispatch'ем
  (через ``_MESSAGE_ROUTES`` или явный special-case в ``handle_message``);
- каждый ``CB_*`` константа из ``messages_ru/_core.py`` имеет router в
  цепочке ``_CALLBACK_ROUTERS`` (с явным allowlist для констант, которые
  по дизайну не идут через callback — например, кнопки Web App);
- каждый маршрут ``API_ROUTES`` без auth возвращает 401/400, не 500.
"""

from __future__ import annotations

import inspect
import json
import socket
import typing
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from satellite.messages_ru import (
    BUTTON_CALENDAR_SOURCES,
    BUTTON_CHECK_CALENDAR,
    BUTTON_CONNECT_CALENDAR,
    BUTTON_CREATE_EVENT,
    BUTTON_DISCONNECT_CALENDAR,
    BUTTON_FOREIGN_CALENDARS,
    BUTTON_INVITATIONS,
    BUTTON_MANAGE_EVENTS,
    BUTTON_RECONNECT_CALENDAR,
    BUTTON_SETTINGS,
    BUTTON_SUBSCRIBE,
    BUTTON_TODAY,
    BUTTON_TOMORROW,
    BUTTON_UNSUBSCRIBE,
    BUTTON_UNSUBSCRIBE_LEGACY,
    BUTTON_UPCOMING,
)
from satellite.messages_ru import _core as messages_core
from satellite.telegram_bot.commands import BOT_COMMANDS
from satellite.telegram_bot.handlers.dispatch import (
    _CALLBACK_ROUTERS,
    _MESSAGE_ROUTES,
)
from satellite.telegram_bot.handlers.routing import (
    CalendarSourcesCommand,
    CheckCommand,
    ConnectCommand,
    CreateCommand,
    DisconnectCommand,
    ForeignCalendarsCommand,
    InvitationsCommand,
    ManageEventsCommand,
    PendingCommand,
    PlanCommand,
    RecognizedCommand,
    SettingsCommand,
    StartOrHelpCommand,
    SubscriptionCommand,
    UpcomingCommand,
    recognize_message,
)
from satellite.users import UserStore
from satellite.web.connect_token import ConnectTokenStore

# --- Alias / command coverage ---------------------------------------------

# Полный список из docs/telegram-ux.md + регулярных выражений из routing.py.
# Если этот список расходится с реальностью — тест ловит регрессию.
_ALIAS_CASES = [
    # short text-mode aliases (без слэша)
    ("td", PlanCommand),
    ("tm", PlanCommand),
    ("dat", PlanCommand),
    ("TD", PlanCommand),
    ("DAT", PlanCommand),
    # short slash aliases
    ("/td", PlanCommand),
    ("/tm", PlanCommand),
    ("/dat", PlanCommand),
    # long menu aliases
    ("/today", PlanCommand),
    ("/tomorrow", PlanCommand),
    ("/aftertomorrow", PlanCommand),
    ("/after_tomorrow", PlanCommand),
    # menu suffix variants
    ("/today@SomeBot", PlanCommand),
    ("/after_tomorrow@SomeBot", PlanCommand),
    # /start, /help, /pending
    ("/start", StartOrHelpCommand),
    ("/help", StartOrHelpCommand),
    ("/pending", PendingCommand),
    # upcoming
    ("/upcoming", UpcomingCommand),
    ("/events", UpcomingCommand),
    # invitations
    ("/invitations", InvitationsCommand),
    ("/invites", InvitationsCommand),
    ("/respond", InvitationsCommand),
    # manage
    ("/manage", ManageEventsCommand),
    ("/edit", ManageEventsCommand),
    ("/status", ManageEventsCommand),
    # create
    ("/create", CreateCommand),
    ("/addevent", CreateCommand),
    # connect / settings / subscribe
    ("/connect", ConnectCommand),
    ("/settings", SettingsCommand),
    ("/digest", SubscriptionCommand),
    ("/subscribe", SubscriptionCommand),
    ("/sub", SubscriptionCommand),
    ("/stopdigest", SubscriptionCommand),
    ("/unsubscribe", SubscriptionCommand),
    ("/unsub", SubscriptionCommand),
    # calendar sources
    ("/calendars", CalendarSourcesCommand),
    ("/calendar_sources", CalendarSourcesCommand),
    # foreign calendars
    ("/foreign", ForeignCalendarsCommand),
    ("/shared_calendars", ForeignCalendarsCommand),
    ("/foreign_calendars", ForeignCalendarsCommand),
    # reply-keyboard buttons
    (BUTTON_TODAY, PlanCommand),
    (BUTTON_TOMORROW, PlanCommand),
    (BUTTON_UPCOMING, UpcomingCommand),
    (BUTTON_INVITATIONS, InvitationsCommand),
    (BUTTON_MANAGE_EVENTS, ManageEventsCommand),
    (BUTTON_CREATE_EVENT, CreateCommand),
    (BUTTON_SETTINGS, SettingsCommand),
    (BUTTON_FOREIGN_CALENDARS, ForeignCalendarsCommand),
    (BUTTON_CALENDAR_SOURCES, CalendarSourcesCommand),
    (BUTTON_SUBSCRIBE, SubscriptionCommand),
    (BUTTON_UNSUBSCRIBE, SubscriptionCommand),
    (BUTTON_UNSUBSCRIBE_LEGACY, SubscriptionCommand),
    (BUTTON_CONNECT_CALENDAR, ConnectCommand),
    (BUTTON_RECONNECT_CALENDAR, ConnectCommand),
    (BUTTON_CHECK_CALENDAR, CheckCommand),
    (BUTTON_DISCONNECT_CALENDAR, DisconnectCommand),
]


@pytest.mark.parametrize("text,expected_type", _ALIAS_CASES)
def test_every_documented_alias_is_recognized(text: str, expected_type) -> None:
    cmd = recognize_message(text)
    assert cmd is not None, f"alias {text!r} не распознаётся"
    assert isinstance(cmd, expected_type), (
        f"alias {text!r} распознался как {type(cmd).__name__}, ожидался {expected_type.__name__}"
    )


def test_unknown_text_is_not_recognized() -> None:
    assert recognize_message("просто болталка") is None
    assert recognize_message("/nope") is None
    assert recognize_message("") is None
    assert recognize_message(None) is None


# --- RecognizedCommand → _MESSAGE_ROUTES coverage --------------------------

_MESSAGE_ROUTE_EXCEPTIONS = {
    # StartOrHelpCommand и PendingCommand обрабатываются как special-case
    # в handle_message ДО _MESSAGE_ROUTES (см. handlers/dispatch.py).
    StartOrHelpCommand,
    PendingCommand,
}


def test_message_routes_cover_every_recognized_command_subclass() -> None:
    """Каждый класс из ``RecognizedCommand`` либо в _MESSAGE_ROUTES, либо в special-case."""
    subclasses = set(typing.get_args(RecognizedCommand))
    routed = set(_MESSAGE_ROUTES.keys())
    handled = routed | _MESSAGE_ROUTE_EXCEPTIONS
    missing = subclasses - handled
    assert not missing, (
        f"RecognizedCommand subclasses без обработчика: {sorted(c.__name__ for c in missing)}"
    )


# --- Меню Telegram: список команд должен соответствовать docs --------------


def test_bot_commands_list_matches_menu_spec() -> None:
    """Список в BOT_COMMANDS должен полностью совпадать с длинными алиасами роутера.

    Каждая команда в меню обязана быть распознаваемой ``recognize_message``.
    """
    for name, description in BOT_COMMANDS:
        cmd = recognize_message(f"/{name}")
        assert cmd is not None, (
            f"BOT_COMMANDS содержит /{name}, но recognize_message его не возвращает"
        )
        assert description and isinstance(description, str)


# --- CB_* → router coverage -----------------------------------------------

# Constants that are intentionally NOT routed through callback chain:
# - admin approve/reject обрабатываются по префиксу, но требуют конкретного user_id
#   в суффиксе (тест добавляет sample suffix);
# - settings_reconnect — мёртвая константа (reconnect живёт в `web_app: {url:}`).
_CB_NOT_ROUTED_ALLOWLIST = {
    "settings_reconnect",  # см. messages_ru/_core.py: web_app кнопка, не callback
    # `cal_sources` объявлен исторически, но в текущих keyboard'ах не используется —
    # реальный entry-point — `CB_SETTINGS_CALENDARS`. Оставлен как allowlisted,
    # чтобы не плодить требование на «route to nowhere».
    "cal_sources",
}


def _all_cb_constants() -> dict[str, str]:
    """Собираем все ``CB_*`` константы из messages_ru/_core.py.

    Возвращаем ``{name: value}`` для exact-match и prefix-match (prefix
    распознаётся по суффиксу ``_PREFIX`` в имени).
    """
    found: dict[str, str] = {}
    for name in dir(messages_core):
        if not name.startswith("CB_"):
            continue
        value = getattr(messages_core, name)
        if isinstance(value, str) and value:
            found[name] = value
    return found


def _sample_data_for_cb(name: str, value: str) -> str:
    """Если CB — префикс, дописываем sample-suffix; иначе оставляем как есть.

    Используем «1» (а не «12345»), чтобы попасть в валидные значения и для
    числовых валидаторов (например, ``pending_digest_d:`` ждёт weekday 0..6).
    Это всё ещё одна цифра, парсится как int и удовлетворяет всем существующим
    проверкам ``_route_*``.
    """
    if name.endswith("_PREFIX") or value.endswith(":"):
        return value + "1"
    return value


def _try_route(routers, ctx, cb) -> bool:
    """Прогоняет cb через цепочку routers; ловит исключения (мокированный ctx
    может бросить при попытке отправить сообщение). Нам важно только что
    router заявил «my data» — это первый router, который не вернул False."""
    for router in routers:
        try:
            claimed = router(ctx, cb)
        except Exception:  # noqa: BLE001 - router начал обработку, значит претендует
            return True
        if claimed:
            return True
    return False


def _fully_mocked_ctx() -> MagicMock:
    """ctx, в котором ВСЕ методы — MagicMock; не зависим от make_ctx."""
    ctx = MagicMock()
    ctx.users = MagicMock()
    ctx.calendar_service = MagicMock()
    ctx.subscriptions = MagicMock()
    ctx.telegram = MagicMock()
    ctx.calendar_state = MagicMock()
    ctx.digest_state = MagicMock()
    ctx.connect_tokens = MagicMock()
    ctx.admin = MagicMock()
    ctx.admin.is_admin = MagicMock(return_value=True)
    ctx.webapp = MagicMock()
    return ctx


def test_every_cb_constant_has_a_router() -> None:
    from satellite.telegram_bot.handlers.context import IncomingCallback

    constants = _all_cb_constants()
    assert constants, "не нашли ни одной CB_* константы"

    failures: list[str] = []
    for idx, (name, value) in enumerate(sorted(constants.items())):
        if value in _CB_NOT_ROUTED_ALLOWLIST:
            continue
        ctx = _fully_mocked_ctx()
        cb = IncomingCallback(
            update_id=idx,
            callback_query_id=f"cb-contract-{idx}",
            chat_id=1,
            message_id=2,
            user_id=3,
            username="alice",
            data=_sample_data_for_cb(name, value),
        )
        if not _try_route(_CALLBACK_ROUTERS, ctx, cb):
            failures.append(f"{name}={value!r}")
    assert not failures, (
        "callback constants без router'а (добавьте route_*_callback или внесите в _CB_NOT_ROUTED_ALLOWLIST): "
        + ", ".join(failures)
    )


def test_cb_not_routed_allowlist_constants_actually_exist() -> None:
    """Если константа из allowlist исчезла из messages_ru — allowlist чистим."""
    constants = set(_all_cb_constants().values())
    stale = _CB_NOT_ROUTED_ALLOWLIST - constants
    assert not stale, f"мёртвые ссылки в _CB_NOT_ROUTED_ALLOWLIST: {stale}"


# --- Web App API_ROUTES contract ------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _http(method: str, url: str, *, body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            try:
                body_obj = json.loads(resp.read().decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body_obj = {}
            return resp.status, body_obj
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return exc.code, json.loads(body_text or "{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": body_text}


@pytest.fixture
def webapp_server(tmp_path: Path):
    from satellite.web.server import WebAppServer, WebAppServerConfig

    users = UserStore(tmp_path / "users.json")
    calendar = MagicMock()
    port = _free_port()
    server = WebAppServer(
        config=WebAppServerConfig(
            host="127.0.0.1",
            port=port,
            bot_token="test-token:12345",
            tz_name="Europe/Moscow",
            connect_tokens=ConnectTokenStore(),
        ),
        calendar_service=calendar,
        users=users,
    )
    server.start()
    try:
        yield server, users, f"http://127.0.0.1:{port}"
    finally:
        server.stop()


def test_every_api_route_returns_auth_error_not_500(webapp_server) -> None:
    """API_ROUTES без auth должны возвращать 401 (no_init_data) или 400 — не 500."""
    from satellite.web.server import API_ROUTES

    _server, _users, base = webapp_server
    for route in API_ROUTES:
        path = route.path or (route.path_prefix or "") + "abc"
        url = base + path
        status, body = _http(route.method, url, body=None if route.method == "GET" else {})
        assert status < 500, f"{route.method} {path} → {status} {body!r}"
        # Должно быть auth/validation, а не «маршрут не найден».
        assert status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN), (
            f"{route.method} {path} → {status} {body!r} — ожидался 400/401/403"
        )


def test_healthz_and_connect_are_unauthenticated(webapp_server) -> None:
    _server, _users, base = webapp_server
    status, body = _http("GET", base + "/healthz")
    assert status == HTTPStatus.OK
    assert body == {"status": "ok"}

    # /connect отдаёт HTML, не JSON; проверяем, что не 401/500
    with urllib.request.urlopen(base + "/connect", timeout=2.0) as resp:
        assert resp.status == HTTPStatus.OK
        ctype = resp.headers.get("Content-Type", "")
        assert "text/html" in ctype, ctype


def test_unknown_path_is_not_500(webapp_server) -> None:
    _server, _users, base = webapp_server
    status, _body = _http("GET", base + "/nope-not-a-route")
    assert status == HTTPStatus.NOT_FOUND


# --- module-level sanity ---------------------------------------------------


def test_recognize_message_is_pure_function() -> None:
    """recognize_message не должна иметь side-effect (никаких глобалов с состоянием)."""
    sig = inspect.signature(recognize_message)
    assert list(sig.parameters) == ["text"]


def test_dispatch_handles_unknown_chat_id_safely() -> None:
    """handle_message без chat_id ничего не отправляет."""
    from satellite.telegram_bot.handlers.dispatch import handle_message

    ctx = _fully_mocked_ctx()
    from satellite.telegram_bot.handlers.context import IncomingMessage

    msg = IncomingMessage(
        update_id=1,
        chat_id=None,
        user_id=42,
        username=None,
        display_name=None,
        text="/td",
    )
    handle_message(ctx, msg)
    ctx.telegram.send_message.assert_not_called()
