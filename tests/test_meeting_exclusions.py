from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from satellite.calendar.event_exclusions import (
    EventExclusionPolicy,
    EventTitleOverride,
    default_is_excluded,
    normalize_event_title,
)
from satellite.meeting_exclusions import (
    MAX_EVENT_TITLE_OVERRIDES,
    MeetingExclusionLimitError,
    MeetingExclusionService,
)
from satellite.security.token_vault import (
    EventTitleOverridePayload,
    EventTitleOverridesPayload,
    TokenDecryptError,
    TokenVault,
)
from satellite.users import UserStore, UserStoreLoadError

USER_ID = 42


def _create_users(path: Path) -> UserStore:
    users = UserStore(path)
    users.upsert_from_telegram(
        telegram_user_id=USER_ID,
        chat_id=USER_ID,
        username="alice",
        display_name="Alice",
        default_status="approved",
    )
    return users


def _vault() -> TokenVault:
    return TokenVault(Fernet.generate_key().decode("ascii"))


def test_event_title_normalization_and_exact_override() -> None:
    assert normalize_event_title("  Weekly \n Sync  ") == "weekly sync"
    policy = EventExclusionPolicy((EventTitleOverride(title="Weekly Sync", excluded=True),))

    assert policy.is_excluded(" weekly   SYNC ")
    assert not policy.is_excluded("Weekly Sync Extended")
    assert not policy.is_excluded("")


@pytest.mark.parametrize(
    "title",
    [
        "🍕 Обед",
        "🍕 ЗАВТРАК команды",
        "Ужин 🍕",
        "Focus time",
        "День без встреч",
    ],
)
def test_builtin_titles_are_excluded_by_default(title: str) -> None:
    assert default_is_excluded(title)
    assert EventExclusionPolicy().is_excluded(title)


def test_meals_can_be_visible_by_default_without_disabling_system_phrases() -> None:
    policy = EventExclusionPolicy(exclude_meals_by_default=False)

    assert not policy.is_excluded("🍕 Обед")
    assert policy.is_excluded("Focus time")


def test_explicit_include_overrides_builtin_title() -> None:
    policy = EventExclusionPolicy((EventTitleOverride(title="Focus time", excluded=False),))

    assert policy.default_is_excluded("FOCUS TIME")
    assert not policy.is_excluded(" focus  time ")


def test_vault_event_title_overrides_round_trip() -> None:
    vault = _vault()
    payload = EventTitleOverridesPayload(
        overrides=(
            EventTitleOverridePayload(title="Weekly sync", excluded=True),
            EventTitleOverridePayload(title="🍕 Обед", excluded=False),
        )
    )

    restored = vault.decrypt_event_title_overrides(vault.encrypt_event_title_overrides(payload))

    assert restored == payload


def test_vault_rejects_invalid_event_title_override_payload() -> None:
    key = Fernet.generate_key()
    blob = Fernet(key).encrypt(b'{"version": 1, "overrides": [{}]}').decode("ascii")

    with pytest.raises(TokenDecryptError):
        TokenVault(key.decode("ascii")).decrypt_event_title_overrides(blob)


def test_users_store_rejects_non_string_encrypted_override_blob(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps({"42": {"encrypted_event_title_overrides": {"unexpected": "object"}}}),
        encoding="utf-8",
    )

    with pytest.raises(
        UserStoreLoadError,
        match="encrypted_event_title_overrides must be a string or null",
    ):
        UserStore(path)


def test_service_toggles_exact_title_and_never_persists_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    users = _create_users(path)
    vault = _vault()
    service = MeetingExclusionService(users, vault)

    assert service.toggle_title(USER_ID, "Weekly Sync")
    assert service.list_overrides(USER_ID) == (
        EventTitleOverride(title="Weekly Sync", excluded=True),
    )
    raw = path.read_text(encoding="utf-8")
    assert "Weekly Sync" not in raw
    assert json.loads(raw)[str(USER_ID)]["encrypted_event_title_overrides"]

    reloaded = MeetingExclusionService(UserStore(path), vault)
    assert reloaded.policy_for_user(USER_ID).is_excluded(" weekly   SYNC ")
    assert not reloaded.toggle_title(USER_ID, "weekly sync")
    assert reloaded.list_overrides(USER_ID) == ()
    assert UserStore(path).get(USER_ID).encrypted_event_title_overrides is None


def test_service_can_include_builtin_and_reset_to_default(tmp_path: Path) -> None:
    users = _create_users(tmp_path / "users.json")
    service = MeetingExclusionService(users, _vault())

    assert not service.toggle_title(USER_ID, "🍕 Обед")
    assert service.list_overrides(USER_ID) == (EventTitleOverride(title="🍕 Обед", excluded=False),)
    assert not service.policy_for_user(USER_ID).is_excluded("🍕 обед")

    assert service.toggle_title(USER_ID, "🍕 ОБЕД")
    assert service.list_overrides(USER_ID) == ()
    assert service.policy_for_user(USER_ID).is_excluded("🍕 Обед")


def test_reset_and_clear_remove_explicit_overrides(tmp_path: Path) -> None:
    users = _create_users(tmp_path / "users.json")
    service = MeetingExclusionService(users, _vault())
    service.toggle_title(USER_ID, "First")
    service.toggle_title(USER_ID, "Second")

    service.reset_title(USER_ID, " first ")
    assert service.list_overrides(USER_ID) == (EventTitleOverride(title="Second", excluded=True),)

    service.clear(USER_ID)
    assert service.list_overrides(USER_ID) == ()


def test_blank_title_is_rejected(tmp_path: Path) -> None:
    service = MeetingExclusionService(
        _create_users(tmp_path / "users.json"),
        _vault(),
    )

    with pytest.raises(ValueError, match="blank"):
        service.toggle_title(USER_ID, " \n ")
    with pytest.raises(ValueError, match="blank"):
        service.reset_title(USER_ID, "")


def test_service_enforces_override_limit(tmp_path: Path) -> None:
    users = _create_users(tmp_path / "users.json")
    vault = _vault()
    payload = EventTitleOverridesPayload(
        overrides=tuple(
            EventTitleOverridePayload(title=f"Meeting {index}", excluded=True)
            for index in range(MAX_EVENT_TITLE_OVERRIDES)
        )
    )
    users.set_encrypted_event_title_overrides(
        USER_ID,
        blob=vault.encrypt_event_title_overrides(payload),
    )
    service = MeetingExclusionService(users, vault)

    with pytest.raises(MeetingExclusionLimitError):
        service.toggle_title(USER_ID, "One too many")


def test_service_propagates_corrupt_blob_as_token_error(tmp_path: Path) -> None:
    users = _create_users(tmp_path / "users.json")
    users.set_encrypted_event_title_overrides(USER_ID, blob="not-fernet")

    with pytest.raises(TokenDecryptError):
        MeetingExclusionService(users, _vault()).list_overrides(USER_ID)


def test_user_record_legacy_json_defaults_to_no_override_blob(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    path.write_text(json.dumps({str(USER_ID): {"status": "approved"}}), encoding="utf-8")

    record = UserStore(path).get(USER_ID)

    assert record is not None
    assert record.encrypted_event_title_overrides is None


def test_override_blob_survives_calendar_disconnect_and_block(tmp_path: Path) -> None:
    users = _create_users(tmp_path / "users.json")
    users.set_encrypted_event_title_overrides(USER_ID, blob="encrypted-preference")
    users.set_calendar_connection(
        USER_ID,
        provider="mailru",
        encrypted_credentials="encrypted-credentials",
        primary_calendar_url="https://calendar.example/",
    )

    disconnected = users.clear_calendar_connection(USER_ID)
    assert disconnected.encrypted_event_title_overrides == "encrypted-preference"

    blocked = users.block(USER_ID, admin_telegram_id=100)
    assert blocked.encrypted_event_title_overrides == "encrypted-preference"


def test_override_blob_setter_is_noop_aware(tmp_path: Path) -> None:
    users = _create_users(tmp_path / "users.json")
    first = users.set_encrypted_event_title_overrides(USER_ID, blob="blob")
    persist = MagicMock()
    users._persist_payload = persist

    unchanged = users.set_encrypted_event_title_overrides(USER_ID, blob="blob")

    assert unchanged is first
    persist.assert_not_called()
