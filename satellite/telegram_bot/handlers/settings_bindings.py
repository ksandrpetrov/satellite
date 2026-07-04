"""Shared digest settings bindings and update helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...messages_ru import (
    CB_DIGEST_BACK,
    CB_DIGEST_CLOSE,
    CB_DIGEST_DAYS,
    CB_DIGEST_DAYS_ALL,
    CB_DIGEST_DAYS_WEEKDAYS,
    CB_DIGEST_SETTINGS,
    CB_DIGEST_TIME,
    CB_DIGEST_TOGGLE,
    CB_PENDING_DIGEST_BACK,
    CB_PENDING_DIGEST_CLOSE,
    CB_PENDING_DIGEST_DAYS,
    CB_PENDING_DIGEST_DAYS_ALL,
    CB_PENDING_DIGEST_DAYS_WEEKDAYS,
    CB_PENDING_DIGEST_SETTINGS,
    CB_PENDING_DIGEST_TIME,
    CB_PENDING_DIGEST_TOGGLE,
    DIGEST_DAYS_ALL_APPLIED_TEXT,
    DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
    DIGEST_SETTINGS_CLOSED_TEXT,
    DIGEST_TIME_INVALID_TEXT,
    PENDING_DIGEST_DAYS_ALL_APPLIED_TEXT,
    PENDING_DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
    PENDING_DIGEST_SETTINGS_CLOSED_TEXT,
    PENDING_DIGEST_TIME_INVALID_TEXT,
    build_digest_days_keyboard,
    build_digest_settings_keyboard,
    build_digest_time_keyboard,
    build_pending_digest_days_keyboard,
    build_pending_digest_settings_keyboard,
    build_pending_digest_time_keyboard,
    digest_days_screen_text,
    digest_settings_screen_text,
    digest_time_applied_text,
    digest_time_screen_text,
    digest_toggle_notice_text,
    pending_digest_days_screen_text,
    pending_digest_settings_screen_text,
    pending_digest_time_applied_text,
    pending_digest_time_screen_text,
    pending_digest_toggle_notice_text,
)
from ...subscriptions import DigestSettings
from ..presenters.bundle import ScreenBundle
from ..presenters.settings_screens import (
    digest_days_bundle,
    digest_settings_bundle,
    digest_time_bundle,
    pending_digest_days_bundle,
    pending_digest_settings_bundle,
)
from .context import HandlerContext
from .digest_state import DIGEST_KIND_DAILY, DIGEST_KIND_PENDING, DigestKind

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DigestKindBindings:
    kind: DigestKind
    enabled_field: str
    days_field: str
    time_field: str
    update_enabled_kw: str
    update_days_kw: str
    update_time_kw: str
    cb_settings: str
    cb_toggle: str
    cb_days: str
    cb_days_weekdays: str
    cb_days_all: str
    cb_time: str
    cb_back: str
    cb_close: str
    screen_text: Callable[..., str]
    days_screen_text: Callable[[str], str]
    time_screen_text: Callable[[str], str]
    time_applied_text: Callable[[str], str]
    time_invalid_text: str
    settings_closed_text: str
    days_weekdays_applied: str
    days_all_applied: str
    toggle_notice: Callable[..., str]
    build_settings_keyboard: Callable[..., dict]
    build_days_keyboard: Callable[..., dict]
    build_time_keyboard: Callable[[], dict]


def _enabled(settings: DigestSettings, bindings: DigestKindBindings) -> bool:
    return bool(getattr(settings, bindings.enabled_field))


def _days(settings: DigestSettings, bindings: DigestKindBindings) -> str:
    return str(getattr(settings, bindings.days_field))


def _time(settings: DigestSettings, bindings: DigestKindBindings) -> str:
    return str(getattr(settings, bindings.time_field))


_BINDINGS: dict[DigestKind, DigestKindBindings] = {
    DIGEST_KIND_DAILY: DigestKindBindings(
        kind=DIGEST_KIND_DAILY,
        enabled_field="digest_enabled",
        days_field="digest_days",
        time_field="digest_time",
        update_enabled_kw="digest_enabled",
        update_days_kw="digest_days",
        update_time_kw="digest_time",
        cb_settings=CB_DIGEST_SETTINGS,
        cb_toggle=CB_DIGEST_TOGGLE,
        cb_days=CB_DIGEST_DAYS,
        cb_days_weekdays=CB_DIGEST_DAYS_WEEKDAYS,
        cb_days_all=CB_DIGEST_DAYS_ALL,
        cb_time=CB_DIGEST_TIME,
        cb_back=CB_DIGEST_BACK,
        cb_close=CB_DIGEST_CLOSE,
        screen_text=digest_settings_screen_text,
        days_screen_text=digest_days_screen_text,
        time_screen_text=digest_time_screen_text,
        time_applied_text=digest_time_applied_text,
        time_invalid_text=DIGEST_TIME_INVALID_TEXT,
        settings_closed_text=DIGEST_SETTINGS_CLOSED_TEXT,
        days_weekdays_applied=DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
        days_all_applied=DIGEST_DAYS_ALL_APPLIED_TEXT,
        toggle_notice=digest_toggle_notice_text,
        build_settings_keyboard=build_digest_settings_keyboard,
        build_days_keyboard=build_digest_days_keyboard,
        build_time_keyboard=build_digest_time_keyboard,
    ),
    DIGEST_KIND_PENDING: DigestKindBindings(
        kind=DIGEST_KIND_PENDING,
        enabled_field="pending_digest_enabled",
        days_field="pending_digest_days",
        time_field="pending_digest_time",
        update_enabled_kw="pending_digest_enabled",
        update_days_kw="pending_digest_days",
        update_time_kw="pending_digest_time",
        cb_settings=CB_PENDING_DIGEST_SETTINGS,
        cb_toggle=CB_PENDING_DIGEST_TOGGLE,
        cb_days=CB_PENDING_DIGEST_DAYS,
        cb_days_weekdays=CB_PENDING_DIGEST_DAYS_WEEKDAYS,
        cb_days_all=CB_PENDING_DIGEST_DAYS_ALL,
        cb_time=CB_PENDING_DIGEST_TIME,
        cb_back=CB_PENDING_DIGEST_BACK,
        cb_close=CB_PENDING_DIGEST_CLOSE,
        screen_text=pending_digest_settings_screen_text,
        days_screen_text=pending_digest_days_screen_text,
        time_screen_text=pending_digest_time_screen_text,
        time_applied_text=pending_digest_time_applied_text,
        time_invalid_text=PENDING_DIGEST_TIME_INVALID_TEXT,
        settings_closed_text=PENDING_DIGEST_SETTINGS_CLOSED_TEXT,
        days_weekdays_applied=PENDING_DIGEST_DAYS_WEEKDAYS_APPLIED_TEXT,
        days_all_applied=PENDING_DIGEST_DAYS_ALL_APPLIED_TEXT,
        toggle_notice=pending_digest_toggle_notice_text,
        build_settings_keyboard=build_pending_digest_settings_keyboard,
        build_days_keyboard=build_pending_digest_days_keyboard,
        build_time_keyboard=build_pending_digest_time_keyboard,
    ),
}


def _bindings(kind: DigestKind) -> DigestKindBindings:
    return _BINDINGS[kind]


def _digest_settings_bundle(
    settings: DigestSettings,
    bindings: DigestKindBindings,
    *,
    kind: DigestKind,
    keyboard: dict,
    weather_in_plan_enabled: bool = True,
) -> ScreenBundle:
    if kind == DIGEST_KIND_DAILY:
        return digest_settings_bundle(
            digest_enabled=_enabled(settings, bindings),
            digest_days=_days(settings, bindings),
            digest_time=_time(settings, bindings),
            weather_in_plan_enabled=weather_in_plan_enabled,
            reply_markup=keyboard,
        )
    return pending_digest_settings_bundle(
        digest_enabled=_enabled(settings, bindings),
        digest_days=_days(settings, bindings),
        digest_time=_time(settings, bindings),
        reply_markup=keyboard,
    )


def _digest_days_bundle(
    digest_days: str,
    bindings: DigestKindBindings,
    *,
    kind: DigestKind,
    keyboard: dict,
) -> ScreenBundle:
    if kind == DIGEST_KIND_DAILY:
        return digest_days_bundle(digest_days=digest_days, reply_markup=keyboard)
    return pending_digest_days_bundle(digest_days=digest_days, reply_markup=keyboard)


def _digest_time_bundle(digest_time: str, keyboard: dict) -> ScreenBundle:
    return digest_time_bundle(digest_time=digest_time, reply_markup=keyboard)


def _update_settings(
    ctx: HandlerContext,
    chat_id: int,
    username: str,
    *,
    telegram_user_id: int,
    bindings: DigestKindBindings,
    **kwargs: Any,
) -> DigestSettings:
    patch: dict[str, Any] = {}
    if "enabled" in kwargs:
        patch[bindings.update_enabled_kw] = kwargs["enabled"]
    if "days" in kwargs:
        patch[bindings.update_days_kw] = kwargs["days"]
    if "time" in kwargs:
        patch[bindings.update_time_kw] = kwargs["time"]
    return ctx.subscriptions.update_settings(
        chat_id,
        username,
        telegram_user_id=telegram_user_id,
        **patch,
    )
