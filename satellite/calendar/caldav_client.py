"""CalDAV-сервис: discovery с fallback'ом по эндпоинтам и потокобезопасный кэш."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, cast
from urllib.parse import unquote
from uuid import uuid4

import requests
from caldav.calendarobjectresource import Event as CaldavEvent
from caldav.davclient import DAVClient
from caldav.lib.error import DAVError
from caldav.lib.url import URL as CaldavURL
from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent
from requests.adapters import HTTPAdapter

from . import caldav_discovery as discovery_helpers
from . import caldav_partstat as partstat_helpers
from .events import day_bounds, event_local_start_date, sort_key
from .events._collectors import event_relevant_for_invitations
from .events._partstat import user_partstat
from .events._time import event_ends_after
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


def _normalize_url(url: str) -> str:
    return discovery_helpers.normalize_url(url)


def login_variants_for_caldav(login: str) -> list[str]:
    """Варианты логина для Basic Auth (Mail.ru / корпоративные @vk.team и др.)."""
    return discovery_helpers.login_variants_for_caldav(login)


def _attendee_matches_login_variants(attendee: Any, login_variants: Sequence[str]) -> bool:
    """True, если ``login_variants`` встречается в сериализованном ATTENDEE.

    ``str(vCalAddress)`` отдаёт только mailto без PARTSTAT — сравниваем через
    ``_attendee_to_str``, как в ``ical_parser`` / ``events.user_partstat``.
    """
    return partstat_helpers.attendee_matches_login_variants(attendee, login_variants)


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


def _update_vevent_pending_attendee_partstat(component: Any, partstat: str) -> bool:
    """Обновляет первого ATTENDEE с NEEDS-ACTION/DELEGATED, если логин не совпал.

    Mail.ru иногда кладёт в ICS другой mailto, чем логин CalDAV (алиас/CN), а
    единственная строка с ожиданием ответа — с PARTSTAT=NEEDS-ACTION.
    """
    return partstat_helpers.update_vevent_pending_attendee_partstat(component, partstat)


def _add_vevent_attendee(component: Any, login: str, partstat: str) -> None:
    """Добавляет ATTENDEE для логина (Mail.ru иногда отдаёт PARTSTAT только в GET)."""
    try:
        partstat_helpers.add_vevent_attendee(component, login, partstat)
    except ValueError as exc:
        raise CalDAVError(str(exc)) from exc


def build_candidate_urls(caldav_url: str | None, login: str) -> list[str]:
    """Возвращает порядок эндпоинтов для попыток discovery (наиболее вероятные сверху)."""
    return discovery_helpers.build_candidate_urls(caldav_url, login)


def _normalize_calendar_name(name: str | None) -> str:
    return (name or "").strip().casefold()


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


@dataclass(frozen=True)
class EnrichStats:
    """Счётчики PARTSTAT-обогащения для тайминг-лога /invitations."""

    multiget_satisfied: int = 0
    phase1_gets: int = 0
    phase2_gets: int = 0


class CalDAVError(RuntimeError):
    """Поднимается, если ни один candidate URL не ответил успешно."""


class CalDAVService:
    """Делает discovery один раз и кэширует principal+calendars между запросами.

    Потокобезопасен: внешние блокировки не нужны. На каждом запросе фильтрует
    только нужный календарь, чтобы не таскать события чужих.
    """

    def __init__(
        self,
        *,
        caldav_url: str,
        login: str,
        app_password: str,
        cache_ttl_sec: int = 300,
        partstat_refresh_limit: int = _PARTSTAT_REFRESH_LIMIT,
        partstat_refresh_timeout_sec: float = _PARTSTAT_REFRESH_TIMEOUT_SEC,
        partstat_refresh_budget_sec: float = _PARTSTAT_REFRESH_BUDGET_SEC,
        partstat_update_timeout_sec: float = _PARTSTAT_UPDATE_TIMEOUT_SEC,
    ) -> None:
        self._caldav_url = caldav_url
        self._login = login
        self._app_password = app_password
        self._cache_ttl_sec = cache_ttl_sec
        self._partstat_refresh_limit = max(0, int(partstat_refresh_limit))
        self._partstat_refresh_timeout_sec = max(0.1, float(partstat_refresh_timeout_sec))
        self._partstat_refresh_budget_sec = max(0.0, float(partstat_refresh_budget_sec))
        self._partstat_update_timeout_sec = max(3.0, float(partstat_update_timeout_sec))
        self._discovery_lock = threading.Lock()
        self._partstat_cache_lock = threading.Lock()
        # _cache читается без блокировки — присваивание атомарно под GIL.
        self._cache: _DiscoveryResult | None = None
        self._partstat_cache: dict[str, tuple[list[str], str | None] | None] = {}
        # Keep-alive пул: PARTSTAT GET/PUT идут пачками, новый TLS на каждый — дорого.
        self._http = _new_http_session()

    # --- HTTP choke points (единственные точки для requests + monkeypatch в тестах) ---

    def _http_get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._http.get(url, **kwargs)

    def _http_put(self, url: str, **kwargs: Any) -> requests.Response:
        return self._http.put(url, **kwargs)

    def _http_head(self, url: str, **kwargs: Any) -> requests.Response:
        return self._http.head(url, **kwargs)

    # --- public API -------------------------------------------------------

    @property
    def login(self) -> str:
        return self._login

    def invalidate(self) -> None:
        self._cache = None

    def list_calendars(self) -> tuple[list[CalendarHandle], str]:
        result = self._ensure_discovery()
        return list(result.calendars), result.endpoint

    def fetch_events_for_day(
        self,
        target_date: date,
        *,
        tz: tzinfo,
        target_calendar_name: str | None = None,
    ) -> tuple[list[Event], str]:
        """Возвращает (события на день, использованный эндпоинт).

        Если `target_calendar_name` задан — опрашивает только подходящий календарь.
        При устаревшем кэше / сетевой ошибке делает один retry с пере-discovery.
        """
        attempt = 0
        last_exc: Exception | None = None
        while attempt < 2:
            try:
                result = self._ensure_discovery()
                events = self._search_events(
                    result.calendars, target_date, tz, target_calendar_name
                )
                return events, result.endpoint
            except (DAVError, ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                log.warning(
                    "CalDAV fetch failed on attempt %d: %s; invalidating cache",
                    attempt + 1,
                    exc,
                )
                self.invalidate()
                attempt += 1
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning(
                    "CalDAV fetch unexpected error on attempt %d: %s; invalidating cache",
                    attempt + 1,
                    exc,
                )
                self.invalidate()
                attempt += 1
        assert last_exc is not None
        raise CalDAVError(f"CalDAV fetch failed: {last_exc}") from last_exc

    def fetch_all_events(self) -> tuple[str, list[dict[str, Any]], list[Event]]:
        """Полная выгрузка всех календарей: meta-info + плоский отсортированный список."""
        result = self._ensure_discovery()
        archive_calendars: list[dict[str, Any]] = []
        all_events: list[Event] = []

        for handle in result.calendars:
            cal_events: list[Event] = []
            try:
                events_iter = handle.obj.get_events()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed to enumerate events for calendar url=%s: %s",
                    _redact_url(handle.url),
                    exc.__class__.__name__,
                )
                events_iter = []
            for event in events_iter:
                cal_events.extend(parse_calendar_events(event.data, handle.name))
            archive_calendars.append(
                {
                    "name": handle.name,
                    "url": handle.url,
                    "events_count": len(cal_events),
                }
            )
            all_events.extend(cal_events)

        all_events.sort(key=lambda event: event.get("dtstart") or "")
        return result.endpoint, archive_calendars, all_events

    def fetch_events_in_range(
        self,
        start_date: date,
        end_date: date,
        *,
        tz: tzinfo,
        calendar_url: str | None = None,
        calendar_urls: Sequence[str] | None = None,
        enrich_partstat: bool = False,
        invitation_partstat_verify: bool = False,
    ) -> list[Event]:
        """События в диапазоне дат включительно для одного или нескольких календарей."""
        if end_date < start_date:
            return []
        result = self._ensure_discovery()
        urls = (
            list(calendar_urls)
            if calendar_urls is not None
            else ([calendar_url] if calendar_url else None)
        )
        handles = self._filter_handles_by_urls(result.calendars, urls)
        if urls and not handles:
            raise CalDAVError("Selected calendar(s) not found for user")
        range_start, _ = day_bounds(start_date, tz)
        _, range_end = day_bounds(end_date, tz)
        report_started = time.monotonic()
        out = self._collect_events_in_range(handles, range_start, range_end)
        report_ms = int((time.monotonic() - report_started) * 1000)
        if enrich_partstat:
            verify_moment = datetime.now(tz) if invitation_partstat_verify else None
            enrich_started = time.monotonic()
            stats = self._enrich_events_partstat(
                out,
                tz=tz,
                prioritize_from=start_date,
                invitation_verify=invitation_partstat_verify,
                moment=verify_moment,
            )
            log.info(
                "CalDAV range fetch enriched: events=%d report_ms=%d enrich_ms=%d "
                "multiget_hits=%d phase1_gets=%d phase2_gets=%d verify=%s",
                len(out),
                report_ms,
                int((time.monotonic() - enrich_started) * 1000),
                stats.multiget_satisfied,
                stats.phase1_gets,
                stats.phase2_gets,
                invitation_partstat_verify,
            )
        out.sort(key=lambda event: event.get("dtstart") or "")
        return out

    def _collect_events_in_range(
        self,
        handles: Sequence[CalendarHandle],
        range_start: datetime,
        range_end: datetime,
    ) -> list[Event]:
        """REPORT по одному или нескольким календарям; при N>1 — параллельно."""
        if not handles:
            return []
        if len(handles) == 1:
            chunks = [self._parse_range_events_from_handle(handles[0], range_start, range_end)]
        else:
            workers = min(len(handles), _RANGE_SEARCH_MAX_WORKERS)
            chunks = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        self._parse_range_events_from_handle,
                        handle,
                        range_start,
                        range_end,
                    )
                    for handle in handles
                ]
                for fut in as_completed(futures):
                    chunks.append(fut.result())
        out: list[Event] = []
        for chunk in chunks:
            out.extend(chunk)
        return out

    def _parse_range_events_from_handle(
        self,
        handle: CalendarHandle,
        range_start: datetime,
        range_end: datetime,
    ) -> list[Event]:
        local: list[Event] = []
        try:
            events_iter = self._iter_calendar_range_search(handle, range_start, range_end)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "CalDAV range search failed url=%s: %s",
                _redact_url(handle.url),
                exc.__class__.__name__,
            )
            return local
        for raw_event in events_iter:
            parsed = parse_calendar_events(raw_event.data, handle.name)
            for ev in parsed:
                ev["url"] = str(getattr(raw_event, "url", "") or "")
            local.extend(parsed)
        return local

    def _iter_calendar_range_search(
        self,
        handle: CalendarHandle,
        range_start: datetime,
        range_end: datetime,
    ) -> Any:
        """REPORT/поиск событий в диапазоне; при битом RRULE — fallback expand=False.

        Mail.ru иногда отдаёт recurrence set, который ``icalendar_searcher`` не
        разворачивает с ``expand=True`` (ValueError). Без fallback весь календарь
        даёт 0 событий и пустой ``/invitations``.
        """
        last_value_error: ValueError | None = None
        for expand in (True, False):
            try:
                return handle.obj.search(
                    start=range_start, end=range_end, event=True, expand=expand
                )
            except ValueError as exc:
                last_value_error = exc
                if expand:
                    log.warning(
                        "CalDAV range search expand=True failed url=%s: %s; retrying expand=False",
                        _redact_url(handle.url),
                        exc,
                    )
                    continue
                raise
        if last_value_error is not None:
            raise last_value_error
        raise CalDAVError("CalDAV range search failed without exception")

    def _report_suggests_invitation_partstat_get(self, ev: Event) -> bool:
        """Есть повод догрузить PARTSTAT: пустые ATTENDEE, открытый статус или наш mailto."""
        attendees = ev.get("attendees") or []
        if not attendees:
            return True
        joined = " ".join(str(attendee).casefold() for attendee in attendees)
        if "partstat=needs-action" in joined or "partstat=delegated" in joined:
            return True
        if not (self._login or "").strip():
            return False
        login_variants = login_variants_for_caldav(self._login)
        for attendee in attendees:
            attendee_norm = str(attendee).casefold()
            if any(
                (variant or "").strip().casefold() in attendee_norm for variant in login_variants
            ):
                return True
        return False

    def _event_needs_partstat_refresh(
        self,
        ev: Event,
        *,
        invitation_verify: bool,
        tz: tzinfo | None = None,
        moment: datetime | None = None,
        lookback_days: int = 14,
    ) -> bool:
        """Нужен ли GET на ресурс события для достоверного PARTSTAT."""
        if invitation_verify:
            login = (self._login or "").strip()
            if not login:
                return False
            if not self._has_user_partstat([ev]):
                return self._report_suggests_invitation_partstat_get(ev)
            status = user_partstat(ev, login)
            if status in {"NEEDS-ACTION", "DELEGATED", "DECLINED"}:
                return False
            if tz is not None and moment is not None:
                start_day = event_local_start_date(ev, tz)
                if start_day is not None:
                    if start_day > moment.date() + timedelta(days=_INVITATION_VERIFY_FORWARD_DAYS):
                        return False
                    if (
                        status in {"ACCEPTED", "TENTATIVE"}
                        and not event_ends_after(ev, tz, moment=moment)
                        and start_day < moment.date() - timedelta(days=lookback_days)
                    ):
                        return False
            # Mail.ru в REPORT иногда отдаёт ложный ACCEPTED — перепроверяем GET.
            return True
        return not self._has_user_partstat([ev])

    def _invitation_partstat_refresh_order(
        self,
        ev: Event,
        *,
        tz: tzinfo,
        moment: datetime,
        lookback_days: int = 14,
    ) -> tuple:
        """Порядок GET для /invitations.

        Tier-0: события без ATTENDEE — без GET вообще ничего не знаем (Mail.ru в
        REPORT с expand=true иногда не отдаёт ATTENDEE), их refresh обязателен.
        Tier-1: будущие события с ATTENDEE (возможный ложный ACCEPTED).
        Tier-2: события в lookback окне.
        Tier-3: остальное.
        Внутри tier — по dtstart asc.
        """
        has_attendees = bool(ev.get("attendees"))
        future = event_ends_after(ev, tz, moment=moment)
        if not has_attendees and future:
            return (0, sort_key(ev, tz))
        if not has_attendees and event_relevant_for_invitations(
            ev, tz, moment=moment, lookback_days=lookback_days
        ):
            return (1, sort_key(ev, tz))
        if future:
            return (2, sort_key(ev, tz))
        if event_relevant_for_invitations(ev, tz, moment=moment, lookback_days=lookback_days):
            day = event_local_start_date(ev, tz)
            inv = -(day.toordinal()) if day is not None else 0
            return (3, inv, sort_key(ev, tz))
        return (4, sort_key(ev, tz))

    @staticmethod
    def _apply_partstat_refresh_to_event(
        ev: Event, refreshed: tuple[list[str], str | None] | None
    ) -> None:
        if refreshed is None:
            return
        attendees, status = refreshed
        if attendees:
            ev["attendees"] = list(attendees)
        if status is not None and not ev.get("status"):
            ev["status"] = status

    def _enrich_invitation_missing_attendees(
        self,
        events: list[Event],
        *,
        tz: tzinfo,
        moment: datetime,
        lookback_days: int,
        refresh_started: float,
    ) -> int:
        """Фаза 1 /invitations: GET для событий без ATTENDEE в REPORT (Mail.ru)."""
        missing = [
            ev
            for ev in events
            if not (ev.get("attendees") or [])
            and str(ev.get("url") or "").strip()
            and (
                event_ends_after(ev, tz, moment=moment)
                or event_relevant_for_invitations(
                    ev, tz, moment=moment, lookback_days=lookback_days
                )
            )
        ]
        missing.sort(
            key=lambda ev: self._invitation_partstat_refresh_order(
                ev, tz=tz, moment=moment, lookback_days=lookback_days
            )
        )
        return self._refresh_events_partstat_parallel(
            missing,
            limit=_INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT,
            deadline=refresh_started + _INVITATION_MISSING_ATTENDEES_BUDGET_SEC,
        )

    def _refresh_events_partstat_parallel(
        self,
        candidates: Sequence[Event],
        *,
        limit: int,
        deadline: float,
    ) -> int:
        """Параллельные PARTSTAT GET: один запрос на уникальный URL.

        У recurring-встреч несколько occurrence делят один ресурс — результат
        применяется ко всем событиям с этим URL (раньше дубли зря съедали
        limit). ``limit`` считается по уникальным URL, ``deadline`` — wall-clock
        (``time.monotonic()``) на весь батч. Возвращает число выполненных GET.
        """
        if limit <= 0:
            return 0
        url_events: dict[str, list[Event]] = {}
        ordered_urls: list[str] = []
        for ev in candidates:
            event_url = str(ev.get("url") or "").strip()
            if not event_url:
                continue
            bucket = url_events.get(event_url)
            if bucket is None:
                url_events[event_url] = [ev]
                ordered_urls.append(event_url)
            else:
                bucket.append(ev)
        target_urls = ordered_urls[:limit]
        if not target_urls:
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 0
        refreshed_count = 0
        workers = min(len(target_urls), _PARTSTAT_GET_MAX_WORKERS)
        executor = ThreadPoolExecutor(max_workers=workers)
        futures = {
            executor.submit(self._refresh_attendees_via_get, url): url for url in target_urls
        }
        try:
            for fut in as_completed(futures, timeout=remaining):
                refreshed = fut.result()
                refreshed_count += 1
                for ev in url_events[futures[fut]]:
                    self._apply_partstat_refresh_to_event(ev, refreshed)
        except FuturesTimeoutError:
            log.info(
                "PARTSTAT refresh deadline reached: done=%d of %d",
                refreshed_count,
                len(target_urls),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return refreshed_count

    def _invitation_refresh_candidates(
        self,
        events: list[Event],
        *,
        tz: tzinfo,
        moment: datetime,
        lookback_days: int,
    ) -> list[Event]:
        """Кандидаты PARTSTAT-refresh для /invitations в tier-порядке."""
        candidates = [
            ev
            for ev in events
            if str(ev.get("url") or "").strip()
            and self._event_needs_partstat_refresh(
                ev,
                invitation_verify=True,
                tz=tz,
                moment=moment,
                lookback_days=lookback_days,
            )
        ]
        candidates.sort(
            key=lambda ev: self._invitation_partstat_refresh_order(
                ev, tz=tz, moment=moment, lookback_days=lookback_days
            )
        )
        return candidates

    def _multiget_partstat_batch(self, candidates: Sequence[Event]) -> set[str]:
        """Фаза 0 /invitations: батчевый calendar-multiget вместо N per-event GET.

        Возвращает URL'ы, для которых сервер отдал непустые ATTENDEE — им
        per-event GET уже не нужен (multiget возвращает тот же полный ресурс,
        что и GET). URL'ы с ошибкой или пустыми ATTENDEE остаются кандидатами
        GET-фаз: если Mail.ru режет ATTENDEE и в multiget, поведение не
        деградирует. Работает только по уже готовому discovery-кэшу — сам
        discovery не инициирует.
        """
        cached = self._cache
        if cached is None or not cached.calendars:
            return set()
        url_events: dict[str, list[Event]] = {}
        ordered_urls: list[str] = []
        for ev in candidates:
            event_url = str(ev.get("url") or "").strip()
            if not event_url:
                continue
            bucket = url_events.get(event_url)
            if bucket is None:
                if len(ordered_urls) >= _INVITATION_MULTIGET_LIMIT:
                    continue
                url_events[event_url] = [ev]
                ordered_urls.append(event_url)
            else:
                bucket.append(ev)
        if not ordered_urls:
            return set()
        by_handle: dict[str, tuple[CalendarHandle, list[str]]] = {}
        for event_url in ordered_urls:
            handle = _handle_for_event_url(cached.calendars, event_url)
            if handle is None:
                continue
            entry = by_handle.setdefault(handle.url, (handle, []))
            entry[1].append(event_url)
        satisfied: set[str] = set()
        for handle, urls in by_handle.values():
            for start in range(0, len(urls), _MULTIGET_CHUNK_SIZE):
                chunk = urls[start : start + _MULTIGET_CHUNK_SIZE]
                try:
                    responses = list(handle.obj.multiget([CaldavURL.objectify(u) for u in chunk]))
                except Exception as exc:  # noqa: BLE001 - сервер может не уметь multiget
                    log.warning(
                        "CalDAV multiget failed url=%s size=%d: %s",
                        _redact_url(handle.url),
                        len(chunk),
                        exc.__class__.__name__,
                    )
                    break  # у этого календаря multiget не работает — следующий handle
                requested = {_multiget_match_key(u): u for u in chunk}
                for obj in responses:
                    extracted = self._extract_multiget_response(obj, requested)
                    if extracted is None:
                        continue
                    original, result = extracted
                    with self._partstat_cache_lock:
                        self._partstat_cache[original] = result
                    for ev in url_events[original]:
                        self._apply_partstat_refresh_to_event(ev, result)
                    satisfied.add(original)
        return satisfied

    @staticmethod
    def _extract_multiget_response(
        obj: Any, requested: dict[str, str]
    ) -> tuple[str, tuple[list[str], str | None]] | None:
        """(исходный URL, (attendees, status)) из одного multiget-ответа или None."""
        try:
            original = requested.get(_multiget_match_key(str(getattr(obj, "url", "") or "")))
            if original is None:
                return None
            data = getattr(obj, "data", None)
            if not data:
                return None
            result = _extract_attendees_status(data)
        except Exception as exc:  # noqa: BLE001 - битый ответ не должен валить батч
            log.debug("CalDAV multiget response skipped: %s", exc.__class__.__name__)
            return None
        if result is None or not result[0]:
            # ATTENDEE нет и здесь — не доверяем (возможен тот же стрип, что в
            # calendar-query REPORT); событие остаётся кандидатом per-event GET.
            return None
        return original, result

    def _enrich_events_partstat(
        self,
        events: list[Event],
        *,
        tz: tzinfo,
        prioritize_from: date | None = None,
        invitation_verify: bool = False,
        moment: datetime | None = None,
        lookback_days: int = 14,
    ) -> EnrichStats:
        """Дополняет ATTENDEE/PARTSTAT там, где REPORT их не отдал.

        Для /invitations: батчевый multiget (фаза 0) → GET событий без ATTENDEE
        (фаза 1) → verify ложных ACCEPTED (фаза 2). GET-фазы параллельные с
        дедупом по URL; лимиты и бюджеты прежние (wall-clock дедлайны).
        """
        if not self._login:
            return EnrichStats()
        refresh_started = time.monotonic()
        multiget_satisfied: set[str] = set()
        phase1_gets = 0
        if invitation_verify and moment is not None:
            multiget_satisfied = self._multiget_partstat_batch(
                self._invitation_refresh_candidates(
                    events, tz=tz, moment=moment, lookback_days=lookback_days
                )
            )
            phase1_gets = self._enrich_invitation_missing_attendees(
                events,
                tz=tz,
                moment=moment,
                lookback_days=lookback_days,
                refresh_started=refresh_started,
            )
            if self._partstat_refresh_limit <= 0:
                return EnrichStats(
                    multiget_satisfied=len(multiget_satisfied),
                    phase1_gets=phase1_gets,
                )
            # Кандидаты считаем после фаз 0-1: обогащённые события выпадают сами,
            # закрытые multiget'ом URL исключаем — их «verify» уже сделан.
            candidates = [
                ev
                for ev in self._invitation_refresh_candidates(
                    events, tz=tz, moment=moment, lookback_days=lookback_days
                )
                if str(ev.get("url") or "") not in multiget_satisfied
            ]
        else:
            if self._partstat_refresh_limit <= 0:
                return EnrichStats()
            candidates = [
                ev
                for ev in events
                if str(ev.get("url") or "").strip()
                and self._event_needs_partstat_refresh(
                    ev,
                    invitation_verify=invitation_verify,
                    tz=tz,
                    moment=moment,
                    lookback_days=lookback_days,
                )
            ]
            if prioritize_from is not None:

                def _group(ev: Event) -> int:
                    day = event_local_start_date(ev, tz)
                    if day is None:
                        return 1
                    return 0 if day >= prioritize_from else 1

                candidates.sort(key=lambda ev: (_group(ev), sort_key(ev, tz)))

        deadline = (
            refresh_started + self._partstat_refresh_budget_sec
            if self._partstat_refresh_budget_sec > 0
            else float("inf")
        )
        phase2_gets = self._refresh_events_partstat_parallel(
            candidates,
            limit=self._partstat_refresh_limit,
            deadline=deadline,
        )
        return EnrichStats(
            multiget_satisfied=len(multiget_satisfied),
            phase1_gets=phase1_gets,
            phase2_gets=phase2_gets,
        )

    def _set_attendee_partstat_once(
        self,
        event_url: str,
        *,
        partstat: str,
        login_variants: Sequence[str],
    ) -> None:
        with self._partstat_cache_lock:
            self._partstat_cache.pop(event_url, None)
        payload, etag = self._get_event_ics_via_http(event_url)
        calendar = IcsCalendar.from_ical(payload)
        updated = False
        vevents = list(calendar.walk("vevent"))
        for component in vevents:
            if _update_vevent_attendee_partstat(component, login_variants, partstat):
                _bump_vevent_dtstamp(component)
                _bump_vevent_sequence(component)
                updated = True
                continue
            if _update_vevent_pending_attendee_partstat(component, partstat):
                _bump_vevent_dtstamp(component)
                _bump_vevent_sequence(component)
                updated = True
        if not updated and vevents:
            _add_vevent_attendee(vevents[0], self._login, partstat)
            _bump_vevent_dtstamp(vevents[0])
            _bump_vevent_sequence(vevents[0])
            updated = True
        if not updated:
            raise CalDAVError("No VEVENT in event data")
        self._put_event_ics_via_http(event_url, calendar.to_ical(), etag=etag)
        with self._partstat_cache_lock:
            self._partstat_cache.pop(event_url, None)

    def set_attendee_partstat(self, event_url: str, partstat: str) -> None:
        """Обновляет PARTSTAT текущего пользователя в ATTENDEE события.

        Загрузка/сохранение через HTTP (как PARTSTAT refresh): у Mail.ru тот же
        auth, что и для GET. ``caldav.Event.save()`` с ``only_this_recurrence=True``
        по умолчанию ломает повторяющиеся приглашения; прямой PUT + SEQUENCE надёжнее.
        """
        normalized = (partstat or "").strip().upper()
        allowed = {"ACCEPTED", "DECLINED", "TENTATIVE", "NEEDS-ACTION", "DELEGATED"}
        if normalized not in allowed:
            raise CalDAVError(f"Unsupported PARTSTAT: {partstat!r}")
        if not (self._login or "").strip():
            raise CalDAVError("Login is required to update PARTSTAT")
        login_variants = login_variants_for_caldav(self._login)
        last_timeout: requests.Timeout | None = None
        try:
            for attempt in range(2):
                try:
                    self._set_attendee_partstat_once(
                        event_url, partstat=normalized, login_variants=login_variants
                    )
                    return
                except requests.Timeout as exc:
                    last_timeout = exc
                    log.warning(
                        "PARTSTAT update timeout attempt=%s url=%s timeout=%ss",
                        attempt + 1,
                        _redact_url(event_url),
                        self._partstat_update_timeout_sec,
                    )
            if last_timeout is not None:
                raise CalDAVError(
                    f"Network error during PARTSTAT update: {last_timeout}"
                ) from last_timeout
        except DAVError as exc:
            log.warning(
                "CalDAV set_attendee_partstat failed url=%s status=%s: %s",
                _redact_url(event_url),
                _dav_status(exc),
                _dav_reason(exc),
            )
            raise CalDAVError(f"Failed to update invitation response: {exc}") from exc
        except ValueError as exc:
            raise CalDAVError(f"Invalid event ICS: {exc}") from exc
        except requests.RequestException as exc:
            raise CalDAVError(f"Network error during PARTSTAT update: {exc}") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise CalDAVError(f"Network error during PARTSTAT update: {exc}") from exc

    def create_event(
        self,
        *,
        calendar_url: str,
        title: str,
        start: datetime,
        end: datetime,
        location: str | None = None,
        description: str | None = None,
    ) -> tuple[str, str]:
        """Создаёт VEVENT. Возвращает (uid, event_url).

        DTSTAMP обязателен по RFC 5545. Время приводится к UTC и сериализуется
        как ``20260520T070000Z`` — иначе ``icalendar`` пишет
        ``DTSTART;TZID=Europe/Moscow:...`` без сопровождающего ``VTIMEZONE``,
        а Mail.ru CalDAV в этом случае отвечает 400 и событие не создаётся.
        """
        handle = self._require_handle(calendar_url)
        uid = f"satellite-{uuid4()}@satellite.local"
        component = IcsEvent()
        component.add("uid", uid)
        component.add("dtstamp", datetime.now(tz=timezone.utc))
        component.add("summary", title)
        component.add("dtstart", _to_utc(start))
        component.add("dtend", _to_utc(end))
        login = (self._login or "").strip()
        if login and "@" in login:
            component.add("organizer", f"mailto:{login}")
        if location:
            component.add("location", location)
        if description:
            component.add("description", description)
        ics = IcsCalendar()
        ics.add("prodid", "-//Satellite Bot//calendar//RU")
        ics.add("version", "2.0")
        ics.add_component(component)
        try:
            handle.obj.add_event(ics.to_ical())
        except DAVError as exc:
            log.warning(
                "CalDAV create_event failed url=%s status=%s: %s",
                _redact_url(handle.url),
                _dav_status(exc),
                _dav_reason(exc),
            )
            raise CalDAVError(f"Failed to create event: {exc}") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise CalDAVError(f"Network error during create: {exc}") from exc
        event_url = f"{handle.url.rstrip('/')}/{uid}.ics"
        return uid, event_url

    def update_event(
        self,
        event_url: str,
        *,
        title: str,
        start: datetime,
        end: datetime,
        location: str | None = None,
        description: str | None = None,
    ) -> None:
        try:
            event_obj = self._get_event_object(event_url)
            event_obj.load(only_if_unloaded=True)
            raw = event_obj.data
            if not raw:
                raise CalDAVError("Empty event data")
            payload = raw.encode() if isinstance(raw, str) else raw
            calendar = IcsCalendar.from_ical(payload)
            utc_start = _to_utc(start)
            utc_end = _to_utc(end)
            for component in calendar.walk("vevent"):
                component["summary"] = title
                # DTSTART/DTEND/DTSTAMP в UTC — без VTIMEZONE блок Mail.ru не примет.
                for prop in ("dtstart", "dtend", "dtstamp"):
                    if prop in component:
                        del component[prop]
                component.add("dtstart", utc_start)
                component.add("dtend", utc_end)
                component.add("dtstamp", datetime.now(tz=timezone.utc))
                if location:
                    component["location"] = location
                elif "location" in component:
                    del component["location"]
                if description:
                    component["description"] = description
                elif "description" in component:
                    del component["description"]
            event_obj.data = calendar.to_ical()
            event_obj.save()
        except DAVError as exc:
            log.warning(
                "CalDAV update_event failed url=%s status=%s: %s",
                _redact_url(event_url),
                _dav_status(exc),
                _dav_reason(exc),
            )
            raise CalDAVError(f"Failed to update event: {exc}") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise CalDAVError(f"Network error during update: {exc}") from exc

    def delete_event(self, event_url: str) -> None:
        try:
            event_obj = self._get_event_object(event_url)
            event_obj.delete()
        except DAVError as exc:
            log.warning(
                "CalDAV delete_event failed url=%s status=%s: %s",
                _redact_url(event_url),
                _dav_status(exc),
                _dav_reason(exc),
            )
            raise CalDAVError(f"Failed to delete event: {exc}") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise CalDAVError(f"Network error during delete: {exc}") from exc

    def primary_calendar_url(self) -> str | None:
        handles, _endpoint = self.list_calendars()
        if not handles:
            return None
        return handles[0].url

    # --- internals --------------------------------------------------------

    def _ensure_discovery(self) -> _DiscoveryResult:
        # Быстрый путь без блокировки: cache-hit самый частый сценарий.
        cached = self._cache
        if cached is not None and (time.monotonic() - cached.cached_at) < self._cache_ttl_sec:
            return cached
        # Медленный путь: только один поток делает discovery, остальные ждут
        # завершения и переиспользуют свежий кэш.
        with self._discovery_lock:
            cached = self._cache
            if cached is not None and (time.monotonic() - cached.cached_at) < self._cache_ttl_sec:
                return cached
            cache = self._do_discovery()
            self._cache = cache
            return cache

    def _do_discovery(self) -> _DiscoveryResult:
        candidates = build_candidate_urls(self._caldav_url, self._login)
        errors: list[str] = []
        for candidate in candidates:
            for username in login_variants_for_caldav(self._login):
                try:
                    client = DAVClient(
                        url=candidate,
                        username=username,
                        password=self._app_password,
                    )
                    principal = client.get_principal()
                    # Sync DAVClient: runtime — list; stubs — list | Coroutine.
                    calendars = cast(list[Any], principal.get_calendars())
                    handles = [self._make_handle(cal) for cal in calendars]
                    log.info(
                        "CalDAV discovery ok: endpoint=%s calendars=%d login_variant=%s",
                        candidate,
                        len(handles),
                        "full" if username == self._login else "local",
                    )
                    return _DiscoveryResult(
                        endpoint=candidate,
                        calendars=handles,
                        cached_at=time.monotonic(),
                        auth_username=username,
                    )
                except Exception as exc:  # noqa: BLE001 - server-specific errors vary
                    user_label = "email" if username == self._login else "local-part"
                    errors.append(f"{candidate} ({user_label}) -> {exc.__class__.__name__}: {exc}")
        details = "\n".join(errors[-8:])
        raise CalDAVError(f"Unable to discover calendars via CalDAV:\n{details}")

    @staticmethod
    def _make_handle(cal: Any) -> CalendarHandle:
        try:
            name = cal.name or str(cal.url)
        except Exception:  # noqa: BLE001
            name = str(cal.url)
        return CalendarHandle(name=name, obj=cal, url=str(cal.url))

    def _search_events(
        self,
        handles: Sequence[CalendarHandle],
        target_date: date,
        tz: tzinfo,
        target_calendar_name: str | None,
    ) -> list[Event]:
        day_start, day_end = day_bounds(target_date, tz)
        out: list[Event] = []
        matched_calendar = False
        refresh_limit = self._partstat_refresh_limit
        refresh_started = time.monotonic()
        refresh_count = 0
        for handle in handles:
            if target_calendar_name and not calendar_matches(handle.name, target_calendar_name):
                continue
            matched_calendar = True
            events_iter = handle.obj.search(start=day_start, end=day_end, event=True, expand=True)
            for raw_event in events_iter:
                parsed = parse_calendar_events(raw_event.data, handle.name)
                event_url = str(getattr(raw_event, "url", "") or "")
                if (
                    refresh_count < refresh_limit
                    and self._partstat_refresh_budget_left(refresh_started)
                    and event_url
                    and self._login
                    and parsed
                    and not self._has_user_partstat(parsed)
                ):
                    refreshed = self._refresh_attendees_via_get(event_url)
                    refresh_count += 1
                    if refreshed is not None:
                        attendees, status = refreshed
                        if attendees or status is not None:
                            for ev in parsed:
                                if attendees and not ev.get("attendees"):
                                    ev["attendees"] = list(attendees)
                                if status is not None and not ev.get("status"):
                                    ev["status"] = status
                out.extend(parsed)
        if target_calendar_name and not matched_calendar:
            log.warning(
                "CalDAV target calendar not matched; calendars_count=%d",
                len(handles),
            )
        return out

    def _filter_handles_by_urls(
        self, handles: Sequence[CalendarHandle], calendar_urls: Sequence[str] | None
    ) -> list[CalendarHandle]:
        if not calendar_urls:
            return list(handles)
        targets = {_normalize_calendar_url(url) for url in calendar_urls if url}
        if not targets:
            return list(handles)
        return [h for h in handles if _normalize_calendar_url(h.url) in targets]

    def _filter_handles(
        self, handles: Sequence[CalendarHandle], calendar_url: str | None
    ) -> list[CalendarHandle]:
        if not calendar_url:
            return list(handles)
        matched = self._filter_handles_by_urls(handles, [calendar_url])
        return matched or list(handles)

    def _find_handle(self, calendar_url: str) -> CalendarHandle | None:
        result = self._ensure_discovery()
        target = _normalize_calendar_url(calendar_url)
        if not target:
            return None
        for handle in result.calendars:
            if _normalize_calendar_url(handle.url) == target:
                return handle
        return None

    def _require_handle(self, calendar_url: str) -> CalendarHandle:
        handle = self._find_handle(calendar_url)
        if handle is not None:
            return handle
        # Кэш discovery мог устареть после смены календарей на стороне Mail.ru.
        self.invalidate()
        handle = self._find_handle(calendar_url)
        if handle is not None:
            return handle
        raise CalDAVError("Calendar handle not found")

    def _auth_username(self) -> str:
        return self._ensure_discovery().auth_username or self._login

    def _dav_client(self) -> DAVClient:
        result = self._ensure_discovery()
        return DAVClient(
            url=result.endpoint,
            username=result.auth_username,
            password=self._app_password,
        )

    def _get_event_object(self, event_url: str) -> Any:
        return CaldavEvent(client=self._dav_client(), url=event_url)

    def _partstat_refresh_budget_left(self, started_at: float) -> bool:
        if self._partstat_refresh_limit <= 0:
            return False
        if self._partstat_refresh_budget_sec <= 0:
            return True
        return (time.monotonic() - started_at) < self._partstat_refresh_budget_sec

    def _has_user_partstat(self, events: Sequence[Event]) -> bool:
        """True, если в parsed-events уже есть ATTENDEE с PARTSTAT для нашего логина.

        Нам не нужны все участники — только понять, отдал ли mail.ru статус
        текущего пользователя. Если хоть в одном occurrence PARTSTAT есть —
        повторно ходить за тем же resource'ом смысла нет.
        """
        if not (self._login or "").strip():
            return True
        login_variants = login_variants_for_caldav(self._login)
        for ev in events:
            for attendee in ev.get("attendees", []) or []:
                attendee_norm = str(attendee).casefold()
                if not any(
                    (variant or "").strip().casefold() in attendee_norm
                    for variant in login_variants
                ):
                    continue
                if "partstat=" in attendee_norm:
                    return True
        return False

    def _get_event_ics_via_http(self, event_url: str) -> tuple[bytes, str | None]:
        """GET ресурса события; ETag с ответа уходит в PUT (без лишнего HEAD)."""
        response = self._http_get(
            event_url,
            auth=(self._auth_username(), self._app_password),
            timeout=self._partstat_update_timeout_sec,
            headers={"Accept": "text/calendar"},
        )
        if response.status_code != 200 or not response.content:
            raise CalDAVError(f"Failed to load event ICS (HTTP {response.status_code})")
        etag = response.headers.get("ETag")
        return response.content, etag

    def _put_event_ics_via_http(
        self, event_url: str, ics: bytes, *, etag: str | None = None
    ) -> None:
        """PUT обновлённого ICS с If-Match, если сервер отдал ETag."""
        auth = (self._auth_username(), self._app_password)
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag
        else:
            try:
                head = self._http_head(
                    event_url,
                    auth=auth,
                    timeout=self._partstat_update_timeout_sec,
                )
                head_etag = head.headers.get("ETag")
                if head_etag:
                    headers["If-Match"] = head_etag
            except requests.RequestException as exc:
                log.debug(
                    "PARTSTAT update HEAD failed url=%s: %s",
                    _redact_url(event_url),
                    exc.__class__.__name__,
                )
        response = self._http_put(
            event_url,
            data=ics,
            auth=auth,
            headers=headers,
            timeout=self._partstat_update_timeout_sec,
        )
        if response.status_code not in (200, 201, 204):
            raise CalDAVError(f"Failed to save event ICS (HTTP {response.status_code})")

    def _refresh_attendees_via_get(self, event_url: str) -> tuple[list[str], str | None] | None:
        """Доп. GET на ресурс события: mail.ru CalDAV в REPORT иногда выкидывает
        ATTENDEE, но в одиночном GET возвращает строку с PARTSTAT для логина,
        под которым мы авторизованы. Это единственный способ получить статус
        для системно-импортированных событий (no local ATTENDEE list).

        Возвращает (attendees, status) или None при сетевой ошибке.
        """
        with self._partstat_cache_lock:
            cached = self._partstat_cache.get(event_url)
            if cached is not None:
                return cached
        try:
            response = self._http_get(
                event_url,
                auth=(self._auth_username(), self._app_password),
                timeout=self._partstat_refresh_timeout_sec,
                headers={"Accept": "text/calendar"},
            )
        except requests.RequestException as exc:
            log.debug(
                "PARTSTAT refresh GET failed url=%s: %s",
                _redact_url(event_url),
                exc.__class__.__name__,
            )
            return None
        if response.status_code != 200 or not response.content:
            log.debug(
                "PARTSTAT refresh GET unexpected status %s url=%s",
                response.status_code,
                _redact_url(event_url),
            )
            return None
        result = _extract_attendees_status(response.content)
        if result is None:
            return None
        with self._partstat_cache_lock:
            self._partstat_cache[event_url] = result
        return result


def _normalize_calendar_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _extract_attendees_status(payload: bytes | str) -> tuple[list[str], str | None] | None:
    """(attendees, status) из ICS полного ресурса (GET или calendar-multiget)."""
    parsed = parse_calendar_events(payload, calendar_name="")
    if not parsed:
        return None
    attendees: list[str] = []
    status: str | None = None
    for ev in parsed:
        for attendee in ev.get("attendees", []) or []:
            if attendee not in attendees:
                attendees.append(str(attendee))
        ev_status = ev.get("status")
        if ev_status and status is None:
            status = str(ev_status)
    return attendees, status


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
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
