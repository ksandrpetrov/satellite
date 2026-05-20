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

В CI (GitHub Actions) используется Python 3.11: compile-check всех модулей,
затем `pytest -q` (workflow [`.github/workflows/test.yml`](../.github/workflows/test.yml)).

Отдельно при публикации GitHub Release собирается Docker-образ и пушится в GHCR
([`.github/workflows/release-docker.yml`](../.github/workflows/release-docker.yml);
образ на Python 3.12). Деплой образа — [deploy/README.md](../deploy/README.md).

Если проект временно перенесен, а venv содержит старые absolute shebang-пути,
можно использовать системный Python с пакетами из venv:

```bash
PYTHONPATH=venv/lib/python3.9/site-packages python3 -m pytest
```

## Быстрые целевые прогоны

Scheduler и настройки:

```bash
python -m pytest tests/test_scheduler.py tests/test_digest_settings.py
```

Telegram helpers:

```bash
python -m pytest tests/test_handlers.py tests/test_chat_action.py tests/test_message_editing.py
```

Calendar, plan service и digest:

```bash
python -m pytest tests/test_calendar_stats.py tests/test_normalize_caldav_event.py \
  tests/test_plan_service.py tests/test_events.py tests/test_time_utils.py \
  tests/test_seagull_render.py tests/test_seagull_digest.py tests/test_seagull_rules.py
```

Config, storage, CalDAV helpers:

```bash
python -m pytest tests/test_config.py tests/test_subscriptions.py \
  tests/test_caldav_candidates.py tests/test_ical_parser.py
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

Autouse-фикстура обнуляет `TYPING_DISPLAY_SECONDS`, чтобы тесты не ждали ~5 с
после `run_with_typing_action`.

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

**Config** (`test_config.py`):

- `DIGEST_MODE` из `.env` поверх env процесса;
- погода из `WEATHER_LOCATION` JSON;
- тесты `parse_user_calendar_map` — legacy, удалятся вместе с миграцией handlers.

**Scheduler, settings, Telegram, weather** — см. соответствующие `test_*.py`.

## Static Checks

В проекте нет закрепленного `pyproject.toml`, `ruff` или `mypy` конфига.
При локальной установке:

```bash
ruff check .
mypy .
```

## Compile Check

На внешних macOS-томах могут появляться AppleDouble-файлы `._*.py`:

```bash
find satellite tests -name '*.py' ! -name '._*' -print0 \
  | xargs -0 python -m py_compile
```

Эквивалент через Makefile: `make compile`.
