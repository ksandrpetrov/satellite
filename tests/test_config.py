from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from satellite.config import (
    is_valid_webapp_base_url,
    load_settings,
    parse_bool_env,
    parse_digest_mode,
)


def test_parse_bool_env_truthy():
    assert parse_bool_env("yes", False) is True
    assert parse_bool_env("TRUE", False) is True
    assert parse_bool_env("1", False) is True
    assert parse_bool_env("on", False) is True


def test_parse_bool_env_falsy():
    assert parse_bool_env("no", True) is False
    assert parse_bool_env("FALSE", True) is False
    assert parse_bool_env("0", True) is False
    assert parse_bool_env("off", True) is False


def test_parse_bool_env_default():
    assert parse_bool_env(None, True) is True
    assert parse_bool_env("", True) is True
    assert parse_bool_env("maybe", True) is True
    assert parse_bool_env("maybe", False) is False


def test_digest_mode_from_env_file_overrides_process_env(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=token\n"
        "TOKEN_ENCRYPTION_KEY=key\n"
        "ADMIN_TELEGRAM_IDS=1\n"
        "WEBAPP_BASE_URL=https://example.com/connect\n"
        "DIGEST_MODE=today\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DIGEST_MODE", "day_after_tomorrow")
    settings = load_settings(env_path=env_file)
    assert settings.digest.mode == "today"


def test_parse_digest_mode():
    assert parse_digest_mode("today") == "today"
    assert parse_digest_mode("Tomorrow") == "tomorrow"
    assert parse_digest_mode("DAY_AFTER_TOMORROW") == "day_after_tomorrow"
    assert parse_digest_mode("garbage") == "today"
    assert parse_digest_mode(None) == "today"
    assert parse_digest_mode("") == "today"


def test_load_settings_weather_location_json(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'WEATHER_LOCATION={"name": "Сочи", "latitude": 43.6, "longitude": 39.7, "timezone": "Europe/Moscow"}\n'
        "WEATHER_ENABLED=true\n"
        "WEATHER_SHOW_NORMAL=true\n"
        "WEATHER_CACHE_TTL_MINUTES=45\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env_file)
    assert settings.weather.enabled is True
    assert settings.weather.location_name == "Сочи"
    assert abs(settings.weather.latitude - 43.6) < 1e-6
    assert settings.weather.show_normal_weather is True
    assert settings.weather.cache_ttl_minutes == 45


def test_load_settings_requires_bot_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("WEBAPP_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=token\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_settings(
            env_path=env_file,
            require_telegram=True,
            require_admin=True,
            require_webapp=True,
            require_encryption_key=True,
        )
    msg = str(exc_info.value)
    assert "TOKEN_ENCRYPTION_KEY" in msg
    assert "ADMIN_TELEGRAM_IDS" in msg
    assert "WEBAPP_BASE_URL" in msg


def test_load_settings_rejects_username_as_admin_id(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("WEBAPP_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=1:abc\n"
        "TOKEN_ENCRYPTION_KEY=key\n"
        "ADMIN_TELEGRAM_IDS=aleksanderpetrov\n"
        "WEBAPP_BASE_URL=https://example.com/connect\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc_info:
        load_settings(
            env_path=env_file,
            require_telegram=True,
            require_admin=True,
            require_webapp=True,
            require_encryption_key=True,
        )
    assert "не @username" in str(exc_info.value)


def test_is_valid_webapp_base_url():
    assert is_valid_webapp_base_url("https://cassinilab.ru/connect")
    assert not is_valid_webapp_base_url("satellite/web/static/connect.html")
    assert not is_valid_webapp_base_url("http://cassinilab.ru/connect")
    assert not is_valid_webapp_base_url("https://cassinilab.ru/static/connect.html")


def test_load_settings_rejects_invalid_webapp_url(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WEBAPP_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=1:abc\n"
        "TOKEN_ENCRYPTION_KEY=key\n"
        "ADMIN_TELEGRAM_IDS=1\n"
        "WEBAPP_BASE_URL=satellite/web/static/connect.html\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc_info:
        load_settings(
            env_path=env_file,
            require_telegram=True,
            require_admin=True,
            require_webapp=True,
            require_encryption_key=True,
        )
    assert "WEBAPP_BASE_URL" in str(exc_info.value)
    assert "connect.html" in str(exc_info.value)


def test_load_settings_rejects_placeholder_bot_token(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("WEBAPP_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=123456:your-bot-token\n"
        "TOKEN_ENCRYPTION_KEY=key\n"
        "ADMIN_TELEGRAM_IDS=1\n"
        "WEBAPP_BASE_URL=https://example.com/connect\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc_info:
        load_settings(
            env_path=env_file,
            require_telegram=True,
            require_admin=True,
            require_webapp=True,
            require_encryption_key=True,
        )
    assert "BotFather" in str(exc_info.value)


def test_load_settings_webapp_host_defaults(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WEBAPP_HOST", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=1:abc\n"
        f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n"
        "ADMIN_TELEGRAM_IDS=1\n"
        "WEBAPP_BASE_URL=https://example.com/connect\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env_file)
    assert settings.webapp.host == "127.0.0.1"


def test_load_settings_webapp_host_0_0_0_0(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WEBAPP_HOST", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=1:abc\n"
        f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n" + "\n"
        "ADMIN_TELEGRAM_IDS=1\n"
        "WEBAPP_BASE_URL=https://example.com/connect\n"
        "WEBAPP_HOST=0.0.0.0\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env_file)
    assert settings.webapp.host == "0.0.0.0"


def test_load_settings_caldav_cache_ttl_sec(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=1:abc\nCALDAV_CACHE_TTL_SEC=120\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env_file)
    assert settings.bot.caldav_cache_ttl_sec == 120


def test_load_settings_hide_all_day_and_lunch_flags(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HIDE_ALL_DAY_EVENTS=false\nHIDE_LUNCH_EVENTS=0\n",
        encoding="utf-8",
    )
    settings = load_settings(env_path=env_file)
    assert settings.plan.hide_all_day_events is False
    assert settings.plan.hide_lunch_events is False
