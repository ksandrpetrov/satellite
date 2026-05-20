#!/usr/bin/env python3
"""Проверка CalDAV с сервера (без Telegram). Запуск из корня репозитория:

  export CALDAV_LOGIN='you@vk.team'
  export CALDAV_APP_PASSWORD='app-token'
  # опционально, если на Mac был полный principal:
  # export CALDAV_URL='https://calendar.mail.ru/principals/vk.team/you/'
  python scripts/diagnose_caldav.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from datetime import datetime, timedelta, timezone  # noqa: E402

from satellite.calendar.caldav_client import (  # noqa: E402
    CalDAVError,
    CalDAVService,
    DEFAULT_CALDAV_URL,
)


def main() -> int:
    login = (os.getenv("CALDAV_LOGIN") or "").strip()
    password = (os.getenv("CALDAV_APP_PASSWORD") or "").strip()
    caldav_url = (os.getenv("CALDAV_URL") or DEFAULT_CALDAV_URL).strip()
    if not login or not password:
        print("Задайте CALDAV_LOGIN и CALDAV_APP_PASSWORD", file=sys.stderr)
        return 1
    service = CalDAVService(
        caldav_url=caldav_url,
        login=login,
        app_password=password,
        cache_ttl_sec=0,
        partstat_refresh_limit=0,
    )
    try:
        primary = service.primary_calendar_url()
        handles, endpoint = service.list_calendars()
    except CalDAVError as exc:
        print("FAIL:", exc)
        return 2
    print("OK")
    print("endpoint:", endpoint)
    print("primary:", primary)
    print("calendars:", len(handles))
    for h in handles[:5]:
        print(" -", h.name, "->", h.url[:72])
    if os.getenv("CALDAV_TEST_CREATE", "").strip().lower() in {"1", "true", "yes"}:
        if not primary:
            print("SKIP create test: no primary calendar")
            return 3
        start = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
        end = start + timedelta(minutes=30)
        try:
            uid, event_url = service.create_event(
                calendar_url=primary,
                title="Satellite diagnose test",
                start=start,
                end=end,
            )
        except CalDAVError as exc:
            print("CREATE FAIL:", exc)
            return 4
        print("CREATE OK:", uid, event_url[:80])
        try:
            service.delete_event(event_url)
            print("DELETE OK (cleanup)")
        except CalDAVError as exc:
            print("DELETE WARN (cleanup failed):", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
