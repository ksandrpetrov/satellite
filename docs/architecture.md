# Архитектура

Проект остается в пакете `satellite/`. Перенос в `src/` сейчас не нужен: серверные
entrypoint уже используют текущие импорты, а структура пакета достаточно
модульная для production-поддержки.

**См. также:** [карта документов](README.md) · [конфигурация](configuration.md) ·
[Telegram UX](telegram-ux.md) · [эксплуатация](operations.md) · [AGENTS.md](../AGENTS.md)

## Содержание

- [Слои](#слои)
- [Entry Points](#entry-points)
- [Interactive Flow](#interactive-flow-целевая-модель)
- [Users and Security](#users-and-security)
- [Telegram Layer](#telegram-layer)
- [Calendar Layer](#calendar-layer)
- [Digest Layer](#digest-layer)
- [Weather Layer](#weather-layer)
- [Storage](#storage)
- [Scheduler](#scheduler)
- [Web App HTTP](#web-app-http)
- [Logging](#logging)
- [Deployment](#deployment-production)

---

## Слои

```text
entrypoints  (telegram_test_command.py)
  -> services.run_bot
  -> TelegramBot lifecycle  +  WebAppServer (background thread)
       |                          |
       v                          v
  telegram_bot/handlers/      web/  (routing -> api/calendar)
       \                       /
        \_____ access _______/
                |
                v
  domain services  (users, subscriptions, plan_service, analytics/service)
                |
                v
  calendar/  (user_calendar_service -> providers/{mailru,yandex} -> caldav_client)
                |
                v
  renderers  (seagull/, weather/, analytics/render_card)
                |
                v
  visual_cards/base.py  — единственная палитра/шрифты/логотип для всех PNG
```

PNG недельной аналитики рендерится через примитивы
[`visual_cards/base.py`](../satellite/visual_cards/base.py) и
[`analytics/render_card.py`](../satellite/analytics/render_card.py).

Handlers принимают Telegram-события и не считают календарную аналитику сами.
Бизнес-логика живёт в сервисах и чистых модулях.

### Data-driven routing

- `telegram_bot/handlers/routing.py` — `_RECOGNIZERS`: список матчеров для
  входящих сообщений; `recognize_message` ходит по таблице, не по if/elif.
- `telegram_bot/handlers/dispatch.py` — `_MESSAGE_ROUTES` (mapping
  `RecognizedCommand` → handler + опциональный access guard) и
  `_CALLBACK_ROUTERS` (список callback-роутеров). Добавление новой команды
  или callback'а — одна запись в таблице, без изменения каркаса.
- `web/routing.py` — аналогичный паттерн: один `Route` на endpoint, диспетчер
  в `server.py` ходит по таблице.

Вспомогательные модули верхнего уровня:

- `satellite/services.py` — `run_bot`.
- `satellite/backup.py` — снапшоты `users.json` / `subscriptions.json` при старте
  (`logs/backups/`, последние 20).
- `satellite/config.py` — `load_settings`, dataclasses конфигов, парсинг `.env`.
- `satellite/users/` — пакет: фасад (`__init__.py`) + `record.py` (`UserRecord`,
  статусы) + `store.py` (`UserStore`, атомарная запись `logs/users.json`) +
  `admin.py` (парсинг `ADMIN_TELEGRAM_IDS`).
- `satellite/security/token_vault.py` — Fernet-шифрование credentials.
- `satellite/digest_utils.py` — `resolve_target_date`, `is_digest_day_allowed`,
  маски дней (`digest_days_to_bitmask`, `format_digest_days_label`, …).
- `satellite/invitations_view.py` — общий экран pending-приглашений для
  `/invitations` и шедулера (`load_pending_invitations_screen`).
- `satellite/messages_ru/` — пакет с user-facing текстами и callback-константами.
  `__init__.py` — фасад (re-export всего публичного API), реализация — в
  `_core.py`. Старые импорты `from satellite.messages_ru import ...` работают
  без изменений.

## Entry Points

- `telegram_test_command.py` — interactive long-polling бот. Единственный entrypoint.

## Interactive Flow (целевая модель)

```text
telegram_test_command.py
  -> satellite.services.run_bot
  -> TelegramBot.run (+ Web App HTTP thread)
  -> TelegramClient.get_updates
  -> handlers.dispatch.handle_message / handle_callback_query
     (/start, /help — всем; остальное — approved + has_calendar)
  -> UserStore: статус, расшифровка credentials через TokenVault
  -> UserCalendarService → provider (mailru | yandex) per user
  -> PlanBuilder.build_text(telegram_user_id → effective_enabled_calendar_urls)
  -> filter_events_for_user (visible + hidden meals)
  -> prepare_seagull_stats   (normalize_caldav_event only)
  -> render_digest_from_stats (rules + render_daily_digest)
  -> weather summary, if enabled
  -> edit_or_send_message
```

Доступ:

1. Новый пользователь: `/start` → запись в `users.json`, заявка `pending`.
2. Админ (`ADMIN_TELEGRAM_IDS`): `/pending` → approve/reject.
3. Одобренный пользователь: Web App → выбор провайдера (`mailru`; `yandex` в UI
   пока «скоро», backend готов) → encrypted credentials + `primary_calendar_url`.
4. Команды плана и дайджест — только при `UserRecord.has_calendar`.

## Users and Security

- `satellite/users/` — пакет: `record.py` (`UserRecord`, статусы доступа и
  календаря), `store.py` (`UserStore`, атомарная запись JSON, thread-safe lock,
  `UserStorePersistenceError` при ошибке диска — caller показывает безопасный
  текст), `admin.py` (`parse_admin_ids` / `admin_id_set`). Фасад в `__init__.py`
  re-export'ит публичный API, поэтому импорты `from satellite.users import …`
  не меняются. Не хранит сырые токены и display name календаря (PII).
- `satellite/security/token_vault.py` — `TokenVault`, `ProviderCredentials`
  (login + app password). Ключ — `TOKEN_ENCRYPTION_KEY` из env.
- `satellite/calendar/user_calendar_service.py` — единый фасад connect/list/create/delete
  для handlers, scheduler, Web App; расшифровка credentials на время запроса.
- `satellite/calendar/operation_log.py` — audit CalDAV-операций.

## Telegram Layer

- `satellite/telegram_bot/bot.py` — lifecycle, long-polling, offset, worker pool,
  scheduler start/stop, graceful shutdown, Web App server bind.
- `satellite/telegram_bot/handlers/` — package with one scenario per file:
  - `context.py` — `HandlerContext` and DTOs.
  - `routing.py` — `recognize_message`, pure parsers.
  - `delivery.py` — send/edit/answer, `notify_handler_failure`.
  - `dispatch.py` — message and callback entrypoints, access gating.
  - `access.py` — `/start`, заявки, gating `approved` / `has_calendar`.
  - `admin.py` — `/pending`, approve/reject callbacks.
  - `settings_hub.py` — inline-хаб «Настройки» (дайджест, аналитика, календари,
    connect); кросс-экранные `CB_SETTINGS_*` / `CB_ANALYTICS_*` только здесь.
  - `settings.py` — экраны дайджеста плана и непринятых (`CB_DIGEST_*`,
    `CB_PENDING_DIGEST_*`, общий `DigestKindBindings`).
  - `analytics.py` — недельная аналитика (PNG + подпись) из хаба;
    `ActionGuard` (45 с cooldown) — один прогон на `chat_id` + защита от
    двойного PNG при повторном callback.
  - `action_guard.py` — общий `ActionGuard`: per `(chat_id, action_key)` блокирует
    параллельный запуск и повтор сразу после успеха. Используют `plan.py` (30 с),
    `calendar_list.py` (15 с), `analytics.py` (45 с), `calendar_invitations.py` /
    `calendar_manage.py` (10 с на открытие списка), `partstat_flow.py` (5 с на ответ
    по событию). Дополняет `ChatLockManager` (сериализация по чату), но не заменяет
    `DigestStateStore.claim_callback` (дедуп одного и того же `callback_query_id`).
  - `calendar_setup.py` — connect / check / disconnect (Web App; check/disconnect
    также из хаба настроек).
  - `calendar_view.py` — общие хелперы списка CalDAV-календарей (fetch, screen lines).
  - `calendar_sources.py` — какие календари учитывать в плане/дайджесте.
  - `calendar_foreign.py` — просмотр пошаренных («чужих») календарей.
  - `calendar_list.py` — `/upcoming`, ближайшие 7 дней.
  - `calendar_create.py` — `/create`, пошаговый FSM создания события.
  - `calendar_invitations.py` — `/invitations`, список NEEDS-ACTION (горизонт
    60 дней вперёд, 14 назад; недавно завершённые без ответа не скрываются),
    streaming open + ответы ACCEPTED / DECLINED / TENTATIVE через CalDAV.
  - `calendar_manage.py` — `/manage`, смена PARTSTAT по любой встрече на 7 дней
    (streaming open списка).
  - `plan.py` — command → plan → streaming reply (`ActionGuard`, 30 с).
  - `subscription.py` — subscribe/unsubscribe.
- `satellite/telegram_bot/api.py` — Bot API client, retries, token sanitizing,
  fallback при отказе Telegram в `<tg-emoji>` / `<blockquote>`.
- `satellite/telegram_bot/html_format.py` — HTML-обёртки (`blockquote`, custom emoji);
  хендлеры не вставляют разметку напрямую.
- `satellite/telegram_bot/visual.py` — typing indicator, message effects, menu button.
- `satellite/telegram_bot/streaming_delivery.py` — потоковый ответ (черновик → финал):
  plan, `/upcoming`, `/invitations`, `/manage`, недельная аналитика.
- `satellite/telegram_bot/presenters/calendar_lists.py` — HTML/Rich HTML presenter'ы
  списков событий (`/upcoming`, `/invitations`, `/manage`); тексты и callback-константы
  остаются в `messages_ru/`.
- `satellite/telegram_bot/message_editing.py` — `edit_callback_message`, fallback
  при неудачном edit (refresh PARTSTAT, хаб настроек).
- `satellite/telegram_bot/handlers/digest_state.py` — in-memory state for digest
  time input.
- `satellite/telegram_bot/handlers/calendar_state.py` — FSM создания события,
  dedup callbacks.
- `satellite/telegram_bot/handlers/partstat_flow.py` — общий PARTSTAT-флоу
  (lookup события + `set_attendee_partstat` + toast + refresh), shared между
  `calendar_invitations.py` и `calendar_manage.py`.
- `satellite/telegram_bot/commands.py` — menu command registration.
- `satellite/telegram_bot/concurrency.py` — `ChatLockManager`, `InflightTracker`.
- `satellite/telegram_bot/instance_lock.py` — single-instance `fcntl` lock.
- `satellite/telegram_bot/offset_store.py` / `offset_tracker.py` — long-polling
  watermark (do not change without dedicated tests).

## Calendar Layer

- `satellite/calendar/providers/` — `mailru` (production) и `yandex` (backend);
  `registry.get_provider` выбирает реализацию по `UserRecord.calendar_provider`.
- `satellite/calendar/user_calendar_service.py` — connect, validate, list/create/delete
  events, `list_events_for_invitations`, `set_attendee_partstat`; единственная точка
  доступа handlers/plan/scheduler/Web App к CalDAV.
- `satellite/calendar/selection.py` — `effective_enabled_calendar_urls`,
  `foreign_calendar_entries` (план/дайджест vs «чужие» календари).
- `satellite/calendar/caldav_client.py` — Mail.ru CalDAV discovery, cache, day
  search, optional PARTSTAT refresh.
- `satellite/calendar/constants.py` — domain constants (lunch marker, all-day label).
- `satellite/calendar/events/` — пакет (раньше один файл `events.py`).
  Фасад `__init__.py` re-export'ит публичный API, импорты
  `from satellite.calendar.events import …` не меняются. Раскладка:
  - `_types.py` — `Event` alias, `PizzaMealKind`, `NUMBER_EMOJI`.
  - `_time.py` — `parse_iso`, `event_datetime_bounds`, `event_occurs_on`,
    `event_local_start_date`, `day_bounds`, `format_time_range`,
    `event_duration_minutes`, `sort_key`, `event_ends_after`.
  - `_partstat.py` — `is_declined_event_for_user`,
    `is_pending_invitation_for_user`, `user_partstat`.
  - `_filters.py` — `is_cancelled_event`, `is_all_day_event`, `is_lunch_event`,
    `pizza_meal_kind`, `event_index_marker`.
  - `_collectors.py` — `format_upcoming_day_header`,
    `build_upcoming_events_groups`, `format_upcoming_events_lines`,
    `format_single_day_events_lines`, `event_relevant_for_invitations`,
    `collect_pending_invitations`, `collect_manageable_events`,
    `format_invitation_list_lines`, `filter_events_for_user`.
- `satellite/calendar/stats.py` — `NormalizedEvent`, `DayCalendarStats`,
  `normalize_caldav_event`. Default workday `10:00–19:00`, lunch `13:00–14:00`.
- `satellite/calendar/time_utils.py` — `normalize_hhmm_input` / `parse_hhmm`
  (гибкий ввод пользователя → канонический `HH:MM`), merge intervals, free slots.

Important invariants:

- Overlapping intervals are merged before busy-time calculation.
- `calculate_day_stats` accepts only `NormalizedEvent`. Tests use
  `tests/conftest.py::make_event`. Production path: CalDAV dict →
  `normalize_caldav_event` → `NormalizedEvent`.

## Digest Layer

- `satellite/plan_service.py` — `PlanBuilder` (CalDAV → filter → optional weather
  → render). `PlanBuilder` не читает `users.json`; callers pass calendar identity
  and construct per-user `UserCalendarService` when needed.
- `satellite/analytics/service.py` — `build_week_analytics`.
- `satellite/analytics/render_card.py`, `caption.py` — PNG и подпись недельного отчёта.
- `satellite/visual_cards/base.py` — общие примитивы отрисовки (шрифты DejaVu, палитра).
- `satellite/seagull/digest.py` — `prepare_seagull_stats`, `render_digest_from_stats`.
- `satellite/seagull/rules.py` — text fragments from metrics.
- `satellite/seagull/render.py` — Telegram HTML, escaping, truncation;
  маркеры встреч через `event_index_marker` из
  [`calendar/events/_filters.py`](../satellite/calendar/events/_filters.py)
  (импорт через фасад `satellite.calendar.events`);
  неподтверждённые приглашения — `⚠️` вместо номера (`is_pending`).
- `satellite/seagull/templates.py` — text templates.

## Weather Layer

- `satellite/weather/client.py` — Open-Meteo HTTP client and TTL cache.
- `satellite/weather/analyzer.py` — aggregate hourly data and warnings.
- `satellite/weather/templates.py` — render weather line.
- `satellite/weather/models.py` — dataclasses.

Weather is optional. If it fails, `PlanBuilder` logs and renders calendar-only digest.

## Storage

### `logs/users.json` (`UserStore`)

Per-user access and calendar connection. See [configuration.md](configuration.md#пользователи-и-доступ-logsusersjson).

### `logs/subscriptions.json` (`SubscriptionStore`)

Per-user digest schedule:

```text
chat_id
telegram_user_id   # ключ в users.json для шедулера (не username)
username
digest_enabled
digest_days
digest_time
digest_timezone
subscribed_at
last_digest_sent_date
pending_digest_enabled
pending_digest_days         # weekdays | all_days | 7-bit mask
pending_digest_time         # default 10:00
pending_digest_timezone
last_pending_digest_sent_date
```

`unsubscribe` не удаляет запись — выставляет `digest_enabled=false`, настройки
сохраняются для повторного включения.

Writes are atomic: temporary file, flush, `fsync`, `os.replace`.

### `logs/connect-tokens.json` (`ConnectTokenStore`)

Краткоживущие токены для `/connect/<token>` из кнопок в чате (TTL 900 с).
Персист переживает рестарт бота; не коммитится. См.
[configuration.md](configuration.md#web-app-connect-токены).

## Scheduler

`satellite/scheduler.py` is a single background thread. It polls active
subscriptions every 30 seconds in each user's timezone.

Two independent per-user schedules live in the same `DigestSettings`
record:

1. **Daily plan** (`digest_enabled`, `digest_days`, `digest_time`,
   `last_digest_sent_date`) — `PlanBuilder.build_text` + `sendMessage`.
2. **Pending invitations** (`pending_digest_enabled`, `pending_digest_days`,
   `pending_digest_time`, `last_pending_digest_sent_date`) — same screen as
   `/invitations` via [`invitations_view.load_pending_invitations_screen`](../satellite/invitations_view.py)
   (inline keyboard included). If there are no NEEDS-ACTION meetings at fire
   time, the tick skips silently (no message, no `last_pending` mark).

Each kind fires only when enabled, day allowed, `HH:MM` matches, not already
sent today, and `has_calendar`. `last_*_sent_date` updates only after
successful `sendMessage`. One failed user does not stop the rest of the tick.

Per tick (daily):

```text
resolve_target_date("today", today in user digest_timezone)
  -> load UserRecord by chat_id / telegram_user_id
  -> skip if not has_calendar
  -> decrypt credentials, UserCalendarService, PlanBuilder.build_text(...)
```

Per tick (pending):

```text
load_pending_invitations_screen(calendar_service, user_id, tz)
  -> if pending empty: skip
  -> else sendMessage(text, reply_markup=keyboard)
```

## Web App HTTP

- `satellite/web/server.py` — `WebAppServer`, lifecycle `ThreadingHTTPServer` в
  фоновом потоке бота. Сам сервер не содержит хендлеров эндпоинтов: он строит
  `Deps` и делегирует роутинг.
- `satellite/web/routing.py` — таблица `(method, path) → handler`;
  добавление нового endpoint = одна запись в этом файле.
- `satellite/web/responses.py` — `json_response`, `png_response`, `AbortRequest`.
- `satellite/web/parsing.py` — `read_json`, `extract_init_data`, `*_token_from_path`,
  `parse_positive_int`, `parse_date`, `parse_datetime`, `serialize_event`.
- `satellite/web/auth.py` — `validated_user` (initData или connect-token +
  `UserStore.approved`).
- `satellite/web/connect_token.py` — `ConnectTokenStore`: issue/resolve,
  TTL 900 с, опционально `logs/connect-tokens.json`.
- `satellite/web/static_pages.py` — единая `serve_html` для `/connect`.
- `satellite/web/api/calendar.py` — REST-хендлеры календаря.
- `satellite/web/init_data.py` — HMAC-валидация Telegram `initData`
  (`InitDataError` с кодами `no_init_data`, `bad_signature`, `expired`).

Авторизация API (`validated_user` в `auth.py`): пользователь `approved` в
`UserStore`. Два пути:

1. **initData** (предпочтительно) — HMAC в `init_data.py`. Источники в порядке
   приоритета: заголовок `X-Telegram-Init-Data` (рекомендуется в nginx); поле
   `initData` в JSON-теле POST; query `?initData=...` (fallback, если прокси
   режет кастомные headers).
2. **Connect-token** — если `initData` нет: токен из path `/connect/<token>`,
   hash `#t=...`, JSON (`t` / `connect_token`) или query. Выдаётся ботом в
   `webapp_connect_url` ([`delivery.py`](../satellite/telegram_bot/handlers/delivery.py));
   store — [`connect_token.py`](../satellite/web/connect_token.py), TTL 15 мин,
   персист в `logs/connect-tokens.json`. Ответ `connect_token_invalid` — истёк
   или ссылка не из бота.

Клиент [`connect.html`](../satellite/web/static/connect.html) дублирует `initData`
и connect-token в заголовок, тело и query для всех API-запросов.

| Метод/путь | Назначение |
|------------|------------|
| `GET /healthz` | Docker HEALTHCHECK; без auth |
| `GET /connect`, `GET /connect/<token>` | SPA [`connect.html`](../satellite/web/static/connect.html) |
| `GET /api/calendar/status` | Статус подключения |
| `POST /api/calendar/connect` | Сохранить credentials (`provider`, `login`, `app_password`) |
| `DELETE /api/calendar/disconnect` | Сбросить подключение |
| `GET /api/calendar/events?from=&to=` | Список событий |
| `POST /api/calendar/events` | Создать событие |
| `DELETE /api/calendar/events/{uid}?url=` | Удалить событие |

`POST /api/calendar/connect` принимает `provider=mailru` (production);
`yandex` в API возвращает `PROVIDER_NOT_IMPLEMENTED` (backend готов, UI disabled).

HTTPS — задача reverse proxy на хосте (nginx/Caddy одинаково для Docker и systemd).
Проксируйте `/connect` и префикс `/api/calendar/` на `127.0.0.1:<satellite_host_port>`.

## Logging

`satellite/logging_setup.py` configures root logging once per process. Production
logs go to `logs/bot.log`.

The bot logs operational failures but sends users only safe, non-technical messages.

## Deployment (production)

Один процесс long-polling на токен. Варианты установки:

- **systemd** — `scripts/install-server.sh`, код и `venv` в `/opt/satellite`,
  `logs/` на диске хоста, Web App за внешним nginx/Caddy
  (`WEBAPP_HOST=127.0.0.1`).
- **Docker** — образ `ghcr.io/ksandrpetrov/satellite`, Ansible playbook
  (`make deploy`); внешний nginx на хосте терминирует TLS и проксирует
  `/connect`, `/api/calendar/*` на `127.0.0.1:<satellite_host_port>` (внутри
  контейнера `WEBAPP_HOST=0.0.0.0`, volume `satellite-logs` → `/app/logs`).

**CI/CD (Docker):** [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) на
push в `main` или тег `v*` — reusable `_checks.yml` (ruff + mypy + `py_compile` + pytest),
сборка в GHCR (`:sha-<short>`; `:latest` на main; semver на теге), затем
`scripts/docker-smoke-image.sh` (импорты, `caldav>=3`, `/healthz` в образе). Rolling update
контейнера на сервере (`scripts/ci-deploy-remote.sh`, `SATELLITE_IMAGE` в `.env`) — только
для `main` и `workflow_dispatch`: `compose pull/up`, ожидание `healthy`, host `/healthz`,
затем `scripts/smoke-prod.sh` с публичного URL (`SMOKE_PUBLIC_BASE_URL`, в Actions
по умолчанию не пустой; пустое значение отключает public smoke).
`logs/` и `TOKEN_ENCRYPTION_KEY` pipeline не трогает.

Состояние (`users.json`, `subscriptions.json`, offset, lock) всегда в `logs/`.
Подробности: [operations.md](operations.md), [deploy/README.md](../deploy/README.md).

---

**Далее:** [configuration.md](configuration.md) · [telegram-ux.md](telegram-ux.md) ·
[operations.md](operations.md) · [testing.md](testing.md)
