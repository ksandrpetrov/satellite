# Архитектура

Проект остается в пакете `satellite/`. Перенос в `src/` сейчас не нужен: серверные
entrypoint уже используют текущие импорты, а структура пакета достаточно
модульная для production-поддержки.

## Слои

```text
entrypoints
  -> services / TelegramBot lifecycle
  -> telegram handlers (+ Web App HTTP)
  -> domain services (users, subscriptions, plan)
  -> calendar / weather clients (per-user CalDAV)
  -> renderers and templates
```

Handlers принимают Telegram-события и не считают календарную аналитику сами.
Бизнес-логика живет в сервисах и чистых модулях.

Вспомогательные модули верхнего уровня:

- `satellite/services.py` — `run_bot`.
- `satellite/config.py` — `load_settings`, dataclasses конфигов, парсинг `.env`.
- `satellite/users.py` — `UserStore`: доступ, заявки, per-user CalDAV в `logs/users.json`.
- `satellite/security/token_vault.py` — Fernet-шифрование credentials.
- `satellite/digest_utils.py` — `resolve_target_date`, `is_digest_day_allowed`.
- `satellite/messages_ru.py` — все user-facing тексты и константы callback data.

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
  -> CalDAVService(login, app_password) per request / per user
  -> PlanBuilder.build_text(calendar_name или primary URL — политика вызывающего)
  -> filter_events_for_user (visible + hidden meals)
  -> prepare_seagull_stats   (normalize_caldav_event only)
  -> render_digest_from_stats (rules + render_daily_digest)
  -> weather summary, if enabled
  -> edit_or_send_message
```

Доступ:

1. Новый пользователь: `/start` → запись в `users.json`, заявка `pending`.
2. Админ (`ADMIN_TELEGRAM_IDS`): `/pending` → approve/reject.
3. Одобренный пользователь: Web App → encrypted credentials + `primary_calendar_url`.
4. Команды плана и дайджест — только при `UserRecord.has_calendar`.

## Users and Security

- `satellite/users.py` — `UserStore`, `UserRecord`, статусы доступа и календаря.
  Атомарная запись JSON, thread-safe lock. Не хранит сырые токены и display name
  календаря (PII).
- `satellite/security/token_vault.py` — `TokenVault`, `ProviderCredentials`
  (login + app password Mail.ru). Ключ — `TOKEN_ENCRYPTION_KEY` из env.

## Telegram Layer

- `satellite/telegram_bot/bot.py` — lifecycle, long-polling, offset, worker pool,
  scheduler start/stop, graceful shutdown, Web App server bind.
- `satellite/telegram_bot/handlers/` — package with one scenario per file:
  - `context.py` — `HandlerContext` and DTOs.
  - `routing.py` — pure parsers.
  - `delivery.py` — send/edit/answer, `notify_handler_failure`.
  - `dispatch.py` — message and callback entrypoints, access gating.
  - `plan.py` — command → plan → reply.
  - `subscription.py` — subscribe/unsubscribe.
  - `settings.py` — digest settings screens and callbacks.
- `satellite/telegram_bot/api.py` — Bot API client, retries, token sanitizing.
- `satellite/telegram_bot/chat_action.py` — `typing` during long operations.
- `satellite/telegram_bot/message_editing.py` — edit loading message, fallback.
- `satellite/telegram_bot/digest_state.py` — in-memory state for time input.
- `satellite/telegram_bot/commands.py` — menu command registration.
- `satellite/telegram_bot/concurrency.py` — `ChatLockManager`, `InflightTracker`.
- `satellite/telegram_bot/instance_lock.py` — single-instance `fcntl` lock.
- `satellite/telegram_bot/offset_store.py` / `offset_tracker.py` — long-polling
  watermark (do not change without dedicated tests).

## Calendar Layer

- `satellite/calendar/caldav_client.py` — Mail.ru CalDAV discovery, cache, day
  search, optional PARTSTAT refresh.
- `satellite/calendar/constants.py` — domain constants (lunch marker, all-day label).
- `satellite/calendar/events.py` — filters, all-day, declined, meals, PARTSTAT.
- `satellite/calendar/stats.py` — `NormalizedEvent`, `DayCalendarStats`,
  `normalize_caldav_event`. Default workday `10:00–19:00`, lunch `13:00–14:00`.
- `satellite/calendar/time_utils.py` — `HH:MM` parsing, interval merge, free slots.

Important invariants:

- Overlapping intervals are merged before busy-time calculation.
- `calculate_day_stats` accepts only `NormalizedEvent`. Tests use
  `tests/conftest.py::make_event`. Production path: CalDAV dict →
  `normalize_caldav_event` → `NormalizedEvent`.

## Digest Layer

- `satellite/plan_service.py` — `PlanBuilder` (CalDAV → filter → optional weather
  → render). `PlanBuilder` не читает `users.json`; callers pass calendar identity
  and construct per-user `CalDAVService` when needed.
- `satellite/seagull/digest.py` — `prepare_seagull_stats`, `render_digest_from_stats`.
- `satellite/seagull/rules.py` — text fragments from metrics.
- `satellite/seagull/render.py` — Telegram HTML, escaping, truncation.
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
username
digest_enabled
digest_days
digest_time
digest_timezone
subscribed_at
last_digest_sent_date
```

Writes are atomic: temporary file, flush, `fsync`, `os.replace`.

## Scheduler

`satellite/scheduler.py` is a single background thread. It polls active
subscriptions every 30 seconds in each user's timezone.

It sends only when:

- `digest_enabled` is true;
- day is allowed by `digest_days`;
- current `HH:MM` equals `digest_time`;
- `last_digest_sent_date` is not today;
- user has connected calendar in `UserStore` (`has_calendar`).

`last_digest_sent_date` updates only after successful Telegram `sendMessage`.
One failed user does not stop the rest of the tick.

Per tick:

```text
resolve_target_date(DIGEST_MODE, today in user timezone)
  -> load UserRecord by chat_id / telegram_user_id
  -> skip if not has_calendar
  -> decrypt credentials, CalDAV fetch, PlanBuilder.build_text(...)
```

## Logging

`satellite/logging_setup.py` configures root logging once per process. Production
logs go to `logs/bot.log`.

The bot logs operational failures but sends users only safe, non-technical messages.
