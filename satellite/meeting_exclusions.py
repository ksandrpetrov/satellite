"""Зашифрованные персональные исключения названий встреч."""

from __future__ import annotations

import threading

from .calendar.event_exclusions import (
    EventExclusionPolicy,
    EventTitleOverride,
    normalize_event_title,
)
from .security.token_vault import (
    EventTitleOverridePayload,
    EventTitleOverridesPayload,
    TokenDecryptError,
    TokenVault,
)
from .users import UserStore

MAX_EVENT_TITLE_OVERRIDES = 50


class MeetingExclusionLimitError(ValueError):
    """Достигнут лимит явных пользовательских правил."""


class MeetingExclusionService:
    """Читает и атомарно сохраняет политику исключений пользователя."""

    def __init__(
        self,
        users: UserStore,
        token_vault: TokenVault,
        *,
        exclude_meals_by_default: bool = True,
    ) -> None:
        self._users = users
        self._token_vault = token_vault
        self._exclude_meals_by_default = exclude_meals_by_default
        self._lock = threading.Lock()

    def policy_for_user(self, user_id: int) -> EventExclusionPolicy:
        return EventExclusionPolicy(
            self.list_overrides(user_id),
            exclude_meals_by_default=self._exclude_meals_by_default,
        )

    def list_overrides(self, user_id: int) -> tuple[EventTitleOverride, ...]:
        record = self._users.get(user_id)
        if record is None:
            raise KeyError(user_id)
        blob = record.encrypted_event_title_overrides
        if blob is None:
            return ()
        payload = self._token_vault.decrypt_event_title_overrides(blob)
        overrides = tuple(
            EventTitleOverride(title=item.title, excluded=item.excluded)
            for item in payload.overrides
        )
        self._validate_stored_overrides(overrides)
        return overrides

    def toggle_title(self, user_id: int, title: str) -> bool:
        display_title = _validated_display_title(title)
        normalized_title = normalize_event_title(display_title)
        with self._lock:
            overrides = list(self.list_overrides(user_id))
            policy = EventExclusionPolicy(
                tuple(overrides),
                exclude_meals_by_default=self._exclude_meals_by_default,
            )
            new_excluded = not policy.is_excluded(display_title)
            default_excluded = policy.default_is_excluded(display_title)
            matching_index = _find_override_index(overrides, normalized_title)

            if new_excluded == default_excluded:
                if matching_index is not None:
                    overrides.pop(matching_index)
            elif matching_index is None:
                if len(overrides) >= MAX_EVENT_TITLE_OVERRIDES:
                    raise MeetingExclusionLimitError(
                        f"At most {MAX_EVENT_TITLE_OVERRIDES} meeting title overrides are allowed"
                    )
                overrides.append(EventTitleOverride(title=display_title, excluded=new_excluded))
            else:
                overrides[matching_index] = EventTitleOverride(
                    title=display_title,
                    excluded=new_excluded,
                )

            self._save(user_id, overrides)
            return new_excluded

    def reset_title(self, user_id: int, title: str) -> None:
        normalized_title = normalize_event_title(_validated_display_title(title))
        with self._lock:
            overrides = list(self.list_overrides(user_id))
            matching_index = _find_override_index(overrides, normalized_title)
            if matching_index is None:
                return
            overrides.pop(matching_index)
            self._save(user_id, overrides)

    def clear(self, user_id: int) -> None:
        with self._lock:
            record = self._users.get(user_id)
            if record is None:
                raise KeyError(user_id)
            self._users.set_encrypted_event_title_overrides(user_id, blob=None)

    def _save(self, user_id: int, overrides: list[EventTitleOverride]) -> None:
        if not overrides:
            self._users.set_encrypted_event_title_overrides(user_id, blob=None)
            return
        payload = EventTitleOverridesPayload(
            overrides=tuple(
                EventTitleOverridePayload(title=item.title, excluded=item.excluded)
                for item in overrides
            )
        )
        blob = self._token_vault.encrypt_event_title_overrides(payload)
        self._users.set_encrypted_event_title_overrides(user_id, blob=blob)

    @staticmethod
    def _validate_stored_overrides(overrides: tuple[EventTitleOverride, ...]) -> None:
        if len(overrides) > MAX_EVENT_TITLE_OVERRIDES:
            raise TokenDecryptError("Decrypted event-title override payload exceeds the limit.")
        seen: set[str] = set()
        for override in overrides:
            normalized = normalize_event_title(override.title)
            if not normalized or normalized in seen:
                raise TokenDecryptError("Decrypted event-title override payload is invalid.")
            seen.add(normalized)


def _validated_display_title(title: str) -> str:
    display_title = str(title or "").strip()
    if not normalize_event_title(display_title):
        raise ValueError("Meeting title must not be blank")
    return display_title


def _find_override_index(
    overrides: list[EventTitleOverride],
    normalized_title: str,
) -> int | None:
    for index, override in enumerate(overrides):
        if normalize_event_title(override.title) == normalized_title:
            return index
    return None


__all__ = [
    "MAX_EVENT_TITLE_OVERRIDES",
    "MeetingExclusionLimitError",
    "MeetingExclusionService",
]
