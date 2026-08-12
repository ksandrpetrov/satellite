"""CalDAV service facade: discovery, cache, CRUD, and mixin-based fetch/PARTSTAT."""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, tzinfo
from math import ceil
from typing import Any, cast
from uuid import uuid4

import requests
from caldav.calendarobjectresource import Event as CaldavEvent
from caldav.davclient import DAVClient
from caldav.lib.error import DAVError
from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent

from .caldav_fetch_mixin import CalDAVFetchMixin
from .caldav_partstat_mixin import CalDAVPartstatMixin
from .caldav_shared import (
    _INVITATION_MISSING_ATTENDEES_BUDGET_SEC,
    _INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT,
    _PARTSTAT_REFRESH_BUDGET_SEC,
    _PARTSTAT_REFRESH_LIMIT,
    _PARTSTAT_REFRESH_TIMEOUT_SEC,
    _PARTSTAT_UPDATE_TIMEOUT_SEC,
    DEFAULT_CALDAV_URL,
    CalDAVError,
    CalendarHandle,
    EnrichStats,
    Event,
    _dav_reason,
    _dav_status,
    _DiscoveryResult,
    _new_http_session,
    _redact_url,
    _to_utc,
    build_candidate_urls,
    calendar_matches,
    log,
    login_variants_for_caldav,
)

__all__ = [
    "DEFAULT_CALDAV_URL",
    "CalDAVError",
    "CalDAVService",
    "CalendarHandle",
    "EnrichStats",
    "Event",
    "_DiscoveryResult",
    "_INVITATION_MISSING_ATTENDEES_BUDGET_SEC",
    "_INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT",
    "build_candidate_urls",
    "calendar_matches",
    "login_variants_for_caldav",
]


class CalDAVService(CalDAVPartstatMixin, CalDAVFetchMixin):
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
        request_timeout_sec: float = 20.0,
    ) -> None:
        self._caldav_url = caldav_url
        self._login = login
        self._app_password = app_password
        self._cache_ttl_sec = cache_ttl_sec
        self._partstat_refresh_limit = max(0, int(partstat_refresh_limit))
        self._partstat_refresh_timeout_sec = max(0.1, float(partstat_refresh_timeout_sec))
        self._partstat_refresh_budget_sec = max(0.0, float(partstat_refresh_budget_sec))
        self._partstat_update_timeout_sec = max(3.0, float(partstat_update_timeout_sec))
        # caldav.DAVClient принимает timeout только целым числом секунд.
        self._request_timeout_sec = max(1, ceil(float(request_timeout_sec)))
        self._discovery_lock = threading.Lock()
        self._partstat_cache_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        # _cache читается без блокировки — присваивание атомарно под GIL.
        self._cache: _DiscoveryResult | None = None
        self._partstat_cache: dict[str, tuple[list[str], str | None] | None] = {}
        # Keep-alive пул: PARTSTAT GET/PUT идут пачками, новый TLS на каждый — дорого.
        self._http = _new_http_session()

    def close(self) -> None:
        """Идемпотентно закрывает owned HTTP-сессии."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            cached = self._cache
            self._cache = None
            try:
                self._http.close()
            except Exception:  # noqa: BLE001 - закрываем остальные owned resources
                log.exception("Failed to close CalDAV HTTP session")
            if cached is not None and cached.client is not None:
                try:
                    cached.client.close()
                except Exception:  # noqa: BLE001 - shutdown остаётся best-effort
                    log.exception("Failed to close CalDAV discovery client")

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
        component.add("dtstamp", datetime.now(tz=UTC))
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
                component.add("dtstamp", datetime.now(tz=UTC))
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
                client: DAVClient | None = None
                try:
                    client = DAVClient(
                        url=candidate,
                        username=username,
                        password=self._app_password,
                        timeout=self._request_timeout_sec,
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
                        client=client,
                    )
                except Exception as exc:  # noqa: BLE001 - server-specific errors vary
                    if client is not None:
                        try:
                            client.close()
                        except Exception:  # noqa: BLE001 - сохраняем исходную discovery-ошибку
                            log.warning("Failed to close rejected CalDAV client", exc_info=True)
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
        if result.client is not None:
            return cast(DAVClient, result.client)
        return DAVClient(
            url=result.endpoint,
            username=result.auth_username,
            password=self._app_password,
            timeout=self._request_timeout_sec,
        )

    def _get_event_object(self, event_url: str) -> Any:
        return CaldavEvent(client=self._dav_client(), url=event_url)
