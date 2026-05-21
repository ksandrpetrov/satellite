#!/usr/bin/env python3
"""Проверка ответа на приглашение (PARTSTAT) без Telegram.

Запуск из корня репозитория на сервере, где есть ``logs/users.json`` и ``.env``:

  # по Telegram id (например aleksanderpetrov → см. logs/subscriptions.json)
  python scripts/diagnose_invitation.py --user-id 84430131 --summary "Техно check"

  # или напрямую CalDAV (как diagnose_caldav.py)
  export CALDAV_LOGIN='you@vk.team'
  export CALDAV_APP_PASSWORD='app-token'
  python scripts/diagnose_invitation.py --summary "SocServ"

Флаг ``--dump-ics`` печатает сырое ICS-тело подозрительного события (если он
найден по подстроке ``--summary``) — полезно увидеть реальные ATTENDEE/PARTSTAT.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from satellite.calendar.caldav_client import (  # noqa: E402
    DEFAULT_CALDAV_URL,
    CalDAVError,
    CalDAVService,
)
from satellite.calendar.events import collect_pending_invitations, user_partstat  # noqa: E402
from satellite.calendar.events._partstat import is_pending_invitation_for_user  # noqa: E402
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
    parser.add_argument(
        "--dump-ics",
        action="store_true",
        help="Скачать сырое ICS подозрительного события и распечатать",
    )
    args = parser.parse_args()

    login, password, caldav_url = _resolve_credentials(args)
    tz = ZoneInfo(args.tz)
    today = datetime.now(tz=tz).date()
    start = today - timedelta(days=14)
    end = today + timedelta(days=60)
    needle = (args.summary or "").casefold()

    service = CalDAVService(
        caldav_url=caldav_url,
        login=login,
        app_password=password,
        cache_ttl_sec=0,
        partstat_refresh_limit=64,
        partstat_refresh_budget_sec=30.0,
    )
    try:
        events = service.fetch_events_in_range(
            start,
            end,
            tz=tz,
            enrich_partstat=True,
            invitation_partstat_verify=True,
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
    print(f"login={login!r}")
    print(f"horizon: {start.isoformat()} .. {end.isoformat()}")
    print(f"events_total={len(events)} pending_total={len(pending)}")

    matched_in_pending = False
    matched_outside_pending: list[dict] = []
    for ev in events:
        summary = str(ev.get("summary") or "")
        if needle and needle not in summary.casefold():
            continue
        url = str(ev.get("url") or "")
        partstat = user_partstat(ev, login)
        pending_flag = is_pending_invitation_for_user(ev, login)
        in_pending = ev in pending
        if in_pending:
            matched_in_pending = True
        else:
            matched_outside_pending.append(ev)
        print("---")
        print("summary:", summary)
        print("calendar:", ev.get("calendar"))
        print("start:", ev.get("dtstart"))
        print("end:", ev.get("dtend"))
        print("user_partstat:", partstat)
        print("is_pending:", pending_flag, "in_pending_list:", in_pending)
        print("url:", url[:120])
        print("attendees_count:", len(ev.get("attendees") or []))
        for att in (ev.get("attendees") or [])[:5]:
            print("  attendee:", str(att)[:160])
        if args.dump_ics and url:
            try:
                resp = requests.get(
                    url,
                    auth=(login, password),
                    timeout=15,
                    headers={"Accept": "text/calendar"},
                )
                print(f"GET status={resp.status_code} bytes={len(resp.content)}")
                print("--- ICS ---")
                print(resp.content.decode("utf-8", errors="replace"))
                print("--- /ICS ---")
            except requests.RequestException as exc:
                print("GET FAIL:", exc)
        if args.accept and url:
            try:
                service.set_attendee_partstat(url, "ACCEPTED")
                print("PUT ACCEPTED: OK")
                refreshed = service._refresh_attendees_via_get(url)
                print("after GET attendees:", refreshed[0] if refreshed else None)
            except CalDAVError as exc:
                print("PUT ACCEPTED: FAIL", exc)
                return 3

    if needle and not matched_in_pending and not matched_outside_pending:
        print(
            f"WARN: event with summary substring {needle!r} not found in fetched range "
            "— возможно отсутствует в выбранных календарях (enabled_calendar_urls)."
        )
    if matched_outside_pending:
        print(
            f"INFO: найдено {len(matched_outside_pending)} событий по подстроке "
            "вне списка pending — см. user_partstat/attendees выше."
        )
    if args.accept and not any(
        (not needle or needle in str(e.get("summary") or "").casefold()) for e in pending
    ):
        print("Нет подходящего pending-события для --accept")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
