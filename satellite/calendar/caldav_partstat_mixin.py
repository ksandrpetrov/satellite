"""CalDAV PARTSTAT refresh and attendee updates."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any

import requests
from caldav.lib.error import DAVError
from caldav.lib.url import URL as CaldavURL
from icalendar import Calendar as IcsCalendar

from .caldav_shared import (
    _INVITATION_MISSING_ATTENDEES_BUDGET_SEC,
    _INVITATION_MISSING_ATTENDEES_REFRESH_LIMIT,
    _INVITATION_MULTIGET_LIMIT,
    _INVITATION_VERIFY_FORWARD_DAYS,
    _MULTIGET_CHUNK_SIZE,
    _PARTSTAT_GET_MAX_WORKERS,
    CalDAVError,
    CalendarHandle,
    EnrichStats,
    Event,
    _add_vevent_attendee,
    _bump_vevent_dtstamp,
    _bump_vevent_sequence,
    _dav_reason,
    _dav_status,
    _extract_attendees_status,
    _handle_for_event_url,
    _multiget_match_key,
    _redact_url,
    _update_vevent_attendee_partstat,
    _update_vevent_pending_attendee_partstat,
    log,
    login_variants_for_caldav,
)
from .events import (
    event_ends_after,
    event_local_start_date,
    event_relevant_for_invitations,
    sort_key,
    user_partstat,
)

if TYPE_CHECKING:
    from .caldav_shared import _DiscoveryResult


class CalDAVPartstatMixin:
    _login: str
    _app_password: str
    _partstat_refresh_limit: int
    _partstat_refresh_timeout_sec: float
    _partstat_refresh_budget_sec: float
    _partstat_update_timeout_sec: float
    _cache: _DiscoveryResult | None
    _partstat_cache: dict[str, tuple[list[str], str | None] | None]
    _partstat_cache_lock: threading.Lock

    def _http_get(self, url: str, **kwargs: Any) -> requests.Response:
        raise NotImplementedError

    def _http_put(self, url: str, **kwargs: Any) -> requests.Response:
        raise NotImplementedError

    def _http_head(self, url: str, **kwargs: Any) -> requests.Response:
        raise NotImplementedError

    def _auth_username(self) -> str:
        raise NotImplementedError

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
