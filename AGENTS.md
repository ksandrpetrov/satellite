# AGENTS.md

Карта проекта для AI-агентов и людей, которые правят код впервые. Цель —
сократить стоимость «вкатывания» и не дать агенту переоткрывать одни и те же
файлы каждую сессию.

Подробная архитектура: [docs/architecture.md](docs/architecture.md).

## Что это

Production Telegram-бот «Чайка». CalDAV → расчёт метрик дня → HTML-дайджест в
Telegram, опционально с погодой. Per-user расписание дайджеста и per-user
подключение календаря (зашифрованные credentials в `logs/users.json`).

## Точки входа

| Файл | Назначение |
|------|------------|
| `telegram_test_command.py` | Production long-polling бот. **Единственный**. |

Тонкий шит, вся логика в `satellite.services.run_bot`.

## Карта модулей

```
satellite/
  services.py            # run_bot
  config.py              # load_settings; SecurityConfig, AdminConfig, WebAppConfig
  users.py               # UserStore, UserRecord, access + calendar connection
  security/
    token_vault.py       # Fernet encrypt/decrypt ProviderCredentials
  digest_utils.py        # resolve_target_date, is_digest_day_allowed
  plan_service.py        # PlanBuilder (не читает users.json)
  scheduler.py           # DigestScheduler
  subscriptions.py       # SubscriptionStore → logs/subscriptions.json
  logging_setup.py
  messages_ru.py         # ВСЕ user-facing тексты

  calendar/
    providers/             # Mail.ru + Yandex, registry
    user_calendar_service.py  # единый фасад для handlers/plan/scheduler/Web App
    operation_log.py       # audit CalDAV-операций
    caldav_client.py       # Mail.ru CalDAV (per-user login/password)
    events.py, stats.py, selection.py, time_utils.py, ical_parser.py, constants.py

  web/
    init_data.py           # HMAC validate_init_data
    server.py              # ThreadingHTTPServer, /connect, /api/calendar/*
    static/connect.html    # SPA

  seagull/               # digest, rules, render, templates
  weather/               # client, analyzer, templates, models

  telegram_bot/
    bot.py               # lifecycle, scheduler, WebAppServer
    handlers/
      dispatch.py        # routing + access gating
      routing.py         # recognize_message — единая точка правды для команд
      calendar_view.py   # общие хелперы списка календарей (sources/foreign/hub)
      delivery.py, context.py
      access.py, admin.py
      settings_hub.py    # inline-хаб «Настройки»
      calendar_setup.py  # connect / check / disconnect
      calendar_list.py   # /upcoming
      calendar_sources.py # календари в плане/дайджесте
      calendar_foreign.py # чужие (пошаренные) календари
      calendar_invitations.py # /invitations, PARTSTAT ACCEPTED/DECLINED/TENTATIVE
      calendar_create.py # /create FSM
      plan.py, settings.py, subscription.py
    api.py, chat_action.py, message_editing.py, commands.py
    digest_state.py, calendar_state.py
    offset_store.py, offset_tracker.py
    concurrency.py, instance_lock.py
```

## Где менять что (типичные правки)

| Хочу поменять | Куда смотреть |
|---------------|---------------|
| Текст любого сообщения пользователю | [`messages_ru.py`](satellite/messages_ru.py), [`seagull/templates.py`](satellite/seagull/templates.py) |
| Логику дайджеста (метрики) | [`calendar/stats.py`](satellite/calendar/stats.py) |
| Финальный рендер | [`seagull/render.py`](satellite/seagull/render.py), [`seagull/rules.py`](satellite/seagull/rules.py) |
| Команду / кнопку | [`recognize_message`](satellite/telegram_bot/handlers/routing.py) → [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py) |
| Хаб настроек / дайджест | [`handlers/settings_hub.py`](satellite/telegram_bot/handlers/settings_hub.py) (роутер всех `CB_SETTINGS_*` / `CB_ANALYTICS_*`), [`handlers/settings.py`](satellite/telegram_bot/handlers/settings.py) (экран дайджеста) |
| Чужие (пошаренные) календари | [`handlers/calendar_foreign.py`](satellite/telegram_bot/handlers/calendar_foreign.py) |
| Список CalDAV-календарей в UI | [`handlers/calendar_view.py`](satellite/telegram_bot/handlers/calendar_view.py) — `fetch_calendars` (→ `CalendarListResult`) и `build_calendar_sources_screen` |
| Какие календари в плане | [`handlers/calendar_sources.py`](satellite/telegram_bot/handlers/calendar_sources.py), поле `enabled_calendar_urls` в [`users.py`](satellite/users.py) |
| URL Web App connect | [`handlers/delivery.py`](satellite/telegram_bot/handlers/delivery.py) — `webapp_connect_url(ctx)` |
| Расписание дайджеста | [`scheduler.py`](satellite/scheduler.py) + [`subscriptions.py`](satellite/subscriptions.py) |
| Доступ, заявки, календарь пользователя | [`users.py`](satellite/users.py), шифрование — [`security/token_vault.py`](satellite/security/token_vault.py) |
| Web App connect | handlers + HTTP в [`bot.py`](satellite/telegram_bot/bot.py); env — [`config.py`](satellite/config.py) |
| Дату дайджеста (mode→дата) | [`digest_utils.py`](satellite/digest_utils.py) |
| Парсинг .env | [`config.py`](satellite/config.py), образец [`.env.example`](.env.example) |
| CalDAV / провайдеры | [`calendar/caldav_client.py`](satellite/calendar/caldav_client.py), [`calendar/providers/`](satellite/calendar/providers/), [`user_calendar_service.py`](satellite/calendar/user_calendar_service.py) |
| Список / создание событий в боте | [`handlers/calendar_list.py`](satellite/telegram_bot/handlers/calendar_list.py), [`calendar_create.py`](satellite/telegram_bot/handlers/calendar_create.py); формат строк — [`events.py`](satellite/calendar/events.py) |
| Приглашения (NEEDS-ACTION, ответ в CalDAV) | [`handlers/calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py), [`events.py`](satellite/calendar/events.py) (`collect_pending_invitations`, `is_pending_invitation_for_user`), [`user_calendar_service.py`](satellite/calendar/user_calendar_service.py) (`list_events_for_invitations`, `set_attendee_partstat`), [`caldav_client.py`](satellite/calendar/caldav_client.py) (PARTSTAT refresh/update) |
| Ввод времени (дайджест, /create) | [`time_utils.py`](satellite/calendar/time_utils.py); подсказки — [`messages_ru.py`](satellite/messages_ru.py) |
| Нумерация встреч (дайджест, /upcoming) | [`event_index_marker`](satellite/calendar/events.py) |
| Web App REST API | [`web/server.py`](satellite/web/server.py) |
| Сборку текста плана | [`plan_service.py`](satellite/plan_service.py) — callers передают calendar identity |
| Недельную аналитику (PNG + подпись) | [`analytics_service.py`](satellite/analytics_service.py), [`calendar/period_stats.py`](satellite/calendar/period_stats.py), [`calendar/event_kinds.py`](satellite/calendar/event_kinds.py), [`handlers/analytics.py`](satellite/telegram_bot/handlers/analytics.py) |
| Диагностика CalDAV с сервера | [`scripts/diagnose_caldav.py`](scripts/diagnose_caldav.py) — см. [troubleshooting.md](docs/troubleshooting.md) |

## Инварианты — не нарушать

1. **Один рендер дайджеста** — [`PlanBuilder.build_text`](satellite/plan_service.py) +
   [`render_digest_from_stats`](satellite/seagull/digest.py).
2. **Секреты пользователей** — только зашифрованный blob в `users.json`;
   расшифровка через `TokenVault` на время CalDAV-запроса; не логировать login/password.
3. **Доступ** — `UserStore` единственный источник `status` / `has_calendar`;
   админы — `ADMIN_TELEGRAM_IDS` из env.
4. **Не считать stats в хендлерах** — только `PlanBuilder`.
5. **Дата дайджеста** — `resolve_target_date` / `is_digest_day_allowed`.
6. **Тексты** — `messages_ru.py` / шаблоны seagull/weather.
7. **Хендлеры не пробрасывают исключения** — safe text из `messages_ru`.
8. **Атомарная запись JSON-store** — `subscriptions.py` и `users.py`: tmp + fsync + os.replace`.
9. **`logs/`, `.env`, `venv/`** — не коммитим.
10. **Команды и кнопки** — только [`recognize_message`](satellite/telegram_bot/handlers/routing.py); любая распознанная команда сбрасывает FSM (`digest_state`, `calendar_state`) в [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py).
11. **Подписка на дайджест** — `DigestSettings.telegram_user_id` в [`subscriptions.py`](satellite/subscriptions.py); scheduler резолвит пользователя через `UserStore.get`, не через `username`.
12. **Навигация настроек** — кросс-экранные `CB_SETTINGS_*` / `CB_ANALYTICS_*` обрабатывает только [`settings_hub.py`](satellite/telegram_bot/handlers/settings_hub.py); `settings.py` и `analytics.py` не импортируют друг друга и не имеют lazy-back-импортов в хаб.
13. **Сбой `UserStore._save_locked`** — поднимает [`UserStorePersistenceError`](satellite/users.py); caller (handler / Web App) ловит на границе и показывает безопасный текст.

## Антипаттерны

- Глобальные `MAIL_LOGIN` / `USER_CALENDAR_MAP` — удалены из `config.py`.
- Свой парсер времени — только [`normalize_hhmm_input`](satellite/calendar/time_utils.py)
  (UI) и [`parse_hhmm`](satellite/calendar/time_utils.py) (минуты от полуночи;
  внутри делегирует в `normalize_hhmm_input`).
- Свои маркеры номеров встреч — только [`event_index_marker`](satellite/calendar/events.py)
  (дайджест и `/upcoming`).
- Inline render дайджеста вне [`seagull/digest.py`](satellite/seagull/digest.py).
- Fallback `edit` → `send` в callback-хендлерах — дубли ([`delivery.py`](satellite/telegram_bot/handlers/delivery.py)).
- Дублировать списки `is_*_request` / `parse_*` в `bot.py` или `dispatch.py` — только `recognize_message`.
- Импорт `_fetch_calendars` из `calendar_sources` в другие хендлеры — только [`calendar_view.py`](satellite/telegram_bot/handlers/calendar_view.py).
- Второй путь нормализации событий — только `normalize_caldav_event`.
- `DIGEST_TIME` / `DIGEST_WEEKDAYS_ONLY` в env — удалены; время в `subscriptions.json`.
- Прямые строки в хендлерах — все user-facing тексты в [`messages_ru.py`](satellite/messages_ru.py).
- Свой `_webapp_url` в хендлерах — только [`delivery.webapp_connect_url`](satellite/telegram_bot/handlers/delivery.py).
- Lazy-back-импорты `settings_hub` из `settings`/`analytics` для «Назад» — навигация только в хабе (см. инвариант 12).

## Не трогать без необходимости

- [`offset_tracker.py`](satellite/telegram_bot/offset_tracker.py) / [`offset_store.py`](satellite/telegram_bot/offset_store.py)
- [`bot.py`](satellite/telegram_bot/bot.py) lifecycle и worker pool
- [`caldav_client.py`](satellite/calendar/caldav_client.py) discovery / PARTSTAT
- [`calculate_day_stats`](satellite/calendar/stats.py) — точные числа busy/free

## Команды разработки

Первичная установка (создаст venv + поставит prod+dev зависимости + сгенерирует
`.env` с Fernet-ключом + создаст `logs/`):

```bash
bash scripts/install.sh --dev   # или: make install-dev
```

Дальше:

```bash
source venv/bin/activate
python -m pytest                                  # make test
find satellite tests -name '*.py' ! -name '._*' -print0 | xargs -0 python -m py_compile  # make compile
python telegram_test_command.py                   # make run
```

Сервер: **systemd** — `sudo bash scripts/install-server.sh`;
**Docker (prod)** — `make deploy` (см. [docs/operations.md](docs/operations.md#запуск-на-сервере),
[deploy/README.md](deploy/README.md));
**Docker (local)** — `make env && make docker-up` (см. корневой `docker-compose.yml`).

CI: [`.github/workflows/test.yml`](.github/workflows/test.yml). Образ в GHCR:
[`.github/workflows/release-docker.yml`](.github/workflows/release-docker.yml) (на GitHub Release).
Деплой Docker: `make deploy` → [`deploy/README.md`](deploy/README.md).

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| [`scripts/install.sh`](scripts/install.sh) | venv, зависимости, `.env` + Fernet, `logs/` |
| [`scripts/install-server.sh`](scripts/install-server.sh) | systemd на VPS (`/opt/satellite`) |
| [`scripts/bootstrap-server.sh`](scripts/bootstrap-server.sh) | apt + clone + `install-server.sh` на чистом хосте |
| [`scripts/diagnose_caldav.py`](scripts/diagnose_caldav.py) | CalDAV с сервера без Telegram (см. troubleshooting) |

## Web App

[`satellite/web/server.py`](satellite/web/server.py) — встроенный
`ThreadingHTTPServer`, поднимаемый из [`bot.py`](satellite/telegram_bot/bot.py).
Валидация сессии — [`init_data.py`](satellite/web/init_data.py).

Все запросы под `/api/calendar/*` авторизуются по Telegram `initData`
(HMAC) и фильтруются по `UserStore.status == approved`. `initData` берётся из
заголовка `X-Telegram-Init-Data`, JSON-тела или query `?initData=...`
(см. `_extract_init_data` в `server.py`).

`WEBAPP_BASE_URL` — только публичный HTTPS (проверка `is_valid_webapp_base_url`
в [`config.py`](satellite/config.py)); не путь к `connect.html` в репозитории.

Endpoint-ы:

| Метод/путь | Назначение |
|------------|------------|
| `GET /healthz` | Docker HEALTHCHECK; без auth |
| `GET /connect` | SPA-страница [`connect.html`](satellite/web/static/connect.html) |
| `GET /api/calendar/status` | Проверка подключения |
| `POST /api/calendar/connect` | Сохранить credentials (Fernet через `TokenVault`) |
| `DELETE /api/calendar/disconnect` | Сбросить подключение |
| `GET /api/calendar/events?from=&to=` | Список событий |
| `POST /api/calendar/events` | Создать событие |
| `DELETE /api/calendar/events/{uid}?url=` | Удалить событие |

HTTPS не делает сам сервер — это задача reverse proxy (Traefik в
production, ngrok/Cloudflare Tunnel в dev).

## Runtime-артефакты

| Файл | Назначение |
|------|------------|
| `logs/bot.log` | Production-логи |
| `logs/bot.lock` | Единственный инстанс |
| `logs/telegram-offset.json` | Watermark long-polling |
| `logs/subscriptions.json` | Per-user дайджест |
| `logs/users.json` | Доступ + зашифрованные CalDAV-credentials |
| `.env` | См. [`.env.example`](.env.example) |

Все в `.gitignore`.
