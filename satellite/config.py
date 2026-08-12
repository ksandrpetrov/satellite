"""Загрузка и валидация настроек приложения из переменных окружения / .env.

Архитектура авторизации (после миграции на per-user calendar auth):

- Глобальные Mail.ru-credentials удалены: ``MAIL_LOGIN`` / ``MAIL_APP_PASSWORD``
  / ``USER_CALENDAR_MAP`` больше не читаются. Каждый пользователь хранит
  свой токен в ``logs/users.json`` (см. ``satellite.users``).
- Обязательные env: ``TELEGRAM_BOT_TOKEN``, ``TOKEN_ENCRYPTION_KEY``,
  ``ADMIN_TELEGRAM_IDS``, ``WEBAPP_BASE_URL`` (для кнопки Telegram Web App).
- Расположение Web App localhost-сервера управляется ``WEBAPP_HOST`` /
  ``WEBAPP_PORT``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv

from .users import parse_admin_ids
from .weather.models import WeatherConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_HIDE_ALL_DAY_EVENTS = True
DEFAULT_HIDE_LUNCH_EVENTS = True
DEFAULT_TZ = "Europe/Moscow"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_BOT_WORKERS = 4
DEFAULT_BOT_LONG_POLL_SEC = 30
DEFAULT_CALDAV_CACHE_TTL_SEC = 300
DEFAULT_DIGEST_MODE = (
    "today"  # today | tomorrow | day_after_tomorrow (legacy env; scheduler uses today)
)
ALLOWED_DIGEST_MODES = frozenset({"today", "tomorrow", "day_after_tomorrow"})
DEFAULT_WEATHER_CACHE_TTL_MINUTES = 30

DEFAULT_WEBAPP_HOST = "127.0.0.1"
DEFAULT_WEBAPP_PORT = 8080

# Значения-заглушки из .env.example — при require_* считаются «не настроено».
PLACEHOLDER_TELEGRAM_BOT_TOKEN = "123456:your-bot-token"
PLACEHOLDER_WEBAPP_BASE_URL = "https://your-domain.example/connect"
DEFAULT_WEBAPP_BASE_URL = "https://cassinilab.ru/connect"


def is_valid_webapp_base_url(url: str) -> bool:
    """Публичный HTTPS URL для кнопки Web App, не путь к файлу в репозитории."""
    normalized = url.strip()
    if not normalized.startswith("https://"):
        return False
    lowered = normalized.lower()
    if "connect.html" in lowered or "/static/" in lowered or "satellite/web/" in lowered:
        return False
    return True


def default_weather_config() -> WeatherConfig:
    """Значения по умолчанию (погода выключена; координаты только для .env).

    ``show_normal_weather=True``: если включить ``WEATHER_ENABLED`` без
    ``WEATHER_SHOW_NORMAL``, в дайджесте всё равно будет строка про спокойный
    день — иначе при «ровной» погоде блок пропадает, хотя запрос к API уже сделан.
    """
    return WeatherConfig(
        enabled=False,
        location_name="Москва",
        latitude=55.7558,
        longitude=37.6173,
        timezone="Europe/Moscow",
        cache_ttl_minutes=DEFAULT_WEATHER_CACHE_TTL_MINUTES,
        show_normal_weather=True,
    )


def parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _parse_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def parse_digest_mode(value: str | None, default: str = DEFAULT_DIGEST_MODE) -> str:
    raw = (value or "").strip().lower()
    if raw in ALLOWED_DIGEST_MODES:
        return raw
    return default


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str


@dataclass(frozen=True)
class PlanConfig:
    hide_all_day_events: bool = DEFAULT_HIDE_ALL_DAY_EVENTS
    hide_lunch_events: bool = DEFAULT_HIDE_LUNCH_EVENTS  # 🍕 + завтрак|обед|ужин
    tz_name: str = DEFAULT_TZ


@dataclass(frozen=True)
class BotConfig:
    workers: int = DEFAULT_BOT_WORKERS
    long_poll_timeout_sec: int = DEFAULT_BOT_LONG_POLL_SEC
    caldav_cache_ttl_sec: int = DEFAULT_CALDAV_CACHE_TTL_SEC


@dataclass(frozen=True)
class DigestConfig:
    """Глобальные параметры дайджеста (legacy).

    Время и дни недели — в ``SubscriptionStore``. Авто-дайджест плана всегда
    на сегодня (см. ``DigestScheduler._deliver_daily``); ``mode`` из env
    оставлен для совместимости и логов.
    """

    mode: str = DEFAULT_DIGEST_MODE  # today | tomorrow | day_after_tomorrow


@dataclass(frozen=True)
class SecurityConfig:
    """Криптография для пользовательских токенов."""

    encryption_key: str


@dataclass(frozen=True)
class AdminConfig:
    """Список Telegram id админов, которые могут одобрять заявки."""

    telegram_ids: tuple[int, ...] = ()

    def is_admin(self, telegram_user_id: int | None) -> bool:
        if telegram_user_id is None:
            return False
        return int(telegram_user_id) in self.telegram_ids


@dataclass(frozen=True)
class WebAppConfig:
    """Параметры встроенного HTTP-сервера для Telegram Web App.

    ``base_url`` — публичный HTTPS URL, который указывается в кнопке Web App
    Telegram-бота (reverse proxy → ``host:port``). Bind-адрес локального
    сервера держим на ``127.0.0.1``: путь к Telegram-клиенту идёт через
    публичный nginx/Cloudflare, прямой доступ к localhost-серверу из интернета
    не должен быть возможен.
    """

    host: str = DEFAULT_WEBAPP_HOST
    port: int = DEFAULT_WEBAPP_PORT
    base_url: str = ""


@dataclass(frozen=True)
class Settings:
    telegram: TelegramConfig
    plan: PlanConfig
    bot: BotConfig
    digest: DigestConfig
    security: SecurityConfig
    admin: AdminConfig
    webapp: WebAppConfig
    log_level: str = DEFAULT_LOG_LEVEL
    project_root: Path = PROJECT_ROOT
    env_path: Path = DEFAULT_ENV_PATH
    weather: WeatherConfig = field(default_factory=default_weather_config)


def _env_value_from_file(key: str, env_path: Path) -> str | None:
    """Значение из .env-файла (без записи в os.environ).

    Нужно для совместимых env-ключей (``DIGEST_MODE`` и соседние): значение из
    ``.env`` должно побеждать уже заданное окружение, потому что ``load_dotenv``
    по умолчанию не перезаписывает переменные процесса.
    """
    if not env_path.is_file():
        return None
    raw = dotenv_values(env_path).get(key)
    if raw is None:
        return None
    stripped = str(raw).strip()
    return stripped or None


def _load_digest_config(env_path: Path) -> DigestConfig:
    return DigestConfig(
        mode=parse_digest_mode(
            _env_value_from_file("DIGEST_MODE", env_path) or os.getenv("DIGEST_MODE"),
            DEFAULT_DIGEST_MODE,
        ),
    )


def _load_weather_config(env_path: Path) -> WeatherConfig:
    """WEATHER_ENABLED, WEATHER_LOCATION (JSON) или отдельные WEATHER_* переменные."""
    base = default_weather_config()

    def _w(key: str) -> str | None:
        raw = _env_value_from_file(key, env_path) or os.getenv(key)
        if raw is None:
            return None
        stripped = str(raw).strip()
        return stripped or None

    enabled = parse_bool_env(_w("WEATHER_ENABLED"), base.enabled)
    show_normal = parse_bool_env(_w("WEATHER_SHOW_NORMAL"), base.show_normal_weather)
    ttl = max(0, _parse_int(_w("WEATHER_CACHE_TTL_MINUTES"), base.cache_ttl_minutes))

    name = base.location_name
    lat = base.latitude
    lon = base.longitude
    tz_name = base.timezone

    loc_json = _w("WEATHER_LOCATION")
    if loc_json and loc_json.lstrip().startswith("{"):
        try:
            data = json.loads(loc_json)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            name = str(data.get("name", name)).strip() or name
            lat = float(data.get("latitude", lat))
            lon = float(data.get("longitude", lon))
            tz_name = str(data.get("timezone", tz_name)).strip() or tz_name
    else:
        if _w("WEATHER_LOCATION_NAME"):
            name = str(_w("WEATHER_LOCATION_NAME")).strip() or name
        lat = _parse_float(_w("WEATHER_LATITUDE"), lat)
        lon = _parse_float(_w("WEATHER_LONGITUDE"), lon)
        if _w("WEATHER_TIMEZONE"):
            tz_name = str(_w("WEATHER_TIMEZONE")).strip() or tz_name

    return WeatherConfig(
        enabled=enabled,
        location_name=name,
        latitude=lat,
        longitude=lon,
        timezone=tz_name,
        cache_ttl_minutes=ttl,
        show_normal_weather=show_normal,
    )


def assert_telegram_bot_token_valid(token: str) -> None:
    """Проверяет токен через Bot API ``getMe`` (сеть). Вызывать перед long-polling."""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )
        payload = resp.json()
    except requests.RequestException as exc:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN: не удалось вызвать getMe (сеть или таймаут). "
            "Проверьте интернет на сервере и токен от @BotFather."
        ) from exc
    if payload.get("ok"):
        return
    desc = payload.get("description") or resp.text[:200]
    raise ValueError(
        f"TELEGRAM_BOT_TOKEN: Telegram отклонил токен (getMe: {desc}). "
        "В @BotFather откройте бота → API Token, скопируйте целиком; в .env одна строка "
        "без кавычек: TELEGRAM_BOT_TOKEN=123456789:AAH..."
    )


def load_settings(
    *,
    env_path: Path | None = None,
    require_telegram: bool = False,
    require_admin: bool = False,
    require_webapp: bool = False,
    require_encryption_key: bool = False,
) -> Settings:
    """Читает .env, валидирует обязательные поля, возвращает иммутабельные настройки.

    ``require_*`` позволяет вызывающему коду требовать только то, что ему нужно;
    production-бот включает все четыре require_*, тесты обычно не включают ничего.
    """
    resolved_env_path = env_path or DEFAULT_ENV_PATH
    if resolved_env_path.is_file():
        load_dotenv(resolved_env_path)

    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    encryption_key = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    admin_ids_raw = os.getenv("ADMIN_TELEGRAM_IDS")
    admin_ids = parse_admin_ids(admin_ids_raw)
    webapp_host = (os.getenv("WEBAPP_HOST") or DEFAULT_WEBAPP_HOST).strip() or DEFAULT_WEBAPP_HOST
    webapp_port = max(1, _parse_int(os.getenv("WEBAPP_PORT"), DEFAULT_WEBAPP_PORT))
    webapp_base_url = (os.getenv("WEBAPP_BASE_URL") or "").strip()

    env_errors: list[str] = []
    if require_telegram and (
        not bot_token
        or bot_token == PLACEHOLDER_TELEGRAM_BOT_TOKEN
        or "your-bot-token" in bot_token
    ):
        env_errors.append(
            "TELEGRAM_BOT_TOKEN: укажите токен от @BotFather (формат 123456789:AAH...), "
            "не значение из .env.example"
        )
    if require_encryption_key and not encryption_key:
        env_errors.append(
            "TOKEN_ENCRYPTION_KEY: сгенерируйте Fernet-ключ (см. .env.example) "
            "или запустите scripts/install.sh"
        )
    if require_admin:
        if not admin_ids:
            raw = (admin_ids_raw or "").strip()
            if not raw:
                env_errors.append(
                    "ADMIN_TELEGRAM_IDS: укажите числовые Telegram user id через запятую "
                    "(узнать свой id: @userinfobot)"
                )
            else:
                env_errors.append(
                    f"ADMIN_TELEGRAM_IDS: нет ни одного числового id (значение {raw!r}). "
                    "Нужен user id (например 123456789), не @username"
                )
    if require_webapp and (
        not webapp_base_url
        or webapp_base_url == PLACEHOLDER_WEBAPP_BASE_URL
        or "your-domain.example" in webapp_base_url
        or "satellite.example.com" in webapp_base_url
        or not is_valid_webapp_base_url(webapp_base_url)
    ):
        env_errors.append(
            "WEBAPP_BASE_URL: укажите публичный HTTPS URL страницы подключения календаря "
            f"(например {DEFAULT_WEBAPP_BASE_URL}), не путь к connect.html в репозитории"
        )
    if env_errors:
        raise ValueError("Invalid .env:\n- " + "\n- ".join(env_errors))

    settings = Settings(
        telegram=TelegramConfig(bot_token=bot_token),
        plan=PlanConfig(
            hide_all_day_events=parse_bool_env(
                os.getenv("HIDE_ALL_DAY_EVENTS"), DEFAULT_HIDE_ALL_DAY_EVENTS
            ),
            hide_lunch_events=parse_bool_env(
                os.getenv("HIDE_LUNCH_EVENTS"), DEFAULT_HIDE_LUNCH_EVENTS
            ),
            tz_name=(os.getenv("TZ_NAME") or DEFAULT_TZ).strip() or DEFAULT_TZ,
        ),
        bot=BotConfig(
            workers=max(1, _parse_int(os.getenv("BOT_WORKERS"), DEFAULT_BOT_WORKERS)),
            long_poll_timeout_sec=max(
                1, _parse_int(os.getenv("BOT_LONG_POLL_SEC"), DEFAULT_BOT_LONG_POLL_SEC)
            ),
            caldav_cache_ttl_sec=max(
                0, _parse_int(os.getenv("CALDAV_CACHE_TTL_SEC"), DEFAULT_CALDAV_CACHE_TTL_SEC)
            ),
        ),
        digest=_load_digest_config(resolved_env_path),
        security=SecurityConfig(encryption_key=encryption_key),
        admin=AdminConfig(telegram_ids=admin_ids),
        webapp=WebAppConfig(
            host=webapp_host,
            port=webapp_port,
            base_url=webapp_base_url,
        ),
        log_level=(os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
        or DEFAULT_LOG_LEVEL,
        project_root=PROJECT_ROOT,
        env_path=resolved_env_path,
        weather=_load_weather_config(resolved_env_path),
    )

    return settings
