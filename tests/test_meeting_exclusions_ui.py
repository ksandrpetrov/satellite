"""Настройки исключений встреч: экран недели и callback-действия."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from satellite.calendar.event_exclusions import EventExclusionPolicy, EventTitleOverride
from satellite.calendar.providers.base import CalendarProviderError
from satellite.messages_ru import (
    CB_SETTINGS_MEETING_EXCLUSIONS,
    MEETING_EXCLUSIONS_CALENDAR_ERROR_TEXT,
    MEETING_EXCLUSIONS_SAVE_ERROR_TEXT,
    MEETING_EXCLUSIONS_STALE_TEXT,
    MEX_CALLBACK_CLEAR,
    MEX_CALLBACK_PAGE_PREFIX,
    MEX_CALLBACK_RESET_PREFIX,
    MEX_CALLBACK_TOGGLE_PREFIX,
)
from satellite.telegram_bot.handlers import handle_callback_query
from satellite.telegram_bot.handlers.dispatch import _CALLBACK_ROUTERS
from satellite.telegram_bot.handlers.meeting_exclusions import (
    reset_meeting_exclusion_cache,
    route_meeting_exclusions_callback,
)
from satellite.testing.delivery_helpers import (
    callback_edit_html,
    callback_edit_markup,
    sent_messages_text,
)
from satellite.users import UserStorePersistenceError
from tests.conftest import make_callback, make_ctx, make_user_store

_USER_ID = 1


def _key(title: str) -> str:
    return " ".join(title.split()).casefold()


class _FakeMeetingExclusions:
    def __init__(self, overrides: tuple[EventTitleOverride, ...] = ()) -> None:
        self.overrides = {_key(item.title): item for item in overrides}

    def policy_for_user(self, _user_id: int) -> EventExclusionPolicy:
        return EventExclusionPolicy(tuple(self.overrides.values()))

    def list_overrides(self, _user_id: int) -> tuple[EventTitleOverride, ...]:
        return tuple(self.overrides.values())

    def toggle_title(self, _user_id: int, title: str) -> bool:
        policy = self.policy_for_user(_user_id)
        excluded = not policy.is_excluded(title)
        if excluded == policy.default_is_excluded(title):
            self.overrides.pop(_key(title), None)
        else:
            self.overrides[_key(title)] = EventTitleOverride(title=title, excluded=excluded)
        return excluded

    def reset_title(self, _user_id: int, title: str) -> None:
        self.overrides.pop(_key(title), None)

    def clear(self, _user_id: int) -> None:
        self.overrides.clear()


def _event(
    title: str,
    *,
    ctx,
    day: int = 0,
    hour: int = 10,
    **extra,
) -> dict:
    today = datetime.now(tz=ctx.tz).date()
    start = datetime.combine(today + timedelta(days=day), time(hour), tzinfo=ctx.tz)
    return {
        "summary": title,
        "dtstart": start.isoformat(),
        "dtend": (start + timedelta(minutes=30)).isoformat(),
        **extra,
    }


def _make_ui_ctx(tmp_path, *, events=(), overrides=()):
    users = make_user_store(tmp_path, approved_with_calendar=[_USER_ID])
    calendar = MagicMock()
    calendar.require_connection.return_value = SimpleNamespace(
        context=SimpleNamespace(login="me@example.com"),
        record=users.get(_USER_ID),
    )
    calendar.list_events.return_value = list(events)
    ctx = make_ctx(users, calendar_service=calendar)
    ctx.meeting_exclusions = _FakeMeetingExclusions(tuple(overrides))
    return ctx


def _flat_buttons(ctx) -> list[dict]:
    markup = callback_edit_markup(ctx.telegram)
    return [button for row in markup["inline_keyboard"] for button in row]


def _button(ctx, *, callback_prefix: str, text_contains: str | None = None) -> dict:
    for button in _flat_buttons(ctx):
        callback = button.get("callback_data", "")
        if callback.startswith(callback_prefix) and (
            text_contains is None or text_contains in button["text"]
        ):
            return button
    raise AssertionError(f"button not found: prefix={callback_prefix!r}")


def test_open_screen_lists_unique_timed_week_events_and_builtin_states(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    ctx.calendar_service.list_events.return_value = [
        _event("Дейли", ctx=ctx, hour=11),
        _event("  ДЕЙЛИ  ", ctx=ctx, hour=12),
        _event("🍕 Обед", ctx=ctx, hour=13),
        _event("Focus time", ctx=ctx, hour=14),
        _event("Отменена", ctx=ctx, hour=15, status="CANCELLED"),
        _event(
            "Отклонена",
            ctx=ctx,
            hour=16,
            attendees=["mailto:me@example.com;PARTSTAT=DECLINED"],
        ),
        {
            "summary": "Весь день",
            "dtstart": datetime.now(tz=ctx.tz).date().isoformat(),
            "dtend": (datetime.now(tz=ctx.tz).date() + timedelta(days=1)).isoformat(),
        },
        _event("За пределами", ctx=ctx, day=7),
    ]

    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )

    assert "Исключения встреч" in callback_edit_html(ctx.telegram)
    labels = [button["text"] for button in _flat_buttons(ctx)]
    assert sum("Дейли" in label for label in labels) == 1
    assert "🚫 🍕 Обед" in labels
    assert "🚫 Focus time" in labels
    assert "✅ Дейли" in labels
    assert not any("Отменена" in label for label in labels)
    assert not any("Отклонена" in label for label in labels)
    assert not any("Весь день" in label for label in labels)
    assert not any("За пределами" in label for label in labels)
    assert all(len(button.get("callback_data", "").encode()) <= 64 for button in _flat_buttons(ctx))
    list_call = ctx.calendar_service.list_events.call_args
    assert list_call.kwargs["end_date"] - list_call.kwargs["start_date"] == timedelta(days=7)
    assert list_call.kwargs["calendar_urls"]


def test_tap_toggles_candidate_without_refetching_calendar(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    ctx.calendar_service.list_events.return_value = [_event("Дейли", ctx=ctx)]
    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )
    toggle = _button(ctx, callback_prefix=MEX_CALLBACK_TOGGLE_PREFIX)

    handle_callback_query(
        ctx,
        make_callback(data=toggle["callback_data"], user_id=_USER_ID),
    )

    assert ctx.calendar_service.list_events.call_count == 1
    assert _key("Дейли") in ctx.meeting_exclusions.overrides
    assert "🚫 Дейли" in [button["text"] for button in _flat_buttons(ctx)]


def test_saved_override_outside_week_has_reset_action(tmp_path):
    override = EventTitleOverride(title="Старый статус", excluded=True)
    ctx = _make_ui_ctx(tmp_path, overrides=(override,))
    ctx.calendar_service.list_events.return_value = [_event("Дейли", ctx=ctx)]
    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )
    reset = _button(
        ctx,
        callback_prefix=MEX_CALLBACK_RESET_PREFIX,
        text_contains="Старый статус",
    )
    assert reset["text"].startswith("↩️ 🚫")

    handle_callback_query(
        ctx,
        make_callback(data=reset["callback_data"], user_id=_USER_ID),
    )

    assert not ctx.meeting_exclusions.overrides
    assert not any("Старый статус" in button["text"] for button in _flat_buttons(ctx))


def test_clear_removes_all_explicit_overrides(tmp_path):
    ctx = _make_ui_ctx(
        tmp_path,
        overrides=(
            EventTitleOverride(title="Первое", excluded=True),
            EventTitleOverride(title="Второе", excluded=True),
        ),
    )
    ctx.calendar_service.list_events.return_value = [_event("Дейли", ctx=ctx)]
    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )

    handle_callback_query(
        ctx,
        make_callback(data=MEX_CALLBACK_CLEAR, user_id=_USER_ID),
    )

    assert not ctx.meeting_exclusions.overrides
    assert not any(
        button.get("callback_data") == MEX_CALLBACK_CLEAR for button in _flat_buttons(ctx)
    )


def test_pagination_uses_cached_snapshot(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    ctx.calendar_service.list_events.return_value = [
        _event(f"Встреча {index}", ctx=ctx, hour=8 + index) for index in range(10)
    ]
    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )
    next_page = _button(ctx, callback_prefix=MEX_CALLBACK_PAGE_PREFIX, text_contains="→")

    handle_callback_query(
        ctx,
        make_callback(data=next_page["callback_data"], user_id=_USER_ID),
    )

    assert "Страница 2 из 2" in callback_edit_html(ctx.telegram)
    assert ctx.calendar_service.list_events.call_count == 1


def test_provider_failure_shows_safe_screen(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    ctx.calendar_service.list_events.side_effect = CalendarProviderError(
        "secret provider details",
        error_code="DOWN",
    )

    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )

    html = callback_edit_html(ctx.telegram)
    assert MEETING_EXCLUSIONS_CALENDAR_ERROR_TEXT in html
    assert "secret provider details" not in html


def test_stale_snapshot_store_failure_replaces_loading_with_safe_error(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    ctx.calendar_service.list_events.return_value = [_event("Дейли", ctx=ctx)]
    handle_callback_query(
        ctx,
        make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID),
    )
    toggle = _button(ctx, callback_prefix=MEX_CALLBACK_TOGGLE_PREFIX)
    reset_meeting_exclusion_cache(_USER_ID)
    ctx.telegram.answer_callback_query.reset_mock()
    ctx.meeting_exclusions.toggle_title = MagicMock(
        side_effect=UserStorePersistenceError("disk failed")
    )

    handle_callback_query(
        ctx,
        make_callback(data=toggle["callback_data"], user_id=_USER_ID),
    )

    assert MEETING_EXCLUSIONS_SAVE_ERROR_TEXT in callback_edit_html(ctx.telegram)
    assert ctx.telegram.answer_callback_query.call_count == 1


def test_stale_token_refetches_once_and_shows_safe_message(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    ctx.calendar_service.list_events.return_value = [_event("Дейли", ctx=ctx)]
    stale_callback = f"{MEX_CALLBACK_TOGGLE_PREFIX}{'0' * 32}:0"

    claimed = route_meeting_exclusions_callback(
        ctx,
        make_callback(data=stale_callback, user_id=_USER_ID),
    )

    assert claimed is True
    assert ctx.calendar_service.list_events.call_count == 1
    assert MEETING_EXCLUSIONS_STALE_TEXT in sent_messages_text(ctx.telegram)


def test_navigation_and_actions_have_explicit_callback_owners(tmp_path):
    ctx = _make_ui_ctx(tmp_path)
    settings_cb = make_callback(data=CB_SETTINGS_MEETING_EXCLUSIONS, user_id=_USER_ID)
    mex_cb = make_callback(data=f"{MEX_CALLBACK_PAGE_PREFIX}0", user_id=_USER_ID)

    assert any(router(ctx, settings_cb) for router in _CALLBACK_ROUTERS)
    assert any(router(ctx, mex_cb) for router in _CALLBACK_ROUTERS)
