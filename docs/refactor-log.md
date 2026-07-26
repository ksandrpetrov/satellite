# Refactor log

Кратко — какие архитектурные фазы прошли через кодовую базу, чтобы будущие
агенты и люди не переоткрывали одни и те же файлы и понимали, какие инварианты
держим. Каждая фаза была behaviour-preserving: внешний контракт (тексты,
callback_data, HTTP-ответы) не менялся без явной продуктовой задачи; baseline
pytest оставался зелёным.

**См. также:** [карта документов](README.md) · [AGENTS.md](../AGENTS.md) ·
[architecture.md](architecture.md)

## Содержание

- [Фазы 1–11](#фазы)
- [Что НЕ менялось](#что-не-менялось)
- [Техдолг](#что-осталось-дешёвым-техдолгом)
- [Хронология по датам](#messages_ru-разбиение-по-сценариям-2026-05-22) (подразделы ниже)

---

## Фазы

1. **`satellite/web/server.py` → пакет `satellite/web/`** — 917-строчный
   god-module распилен на `routing`, `responses`, `parsing`, `auth`,
   `static_pages`, `api/calendar`. `WebAppServer` остался тонким
   lifecycle. Новый endpoint = один `Route` в `routing.py` + одна функция в
   `api/`.
2. **Канонический PNG-рендер в `visual_cards/base.py`** — палитра, шрифты,
   логотип и draw-примитивы существовали в 3 копиях
   (`analytics/render_card.py`, `visual_cards/base.py`).
   Оставили один источник: `visual_cards/base.py`, остальные импортируют
   `vc.pil`, `vc.load_font`, `vc.paste_brand_logo`, `vc.rounded_rect`, и т.д.
3. **`partstat_flow` для invitations и manage** — два handler'а на ~250 строк
   каждый разделяли `PARTSTAT_BY_CODE`, lookup события, `set_attendee_partstat`,
   refresh UI. Извлекли `handlers/partstat_flow.py`; `calendar_invitations.py`
   и `calendar_manage.py` стали тонкими адаптерами (свои тексты и
   `PartstatFlow`-конфиг).
4. **Single mutator в `UserStore` и `SubscriptionStore`** — 13 mutator-методов
   повторяли `lock → get → replace(updated_at=now, ...) → save`. Ввели
   `UserStore._update_locked(uid, **fields)` /
   `_update_locked_with(uid, fn)` и `SubscriptionStore._upsert_locked`.
   Сериализация ушла в `UserRecord.{to,from}_json` /
   `DigestSettings.{to,from}_json`. (На момент фазы код жил в одном `users.py`;
   позже вынесен в пакет `satellite/users/` — см. раздел ниже.)
5. **Data-driven routing** — `handlers/dispatch.py` и `handlers/routing.py`
   перешли с `isinstance`/`if-elif` цепочек на таблицы: `_MESSAGE_ROUTES`,
   `_CALLBACK_ROUTERS`, `_RECOGNIZERS`. Хелпер `_button_or_command`
   объединил все `is_*_request`-проверки. Добавление новой команды теперь
   стоит одну строку в таблице.
6. **`HandlerContext`, `ensure_calendar_*` по IDs** —
   `ensure_calendar_access`
   и `ensure_calendar_connected` принимают keyword-only `chat_id`/`user_id` —
   фабрикация `IncomingMessage` (`_msg_from_cb`) удалена. Экспериментальные
   role-view свойства позднее удалены как неиспользуемые (см. hardening ниже).
7. **`messages_ru.py` → пакет** — 1272-строчный файл превращён в пакет
   `satellite/messages_ru/`. `__init__.py` ре-экспортирует публичное API из
   `_core.py`. Старые импорты `from satellite.messages_ru import X`
   продолжают работать без правок.
8. **Чистка `telegram_bot/`** —
   - `api.py`: 3 метода `setMyName/Description/ShortDescription` свелись к
     wrapper'ам над общим `_set_my(method_name, **fields)`.
   - `analytics_service.py` переехал в `analytics/service.py` (shim удалён
     в Фазе 11 — все импорты обновлены на canonical путь).
   - `telegram_bot/{calendar,digest}_state.py` переехали в `handlers/`
     (shim'ы удалены в Фазе 11; canonical путь —
     `satellite.telegram_bot.handlers.{calendar,digest}_state`).
   - В `calendar_create.py` удалили синтетическую обёртку `do_create()` —
     `try/except` теперь напрямую вокруг вызова.
9. **Tooling: ruff + mypy + pre-commit + CI** —
    - `pyproject.toml` с конфигом `ruff` (lint + format) и `mypy`.
    - `requirements-dev.txt` дополнен `ruff`, `mypy`, `pre-commit`.
    - `.pre-commit-config.yaml`: ruff (auto-fix), ruff-format, mypy.
    - `Makefile`: `make lint`, `make format`, `make typecheck`,
      `make check` = `lint + typecheck + compile + test`.
    - CI (`.github/workflows/_checks.yml`): reusable workflow с ruff (lint +
      format), mypy, py_compile, pytest. Все стадии блокирующие.
      `test.yml` (PR) и `deploy.yml` (push в main / тег `v*`) вызывают этот
      reusable, дублирования больше нет.
10. **Документация** — AGENTS.md и docs/ синхронизированы с canonical-путями
    (`visual_cards/base`, `partstat_flow`, `action_guard`,
    single mutator, data-driven routing, `messages_ru/`, `analytics/service`,
    `make check`, `logs/backups/`). Этот файл — чек-лист для будущих
    рефакторингов. Пакеты `users/`, `calendar/events/` — отдельный раздел ниже.
11. **Guard недельной аналитики** — изначально `_AnalyticsRunGuard` в
    `handlers/analytics.py`; позже обобщён в `ActionGuard`
    (`handlers/action_guard.py`) и подключён к plan, upcoming, invitations,
    manage, partstat. Аналитика: повторный `CB_ANALYTICS_RUN` во время сборки
    или в течение 45 с после успешного `sendPhoto` → toast `ANALYTICS_BUSY_TOAST`.
    Регрессии — `tests/test_analytics_handler.py`,
    `tests/test_action_guard.py`; между тестами guard'ы сбрасывает
    `conftest._reset_action_guards`.

## Что НЕ менялось

- Внешние тексты (`messages_ru`), seagull-render, callback_data, HTTP-контракт
  `/api/calendar/*`.
- Формат `users.json` / `subscriptions.json` — добавились helpers, но JSON
  совместимый.
- CalDAV-протокол, PARTSTAT-логика провайдеров, watermark long-polling.
- Один entrypoint `telegram_test_command.py`.

## Что осталось «дешёвым» техдолгом

- mypy strict включён для persistence, scheduler, dispatcher и bot lifecycle.
  Остальные модули переводятся постепенно; базовый mypy блокирует весь проект.

## messages_ru: разбиение по сценариям (2026-05-22)

- Монолит `_core.py` (~1350 строк) распилен на подмодули:
  `buttons`, `identity`, `access`, `admin_messages`, `calendar_ui`,
  `settings_ui`, `plan_strings`, `duration`. `_core.py` — тонкий реэкспорт;
  `from satellite.messages_ru import …` без изменений.
- Агенту проще править один сценарий (например, только `settings_ui.py`
  для дайджеста) без прокрутки тысячи строк.

## dispatch: единая обёртка ошибок + /start в таблице (2026-05-22)

- `handlers/dispatch.py`: `_safe_message_run` — один try/except для всех
  message-путей (стабильность, меньше копипасты).
- `StartOrHelpCommand` и `PendingCommand` перенесены в `_MESSAGE_ROUTES`;
  `/start` и `/help` теперь сбрасывают FSM (`digest_state`, `calendar_state`),
  как и остальные распознанные команды (инвариант AGENTS.md §10).

## GitHub Actions автодеплой (2026-05-21)

- `.github/workflows/deploy.yml`: test → образ в GHCR (`:sha-<short>`; `:latest` на main;
  semver на теге `v*`) → SSH rolling deploy (`scripts/ci-deploy-remote.sh`) только для
  `main` и `workflow_dispatch`. Workflow целиком также триггерится тегом `v*`, но job deploy
  на теге не запускается.
- Job deploy: явная проверка секретов `DEPLOY_HOST` / `DEPLOY_USER` / `SSH_PRIVATE_KEY`;
  lowercase имени образа в GHCR (`tr` вместо `${var,,}`).
- `ci-deploy-remote.sh`: stop/disable legacy `satellite-bot.service` перед `compose up`
  (как в Ansible playbook); нормализация `DEPLOY_HOST`/`DEPLOY_USER`/`SATELLITE_IMAGE`
  (trim CR/LF — иначе SSH: `hostname contains invalid characters`).
- Compose с `image: ${SATELLITE_IMAGE}`; шаблон `env.j2` пишет `SATELLITE_IMAGE` в `.env` при
  первичном `make deploy`, дальше Actions сам перезаписывает значение.
- Старый `release-docker.yml` удалён (заменён `deploy.yml`).
- Дополнено в тот же день: smoke после build/deploy, `GHCR_TOKEN` fallback — см. разделы
  «Smoke после сборки…» и «GHCR login без отдельного PAT» ниже.

## Приглашения: lookback 14 дней (2026-05-21)

- `/invitations`: горизонт 60 дней вперёд + 14 дней назад; недавно завершённые
  встречи с `NEEDS-ACTION`/`DELEGATED` остаются в списке (`event_relevant_for_invitations`
  + `lookback_days` в `collect_pending_invitations`).
- Документация UX: [telegram-ux.md](telegram-ux.md); тесты — `test_calendar_invitations.py`.

## Docker-деплой: внешний nginx вместо Traefik (2026-05-21)

- Compose на сервере — только `satellite`; TLS и `/connect` → `127.0.0.1:<satellite_host_port>`
  настраивает хостовой nginx ([`deploy/nginx/satellite-webapp.conf.example`](../deploy/nginx/satellite-webapp.conf.example)).
- Ansible: `satellite_host_port`, миграция со старого стека Traefik/Certbot в playbook.
- Документация: `deploy/README.md`, `docs/operations.md`, `docs/configuration.md`,
  `docs/troubleshooting.md`, `README.md`, `AGENTS.md`.

## ActionGuard и streaming plan/upcoming (2026-05-21)

- `handlers/action_guard.py` — дедуп долгих действий per `(chat_id, action_key)`:
  блокирует параллельный запуск и повтор сразу после успеха (cooldown настраивается
  per сценарий). Закрывает прод-инцидент с двумя PNG аналитики при двойном тапе
  (см. комментарии в `action_guard.py` / `analytics.py`).
- План (`plan.py`) и `/upcoming` (`calendar_list.py`) переведены на
  `open_streaming_reply`; guard'ы 30 с / 15 с — без второго дайджеста/списка.
- Документация: AGENTS.md, architecture.md, telegram-ux.md, testing.md,
  troubleshooting.md.

## Streaming: `/invitations` и `/manage` (2026-05-21)

- Открытие списка — `open_streaming_reply` (как plan/upcoming), не отдельное
  loading-сообщение + `editMessageText`.
- `ActionGuard` 10 с на open; refresh и ответ PARTSTAT — `edit_callback_message`.
- Документация: README.md, architecture.md, telegram-ux.md, testing.md, troubleshooting.md.

## Web App connect-токены (2026-05-21)

- `ConnectTokenStore` (`web/connect_token.py`): краткоживущие токены, когда
  Telegram WebView не передаёт `initData` в `web_app`-кнопках.
- Кнопки в чате → `webapp_connect_url` → `/connect/<token>#t=...`; API принимает
  токен из path/hash/body/query (`auth.validated_user` fallback после initData).
- Персист `logs/connect-tokens.json` (TTL 900 с). Тесты — `test_connect_token.py`,
  `test_web_server.py::test_status_with_connect_token_without_init_data`.
- Документация: AGENTS.md, architecture.md, configuration.md, telegram-ux.md,
  troubleshooting.md, operations.md, README.md.

## Пакеты `users/` и `calendar/events/` (2026-05-21)

- `satellite/users.py` → `satellite/users/`: `record.py` (`UserRecord`, статусы),
  `store.py` (`UserStore`, атомарная запись), `admin.py` (`parse_admin_ids`);
  фасад `__init__.py` re-export'ит публичный API.
- `satellite/calendar/events.py` → `satellite/calendar/events/`: `_types`,
  `_time`, `_partstat`, `_filters`, `_collectors`; фасад `__init__.py`.
- Импорты `from satellite.users import …` и
  `from satellite.calendar.events import …` без изменений (handlers, тесты, Web App).
- Документация: AGENTS.md, architecture.md, configuration.md (уже был пакет),
  telegram-ux.md, testing.md, refactor-log.

## Синхронизация docs с CI и Docker-деплоем (2026-05-21)

- Единое описание job **test** в `deploy.yml` и PR-гейта — reusable `_checks.yml`
  (ruff lint + format + mypy + py_compile + pytest); README, AGENTS, architecture,
  testing, deploy/README, operations.
- Секреты `DEPLOY_HOST` / trim SSH — operations, deploy/README, troubleshooting.
- CalDAV-диагностика: разделение systemd (`venv` в `/opt/satellite`) vs Docker
  (только compose + volume; скрипты — из отдельного клона или с ноутбука).

## Фаза 11: mypy clean, reusable CI, удаление shim'ов (2026-05-21)

- **mypy 0 ошибок** на 106 модулях. Раньше был `continue-on-error: true` —
  гейт не работал, накопилось 59 ошибок в 18 файлах. Точечные правки по
  файлам: `Event = Mapping[str, Any]` (расширили contravariantly), типизация
  `dict[str, Any]` для `call_kw` в `TelegramClient`, `_to_int_or_none`
  для precipitation probability, явные `(int, int, int)` tuple для draw_pill,
  локальный capture `user_id = cb.user_id` в nested `build()` функциях,
  None-checks для `screen.text` / `screen.keyboard`, `# type: ignore[attr-defined]`
  для динамического маркера `_satellite_managed` на logging-handler.
  Переименование `SubscriptionStore.list()` → `list_active()` (имя
  shadow'ило builtin `list` в type-hint'ах класса).
- **Reusable CI** (`.github/workflows/_checks.yml`): один workflow для ruff
  (lint + format) + mypy + py_compile + pytest. `test.yml` (PR) и `deploy.yml`
  (push в main / тег `v*`) вызывают его через `uses: ./...`. Раньше шаги
  жили в двух местах; в `deploy.yml` забыли `ruff format --check`, поэтому
  неотформатированный `config.py` спокойно уехал в `main`. Гейт mypy теперь
  блокирующий.
- **Удалены shim-модули**: `satellite/analytics_service.py`,
  `satellite/telegram_bot/calendar_state.py`,
  `satellite/telegram_bot/digest_state.py`. Внутри проекта на них никто не
  опирался; три теста обновлены на canonical путь
  (`satellite.telegram_bot.handlers.{calendar,digest}_state`,
  `satellite.analytics.service`).
- **Документация**: AGENTS.md, architecture.md, configuration.md,
  refactor-log.md синхронизированы с новой раскладкой.
- `pyproject.toml`: убраны устаревшие per-file-ignores под удалённые shim'ы;
  добавлены под фасады `users/__init__.py` и `calendar/events/__init__.py`.

## caldav 3.x (2026-05-21)

- `requirements.txt`: `caldav>=3.0,<4` (Python 3.10+; CI/Docker уже на 3.11+).
- `caldav_client.py`: импорт `DAVClient`/`Event` из подмодулей (mypy); API v3 —
  `get_principal`, `get_calendars`, `get_events`, `search`, `add_event`.
- `tests/test_requirements.py`, `smoke_container.py` — контракт на пин 3.x.

## caldav 2.x и явные импорты (2026-05-21, superseded)

- Было: `caldav>=2.2,<3`, импорт из подмодулей. Заменено миграцией на 3.x выше.

## Smoke после сборки и деплоя (2026-05-21)

- `scripts/smoke_container.py` + `docker-smoke-image.sh` — job **build** в
  `deploy.yml` после push в GHCR.
- `scripts/smoke-prod.sh` — после rolling deploy (`ci-deploy-remote.sh`);
  variable `SMOKE_PUBLIC_BASE_URL`; Makefile: `docker-smoke`, `smoke-prod`.
- `Dockerfile` копирует `scripts/smoke_container.py` в образ для CI smoke.
- Документация: README, operations, architecture, testing, troubleshooting,
  configuration (smoke env), deploy/README, AGENTS.md.

## GHCR login без отдельного PAT (2026-05-21)

- `deploy.yml`: `GHCR_TOKEN: secrets.GHCR_PULL_TOKEN || github.token` — rolling
  deploy на сервере делает `docker login` без обязательного `GHCR_PULL_TOKEN`
  для пакета этого repo.

## Миграция systemd → Docker: logs в volume (2026-05-21)

- `scripts/migrate-legacy-logs.sh` — перенос `/opt/satellite/logs/` (хост) в
  volume `satellite_satellite-logs`, rescue-копия, `chown` под uid `satellite` в образе.
- `ci-deploy-remote.sh` — перед `compose up` сравнивает `users.json` на хосте и в volume;
  host > volume → fail deploy с указателем на migrate.
- `bot.warn_if_users_lost` — WARNING при пустом сторе, но есть `users.json.*.bak` в
  `logs/backups/`; тесты — `test_persistence_warning.py`.
- Документация: AGENTS.md (раздел миграции), operations, troubleshooting, README.

## Deploy: `/healthz` через JSON parse (2026-05-21)

- `ci-deploy-remote.sh`: host smoke сравнивает распарсенный JSON `{"status": "ok"}`,
  а не точную строку тела — иначе ложный fail при `json.dumps` с пробелами при
  живом боте.
- Документация: operations, troubleshooting.

## Дайджест непринятых: docs sync (2026-05-21)

- Шедулер (`_deliver_pending`) и UI (`/settings` → «📨 Дайджест непринятых встреч»,
  `pending_digest_*`) работают; в `configuration.md` / `architecture.md` оставалась
  устаревшая пометка «шедулер/UI пока не шлют».
- Обновлены: README, configuration, architecture, telegram-ux, troubleshooting.

## Дни `pending_digest_days`: маска по будням (2026-05-21)

- UI «📨 Дайджест непринятых» — галочки Пн…Вс + «Будни»/«Все дни»; в JSON —
  `weekdays` | `all_days` | `1111100` (`is_valid_pending_digest_days`,
  `toggle_digest_days_bitmask` в `digest_utils.py`).
- Плановый дайджест (`digest_days`) по-прежнему только два пресета в UI.
- Тесты: `test_digest_settings.py` (pending bitmask), `test_scheduler.py`.

## Авто-дайджест плана: всегда «сегодня» (2026-05-22)

- `DigestScheduler._deliver_daily` вызывает `resolve_target_date("today", …)`;
  `DIGEST_MODE` из `.env` на дату авто-отправки не влияет (legacy для логов /
  совместимости; дефолт `today`).
- `resolve_target_date`: неизвестный режим → `today` (раньше — `tomorrow`).
- Документация и `.env.example`: README, configuration, architecture, telegram-ux,
  troubleshooting, AGENTS.md, refactor-log.

---

## Фазы 12–15: архитектурный аудит (2026-07-04)

12. **Стабильность** — `tests/test_update_dispatcher.py`, `tests/test_startup_checks.py`;
    `ConnectTokenStore.now_fn` для детерминированных TTL-тестов; canonical import
    `warn_if_users_lost` из `startup_checks`.
13. **Слой presentation/** — canonical HTML/Rich/calendar_lists/delivery;
    `formatters/` re-export; убраны lazy-imports domain→telegram_bot;
    `inv:back` → invitations router; из хаба настроек «Назад» — `CB_SETTINGS_CALENDAR_BACK`;
    `subscriptions/` пакет (как `users/`);
    `tests/test_import_layers.py`.
14. **Handlers/transport split** — `settings_bindings.py` + `settings_callbacks.py`;
    `telegram_bot/api/` (client + errors); `telegram_bot/streaming/` (helpers + session);
    `streaming_delivery.py` — facade.
15. **CalDAV split** — `caldav_shared.py`, `caldav_fetch_mixin.py`,
    `caldav_partstat_mixin.py`; `caldav_client.py` — facade ~390 строк + mixins.

Behaviour-preserving: `make check` зелёный (954 теста).

---

## Фаза 16: один canonical-путь + слои импортов (2026-07-04)

Цель — «какой импорт правильный?» перестаёт быть вопросом: один canonical-путь
`presentation/*`, домен не знает о `telegram_bot`, дубли схлопнуты.

1. **Canonical presentation** — удалены шимы `telegram_bot/{html_format,rich_message,message_delivery}.py`,
   `telegram_bot/presenters/calendar_lists.py`, пакет `formatters/`,
   `messages_ru/_core.py`; `strip_bold_tags` переехал в `presentation/html.py`;
   `presentation/__init__.py` — docstring-only (без re-export'ов, ушёл скрытый
   цикл `presentation ↔ telegram_bot.api`); фасад `messages_ru/__init__` —
   star-import подмодулей напрямую. Импортёры (прод + тесты) переведены на
   `satellite.presentation.*`.
2. **Lazy-imports hoisted** — top-level импорты в `api/client.py`,
   `seagull/templates.py`, `messages_ru/{settings_ui,identity}.py`,
   `presenters/settings_screens.py`, `calendar/stats.py` (комментарии «avoid
   cycle» устарели). Единственный оставшийся lazy — `calendar_ui.py →
   calendar.selection` (реальный цикл через `caldav_client → events →
   messages_ru`, задокументирован на месте).
3. **Слой-тест** — `tests/test_import_layers.py` переписан: чистый домен
   (calendar, seagull, weather, analytics, messages_ru, presentation,
   scheduler, plan_service, …) не импортирует `telegram_bot`; allowlist —
   только `presentation/delivery.py → telegram_bot.api`; web/scheduler не
   импортируют `telegram_bot.handlers`.
4. **Scheduler** — постоянный `ThreadPoolExecutor` (создаётся в `__init__`,
   закрывается в `stop()`, отмена queued-доставок при остановке) вместо нового
   пула каждые 30 с; единый блок агрегации вместо двух копий
   (sequential/parallel).
5. **TelegramClient** — `_attach_reply_markup` (5 копий сериализации → 1) и
   `_call_with_fallbacks` (3 копии retry-без-effect → 1, включая HTML-fallback).
6. **messages_ru split** — `settings_ui.py` (740 строк) → `settings_ui.py`
   (хаб + аналитика + подэкран «Календарь» + ERR_*), `digest_ui.py` (daily +
   pending настройки), `meetings_ui.py` (/invitations + /manage UI); plan-тексты
   → `plan_strings.py`, upcoming/foreign-тоасты → `calendar_ui.py`. Фасад
   сохраняет все имена.
7. **settings_bindings** — публичный кросс-модульный API: `BINDINGS`,
   `bindings_for`, `enabled_value`/`days_value`/`time_value`, `update_settings`,
   `build_{settings,days,time}_screen_bundle` (вместо `_BINDINGS`, `_bindings`, …).
8. **Docs** — AGENTS.md (карта модулей, инвариант 15 «слои импортов»,
   антипаттерны), architecture.md, telegram-ux.md; `pyproject.toml` — вычищен
   stale ignore `messages_ru/_core.py`.

Behaviour-preserving: тексты, callback_data, HTTP-контракт, формат сторов не
менялись. `make check` зелёный.

---

## Pre-release audit (2026-07-05)

Цель — стабильность и чистота перед релизом без смены внешнего контракта.

1. **Мёртвый код** — `BRAND_EMOJI`, `spoiler`/`code`/`reference` в `presentation/rich.py`,
   `InflightTracker`, неиспользуемые строки в `streaming_ui.py`, orphan `CB_CAL_SOURCES`,
   тройной `_normalize_calendar_url` → `calendar/selection.normalize_calendar_url`.
2. **Invitations UX** — без дубля «В календарь» вне хаба; `from_settings_hub` в
   `EventTokenCache`; refresh/respond сохраняют `CB_SETTINGS_CALENDAR_BACK`; тон «попробуй».
3. **Тексты presenters** — shared strings из `messages_ru` для hub/calendar/upcoming.
4. **Persistence + guards** — `UserStorePersistenceError` в access/admin/analytics/
   calendar_sources/settings; weather toggle toast; ActionGuard на refresh invitations/manage;
   WARNING при failed `mark_*_sent` в scheduler.
5. **Тесты** — invitations hub/keyboard, `duration_format`, `scheduler_policy`,
   `streaming_caldav`, `partstat_flow` dedup, `settings_bindings`, scheduler `stop()`.

JsonStore memory/disk divergence закрыт в hardening 2026-07-26 ниже.

---

## Архитектурный hardening (2026-07-26)

Точечный аудит по стабильности, поддерживаемости и стоимости agent-driven
правок. Внешние Telegram/Web API и wire-format durable JSON не менялись.

1. **Transactional stores** — generic `JsonStoreBase[T]`, сериализованный
   commit `candidate → tmp/fsync/replace → _items`. Write failure сохраняет
   старое memory/disk состояние; version/write-lock схема удалена.
2. **Fail-fast load** — missing file остаётся пустым store, а битый JSON/root/
   record даёт `UserStoreLoadError` / `SubscriptionStoreLoadError`. Startup
   сначала создаёт backup, затем отказывается запускать Web App/scheduler с
   recovery-инструкцией.
3. **Scheduler checkpoints** — pending outcome стал enum; empty отмечается как
   обработанный день. Process-local checkpoint предотвращает повторный send или
   CalDAV fetch при сбое marker persistence.
4. **Lifecycle/backpressure** — shutdown независимо закрывает scheduler, Web
   App, worker pool, Telegram и weather; dispatcher ограничивает running+queued
   updates значением `2 × BOT_WORKERS`, не подтверждая неотправленную в pool
   задачу.
5. **Меньше ложных абстракций** — неиспользуемые role-view типы
   `HandlerContext` удалены; остался плоский явный DI-контейнер. Strict-набор
   mypy включён только для затронутых критических модулей.
6. **Reproducible tooling** — Python baseline 3.11, CI 3.11/3.12, Docker 3.12;
   direct pins в `requirements*.in`, generated locks через `uv==0.11.32`,
   `make lock` / `make lock-check`.

---

**Далее:** [architecture.md](architecture.md) · [AGENTS.md](../AGENTS.md) ·
[test-coverage-audit.md](test-coverage-audit.md)
