"""CalDAV range search and event collection."""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, tzinfo
from typing import Any

from .caldav_shared import (
    _RANGE_SEARCH_MAX_WORKERS,
    CalDAVError,
    CalendarHandle,
    Event,
    _normalize_calendar_url,
    _redact_url,
    calendar_matches,
    log,
)
from .events import day_bounds
from .ical_parser import parse_calendar_events


class CalDAVFetchMixin:
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
