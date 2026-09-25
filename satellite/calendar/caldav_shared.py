"""CalDAV-сервис: discovery с fallback'ом по эндпоинтам и потокобезопасный кэш."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import requests
from caldav.lib.url import URL as CaldavURL
from requests.adapters import HTTPAdapter

from . import caldav_discovery as discovery_helpers
from . import caldav_partstat as partstat_helpers
from .ical_parser import parse_calendar_events

DEFAULT_CALDAV_URL = "https://calendar.mail.ru/"

# Дополнительная догрузка ATTENDEE через GET полезна для маркеров
# NEEDS-ACTION/TENTATIVE, но у mail.ru она может быть существенно медленнее
# основного REPORT. По умолчанию держим её дешёвой, а для интерактивного бота
# вызывающий код может отключить её полностью.
_PARTSTAT_REFRESH_LIMIT = 4
_PARTSTAT_REFRESH_TIMEOUT_SEC = 0.8
_PARTSTAT_REFRESH_BUDGET_SEC = 1.5
# Ложный ACCEPTED в REPORT у Mail.ru — перепроверяем GET, но не на всём 60-дневном горизонте.
_INVITATION_VERIFY_FORWARD_DAYS = 42
# REPORT (expand=true) часто без ATTENDEE — отдельная фаза GET до verify ACCEPTED.
_INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT = 48
_INVITATION_MISSING_ATTENDEES_BUDGET_SEC = 14.0
_RANGE_SEARCH_MAX_WORKERS = 6
# PARTSTAT-обогащение: GET'ы к Mail.ru идут параллельно (бюджеты выше — wall-clock дедлайны).
_PARTSTAT_GET_MAX_WORKERS = 6
# Батчевый calendar-multiget перед per-event GET: кап на URL'ы и размер одного REPORT.
_INVITATION_MULTIGET_LIMIT = 80
_MULTIGET_CHUNK_SIZE = 40
# Ответ на приглашение (GET+PUT): Mail.ru часто отвечает >0.8s; не reuse refresh timeout.
_PARTSTAT_UPDATE_TIMEOUT_SEC = 20.0
_HTTP_POOL_MAXSIZE = 16

log = logging.getLogger(__name__)

Event = dict[str, Any]


def _new_http_session() -> requests.Session:
    """Сессия с keep-alive пулом: без неё каждый PARTSTAT GET — новый TCP+TLS."""
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=_HTTP_POOL_MAXSIZE)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def login_variants_for_caldav(login: str) -> list[str]:
    """Варианты логина для Basic Auth (Mail.ru / корпоративные @vk.team и др.)."""
    return discovery_helpers.login_variants_for_caldav(login)


def _bump_vevent_dtstamp(component: Any) -> None:
    partstat_helpers.bump_vevent_dtstamp(component)


def _bump_vevent_sequence(component: Any) -> None:
    """Инкремент SEQUENCE перед PUT (Mail.ru отклоняет устаревшую версию без него)."""
    partstat_helpers.bump_vevent_sequence(component)


def _update_vevent_attendee_partstat(
    component: Any, login_variants: Sequence[str], partstat: str
) -> bool:
    """Обновляет PARTSTAT существующего ATTENDEE; False, если совпадений нет."""
    return partstat_helpers.update_vevent_attendee_partstat(component, login_variants, partstat)


def build_candidate_urls(caldav_url: str | None, login: str) -> list[str]:
    """Возвращает порядок эндпоинтов для попыток discovery (наиболее вероятные сверху)."""
    return discovery_helpers.build_candidate_urls(caldav_url, login)


def calendar_matches(cal_name: str | None, target: str | None) -> bool:
    return discovery_helpers.calendar_matches(cal_name, target)


@dataclass
class CalendarHandle:
    name: str
    obj: Any  # caldav.Calendar; держим opaque
    url: str


@dataclass
class _DiscoveryResult:
    endpoint: str
    calendars: list[CalendarHandle]
    cached_at: float
    auth_username: str
    client: Any | None = None


@dataclass(frozen=True)
class EnrichStats:
    """Счётчики PARTSTAT-обогащения для тайминг-лога /invitations."""

    multiget_satisfied: int = 0
    phase1_gets: int = 0
    phase2_gets: int = 0


class CalDAVError(RuntimeError):
    """Поднимается, если ни один candidate URL не ответил успешно."""


class CalDAVPartstatUnconfirmedError(CalDAVError):
    """A write may have succeeded, but the requested participant state is unverified."""


class CalDAVConflictError(CalDAVError):
    """The event changed since it was read; a fresh resource is required."""


def _extract_partstat_components(payload: bytes | str) -> list[Event] | None:
    """Keep each recurrence's attendees and cancellation status separate."""
    return parse_calendar_events(payload, calendar_name="") or None


def _multiget_match_key(url: str) -> str:
    """Ключ сопоставления href'ов multiget-ответа с исходными URL (path без квотинга)."""
    path = CaldavURL.objectify(url).path or ""
    return unquote(path).rstrip("/")


def _handle_for_event_url(
    handles: Sequence[CalendarHandle], event_url: str
) -> CalendarHandle | None:
    """Handle календаря, которому принадлежит ресурс (самый длинный префикс URL)."""
    best: CalendarHandle | None = None
    best_len = -1
    for handle in handles:
        base = (handle.url or "").rstrip("/") + "/"
        if event_url.startswith(base) and len(base) > best_len:
            best = handle
            best_len = len(base)
    return best


def _to_utc(value: datetime) -> datetime:
    """Приводит datetime к UTC. Naive значения трактуются как UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dav_status(exc: BaseException) -> str:
    """Достаёт HTTP-статус из ``DAVError`` (best-effort), не падает на отсутствии."""
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "code", None)
    return str(status) if status is not None else "?"


def _dav_reason(exc: BaseException) -> str:
    """Безопасное краткое описание DAV-ошибки для лога (без тела body)."""
    reason = getattr(exc, "reason", None)
    text = str(reason) if reason else str(exc)
    return text.splitlines()[0][:200] if text else exc.__class__.__name__


def _redact_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return "<empty>"
    if len(raw) <= 12:
        return raw[:4] + "…"
    return raw[:8] + "…" + raw[-4:]
