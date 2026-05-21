"""Работа с ATTENDEE/PARTSTAT: declined, pending, лучший статус пользователя.

PARTSTAT — параметр CalDAV-строки ATTENDEE с состоянием ответа конкретного
участника (ACCEPTED / TENTATIVE / DECLINED / NEEDS-ACTION / DELEGATED).
В одной встрече участник может фигурировать несколькими строками — все
функции здесь устойчивы к дубликатам.
"""

from __future__ import annotations

from ._types import Event


def is_declined_event_for_user(event: Event, login: str) -> bool:
    login_norm = (login or "").strip().casefold()
    if not login_norm:
        return False
    for attendee in event.get("attendees", []):
        attendee_norm = str(attendee).casefold()
        if login_norm in attendee_norm and "partstat=declined" in attendee_norm:
            return True
    return False


def _login_match_needles(login: str) -> list[str]:
    """Варианты логина для поиска в строке ATTENDEE (полный email и local-part)."""
    normalized = (login or "").strip().casefold()
    if not normalized:
        return []
    needles = [normalized]
    local, sep, _domain = normalized.partition("@")
    if sep and local and local not in needles:
        needles.append(local)
    return needles


def _attendee_line_matches_login(attendee_line: str, login: str) -> bool:
    blob = (attendee_line or "").casefold()
    return any(needle in blob for needle in _login_match_needles(login))


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
    """True, если пользователю нужно ответить на приглашение (NEEDS-ACTION / DELEGATED).

    В отличие от ``user_partstat``, пессимистичная свёртка по строкам ATTENDEE:
    если на один mailto несколько записей и хотя бы в одной NEEDS-ACTION —
    приглашение неотвеченное (``user_partstat`` взял бы «лучший» ACCEPTED).
    Строки без PARTSTAT не считаем pending — см. ``user_partstat``.
    """
    login_norm = (login or "").strip()
    if not login_norm:
        return False
    for attendee in event.get("attendees", []):
        if not _attendee_line_matches_login(str(attendee), login_norm):
            continue
        status = _partstat_from_attendee_line(str(attendee))
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
