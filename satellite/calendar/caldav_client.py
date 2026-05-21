"""CalDAV-сервис: discovery с fallback'ом по эндпоинтам и потокобезопасный кэш."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, cast
from uuid import uuid4

import requests
from caldav.calendarobjectresource import Event as CaldavEvent
from caldav.davclient import DAVClient
from caldav.lib.error import DAVError
from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent

from .events import day_bounds, event_local_start_date, sort_key
from .events._collectors import event_relevant_for_invitations
from .events._partstat import user_partstat
from .events._time import event_ends_after
from .ical_parser import _attendee_to_str, parse_calendar_events

DEFAULT_CALDAV_URL = "https://calendar.mail.ru/"

# Дополнительная догрузка ATTENDEE через GET полезна для маркеров
# NEEDS-ACTION/TENTATIVE, но у mail.ru она может быть существенно медленнее
# основного REPORT. По умолчанию держим её дешёвой, а для интерактивного бота
# вызывающий код может отключить её полностью.
_PARTSTAT_REFRESH_LIMIT = 4
_PARTSTAT_REFRESH_TIMEOUT_SEC = 0.8
_PARTSTAT_REFRESH_BUDGET_SEC = 1.5
# Ответ на приглашение (GET+PUT): Mail.ru часто отвечает >0.8s; не reuse refresh timeout.
_PARTSTAT_UPDATE_TIMEOUT_SEC = 20.0

log = logging.getLogger(__name__)

Event = dict[str, Any]


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def login_variants_for_caldav(login: str) -> list[str]:
    """Варианты логина для Basic Auth (Mail.ru / корпоративные @vk.team и др.)."""
    normalized = (login or "").strip()
    if not normalized:
        return [""]
    variants = [normalized]
    local, sep, _domain = normalized.partition("@")
    if sep and local and local not in variants:
        variants.append(local)
    return variants


def _attendee_matches_login_variants(attendee: Any, login_variants: Sequence[str]) -> bool:
    """True, если ``login_variants`` встречается в сериализованном ATTENDEE.

    ``str(vCalAddress)`` отдаёт только mailto без PARTSTAT — сравниваем через
    ``_attendee_to_str``, как в ``ical_parser`` / ``events.user_partstat``.
    """
    blob = _attendee_to_str(attendee).casefold()
    if not blob:
        return False
    for variant in login_variants:
        needle = (variant or "").strip().casefold()
        if needle and needle in blob:
            return True
    return False


def _bump_vevent_dtstamp(component: Any) -> None:
    for prop in ("dtstamp", "DTSTAMP"):
        if prop in component:
            del component[prop]
    component.add("dtstamp", datetime.now(tz=timezone.utc))


def _bump_vevent_sequence(component: Any) -> None:
    """Инкремент SEQUENCE перед PUT (Mail.ru отклоняет устаревшую версию без него)."""
    seq = component.get("SEQUENCE")
    try:
        next_seq = int(seq) + 1 if seq is not None else 0
    except (TypeError, ValueError):
        next_seq = 1
    for prop in ("sequence", "SEQUENCE"):
        if prop in component:
            del component[prop]
    component.add("sequence", next_seq)


def _update_vevent_attendee_partstat(
    component: Any, login_variants: Sequence[str], partstat: str
) -> bool:
    """Обновляет PARTSTAT существующего ATTENDEE; False, если совпадений нет."""
    raw_attendees = component.get("ATTENDEE")
    if raw_attendees is None:
        return False
    items = raw_attendees if isinstance(raw_attendees, list) else [raw_attendees]
    updated = False
    for attendee in items:
        if not _attendee_matches_login_variants(attendee, login_variants):
            continue
        attendee.params["PARTSTAT"] = partstat
        updated = True
    return updated


def _update_vevent_pending_attendee_partstat(component: Any, partstat: str) -> bool:
    """Обновляет первого ATTENDEE с NEEDS-ACTION/DELEGATED, если логин не совпал.

    Mail.ru иногда кладёт в ICS другой mailto, чем логин CalDAV (алиас/CN), а
    единственная строка с ожиданием ответа — с PARTSTAT=NEEDS-ACTION.
    """
    raw_attendees = component.get("ATTENDEE")
    if raw_attendees is None:
        return False
    items = raw_attendees if isinstance(raw_attendees, list) else [raw_attendees]
    for attendee in items:
        blob = _attendee_to_str(attendee).casefold()
        if "partstat=needs-action" in blob or "partstat=delegated" in blob:
            attendee.params["PARTSTAT"] = partstat
            return True
    return False


def _add_vevent_attendee(component: Any, login: str, partstat: str) -> None:
    """Добавляет ATTENDEE для логина (Mail.ru иногда отдаёт PARTSTAT только в GET)."""
    mailto = (login or "").strip()
    if not mailto:
        raise CalDAVError("Login is required to add ATTENDEE")
    component.add(
        "attendee",
        f"mailto:{mailto}",
        parameters={
            "PARTSTAT": partstat,
            "RSVP": "TRUE",
            "ROLE": "REQ-PARTICIPANT",
        },
    )


def build_candidate_urls(caldav_url: str | None, login: str) -> list[str]:
    """Возвращает порядок эндпоинтов для попыток discovery (наиболее вероятные сверху)."""
    login_name, _, domain = (login or "").partition("@")
    domain = domain or "mail.ru"

    seed = _normalize_url(caldav_url) if caldav_url else _normalize_url(DEFAULT_CALDAV_URL)
    roots = [seed]
    if seed.startswith("https://calendar.mail.ru"):
        default_root = _normalize_url(DEFAULT_CALDAV_URL)
        if default_root not in roots:
            roots.append(default_root)

    direct_mailru_principal = (
        f"https://calendar.mail.ru/principals/{domain}/{login_name}" if login_name else ""
    )
    candidates: list[str] = []
    if seed.startswith("https://calendar.mail.ru") and direct_mailru_principal:
        candidates.append(direct_mailru_principal)
        candidates.append(f"{direct_mailru_principal}/")
    for root in roots:
        candidates.extend(
            [
                root,
                f"{root}/.well-known/caldav",
                f"{root}/caldav",
                f"{root}/dav",
                f"{root}/principals/{domain}/{login_name}",
                f"{root}/principals/{domain}/{login_name}/",
                f"{root}/calendars/{domain}/{login_name}",
                f"{root}/calendars/{domain}/{login_name}/",
            ]
        )

    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        key = item.rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _normalize_calendar_name(name: str | None) -> str:
    return (name or "").strip().casefold()


def calendar_matches(cal_name: str | None, target: str | None) -> bool:
    target_norm = _normalize_calendar_name(target)
    if not target_norm:
        return True
    return _normalize_calendar_name(cal_name) == target_norm


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
        out: list[Event] = []
        for handle in handles:
            try:
                events_iter = self._iter_calendar_range_search(handle, range_start, range_end)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "CalDAV range search failed url=%s: %s",
                    _redact_url(handle.url),
                    exc.__class__.__name__,
                )
                continue
            for raw_event in events_iter:
                parsed = parse_calendar_events(raw_event.data, handle.name)
                for ev in parsed:
                    ev["url"] = str(getattr(raw_event, "url", "") or "")
                out.extend(parsed)
        if enrich_partstat:
            verify_moment = datetime.now(tz) if invitation_partstat_verify else None
            self._enrich_events_partstat(
                out,
                tz=tz,
                prioritize_from=start_date,
                invitation_verify=invitation_partstat_verify,
                moment=verify_moment,
            )
        out.sort(key=lambda event: event.get("dtstart") or "")
        return out

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
                return True
            status = user_partstat(ev, login)
            if status in {"NEEDS-ACTION", "DELEGATED", "DECLINED"}:
                return False
            if (
                status in {"ACCEPTED", "TENTATIVE"}
                and tz is not None
                and moment is not None
                and not event_ends_after(ev, tz, moment=moment)
            ):
                start_day = event_local_start_date(ev, tz)
                if start_day is not None and start_day < moment.date() - timedelta(
                    days=lookback_days
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

    def _enrich_events_partstat(
        self,
        events: list[Event],
        *,
        tz: tzinfo,
        prioritize_from: date | None = None,
        invitation_verify: bool = False,
        moment: datetime | None = None,
        lookback_days: int = 14,
    ) -> None:
        """Дополняет ATTENDEE/PARTSTAT через GET там, где REPORT их не отдал."""
        if self._partstat_refresh_limit <= 0 or not self._login:
            return
        refresh_started = time.monotonic()
        refresh_count = 0
        ordered = list(events)
        if invitation_verify and moment is not None:
            ordered.sort(
                key=lambda ev: self._invitation_partstat_refresh_order(
                    ev, tz=tz, moment=moment, lookback_days=lookback_days
                )
            )
        elif prioritize_from is not None:

            def _group(ev: Event) -> int:
                day = event_local_start_date(ev, tz)
                if day is None:
                    return 1
                return 0 if day >= prioritize_from else 1

            ordered.sort(key=lambda ev: (_group(ev), sort_key(ev, tz)))

        for ev in ordered:
            if refresh_count >= self._partstat_refresh_limit:
                break
            if not self._partstat_refresh_budget_left(refresh_started):
                break
            event_url = str(ev.get("url") or "")
            if not event_url or not self._event_needs_partstat_refresh(
                ev,
                invitation_verify=invitation_verify,
                tz=tz,
                moment=moment,
                lookback_days=lookback_days,
            ):
                continue
            refreshed = self._refresh_attendees_via_get(event_url)
            refresh_count += 1
            if refreshed is None:
                continue
            attendees, status = refreshed
            if attendees:
                ev["attendees"] = list(attendees)
            if status is not None and not ev.get("status"):
                ev["status"] = status
        # #region agent log
        if invitation_verify and moment is not None:
            no_attendees_count = sum(1 for ev in events if not ev.get("attendees"))
            log.warning(
                "DEBUG_2d45ee PARTSTAT_REFRESH_DONE refreshed=%d/%d total_events=%d "
                "no_attendees_in_report=%d budget_left=%.2fs",
                refresh_count,
                self._partstat_refresh_limit,
                len(events),
                no_attendees_count,
                max(
                    0.0,
                    self._partstat_refresh_budget_sec - (time.monotonic() - refresh_started),
                ),
            )
        # #endregion

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
        response = requests.get(
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
                head = requests.head(
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
        response = requests.put(
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
            response = requests.get(
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
        parsed = parse_calendar_events(response.content, calendar_name="")
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
        result = (attendees, status)
        with self._partstat_cache_lock:
            self._partstat_cache[event_url] = result
        return result


def _normalize_calendar_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


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
