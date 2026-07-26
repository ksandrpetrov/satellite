# Тестирование

**См. также:** [карта документов](README.md) · [test-coverage-audit.md](test-coverage-audit.md) ·
[AGENTS.md § тесты](../AGENTS.md#тесты-и-регрессии-для-агентов)

## Содержание

- [Установка dev-зависимостей](#установка-dev-зависимостей)
- [Полный прогон](#полный-прогон)
- [Smoke](#smoke-образ-и-production-url)
- [Целевые прогоны](#быстрые-целевые-прогоны)
- [Release-blocking](#release-blocking-бизнес-сценарии)
- [Фикстуры](#фикстуры)
- [Что покрыто](#что-покрыто)
- [Static Checks](#static-checks)

---

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
pip install -r requirements-dev.txt
```

## Полный прогон

```bash
python -m pytest
# или: make test
```

В CI на **pull request** ([`.github/workflows/test.yml`](../.github/workflows/test.yml))
и перед **deploy** ([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml))
один reusable workflow [`.github/workflows/_checks.yml`](../.github/workflows/_checks.yml)
в матрице Python 3.11/3.12:

- **lock-check** — generated locks соответствуют `requirements*.in`;
- **ruff** — `ruff check` и `ruff format --check` (блокирующий);
- **mypy** — `mypy satellite` (блокирующий);
- **py_compile** — все модули `satellite/` и `tests/`;
- **pytest** — `pytest -q`.

Перед коммитом локально: `make check` (= lint + typecheck + compile + test).

На каждый push в `main` или тег `v*` workflow
[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) сначала вызывает тот же
`_checks.yml`, затем собирает Docker-образ (Python 3.12) в GHCR и гоняет
[`docker-smoke-image.sh`](../scripts/docker-smoke-image.sh) (см. ниже). Rolling deploy по SSH
выполняется **только** для `main` (и при ручном **Run workflow**); тег `v*` лишь публикует
semver-образ. После деплоя CI вызывает [`smoke-prod.sh`](../scripts/smoke-prod.sh).
Подробности и секреты — [deploy/README.md](../deploy/README.md).

## Контракт зависимостей (`test_requirements.py`)

[`requirements.in`](../requirements.in) и
[`requirements-dev.in`](../requirements-dev.in) содержат только прямые точные
пины. `requirements.txt` и `requirements-dev.txt` — generated uv-locks всех
runtime/dev/transitive пакетов для Python 3.11/3.12, macOS/Linux; хеши
distribution намеренно не включены. Обновление:

```bash
make lock        # только uv 0.11.32
make lock-check  # не меняет рабочие lock-файлы
```

[`tests/test_requirements.py`](../tests/test_requirements.py) проверяет inputs,
generated header, точные версии, Python baseline и `caldav==3.2.1`. Smoke
сверяет lock с реально установленной версией. Не ослабляйте assert без
осознанной смены контракта зависимостей.

## Smoke (образ и production URL)

| Команда / скрипт | Когда |
|------------------|-------|
| `make docker-smoke` | После `docker build` локально: `docker-smoke-image.sh` → `smoke_container.py` |
| `bash scripts/docker-smoke-image.sh <image-ref>` | CI после push в GHCR; `SMOKE_SKIP_PULL=1` для локального тега |
| `make smoke-prod` | После деплоя: curl `/healthz`, `/connect`, `/api/calendar/status` снаружи |
| `SATELLITE_BASE_URL=https://… bash scripts/smoke-prod.sh` | Другой домен (как `SMOKE_PUBLIC_BASE_URL` в Actions) |

`smoke_container.py` проверяет импорт всех модулей `satellite`, подмодули `caldav`,
и поднимает `WebAppServer` на случайном порту для `GET /healthz` без Telegram.

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

Бизнес-сценарии (release-blocking):

```bash
python -m pytest tests/test_business_routes_contract.py tests/test_business_flows_*.py
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

## Release-blocking (бизнес-сценарии)

Полная карта сценариев → реализация → покрытие: [`test-coverage-audit.md`](test-coverage-audit.md).

Перед релизом **обязателен** `make check`. Минимальный целевой прогон регрессий:

```bash
python -m pytest tests/test_business_routes_contract.py \
  tests/test_business_flows_*.py -q
```

| Файл | Что ловит |
|------|-----------|
| `test_business_routes_contract.py` | алиасы команд, `_MESSAGE_ROUTES`, `CB_*` → router, `API_ROUTES` без 500 |
| `test_business_flows_access.py` | access guards, `/help` + `REPLY_KEYBOARD_REMOVE`, `/pending` |
| `test_business_flows_plan.py` | план дня, ActionGuard release при CalDAV-ошибке |
| `test_business_flows_upcoming.py` | `/upcoming` 7 дней, пустой список, guard |
| `test_business_flows_invitations.py` | горизонт 60d/14d, лимит 12, PARTSTAT, cooldown 10 с |
| `test_calendar_manage.py` | `/manage` streaming, PARTSTAT, cooldown 10 с |
| `test_business_flows_create.py` | FSM `/create` целиком |
| `test_business_flows_settings.py` | callbacks настроек и навигация «Назад» |
| `test_business_flows_webapp.py` | initData, секреты в `users.json`, 403 pending |
| `test_business_flows_runtime_state.py` | `TokenVault`, атомарность subscriptions |
| `test_business_flows_smoke.py` | импорт всех модулей `satellite`, `/healthz` |

## Фикстуры

`tests/conftest.py`:

- `make_event(title, start, end, ...)` — `NormalizedEvent` из `HH:MM` для метрик;
- autouse `_reset_action_guards` — сброс `ActionGuard` между тестами;
- `make_fake_telegram`, `make_ctx`, `make_msg`, `make_callback`, `make_user_store`,
  `FakeCalendarService`, `freeze_now`, `free_tcp_port` — для business-flow тестов.

Production-путь нормализации — только `normalize_caldav_event`; в тестах метрик
CalDAV-словари в `calculate_day_stats` не подаём напрямую.

## Что покрыто

**Users / security** (по мере появления тестов):

- пакет [`satellite/users/`](../satellite/users/) (`record.py`, `store.py`, `admin.py`);
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

- реализация в пакете [`satellite/calendar/events/`](../satellite/calendar/events/)
  (фасад `satellite.calendar.events`; раскладка — `_filters`, `_collectors`, …);
- `format_upcoming_events_lines` — нумерация `1️⃣`… как в дайджесте.

**Invitations** (`test_calendar_invitations.py`, PARTSTAT в `test_events.py`,
`test_seagull_digest.py`, `test_caldav_candidates.py`):

- `is_pending_invitation_for_user` (`_partstat.py`), `event_relevant_for_invitations`,
  `collect_pending_invitations` (`_collectors.py`; в т.ч. lookback 14 дней для
  завершённых без ответа);
- роутинг `/invitations`, streaming open (`open_streaming_reply`) и CalDAV
  `set_attendee_partstat` (mock provider).

**Calendar selection** (`test_calendar_selection.py`):

- `effective_enabled_calendar_urls` — пустой список → primary;
- `UserStore.set_enabled_calendar_urls`;
- inline-клавиатура источников, роутинг `/calendars`.

**Settings hub** (`test_digest_settings.py` и др.):

- переход «Дайджест» из хаба, закрытие хаба без лишних ошибок.

**Config** (`test_config.py`):

- `DIGEST_MODE` из `.env` (legacy; scheduler авто-дайджеста всегда на today);
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
- подпись и хендлер аналитики из хаба настроек (ошибки сборки/`sendPhoto`,
  `ActionGuard` — второй callback в cooldown → toast, один `sendPhoto`);

**ActionGuard** (`test_action_guard.py`):

- `try_acquire` / `release`, cooldown после `sent=True`;
- autouse-фикстура `_reset_action_guards` в `conftest.py` сбрасывает синглтоны
  plan/upcoming/analytics/invitations/manage/partstat между тестами.
- `period_stats` / `event_kinds` — фильтры для недельного отчёта.

**Telegram presentation** (`test_visual.py`, `test_html_format.py`,
`test_chat_menu_button.py`):

- message effects, typing, menu button;
- HTML-хелперы и fallback в `api.py`.

**Calendar service / Web App tokens** (`test_user_calendar_service.py`,
`test_connect_token.py`, `test_calendar_view_helpers.py`, `test_mailru_create.py`):

- фасад `UserCalendarService`, connect-токены, хелперы списка календарей,
  создание события Mail.ru (mock).

**Infrastructure** (`test_backup.py`, `test_streaming_delivery.py`,
`test_settings_hub.py`, `test_calendar_manage.py`, `test_user_access.py`):

- снапшоты `users.json` / `subscriptions.json` при старте;
- потоковый ответ (черновик → финал) для plan, upcoming, invitations, manage;
- навигация хаба настроек и manage PARTSTAT (streaming open + callback refresh).

## Static Checks

Конфиг инструментов — [`pyproject.toml`](../pyproject.toml) (`ruff`, `mypy`,
`pytest`). Mypy strict включён точечно для persistence, scheduler, dispatcher
и bot lifecycle; остальной проект остаётся на базовом блокирующем режиме.
Dev-зависимости устанавливаются из `requirements-dev.txt`; опционально
`pre-commit install` (см. [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)).

```bash
make lint        # ruff check satellite tests
make format      # ruff format satellite tests
make typecheck   # mypy satellite (блокирующий гейт, как в CI)
make compile     # py_compile всех .py
make check       # lint + typecheck + compile + test
make lock-check  # generated dependency locks актуальны
```

## Compile Check

На внешних macOS-томах могут появляться AppleDouble-файлы `._*.py`:

```bash
find satellite tests -name '*.py' ! -name '._*' -print0 \
  | xargs -0 python -m py_compile
```

Эквивалент через Makefile: `make compile`.

---

**Далее:** [test-coverage-audit.md](test-coverage-audit.md) · [troubleshooting.md](troubleshooting.md) ·
[operations.md](operations.md)
