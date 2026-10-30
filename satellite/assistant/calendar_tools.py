"""Bounded calendar use cases; identity and write authority stay on the server."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..calendar.events import event_datetime_bounds, is_all_day_event
from ..calendar.period_stats import workday_options_from_preset
from ..calendar.providers.base import (
    CalendarEventPayload,
    CalendarEventRef,
    CalendarMutation,
    CalendarProviderError,
)
from ..calendar.selection import effective_enabled_calendar_urls_from_parts
from ..calendar.time_utils import add_elapsed_minutes, validate_local_datetime
from ..calendar.url_utils import normalize_calendar_url
from ..calendar.user_calendar_service import UserCalendarService
from ..messages_ru import (
    AI_ALTERNATIVES,
    AI_CONFLICT,
    AI_EVENT_CHANGED,
    AI_FOCUS_TITLE,
    AI_NEED_DETAILS,
    AI_NEED_MOVE,
    AI_NO_ALTERNATIVES,
    AI_NOT_FOUND,
    AI_SELECTION,
    AI_WRITE_FORBIDDEN,
    ai_calendar_choice,
    ai_conflict_events,
    ai_receipt,
    ai_report_text,
)
from .optimization import (
    Preferences,
    active_events,
    build_optimization,
    event_id,
    free_slots,
    metrics,
)
from .provider import TurnBudget
from .store import AiStore


def _word_stem(word: str) -> str:
    # Limited inflection normalization; never substitute semantically similar names.
    for suffix in (
        "иями",
        "ами",
        "ями",
        "ого",
        "ему",
        "ому",
        "иях",
        "ах",
        "ях",
        "ов",
        "ев",
        "ам",
        "ям",
        "ой",
        "ый",
        "ий",
        "ая",
        "ую",
        "ое",
        "ые",
        "ом",
        "ем",
        "а",
        "я",
        "у",
        "ю",
        "ы",
        "и",
        "е",
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def title_matches(title: str, query: str) -> bool:
    title, query = title.casefold().replace("ё", "е"), query.casefold().replace("ё", "е")
    if query in title:
        return True
    wanted = {_word_stem(w) for w in re.findall(r"\w+", query)}
    actual = {_word_stem(w) for w in re.findall(r"\w+", title)}
    return bool(wanted) and wanted <= actual


def parse_datetime(value: str | None, tz: ZoneInfo) -> datetime | None:
    if not value:
        return None
    result = datetime.fromisoformat(value)
    if not result.tzinfo:
        result = result.replace(tzinfo=tz)
    return validate_local_datetime(result.astimezone(tz))


def public_event(event: dict[str, Any], option: int, tz: ZoneInfo) -> dict[str, Any]:
    start, end = event_datetime_bounds(event, tz)
    return {
        "option": option,
        "title": str(event.get("summary") or "")[:240],
        "calendar": str(event.get("calendar") or "")[:120],
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "all_day": is_all_day_event(event, tz),
        "status_unverified": bool(event.get("_partstat_unverified")),
    }


def mutation_to_dict(mutation: CalendarMutation) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(mutation), default=lambda d: d.isoformat()))


def mutation_from_dict(data: dict[str, Any]) -> CalendarMutation:
    values = dict(data)
    payload = dict(values["payload"])
    payload["start"], payload["end"] = (
        datetime.fromisoformat(payload["start"]),
        datetime.fromisoformat(payload["end"]),
    )
    values["payload"] = CalendarEventPayload(**payload)
    if values.get("event_ref"):
        values["event_ref"] = CalendarEventRef(**values["event_ref"])
    for key in ("original_start", "original_end", "recurrence_id"):
        if values.get(key):
            values[key] = datetime.fromisoformat(values[key])
    return CalendarMutation(**values)


class CalendarTools:
    def __init__(
        self,
        service: UserCalendarService,
        store: AiStore,
        user_id: int,
        update_id: int,
        conversation: dict[str, Any],
        tz: ZoneInfo,
        now: datetime,
        budget: TurnBudget,
    ) -> None:
        self.service, self.store, self.user_id, self.update_id = service, store, user_id, update_id
        self.conversation, self.tz, self.now, self.budget = conversation, tz, now, budget
        connected = service.require_connection(user_id)
        self.connection = service.connection_id(user_id)
        self.login = connected.context.login
        self.primary = connected.context.primary_calendar_url or ""
        self.selected_urls = effective_enabled_calendar_urls_from_parts(
            enabled_calendar_urls=connected.context.enabled_calendar_urls,
            primary_calendar_url=connected.context.primary_calendar_url,
        )
        self.selected_urls = tuple(normalize_calendar_url(url) for url in self.selected_urls)
        self.preferences = Preferences(
            workday=workday_options_from_preset(connected.record.analytics_workday)
        )
        self.current_plan: dict[str, Any] = {}

    def period(self, args: dict[str, Any], days: int = 1) -> tuple[date, date]:
        start = date.fromisoformat(args["from_date"]) if args.get("from_date") else self.now.date()
        end = (
            date.fromisoformat(args["to_date"])
            if args.get("to_date")
            else start + timedelta(days=days)
        )
        if not 1 <= (end - start).days <= 31:
            raise ValueError("Period must contain 1 to 31 days")
        return start, end

    def load(self, start: date, end: date) -> list[dict[str, Any]]:
        self.budget.remaining()
        events = self.service.list_events_for_analytics(
            self.user_id, start_date=start, end_date=end - timedelta(days=1), tz=self.tz
        )
        self.budget.remaining()
        if len(events) > 1000 or self.service.connection_id(self.user_id) != self.connection:
            raise CalendarProviderError(
                "Calendar changed or oversized", error_code="CALENDAR_CONNECTION_CHANGED"
            )
        return sorted(
            [dict(e) for e in active_events(events, self.tz, self.login)],
            key=lambda e: event_datetime_bounds(e, self.tz)[0] or datetime.max.replace(tzinfo=UTC),
        )

    def _options(self, kind: str, values: list[dict[str, Any]]) -> None:
        self.conversation["option_kind"] = kind
        self.conversation["options"] = values

    def execute(self, plan: dict[str, Any]) -> dict[str, Any] | str:
        self.current_plan = plan
        action, args = plan["name"], plan["arguments"]
        if action == "clarify":
            return str(args["question"])[:1000]
        if action in {"create_event", "reschedule_event", "apply_suggestion"}:
            return self.write(action, args)
        if action == "week_overview" and not args.get("from_date"):
            args = dict(
                args, from_date=(self.now.date() - timedelta(days=self.now.weekday())).isoformat()
            )
        start, end = self.period(args, 7 if action in {"optimize", "week_overview"} else 1)
        events = self.load(start, end)
        result: dict[str, Any] = {
            "from_date": str(start),
            "to_date_exclusive": str(end),
            "timezone": str(self.tz),
        }
        if action == "free_time":
            duration = args.get("duration_minutes") or 30
            slots = free_slots(
                events, start, end, self.tz, self.login, self.preferences, duration, now=self.now
            )
            options = [
                {
                    "option": i,
                    "start": a.isoformat(),
                    "end": (a + timedelta(minutes=duration)).isoformat(),
                    "free_until": b.isoformat(),
                }
                for i, (a, b) in enumerate(slots[:20], 1)
            ]
            self._options("slots", options)
            return {
                **result,
                "options": options,
                "total_windows": len(slots),
                "truncated": len(slots) > 20,
            }
        if action == "optimize":
            preferences = Preferences(
                self.preferences.workday,
                args.get("focus_minutes") or 90,
                args["break_minutes"] if args.get("break_minutes") is not None else 10,
            )
            report = build_optimization(
                events,
                start=start,
                end=end,
                tz=self.tz,
                login=self.login,
                preferences=preferences,
                now=self.now,
                check_deadline=self.budget.remaining,
            )
            candidates = report.candidates
            by_id = {event_id(e): e for e in events}
            self._options(
                "suggestions",
                [{**c, "event": by_id.get(c.get("event_id", ""))} for c in candidates],
            )
            return asdict(report)
        if action == "search_events":
            if args.get("query"):
                events = [
                    e for e in events if title_matches(str(e.get("summary") or ""), args["query"])
                ]
            elif (
                args.get("option") is not None and self.conversation.get("option_kind") == "events"
            ):
                events = [self.select_option(args["option"])]
        options = events[:40]
        self._options("events", options)
        result.update(
            events=[public_event(e, i, self.tz) for i, e in enumerate(options, 1)],
            total_events=len(events),
            truncated=len(events) > 40,
        )
        if action == "search_events":
            result["search"] = True
        else:
            result["metrics"] = metrics(
                events, start, end, self.tz, self.login, self.preferences, self.now
            )
        return result

    def select_option(self, option: int) -> dict[str, Any]:
        options = self.conversation.get("options", [])
        if type(option) is not int or not 1 <= option <= len(options):
            raise ValueError("Invalid option")
        return dict(options[option - 1])

    def write(self, action: str, args: dict[str, Any]) -> str:
        event = None
        title = args.get("title")
        start, end = (
            parse_datetime(args.get("start"), self.tz),
            parse_datetime(args.get("end"), self.tz),
        )
        if action == "apply_suggestion":
            if self.conversation.get("option_kind") != "suggestions" or args.get("option") is None:
                return AI_NEED_MOVE
            suggestion = self.select_option(args["option"])
            start, end = (
                parse_datetime(suggestion["start"], self.tz),
                parse_datetime(suggestion["end"], self.tz),
            )
            event = suggestion.get("event")
            title = AI_FOCUS_TITLE if suggestion["kind"] == "focus" else suggestion.get("title")
            action = "reschedule_event" if event else "create_event"
        if action == "reschedule_event" and event is None:
            if args.get("option") is not None and self.conversation.get("option_kind") == "events":
                event = self.select_option(args["option"])
            elif (
                not args.get("query")
                and self.conversation.get("option_kind") == "events"
                and len(self.conversation.get("options", [])) == 1
            ):
                event = self.select_option(1)
            else:
                from_date, to_date = self.period(args, 7)
                events = self.load(from_date, to_date)
                query = str(args.get("query") or "").casefold().strip()
                if not query:
                    return AI_NEED_MOVE
                matches = [e for e in events if title_matches(str(e.get("summary") or ""), query)]
                if not matches:
                    return AI_NOT_FOUND
                self._options("events", matches[:40])
                if len(matches) != 1:
                    return AI_SELECTION.format(
                        options=ai_report_text(
                            {
                                "from_date": str(from_date),
                                "to_date_exclusive": str(to_date),
                                "timezone": str(self.tz),
                                "events": [
                                    public_event(e, i, self.tz)
                                    for i, e in enumerate(matches[:40], 1)
                                ],
                                "truncated": len(matches) > 40,
                            }
                        )
                    )
                event = matches[0]
        original_start = original_end = recurrence = None
        ref = None
        calendar_url = self.primary
        calendar_name = ""
        if event is None and args.get("calendar_name"):
            allowed = {normalize_calendar_url(self.primary), *self.selected_urls}
            calendars = [
                c
                for c in self.service.list_calendars(self.user_id)
                if normalize_calendar_url(c.url) in allowed
            ]
            requested = str(args["calendar_name"]).strip().casefold()
            matching_names = [c for c in calendars if c.name.strip().casefold() == requested]
            if len(matching_names) != 1:
                return ai_calendar_choice([c.name for c in calendars])
            calendar_url = matching_names[0].url
        if event:
            original_start, original_end = event_datetime_bounds(event, self.tz)
            if is_all_day_event(event, self.tz):
                raise CalendarProviderError("Timed events only", error_code="TIMED_EVENTS_ONLY")
            if not original_start or not original_end:
                return AI_NEED_MOVE
            title = str(event.get("summary") or "")
            ref = CalendarEventRef(str(event.get("uid") or ""), event.get("url"), self.connection)
            recurrence = parse_datetime(event.get("recurrence_id"), self.tz)
            calendar_name = str(event.get("calendar") or "")
            # Resolve the source from authenticated discovery, never from a model URL.
            calendars = self.service.list_calendars(self.user_id)
            matching = [
                c for c in calendars if ref.url and ref.url.startswith(c.url.rstrip("/") + "/")
            ]
            if not matching:
                return AI_EVENT_CHANGED
            calendar_url = max(matching, key=lambda c: len(c.url)).url
            if args.get("shift_minutes") is not None:
                start = add_elapsed_minutes(original_start, args["shift_minutes"])
            if start and not end:
                end = add_elapsed_minutes(
                    start,
                    int(
                        (
                            original_end.astimezone(UTC) - original_start.astimezone(UTC)
                        ).total_seconds()
                        // 60
                    ),
                )
        elif args.get("option") is not None and self.conversation.get("option_kind") == "slots":
            selected = self.select_option(args["option"])
            start, end = (
                parse_datetime(selected["start"], self.tz),
                parse_datetime(selected["end"], self.tz),
            )
        if start and not end and args.get("duration_minutes"):
            end = add_elapsed_minutes(start, args["duration_minutes"])
        if not title or not start or not end:
            return AI_NEED_DETAILS if event is None else AI_NEED_MOVE
        if (
            start < self.now
            or not 0 < (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() <= 86400
            or len(title) > 240
        ):
            raise ValueError("Invalid write interval or title")
        events = self.load(start.date(), end.date() + timedelta(days=1))
        if normalize_calendar_url(calendar_url) not in self.selected_urls:
            # A hidden primary calendar is still the create destination; its events
            # must also block creation even when excluded from the user's digest.
            extra = self.service.list_events(
                self.user_id,
                start_date=start.date(),
                end_date=end.date(),
                tz=self.tz,
                calendar_urls=(calendar_url,),
            )
            events = [dict(e) for e in active_events([*events, *extra], self.tz, self.login)]
            self.budget.remaining()
        conflicts = []
        for other in events:
            if event and event_id(other) == event_id(event):
                continue
            begin, finish = event_datetime_bounds(other, self.tz)
            if begin and finish and begin < end and finish > start:
                conflicts.append(other)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "kind": action,
                    "event": event_id(event) if event else None,
                    "title": title,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "conflicts": sorted(event_id(e) for e in conflicts),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if conflicts and not (
            args.get("allow_conflicts") and self.conversation.get("conflict") == fingerprint
        ):
            self.conversation["conflict"] = fingerprint
            duration = int((end - start).total_seconds() // 60)
            alternatives = free_slots(
                events,
                start.date(),
                start.date() + timedelta(days=1),
                self.tz,
                self.login,
                self.preferences,
                duration,
                now=self.now,
            )
            text = (
                AI_ALTERNATIVES.format(
                    slots=", ".join(a.strftime("%d.%m %H:%M") for a, _ in alternatives[:3])
                )
                if alternatives
                else AI_NO_ALTERNATIVES
            )
            return AI_CONFLICT.format(
                events=ai_conflict_events(
                    [public_event(e, i, self.tz) for i, e in enumerate(conflicts[:10], 1)]
                ),
                alternatives=text,
            )
        calendars = self.service.list_calendars(self.user_id)
        calendar_name = next(
            (
                c.name
                for c in calendars
                if normalize_calendar_url(c.url) == normalize_calendar_url(calendar_url)
            ),
            calendar_name,
        )
        operation_id = hashlib.sha256(
            f"{self.user_id}:{self.update_id}:{self.connection}".encode()
        ).hexdigest()
        mutation = CalendarMutation(
            operation_id,
            "reschedule" if event else "create",
            calendar_url,
            self.connection,
            CalendarEventPayload(title, start, end),
            ref,
            original_start,
            original_end,
            recurrence,
        )
        self.store.save_turn(
            self.user_id,
            self.update_id,
            {
                "connection": self.connection,
                "mutation": mutation_to_dict(mutation),
                "calendar": calendar_name,
                "status": "pending",
            },
        )
        self.budget.remaining()
        try:
            self.service.apply_mutation(self.user_id, mutation, deadline=self.budget.deadline)
        except CalendarProviderError as exc:
            if exc.error_code != "WRITE_FORBIDDEN":
                raise
            text = AI_WRITE_FORBIDDEN.format(calendar=calendar_name)
            if event is None:
                calendar_alternatives = [
                    c.name
                    for c in calendars
                    if normalize_calendar_url(c.url) in self.selected_urls
                    and normalize_calendar_url(c.url) != normalize_calendar_url(calendar_url)
                ]
                text += "\n\n" + ai_calendar_choice(calendar_alternatives)
            self.store.save_turn(
                self.user_id,
                self.update_id,
                {
                    "connection": self.connection,
                    "mutation": mutation_to_dict(mutation),
                    "calendar": calendar_name,
                    "status": "rejected",
                    "response": text,
                },
            )
            return text
        return self.finish_mutation(mutation, calendar_name)

    def finish_mutation(self, mutation: CalendarMutation, calendar_name: str) -> str:
        payload = mutation.payload
        text = ai_receipt(
            moved=mutation.kind == "reschedule",
            title=payload.title,
            calendar=calendar_name,
            start=payload.start.astimezone(self.tz),
            end=payload.end.astimezone(self.tz),
        )
        turn = {
            "connection": self.connection,
            "mutation": mutation_to_dict(mutation),
            "calendar": calendar_name,
            "status": "done",
            "response": text,
        }
        self.store.save_turn(self.user_id, self.update_id, turn)
        ref = mutation.event_ref
        uid = ref.uid if ref else f"satellite-ai-{mutation.operation_id}@satellite.local"
        url = ref.url if ref else f"{mutation.calendar_url.rstrip('/')}/{uid}.ics"
        self._options(
            "events",
            [
                {
                    "uid": uid,
                    "url": url,
                    "summary": payload.title,
                    "calendar": calendar_name,
                    "dtstart": payload.start.isoformat(),
                    "dtend": payload.end.isoformat(),
                    "recurrence_id": (mutation.recurrence_id or mutation.original_start).isoformat()
                    if mutation.original_start
                    else None,
                }
            ],
        )
        self.conversation.pop("conflict", None)
        return text
