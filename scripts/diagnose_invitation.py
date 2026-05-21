#!/usr/bin/env python3
"""Проверка ответа на приглашение (PARTSTAT) без Telegram.

Запуск из корня репозитория на сервере, где есть ``logs/users.json`` и ``.env``:

  # по Telegram id (например aleksanderpetrov → см. logs/subscriptions.json)
  python scripts/diagnose_invitation.py --user-id 84430131 --summary "Техно check"

  # или напрямую CalDAV (как diagnose_caldav.py)
  export CALDAV_LOGIN='you@vk.team'
  export CALDAV_APP_PASSWORD='app-token'
  python scripts/diagnose_invitation.py --summary "SocServ"
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from satellite.calendar.caldav_client import CalDAVError, CalDAVService, DEFAULT_CALDAV_URL  # noqa: E402
from satellite.calendar.events import collect_pending_invitations, user_partstat  # noqa: E402
from satellite.config import load_settings  # noqa: E402
from satellite.security.token_vault import TokenVault  # noqa: E402
from satellite.users import UserStore  # noqa: E402


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str, str | None]:
    login = (os.getenv("CALDAV_LOGIN") or "").strip()
    password = (os.getenv("CALDAV_APP_PASSWORD") or "").strip()
    caldav_url = (os.getenv("CALDAV_URL") or DEFAULT_CALDAV_URL).strip()
    if login and password:
        return login, password, caldav_url
    if not args.user_id:
        print(
            "Укажите --user-id (из logs/users.json) или CALDAV_LOGIN + CALDAV_APP_PASSWORD",
            file=sys.stderr,
        )
        sys.exit(1)
    settings = load_settings(ROOT / ".env")
    store = UserStore(ROOT / "logs" / "users.json")
    record = store.get(args.user_id)
    if record is None or not record.has_calendar:
        print(f"user_id={args.user_id}: календарь не подключён", file=sys.stderr)
        sys.exit(1)
    vault = TokenVault(settings.security.token_encryption_key)
    creds = vault.decrypt(record.encrypted_credentials or "")
    return creds.login.strip(), creds.secret, caldav_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose invitation PARTSTAT accept")
    parser.add_argument("--user-id", type=int, help="Telegram user id из logs/users.json")
    parser.add_argument(
        "--summary",
        default="",
        help="Подстрока в названии встречи (например 'Техно check')",
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="Реально отправить ACCEPTED в CalDAV (иначе только просмотр)",
    )
    parser.add_argument("--tz", default=os.getenv("TZ_NAME", "Europe/Moscow"))
    args = parser.parse_args()

    login, password, caldav_url = _resolve_credentials(args)
    tz = ZoneInfo(args.tz)
    today = datetime.now(tz=tz).date()
    start = today - timedelta(days=14)
    end = today + timedelta(days=90)
    needle = (args.summary or "").casefold()

    service = CalDAVService(
        caldav_url=caldav_url,
        login=login,
        app_password=password,
        cache_ttl_sec=0,
        partstat_refresh_limit=32,
        partstat_refresh_budget_sec=8.0,
    )
    try:
        primary = service.primary_calendar_url()
        events = service.fetch_events_in_range(
            start,
            end,
            tz=tz,
            calendar_url=primary,
            enrich_partstat=True,
        )
    except CalDAVError as exc:
        print("FAIL:", exc)
        return 2

    pending = collect_pending_invitations(
        events,
        login,
        tz,
        now=datetime.now(tz=tz),
        max_events=50,
        lookback_days=14,
    )
    print(f"login={login!r} primary={primary}")
    print(f"pending_total={len(pending)}")
    for ev in pending:
        summary = str(ev.get("summary") or "")
        if needle and needle not in summary.casefold():
            continue
        url = str(ev.get("url") or "")
        partstat = user_partstat(ev, login)
        print("---")
        print("summary:", summary)
        print("start:", ev.get("dtstart"))
        print("partstat:", partstat)
        print("url:", url[:100])
        if args.accept and url:
            try:
                service.set_attendee_partstat(url, "ACCEPTED")
                print("PUT ACCEPTED: OK")
                refreshed = service._refresh_attendees_via_get(url)
                print("after GET attendees:", refreshed[0] if refreshed else None)
            except CalDAVError as exc:
                print("PUT ACCEPTED: FAIL", exc)
                return 3
    if args.accept and not any(
        (not needle or needle in str(e.get("summary") or "").casefold()) for e in pending
    ):
        print("Нет подходящего pending-события для --accept")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
