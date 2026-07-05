"""Извлечение ссылок на видеоконференции из полей CalDAV-события."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlparse

# Должно совпадать с ``seagull.templates.ROOM_ONLINE``.
_ONLINE_LABEL = "онлайн"

_URL_RE = re.compile(
    r'https?://[^\s<>"\')\]]+',
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"""href=["'](https?://[^"']+)["']""", re.IGNORECASE)

# Прямая ссылка на вход в видеозвонок (не permalink календаря и не произвольный URL).
_CALL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"vk\.com/call/join|"
    r"meet\.google\.com|"
    r"zoom\.us/j|"
    r"[^/]+\.zoom\.us/j|"
    r"teams\.microsoft\.com/l/meetup-join|"
    r"call\.whatsapp\.com/(?:video|voice)|"
    r"join\.skype\.com|"
    r"telemost\.yandex\.ru/j|"
    r"discord\.gg|"
    r"discord\.com/invite|"
    r"meet\.jit\.si|"
    r"whereby\.com"
    r")/?[^\s<>()\"]*",
    re.IGNORECASE,
)

# Подстрока in host → ключ провайдера (порядок = приоритет при выборе из description).
_PROVIDER_HOSTS: tuple[tuple[str, str], ...] = (
    ("meet.google.com", "meet"),
    ("zoom.us", "zoom"),
    ("teams.microsoft.com", "teams"),
    ("teams.live.com", "teams"),
    ("vk.team", "vk_teams"),
    ("vkcalls", "vk_teams"),
    ("telemost.yandex.", "telemost"),
    ("jit.si", "jitsi"),
    ("jitsi", "jitsi"),
    ("webex.com", "webex"),
)

# Permalink на страницу события в календаре — не ссылка на звонок (часто в поле ``URL``).
_CALENDAR_PERMALINK_MARKERS: tuple[str, ...] = (
    "calendar.yandex.",
    "calendar.google.com",
    "calendar.mail.ru",
    "e.mail.ru/calendar",
    "outlook.office.com/calendar",
    "outlook.live.com/calendar",
    "outlook.office365.com/calendar",
)


def _is_safe_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _strip_trailing_punct(url: str) -> str:
    return url.rstrip(").,;")


def _normalize_url(raw: str) -> str | None:
    cleaned = _strip_trailing_punct(raw.strip())
    if cleaned and _is_safe_http_url(cleaned):
        return cleaned
    return None


def is_conference_call_url(url: str) -> bool:
    """True, если URL — прямая ссылка на вход в известный видеозвонок."""
    normalized = _normalize_url(url)
    if not normalized:
        return False
    return _CALL_URL_RE.fullmatch(normalized) is not None


def _urls_in_text(text: str) -> list[str]:
    found: list[str] = []
    for match in _URL_RE.finditer(text):
        url = _normalize_url(match.group(0))
        if url:
            found.append(url)
    for match in _HREF_RE.finditer(text):
        url = _normalize_url(match.group(1))
        if url and url not in found:
            found.append(url)
    return found


def conference_provider(url: str) -> str:
    """Ключ провайдера для подписи ссылки: meet, zoom, teams, …, generic."""
    host = urlparse(url).netloc.lower()
    for pattern, key in _PROVIDER_HOSTS:
        if pattern in host:
            return key
    return "generic"


def _provider_rank(url: str) -> int:
    key = conference_provider(url)
    if key == "generic":
        return len(_PROVIDER_HOSTS)
    for index, (_, provider_key) in enumerate(_PROVIDER_HOSTS):
        if provider_key == key:
            return index
    return len(_PROVIDER_HOSTS)


def _pick_best_url(urls: list[str]) -> str | None:
    if not urls:
        return None
    return min(urls, key=lambda candidate: (_provider_rank(candidate), len(candidate)))


def _is_calendar_event_permalink(url: str) -> bool:
    """Страница события в календаре, а не прямой вход в видеозвонок."""
    parsed = urlparse(url)
    host_path = f"{parsed.netloc.lower()}{parsed.path.lower()}"
    if host_path.endswith(".ics"):
        return True
    return any(marker in host_path for marker in _CALENDAR_PERMALINK_MARKERS)


def _append_candidate(
    candidates: list[str],
    url: str | None,
    *,
    skip_calendar_permalinks: bool,
) -> None:
    if not url or url in candidates:
        return
    if not is_conference_call_url(url):
        return
    if skip_calendar_permalinks and _is_calendar_event_permalink(url):
        return
    candidates.append(url)


def extract_conference_url(event: Mapping[str, object]) -> str | None:
    """URL видеозвонка: лучший по провайдеру из ``url``, ``location`` и ``description``.

    Поле ``URL`` в ICS часто содержит permalink события (Yandex/Google/Mail.ru),
    а ссылка на Meet/Zoom лежит в ``location`` или ``description`` — поэтому
    собираем все кандидаты и отдаём приоритет известным видеохостам.
    """
    candidates: list[str] = []

    url_field = event.get("url")
    if url_field is not None:
        _append_candidate(
            candidates,
            _normalize_url(str(url_field)),
            skip_calendar_permalinks=True,
        )

    location = event.get("location")
    if location is not None:
        _append_candidate(
            candidates,
            _normalize_url(str(location).strip()),
            skip_calendar_permalinks=False,
        )

    description = event.get("description")
    if description is not None:
        for url in _urls_in_text(str(description)):
            _append_candidate(candidates, url, skip_calendar_permalinks=True)

    return _pick_best_url(candidates)


def display_room_location(
    location: str | None,
    conference_url: str | None,
) -> str | None:
    """Текст переговорной для ``ROOM_LINE``; ``None`` → «без переговорной»."""
    if not location:
        return None
    loc = location.strip()
    if not loc:
        return None
    loc_url = _normalize_url(loc)
    if loc_url and is_conference_call_url(loc_url):
        return _ONLINE_LABEL
    return loc
