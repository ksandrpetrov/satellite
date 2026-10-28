"""Rich + fallback presenter'ы экранов настроек."""

from __future__ import annotations

from ...messages_ru import (
    ANALYTICS_WORKDAY_APPLIED_TEXT,
    SETTINGS_CALENDAR_MENU_TEXT,
    SETTINGS_DISCONNECT_CONFIRM_TEXT,
    SETTINGS_HUB_INTRO,
    SETTINGS_HUB_TITLE_PLAIN,
    analytics_options_screen_text,
    digest_days_screen_text,
    digest_settings_screen_text,
    digest_time_screen_text,
    meeting_exclusions_screen_text,
    pending_digest_days_screen_text,
    pending_digest_settings_screen_text,
    settings_hub_status_bits,
    settings_hub_text,
)
from ...presentation.html import strip_bold_tags
from ...presentation.rich import blockquote, join_blocks, paragraph, section_heading
from .bundle import ScreenBundle


def _text_screen_bundle(
    text: str, *, reply_markup: dict | None, heading: bool = True
) -> ScreenBundle:
    """Render the shared settings copy in Rich HTML without duplicating its words."""
    first, *rest = text.splitlines()
    blocks = [section_heading(strip_bold_tags(first), level=3) if heading else paragraph(first)]
    blocks.extend(paragraph(line) for line in rest if line)
    return ScreenBundle(
        rich_html=join_blocks(blocks), fallback_html=text, reply_markup=reply_markup
    )


def settings_hub_bundle(
    *,
    digest_enabled: bool | None = None,
    pending_digest_enabled: bool | None = None,
    weather_in_plan_enabled: bool | None = None,
    has_calendar: bool = True,
    reply_markup: dict | None = None,
) -> ScreenBundle:
    fallback = settings_hub_text(
        digest_enabled=digest_enabled,
        pending_digest_enabled=pending_digest_enabled,
        weather_in_plan_enabled=weather_in_plan_enabled,
        has_calendar=has_calendar,
    )
    bits = settings_hub_status_bits(
        digest_enabled=digest_enabled,
        pending_digest_enabled=pending_digest_enabled,
        weather_in_plan_enabled=weather_in_plan_enabled,
        has_calendar=has_calendar,
    )
    blocks = [
        section_heading(SETTINGS_HUB_TITLE_PLAIN, level=3),
        paragraph(SETTINGS_HUB_INTRO),
    ]
    if bits:
        blocks.append(blockquote(" · ".join(bits)))
    return ScreenBundle(
        rich_html=join_blocks(blocks),
        fallback_html=fallback,
        reply_markup=reply_markup,
    )


def settings_calendar_menu_bundle(*, reply_markup: dict | None = None) -> ScreenBundle:
    return _text_screen_bundle(SETTINGS_CALENDAR_MENU_TEXT, reply_markup=reply_markup)


def settings_disconnect_confirm_bundle(*, reply_markup: dict | None = None) -> ScreenBundle:
    return _text_screen_bundle(
        SETTINGS_DISCONNECT_CONFIRM_TEXT, reply_markup=reply_markup, heading=False
    )


def meeting_exclusions_bundle(
    *,
    week_count: int,
    saved_outside_week_count: int,
    page: int,
    page_count: int,
    truncated: bool = False,
    reply_markup: dict | None = None,
) -> ScreenBundle:
    fallback = meeting_exclusions_screen_text(
        week_count=week_count,
        saved_outside_week_count=saved_outside_week_count,
        page=page,
        page_count=page_count,
        truncated=truncated,
    )
    return ScreenBundle(
        rich_html=fallback,
        fallback_html=fallback,
        reply_markup=reply_markup,
    )


def meeting_exclusions_error_bundle(
    text: str,
    *,
    reply_markup: dict | None = None,
) -> ScreenBundle:
    return ScreenBundle(rich_html=text, fallback_html=text, reply_markup=reply_markup)


def digest_settings_bundle(
    *,
    digest_enabled: bool,
    digest_days: str,
    digest_time: str,
    weather_in_plan_enabled: bool,
    reply_markup: dict | None = None,
) -> ScreenBundle:
    return _text_screen_bundle(
        digest_settings_screen_text(
            digest_enabled=digest_enabled,
            digest_days=digest_days,
            digest_time=digest_time,
            weather_in_plan_enabled=weather_in_plan_enabled,
        ),
        reply_markup=reply_markup,
    )


def digest_days_bundle(*, digest_days: str, reply_markup: dict | None = None) -> ScreenBundle:
    return _text_screen_bundle(digest_days_screen_text(digest_days), reply_markup=reply_markup)


def digest_time_bundle(*, digest_time: str, reply_markup: dict | None = None) -> ScreenBundle:
    return _text_screen_bundle(digest_time_screen_text(digest_time), reply_markup=reply_markup)


def pending_digest_settings_bundle(
    *,
    digest_enabled: bool,
    digest_days: str,
    digest_time: str,
    reply_markup: dict | None = None,
) -> ScreenBundle:
    return _text_screen_bundle(
        pending_digest_settings_screen_text(
            digest_enabled=digest_enabled,
            digest_days=digest_days,
            digest_time=digest_time,
        ),
        reply_markup=reply_markup,
    )


def pending_digest_days_bundle(
    *, digest_days: str, reply_markup: dict | None = None
) -> ScreenBundle:
    return _text_screen_bundle(
        pending_digest_days_screen_text(digest_days), reply_markup=reply_markup
    )


def analytics_options_bundle(
    *, workday_preset: str, reply_markup: dict | None = None
) -> ScreenBundle:
    return _text_screen_bundle(
        analytics_options_screen_text(workday_preset=workday_preset), reply_markup=reply_markup
    )


def analytics_workday_applied_bundle(
    *, workday_preset: str, reply_markup: dict | None = None
) -> ScreenBundle:
    return _text_screen_bundle(
        ANALYTICS_WORKDAY_APPLIED_TEXT, reply_markup=reply_markup, heading=False
    )
