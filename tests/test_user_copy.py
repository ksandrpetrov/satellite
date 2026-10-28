"""Copy regressions: shared meaning, actionable errors and existing Telegram buttons."""

import json
import re
from html import unescape
from html.parser import HTMLParser
from http import HTTPStatus
from pathlib import Path

import pytest

from satellite.analytics.caption import format_event_count_ru
from satellite.calendar.providers.base import CalendarProviderError
from satellite.messages_ru import (
    BOT_DESCRIPTION_RU,
    BUTTON_FOREIGN_CALENDARS,
    CREATE_EVENT_UNCONFIRMED_HTML,
    PARTSTAT_UNCONFIRMED_TEXT,
    WEBAPP_COPY,
    format_meeting_count_ru,
)
from satellite.telegram_bot.handlers.routing import ForeignCalendarsCommand, recognize_message
from satellite.telegram_bot.presenters import settings_screens as screens
from satellite.web.calendar_api_service import CalendarApiService


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def visible_text(html):
    parser = _Text()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


@pytest.mark.parametrize(
    ("builder", "kwargs"),
    [
        (screens.settings_hub_bundle, {"digest_enabled": True, "pending_digest_enabled": False}),
        (screens.settings_calendar_menu_bundle, {}),
        (screens.settings_disconnect_confirm_bundle, {}),
        (
            screens.digest_settings_bundle,
            {
                "digest_enabled": True,
                "digest_days": "weekdays",
                "digest_time": "08:35",
                "weather_in_plan_enabled": False,
            },
        ),
        (screens.digest_days_bundle, {"digest_days": "all_days"}),
        (screens.digest_time_bundle, {"digest_time": "19:25"}),
        (
            screens.pending_digest_settings_bundle,
            {"digest_enabled": False, "digest_days": "1010100", "digest_time": "10:15"},
        ),
        (screens.pending_digest_days_bundle, {"digest_days": "1010100"}),
        (screens.analytics_options_bundle, {"workday_preset": "9-18"}),
        (screens.analytics_workday_applied_bundle, {"workday_preset": "10-19"}),
    ],
)
def test_settings_rich_and_fallback_keep_the_same_words_and_actions(builder, kwargs):
    keyboard = {"inline_keyboard": [[{"text": "Назад", "callback_data": "settings_back"}]]}
    bundle = builder(**kwargs, reply_markup=keyboard)
    assert visible_text(bundle.rich_html) == visible_text(bundle.fallback_html)
    assert "&lt;b&gt;" not in bundle.rich_html
    assert bundle.reply_markup == keyboard


def test_disconnect_explains_credential_removal_and_reconnection_in_both_formats():
    bundle = screens.settings_disconnect_confirm_bundle()
    for html in (bundle.rich_html, bundle.fallback_html):
        text = visible_text(html)
        assert "логин и пароль будут удалены" in text
        assert "Настройки дайджеста и аналитики останутся" in text
        assert "снова ввести почту и пароль приложения" in text


def test_analytics_options_describe_the_actual_period():
    bundle = screens.analytics_options_bundle(workday_preset="9-18")
    for html in (bundle.rich_html, bundle.fallback_html):
        text = visible_text(html)
        assert "9:00–18:00" in text
        assert "с понедельника по пятницу, включая будущие встречи" in text
        assert "сравнение с прошлой неделей" in text
        assert "13 недель" in text
        assert "последним семи дням" not in text


@pytest.mark.parametrize(
    "label",
    [BUTTON_FOREIGN_CALENDARS, "👥 Чужие календари", "👥\ufe0f Чужие календари", "/foreign"],
)
def test_shared_calendars_new_and_historical_buttons_use_the_same_route(label):
    assert isinstance(recognize_message(label), ForeignCalendarsCommand)


def test_bot_profile_does_not_advertise_unimplemented_yandex_connection():
    assert "календаря Mail.ru" in BOT_DESCRIPTION_RU
    assert "Яндекс Календарь пока недоступен." in BOT_DESCRIPTION_RU
    assert "Яндекс — пока недоступен" == WEBAPP_COPY["provider_yandex"]


@pytest.mark.parametrize(
    ("count", "meetings", "events"),
    [
        (0, "0 встреч", "0 событий"),
        (1, "1 встреча", "1 событие"),
        (2, "2 встречи", "2 события"),
        (4, "4 встречи", "4 события"),
        (5, "5 встреч", "5 событий"),
        (11, "11 встреч", "11 событий"),
        (21, "21 встреча", "21 событие"),
        (22, "22 встречи", "22 события"),
        (111, "111 встреч", "111 событий"),
    ],
)
def test_counts_use_correct_russian_forms(count, meetings, events):
    assert format_meeting_count_ru(count) == meetings
    assert format_event_count_ru(count) == events


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        ("CREATE_UNCONFIRMED", HTTPStatus.BAD_GATEWAY, CREATE_EVENT_UNCONFIRMED_HTML),
        ("PARTSTAT_UPDATE_UNCONFIRMED", HTTPStatus.BAD_GATEWAY, PARTSTAT_UNCONFIRMED_TEXT),
        (
            "CALENDAR_CONNECTION_CHANGED",
            HTTPStatus.CONFLICT,
            "Подключение календаря изменилось. Обнови список встреч и повтори действие.",
        ),
        (
            "CALDAV_UNAVAILABLE",
            HTTPStatus.BAD_GATEWAY,
            "Не удалось получить данные календаря. Попробуй ещё раз позже.",
        ),
        (
            "FUTURE_PROVIDER_ERROR",
            HTTPStatus.BAD_GATEWAY,
            "Не удалось выполнить действие. Попробуй ещё раз позже.",
        ),
    ],
)
def test_web_error_copy_preserves_codes_and_uncertain_outcomes(code, status, expected):
    exc = CalendarProviderError("Technical provider response", error_code=code)
    result = CalendarApiService._provider_error(exc)
    assert result.status == status
    assert result.payload == {"error": code, "message": expected}
    assert "Technical provider response" not in result.payload["message"]


def test_webapp_static_and_javascript_fallback_copy_matches_catalog():
    page = Path(__file__).resolve().parents[1] / "satellite/web/static/connect.html"
    source = page.read_text()
    static = re.findall(
        r'<([\w-]+)\b[^>]* data-copy(?:-html)?="([^"]+)"[^>]*>(.*?)</\1>',
        source,
        flags=re.DOTALL,
    )
    assert len(static) >= 30
    for _, key, fallback in static:
        assert unescape(fallback) == WEBAPP_COPY[key], key
    for tag in re.findall(r'<input\b[^>]*data-copy-placeholder="[^"]+"[^>]*>', source):
        key = re.search(r'data-copy-placeholder="([^"]+)"', tag).group(1)
        fallback = re.search(r' placeholder="([^"]+)"', tag).group(1)
        assert unescape(fallback) == WEBAPP_COPY[key], key
    dynamic = re.findall(r"copyText\('([^']+)', (\"(?:[^\"\\]|\\.)*\")\)", source)
    assert len(dynamic) >= 40
    for key, fallback in dynamic:
        assert json.loads(fallback) == WEBAPP_COPY[key], key
