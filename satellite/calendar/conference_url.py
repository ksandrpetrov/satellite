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

# Подстрока в host → ключ провайдера (порядок = приоритет при выборе из description).
_PROVIDER_HOSTS: tuple[tuple[str, str], ...] = (
    ("meet.google.com", "meet"),
    ("zoom.us", "zoom"),
    ("teams.microsoft.com", "teams"),
    ("teams.live.com", "teams"),
    ("vk.team", "vk_teams"),
    ("vkcalls", "vk_teams"),
    ("jit.si", "jitsi"),
    ("jitsi", "jitsi"),
    ("webex.com", "webex"),
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


def extract_conference_url(event: Mapping[str, object]) -> str | None:
    """URL видеозвонка: ``url`` → ``location`` → ``description`` (лучший по провайдеру)."""
    url_field = event.get("url")
    if url_field is not None:
        normalized = _normalize_url(str(url_field))
        if normalized:
            return normalized

    location = event.get("location")
    if location is not None:
        normalized = _normalize_url(str(location).strip())
        if normalized:
            return normalized

    description = event.get("description")
    if description is not None:
        return _pick_best_url(_urls_in_text(str(description)))

    return None


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
    if loc_url:
        return _ONLINE_LABEL
    return loc
