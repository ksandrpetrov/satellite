"""Работа с ATTENDEE/PARTSTAT: declined, pending, лучший статус пользователя.

PARTSTAT — параметр CalDAV-строки ATTENDEE с состоянием ответа конкретного
участника (ACCEPTED / TENTATIVE / DECLINED / NEEDS-ACTION / DELEGATED).
В одной встрече участник может фигурировать несколькими строками — все
функции здесь устойчивы к дубликатам.
"""

from __future__ import annotations

from ..attendee_identity import attendee_matches_account
from ._types import Event


def is_declined_event_for_user(event: Event, login: str) -> bool:
    login_norm = (login or "").strip().casefold()
    if not login_norm:
        return False
    for attendee in event.get("attendees", []):
        attendee_norm = str(attendee).casefold()
        if attendee_matches_account(str(attendee), login) and "partstat=declined" in attendee_norm:
            return True
    return False


def _attendee_line_matches_login(attendee_line: str, login: str) -> bool:
    return attendee_matches_account(attendee_line, login)


def _partstat_from_attendee_line(attendee_line: str) -> str | None:
    """PARTSTAT из одной строки ATTENDEE или None, если параметра нет."""
    attendee_norm = (attendee_line or "").casefold()
    idx = attendee_norm.find("partstat=")
    if idx < 0:
        return None
    tail = attendee_norm[idx + len("partstat=") :]
    end = len(tail)
    for sep in (";", ",", ":", " "):
        pos = tail.find(sep)
        if 0 <= pos < end:
            end = pos
    status = tail[:end].strip().upper()
    return status or None


def is_pending_invitation_for_user(event: Event, login: str) -> bool:
    """Pending only for the exact address of the connected calendar account."""
    login_norm = (login or "").strip()
    if not login_norm:
        return False
    for attendee in event.get("attendees", []):
        line = str(attendee)
        if not _attendee_line_matches_login(line, login_norm):
            continue
        status = _partstat_from_attendee_line(line)
        if status in {"NEEDS-ACTION", "DELEGATED"}:
            return True
    return False


def user_partstat(event: Event, login: str) -> str | None:
    """Возвращает PARTSTAT пользователя в событии (верхним регистром) или None.

    Если пользователь встречается в attendees несколько раз — выбираем самое
    «доброе» состояние: ``ACCEPTED`` > ``TENTATIVE`` > ``DELEGATED`` >
    ``NEEDS-ACTION`` > ``DECLINED``. Это даёт стабильный ответ для редкого, но
    реального случая дублирующихся ATTENDEE-строк.

    Возвращает None, если пользователь в attendees не найден или PARTSTAT не
    указан — это означает «не знаем», и downstream-логика трактует такое как
    подтверждённое (рисуем обычный номер).
    """
    login_norm = (login or "").strip().casefold()
    if not login_norm:
        return None
    rank = {
        "ACCEPTED": 5,
        "TENTATIVE": 4,
        "DELEGATED": 3,
        "NEEDS-ACTION": 2,
        "DECLINED": 1,
    }
    best: str | None = None
    for attendee in event.get("attendees", []):
        attendee_norm = str(attendee).casefold()
        if not _attendee_line_matches_login(attendee_norm, login):
            continue
        idx = attendee_norm.find("partstat=")
        if idx < 0:
            continue
        tail = attendee_norm[idx + len("partstat=") :]
        end = len(tail)
        for sep in (";", ",", ":", " "):
            pos = tail.find(sep)
            if 0 <= pos < end:
                end = pos
        status = tail[:end].strip().upper()
        if not status:
            continue
        if best is None or rank.get(status, 0) > rank.get(best, 0):
            best = status
    return best
