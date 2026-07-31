"""Rich + fallback presenter'ы экранов настроек."""

from __future__ import annotations

from ...digest_utils import format_digest_days_label
from ...messages_ru import (
    ANALYTICS_WORKDAY_APPLIED_TEXT,
    DIGEST_DAYS_LABEL,
    SETTINGS_CALENDAR_MENU_BODY,
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
from ...presentation.rich import blockquote, bold, join_blocks, paragraph, section_heading
from .bundle import ScreenBundle


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
    fallback = SETTINGS_CALENDAR_MENU_TEXT
    rich = join_blocks(
        [
            section_heading("📅 Календарь", level=3),
            paragraph(SETTINGS_CALENDAR_MENU_BODY),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def settings_disconnect_confirm_bundle(*, reply_markup: dict | None = None) -> ScreenBundle:
    fallback = SETTINGS_DISCONNECT_CONFIRM_TEXT
    rich = join_blocks(
        [
            paragraph("🪶 Точно отключить календарь?"),
            paragraph(
                "Чайка забудет логин и пароль, но настройки дайджеста и аналитики сохранятся. "
                "Заново подключить можно одной кнопкой."
            ),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


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
    fallback = digest_settings_screen_text(
        digest_enabled=digest_enabled,
        digest_days=digest_days,
        digest_time=digest_time,
        weather_in_plan_enabled=weather_in_plan_enabled,
    )
    status_emoji = "🔔" if digest_enabled else "🔕"
    status_text = "включён" if digest_enabled else "отключён"
    weather_emoji = "🌤" if weather_in_plan_enabled else "🔕"
    weather_text = "включена" if weather_in_plan_enabled else "выключена"
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    rich = join_blocks(
        [
            section_heading("📅 Настройки дайджеста на сегодня", level=3),
            paragraph(f"{status_emoji} Статус: {bold(status_text)}"),
            paragraph(f"📆 Дни: {bold(days_label)}"),
            paragraph(f"🕘 Время: {bold(f'{digest_time} МСК')}"),
            paragraph(f"{weather_emoji} Погода в дайджесте: {bold(weather_text)}"),
            paragraph("Что меняем?"),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def digest_days_bundle(*, digest_days: str, reply_markup: dict | None = None) -> ScreenBundle:
    fallback = digest_days_screen_text(digest_days)
    days_label = DIGEST_DAYS_LABEL.get(digest_days, digest_days)
    rich = join_blocks(
        [
            section_heading("📆 Дни отправки", level=3),
            paragraph(f"Сейчас: {bold(days_label)}."),
            paragraph("Когда Чайке присылать сводку на сегодня?"),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def digest_time_bundle(*, digest_time: str, reply_markup: dict | None = None) -> ScreenBundle:
    fallback = digest_time_screen_text(digest_time)
    rich = join_blocks(
        [
            section_heading("🕘 Время отправки", level=3),
            paragraph(f"Сейчас: {bold(f'{digest_time} МСК')}."),
            paragraph("Напиши новое время одной строкой:"),
            paragraph("<i>09:30</i> · <i>9 30</i> · <i>8:00</i> · <i>18:25</i>"),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def pending_digest_settings_bundle(
    *,
    digest_enabled: bool,
    digest_days: str,
    digest_time: str,
    reply_markup: dict | None = None,
) -> ScreenBundle:
    fallback = pending_digest_settings_screen_text(
        digest_enabled=digest_enabled,
        digest_days=digest_days,
        digest_time=digest_time,
    )
    status_emoji = "📨" if digest_enabled else "🔕"
    status_text = "включён" if digest_enabled else "отключён"
    days_label = format_digest_days_label(digest_days)
    rich = join_blocks(
        [
            section_heading("📨 Дайджест непринятых встреч", level=3),
            paragraph(f"{status_emoji} Статус: {bold(status_text)}"),
            paragraph(f"📆 Дни: {bold(days_label)}"),
            paragraph(f"🕘 Время: {bold(f'{digest_time} МСК')}"),
            paragraph("По расписанию Чайка напомнит принять встречи — как в «Входящие»."),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def pending_digest_days_bundle(
    *, digest_days: str, reply_markup: dict | None = None
) -> ScreenBundle:
    fallback = pending_digest_days_screen_text(digest_days)
    days_label = format_digest_days_label(digest_days)
    rich = join_blocks(
        [
            section_heading("📆 Дни отправки", level=3),
            paragraph(f"Сейчас: {bold(days_label)}."),
            paragraph("Отметь дни недели — можно один или несколько."),
            paragraph("Снять последнюю галочку нельзя: нужен хотя бы один день."),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def analytics_options_bundle(
    *, workday_preset: str, reply_markup: dict | None = None
) -> ScreenBundle:
    fallback = analytics_options_screen_text(workday_preset=workday_preset)
    label = "9:00–18:00" if workday_preset == "9-18" else "10:00–19:00"
    rich = join_blocks(
        [
            section_heading("📊 Аналитика недели", level=3),
            paragraph(f"Рабочий день для расчёта занятости: {bold(label)}."),
            paragraph(
                "Жми «Построить отчёт» — Чайка пришлёт картинку с графиком "
                "и сводкой по последним семи дням."
            ),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)


def analytics_workday_applied_bundle(
    *, workday_preset: str, reply_markup: dict | None = None
) -> ScreenBundle:
    fallback = ANALYTICS_WORKDAY_APPLIED_TEXT
    rich = join_blocks(
        [
            paragraph("📊 Рабочий день для аналитики обновлён."),
            paragraph("Жми «Построить отчёт» — Чайка пересчитает по новым границам."),
        ]
    )
    return ScreenBundle(rich_html=rich, fallback_html=fallback, reply_markup=reply_markup)
