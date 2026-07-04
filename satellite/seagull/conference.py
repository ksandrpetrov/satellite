"""Подписи ссылок на видеозвонки в дайджесте."""

from __future__ import annotations

from ..calendar.conference_url import conference_provider
from . import templates as t

_LABELS: dict[str, str] = {
    "meet": t.CONFERENCE_JOIN_MEET,
    "zoom": t.CONFERENCE_JOIN_ZOOM,
    "teams": t.CONFERENCE_JOIN_TEAMS,
    "vk_teams": t.CONFERENCE_JOIN_VK_TEAMS,
    "jitsi": t.CONFERENCE_JOIN_JITSI,
    "webex": t.CONFERENCE_JOIN_WEBEX,
}


def conference_join_label(url: str) -> str:
    """Человекочитаемая подпись ссылки по URL провайдера."""
    return _LABELS.get(conference_provider(url), t.CONFERENCE_JOIN_GENERIC)
