"""Rich + fallback presenter'ы экранов настроек."""

from __future__ import annotations

from ...formatters.rich import blockquote, bold, join_blocks, paragraph, section_heading
from ...messages_ru.settings_ui import (
    ANALYTICS_WORKDAY_APPLIED_TEXT,
    DIGEST_DAYS_LABEL,
    SETTINGS_CALENDAR_MENU_TEXT,
    SETTINGS_DISCONNECT_CONFIRM_TEXT,
    analytics_options_screen_text,
    digest_days_screen_text,
    digest_settings_screen_text,
    digest_time_screen_text,
    pending_digest_days_screen_text,
    pending_digest_settings_screen_text,
    pending_digest_time_screen_text,
    settings_hub_text,
)
from .bundle import ScreenBundle


def _status_bits(
    *,
    digest_enabled: bool | None,
    pending_digest_enabled: bool | None,
    weather_in_plan_enabled: bool | None,
    has_calendar: bool,
) -> list[str]:
    bits: list[str] = []
    if digest_enabled is not None:
        bits.append(
            "🔔 Дайджест на сегодня включён"
            if digest_enabled
            else "🔕 Дайджест на сегодня выключен"
        )
    if pending_digest_enabled is not None:
        bits.append(
            "📨 Дайджест непринятых включён"
            if pending_digest_enabled
            else "📨 Дайджест непринятых выключен"
        )
    if weather_in_plan_enabled is not None:
        bits.append(
            "🌤 Погода в плане включена"
            if weather_in_plan_enabled
            else "🔕 Погода в плане выключена"
        )
    bits.append("📅 Календарь подключён" if has_calendar else "🔌 Календарь не подключён")
    return bits


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
    bits = _status_bits(
        digest_enabled=digest_enabled,
        pending_digest_enabled=pending_digest_enabled,
        weather_in_plan_enabled=weather_in_plan_enabled,
        has_calendar=has_calendar,
    )
    blocks = [
        section_heading("⚙️ Настройки Чайки", level=3),
        paragraph(
            "Здесь живут дайджесты, погода в плане, аналитика и календарь. Выбери, что настроить."
        ),
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
            paragraph("Управление подключением, приглашения и выбор календарей для плана."),
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
    from ...digest_utils import format_digest_days_label

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
    from ...digest_utils import format_digest_days_label

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


def pending_digest_time_bundle(
    *, digest_time: str, reply_markup: dict | None = None
) -> ScreenBundle:
    fallback = pending_digest_time_screen_text(digest_time)
    rich = join_blocks(
        [
            section_heading("🕘 Время отправки", level=3),
            paragraph(f"Сейчас: {bold(f'{digest_time} МСК')}."),
            paragraph("Напиши новое время одной строкой:"),
            paragraph("<i>09:30</i> · <i>9 30</i> · <i>8:00</i> · <i>18:25</i>"),
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
