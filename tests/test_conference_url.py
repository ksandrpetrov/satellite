"""Тесты извлечения ссылок на видеоконференции."""

from __future__ import annotations

from satellite.calendar.conference_url import (
    conference_provider,
    display_room_location,
    extract_conference_url,
)
from satellite.seagull.conference import conference_join_label
from satellite.seagull.templates import ROOM_ONLINE


def test_extract_from_url_field():
    event = {"url": "https://meet.google.com/abc-defg-hij"}
    assert extract_conference_url(event) == "https://meet.google.com/abc-defg-hij"


def test_extract_from_location_when_url_field_missing():
    event = {"location": "https://zoom.us/j/123456789"}
    assert extract_conference_url(event) == "https://zoom.us/j/123456789"


def test_extract_from_description_plain_url():
    event = {
        "description": "Join: https://teams.microsoft.com/l/meetup-join/abc123",
    }
    assert extract_conference_url(event) == "https://teams.microsoft.com/l/meetup-join/abc123"


def test_extract_from_description_html_href():
    event = {
        "description": '<a href="https://meet.google.com/xyz-abcd-efg">Join</a>',
    }
    assert extract_conference_url(event) == "https://meet.google.com/xyz-abcd-efg"


def test_url_field_has_priority_over_description():
    event = {
        "url": "https://meet.google.com/from-url",
        "description": "https://zoom.us/j/999",
    }
    assert extract_conference_url(event) == "https://meet.google.com/from-url"


def test_prefers_known_video_host_in_description():
    event = {
        "description": ("Docs: https://example.com/agenda Call: https://meet.google.com/best-link"),
    }
    assert extract_conference_url(event) == "https://meet.google.com/best-link"


def test_strips_trailing_punctuation_from_url():
    event = {"url": "https://meet.google.com/abc-defg-hij)."}
    assert extract_conference_url(event) == "https://meet.google.com/abc-defg-hij"


def test_rejects_non_http_schemes():
    event = {"url": "javascript:alert(1)"}
    assert extract_conference_url(event) is None


def test_no_url_returns_none():
    assert extract_conference_url({"location": "Room A1"}) is None


def test_display_room_location_physical_room():
    assert display_room_location("A1", "https://meet.google.com/x") == "A1"


def test_display_room_location_url_becomes_online():
    url = "https://meet.google.com/abc-defg-hij"
    assert display_room_location(url, url) == ROOM_ONLINE


def test_display_room_location_url_without_conference_still_online():
    assert display_room_location("https://zoom.us/j/1", None) == ROOM_ONLINE


def test_conference_provider_labels():
    assert conference_provider("https://meet.google.com/x") == "meet"
    assert conference_provider("https://us06web.zoom.us/j/123") == "zoom"
    assert conference_provider("https://example.com/call") == "generic"


def test_conference_join_label_by_provider():
    assert conference_join_label("https://meet.google.com/x") == "Войти в Google Meet"
    assert conference_join_label("https://zoom.us/j/1") == "Войти в Zoom"
    assert conference_join_label("https://example.com/x") == "Войти в видеозвонок"
