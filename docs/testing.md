# Тестирование

## Установка dev-зависимостей

Через bootstrap-скрипт (создаст venv, поставит prod + dev зависимости,
сгенерирует `.env` с Fernet-ключом, создаст `logs/`):

```bash
bash scripts/install.sh --dev
# или: make install-dev
```

Если venv уже существует:

```bash
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Полный прогон

```bash
python -m pytest
# или: make test
```

В CI (GitHub Actions, [`.github/workflows/test.yml`](../.github/workflows/test.yml)) —
три job'а на Python 3.11:

- **ruff** — `ruff check` и `ruff format --check` (блокирующий);
- **mypy** — `mypy satellite` (информативный, `continue-on-error: true`);
- **pytest** — `py_compile` всех модулей, затем `pytest -q`.

Перед коммитом локально: `make check` (= lint + typecheck + compile + test).

Отдельно при публикации GitHub Release собирается Docker-образ и пушится в GHCR
([`.github/workflows/release-docker.yml`](../.github/workflows/release-docker.yml);
образ на Python 3.12). Деплой образа — [deploy/README.md](../deploy/README.md).

Если проект временно перенесен, а venv содержит старые absolute shebang-пути,
можно использовать системный Python с пакетами из venv:

```bash
# подставьте версию Python из venv (в CI — 3.11)
PYTHONPATH=venv/lib/python3.11/site-packages python3 -m pytest
```

## Быстрые целевые прогоны

Scheduler и настройки:

```bash
python -m pytest tests/test_scheduler.py tests/test_digest_settings.py
```

Telegram helpers:

```bash
python -m pytest tests/test_handlers.py tests/test_message_editing.py
```

Calendar, plan service и digest:

```bash
python -m pytest tests/test_calendar_stats.py tests/test_normalize_caldav_event.py \
  tests/test_plan_service.py tests/test_events.py tests/test_calendar_invitations.py \
  tests/test_time_utils.py tests/test_seagull_render.py tests/test_seagull_digest.py \
  tests/test_seagull_rules.py
```

Config, storage, CalDAV helpers, Web App:

```bash
python -m pytest tests/test_config.py tests/test_subscriptions.py \
  tests/test_caldav_candidates.py tests/test_ical_parser.py \
  tests/test_web_server.py tests/test_init_data.py
```

Bot infrastructure:

```bash
python -m pytest tests/test_bot_commands.py tests/test_offset_store.py \
  tests/test_instance_lock.py tests/test_concurrency.py tests/test_telegram_api.py \
  tests/test_messages.py
```

Weather:

```bash
python -m pytest tests/test_weather.py
```

## Фикстуры

`tests/conftest.py` экспортирует `make_event(title, start, end, ...)` — сборку
`NormalizedEvent` из `HH:MM` для тестов метрик. Production-путь — только
`normalize_caldav_event`; в тестах CalDAV-словари не подаём в `calculate_day_stats`
напрямую.

## Что покрыто

**Users / security** (по мере появления тестов):

- `UserStore` — атомарная запись, статусы, заявки, `has_calendar`;
- `TokenVault` — encrypt/decrypt, неверный ключ;
- `parse_admin_ids`.

**Plan service** (`test_plan_service.py`):

- `PlanBuilder.build_text` — CalDAV → фильтр → рендер;
- функции `resolve_calendar_for_*` — legacy до полной миграции на `users.json`.

**Normalization** (`test_normalize_caldav_event.py`):

- `normalize_caldav_event` — CalDAV dict → `NormalizedEvent`.

**Calendar stats** (`test_calendar_stats.py`):

- busy/free, пересечения, обеденное окно, all-day, declined.

**Time utils** (`test_time_utils.py`):

- `parse_hhmm` / `normalize_hhmm_input` — гибкий ввод (`9:30`, `9 30` → `09:30`).

**Events / upcoming** (`test_events.py`, `test_calendar_foreign.py`):

- `format_upcoming_events_lines` — нумерация `1️⃣`… как в дайджесте.

**Invitations** (`test_calendar_invitations.py`, PARTSTAT в `test_events.py`,
`test_seagull_digest.py`, `test_caldav_candidates.py`):

- `is_pending_invitation_for_user`, `collect_pending_invitations`;
- роутинг `/invitations` и CalDAV `set_attendee_partstat` (mock provider).

**Calendar selection** (`test_calendar_selection.py`):

- `effective_enabled_calendar_urls` — пустой список → primary;
- `UserStore.set_enabled_calendar_urls`;
- inline-клавиатура источников, роутинг `/calendars`.

**Settings hub** (`test_digest_settings.py` и др.):

- переход «Дайджест» из хаба, закрытие хаба без лишних ошибок.

**Config** (`test_config.py`):

- `DIGEST_MODE` из `.env` поверх env процесса;
- погода из `WEATHER_LOCATION` JSON;
- `is_valid_webapp_base_url` — отклонение путей `connect.html` / `/static/`;
- `load_settings(require_webapp=True)` — заглушки и невалидный `WEBAPP_BASE_URL`;
- тесты `parse_user_calendar_map` — legacy, удалятся вместе с миграцией handlers.

**Scheduler, settings, Telegram, weather** — см. соответствующие `test_*.py`.

**Web App** (`test_web_server.py`, `test_init_data.py`, `test_web_app_connect.py`):

- `GET /healthz` без auth;
- gate `approved` для `/api/calendar/*`;
- HMAC-валидация `initData` (коды ошибок `no_init_data`, `bad_signature`, `expired`);
- `initData` из заголовка, JSON-тела и query;
- connect/disconnect и CRUD событий (mock `UserCalendarService`).

**Analytics** (`test_analytics_card.py`, `test_analytics_caption.py`,
`test_analytics_handler.py`, `test_period_stats.py`, `test_event_kinds.py`):

- PNG недельной аналитики;
- подпись и хендлер аналитики из хаба настроек;
- `period_stats` / `event_kinds` — фильтры для недельного отчёта.

**Infrastructure** (`test_backup.py`, `test_streaming_delivery.py`,
`test_settings_hub.py`, `test_calendar_manage.py`, `test_user_access.py`):

- снапшоты `users.json` / `subscriptions.json` при старте;
- потоковый ответ (черновик → финал);
- навигация хаба настроек и manage PARTSTAT.

## Static Checks

Конфиг инструментов — [`pyproject.toml`](../pyproject.toml) (`ruff`, `mypy`,
`pytest`). Dev-зависимости — `requirements-dev.txt`; опционально
`pre-commit install` (см. [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)).

```bash
make lint        # ruff check satellite tests
make format      # ruff format satellite tests
make typecheck   # mypy satellite (информативно, как в CI)
make compile     # py_compile всех .py
make check       # lint + typecheck + compile + test
```

## Compile Check

На внешних macOS-томах могут появляться AppleDouble-файлы `._*.py`:

```bash
find satellite tests -name '*.py' ! -name '._*' -print0 \
  | xargs -0 python -m py_compile
```

Эквивалент через Makefile: `make compile`.
