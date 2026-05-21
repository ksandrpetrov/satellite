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
  plan_service.py        # PlanBuilder (не читает users.json) + build_day_stats
  share_service.py       # build_share_png (plan / upcoming / analytics)
  share/
    cards.py             # render_plan_share_card, render_upcoming_share_card
  visual_cards/
    base.py              # палитра, шрифты, примитивы PNG (план, upcoming, аналитика)
  scheduler.py           # DigestScheduler
  subscriptions.py       # SubscriptionStore → logs/subscriptions.json
  logging_setup.py
  messages_ru/           # ВСЕ user-facing тексты (пакет: __init__ = фасад, _core = реализация)
    __init__.py          # реэкспорт публичного API; импорты не меняются
    _core.py             # текстовые константы, keyboard builders, helpers

  analytics/             # недельная аналитика
    service.py           # build_week_analytics (raw → отчёт → PNG + подпись)
    caption.py, render_card.py, period_stats — см. calendar/

  calendar/
    providers/             # Mail.ru + Yandex, registry
    user_calendar_service.py  # единый фасад для handlers/plan/scheduler/Web App
    operation_log.py       # audit CalDAV-операций
    caldav_client.py       # Mail.ru CalDAV (per-user login/password)
    events.py, stats.py, selection.py, time_utils.py, ical_parser.py, constants.py

  web/                   # пакет: тонкий router + per-endpoint модули
    server.py            # WebAppServer (lifecycle), делегирует роутинг
    routing.py           # таблица (method, path) → handler
    responses.py         # json_response / png_response / AbortRequest
    parsing.py           # read_json, extract_init_data, *_token, parse_*
    auth.py              # validated_user (initData + UserStore)
    static_pages.py      # serve_html для /connect, /share
    init_data.py         # HMAC validate_init_data
    api/
      calendar.py        # /api/calendar/* (status/connect/disconnect/events)
      share.py           # /api/share/card → PNG
    static/connect.html, static/share.html

  seagull/               # digest, rules, render, templates
  weather/               # client, analyzer, templates, models

  telegram_bot/
    bot.py               # lifecycle, scheduler, WebAppServer
    handlers/
      dispatch.py        # data-driven routing + access gating (см. _MESSAGE_ROUTES)
      routing.py         # recognize_message — таблица матчеров _RECOGNIZERS
      partstat_flow.py   # общий PARTSTAT-флоу для invitations и manage
      calendar_view.py   # общие хелперы списка календарей (sources/foreign/hub)
      delivery.py, context.py  # context.py: HandlerContext + role-based views
      access.py, admin.py
      settings_hub.py    # inline-хаб «Настройки»
      calendar_setup.py  # connect / check / disconnect
      calendar_list.py   # /upcoming
      calendar_sources.py # календари в плане/дайджесте
      calendar_foreign.py   # чужие (пошаренные) календари
      calendar_invitations.py # /invitations — тонкий адаптер над partstat_flow
      calendar_manage.py    # /manage — тонкий адаптер над partstat_flow
      calendar_create.py    # /create FSM
      digest_state.py, calendar_state.py  # FSM-сторы (in-memory)
      plan.py, settings.py, subscription.py, analytics.py
    api.py, message_editing.py, streaming_delivery.py, visual.py, commands.py
    offset_store.py, offset_tracker.py
    concurrency.py, instance_lock.py
    # shims (back-compat): calendar_state.py, digest_state.py — re-export из handlers/
```

## Где менять что (типичные правки)

| Хочу поменять | Куда смотреть |
|---------------|---------------|
| Текст любого сообщения пользователю | [`messages_ru/`](satellite/messages_ru/) (фасад в `__init__.py`, реализация в `_core.py`), [`seagull/templates.py`](satellite/seagull/templates.py) |
| Логику дайджеста (метрики) | [`calendar/stats.py`](satellite/calendar/stats.py) |
| Финальный рендер | [`seagull/render.py`](satellite/seagull/render.py), [`seagull/rules.py`](satellite/seagull/rules.py) |
| Команду / кнопку | [`recognize_message`](satellite/telegram_bot/handlers/routing.py) → запись в `_RECOGNIZERS`; маршрутизация — [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py) (`_MESSAGE_ROUTES`, `_CALLBACK_ROUTERS`) |
| Хаб настроек / дайджест | [`handlers/settings_hub.py`](satellite/telegram_bot/handlers/settings_hub.py) (роутер всех `CB_SETTINGS_*` / `CB_ANALYTICS_*`), [`handlers/settings.py`](satellite/telegram_bot/handlers/settings.py) (экран дайджеста) |
| Чужие (пошаренные) календари | [`handlers/calendar_foreign.py`](satellite/telegram_bot/handlers/calendar_foreign.py) |
| Список CalDAV-календарей в UI | [`handlers/calendar_view.py`](satellite/telegram_bot/handlers/calendar_view.py) — `fetch_calendars` (→ `CalendarListResult`) и `build_calendar_sources_screen` |
| Какие календари в плане | [`handlers/calendar_sources.py`](satellite/telegram_bot/handlers/calendar_sources.py), поле `enabled_calendar_urls` в [`users.py`](satellite/users.py) |
| URL Web App connect | [`handlers/delivery.py`](satellite/telegram_bot/handlers/delivery.py) — `webapp_connect_url(ctx)` |
| URL Web App «Поделиться» | [`delivery.py`](satellite/telegram_bot/handlers/delivery.py) — `webapp_share_url`, `share_reply_markup`; PNG — [`share_service.py`](satellite/share_service.py), [`share/cards.py`](satellite/share/cards.py), [`visual_cards/base.py`](satellite/visual_cards/base.py) |
| Потоковый ответ (черновик + финал) | [`streaming_delivery.py`](satellite/telegram_bot/streaming_delivery.py), [`handlers/delivery.py`](satellite/telegram_bot/handlers/delivery.py) — `open_streaming_reply` |
| Визуал Telegram (typing, effects, меню) | [`visual.py`](satellite/telegram_bot/visual.py) — `TypingIndicator`, `pick_plan_message_effect`, `set_default_menu_button_for_chat`; HTML — [`html_format.py`](satellite/telegram_bot/html_format.py); профиль бота на старте — [`commands.py`](satellite/telegram_bot/commands.py) `setup_bot_identity` |
| Расписание дайджеста | [`scheduler.py`](satellite/scheduler.py) + [`subscriptions.py`](satellite/subscriptions.py) |
| Доступ, заявки, календарь пользователя | [`users.py`](satellite/users.py), шифрование — [`security/token_vault.py`](satellite/security/token_vault.py) |
| Web App connect | handlers + HTTP в [`bot.py`](satellite/telegram_bot/bot.py); env — [`config.py`](satellite/config.py) |
| Дату дайджеста (mode→дата) | [`digest_utils.py`](satellite/digest_utils.py) |
| Парсинг .env | [`config.py`](satellite/config.py), образец [`.env.example`](.env.example) |
| CalDAV / провайдеры | [`calendar/caldav_client.py`](satellite/calendar/caldav_client.py), [`calendar/providers/`](satellite/calendar/providers/), [`user_calendar_service.py`](satellite/calendar/user_calendar_service.py) |
| Список / создание событий в боте | [`handlers/calendar_list.py`](satellite/telegram_bot/handlers/calendar_list.py), [`calendar_create.py`](satellite/telegram_bot/handlers/calendar_create.py); формат строк — [`events.py`](satellite/calendar/events.py) |
| Приглашения (NEEDS-ACTION, ответ в CalDAV) | [`handlers/calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py), [`events.py`](satellite/calendar/events.py) (`collect_pending_invitations`, `is_pending_invitation_for_user`), [`user_calendar_service.py`](satellite/calendar/user_calendar_service.py) (`list_events_for_invitations`, `set_attendee_partstat`), [`caldav_client.py`](satellite/calendar/caldav_client.py) (PARTSTAT refresh/update) |
| «Изменить статус встречи» (любой PARTSTAT) | [`handlers/calendar_manage.py`](satellite/telegram_bot/handlers/calendar_manage.py), [`events.py`](satellite/calendar/events.py) (`collect_manageable_events`) — список + детальный экран по встрече, действия завязаны на тот же `set_attendee_partstat` |
| Ввод времени (дайджест, /create) | [`time_utils.py`](satellite/calendar/time_utils.py); подсказки — [`messages_ru.py`](satellite/messages_ru.py) |
| Нумерация встреч (дайджест, /upcoming) | [`event_index_marker`](satellite/calendar/events.py) |
| Web App REST API | [`web/api/calendar.py`](satellite/web/api/calendar.py), [`web/api/share.py`](satellite/web/api/share.py); регистрация маршрута — [`web/routing.py`](satellite/web/routing.py); сам сервер — [`web/server.py`](satellite/web/server.py) |
| Сборку текста плана | [`plan_service.py`](satellite/plan_service.py) — callers передают calendar identity; статистика дня — `PlanBuilder.build_day_stats` (тот же путь, что и share/digest) |
| Недельную аналитику (PNG + подпись) | [`analytics/service.py`](satellite/analytics/service.py) (canonical путь; `satellite/analytics_service.py` — shim для back-compat), [`calendar/period_stats.py`](satellite/calendar/period_stats.py), [`calendar/event_kinds.py`](satellite/calendar/event_kinds.py), [`handlers/analytics.py`](satellite/telegram_bot/handlers/analytics.py) |
| Ответ на встречу (PARTSTAT) | [`handlers/partstat_flow.py`](satellite/telegram_bot/handlers/partstat_flow.py) — общий флоу; [`calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py) и [`calendar_manage.py`](satellite/telegram_bot/handlers/calendar_manage.py) — тонкие адаптеры |
| PNG-карточку (план / upcoming / аналитика) | [`visual_cards/base.py`](satellite/visual_cards/base.py) — единая палитра/шрифты/логотип; per-kind — `share/cards.py` и `analytics/render_card.py` (импортируют примитивы) |
| JSON-store мутацию (users / subscriptions) | [`users.py`](satellite/users.py) (`_update_locked`, `UserRecord.{to,from}_json`) и [`subscriptions.py`](satellite/subscriptions.py) (`_upsert_locked`, `DigestSettings.{to,from}_json`); прямой `replace()` не использовать |
| Контекст хендлера (роли) | [`handlers/context.py`](satellite/telegram_bot/handlers/context.py) — `HandlerContext` + view-свойства `.messaging` / `.identity` / `.calendar` / `.scheduling`; для access — `ensure_calendar_*` принимает `chat_id` / `user_id` явно, без `IncomingMessage`-фейков |
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
14. **Перед коммитом** — `make check` (ruff lint + mypy + py_compile + pytest). Стиль/форматирование — только [`ruff`](pyproject.toml) (lint + format); blackd/isort не используем.

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
- Прямые строки в хендлерах — все user-facing тексты в [`messages_ru/`](satellite/messages_ru/) (импорт через корневой фасад).
- Свой `_webapp_url` в хендлерах — только [`delivery.webapp_connect_url`](satellite/telegram_bot/handlers/delivery.py).
- Lazy-back-импорты `settings_hub` из `settings`/`analytics` для «Назад» — навигация только в хабе (см. инвариант 12).
- Прямой `<blockquote>` / `<tg-emoji>` в хендлерах — только [`html_format.py`](satellite/telegram_bot/html_format.py); fallback при отказе Telegram — в [`api.py`](satellite/telegram_bot/api.py), не дублировать в сценариях.
- Свой retry без `<tg-emoji>` в хендлерах — только `TelegramClient.send_message` / `edit_message_text`.
- Дублирование PARTSTAT-логики в [`calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py) / [`calendar_manage.py`](satellite/telegram_bot/handlers/calendar_manage.py) — общий флоу только в [`partstat_flow.py`](satellite/telegram_bot/handlers/partstat_flow.py).
- Параллельный PNG-render (своя палитра/шрифты/`_load_font`/`_paste_brand_logo`) — все примитивы только в [`visual_cards/base.py`](satellite/visual_cards/base.py).
- Прямой mutate `UserRecord`/`DigestSettings` в `users.json`/`subscriptions.json` без `_update_locked` / `_upsert_locked` — атомарность теряется.
- Параллельный путь сбора `DayCalendarStats` (свой `fetch_events_for_day` + `prepare_seagull_stats`) — только [`PlanBuilder.build_day_stats`](satellite/plan_service.py).
- `isinstance(..., RecognizedFoo)` / `if/elif` для роутинга команд и callback'ов — только таблицы `_MESSAGE_ROUTES` / `_CALLBACK_ROUTERS` в [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py).
- `_msg_from_cb` или фабрикация `IncomingMessage` ради `ensure_calendar_connected` — функция принимает `chat_id` / `user_id` напрямую.
- `do_create()` или подобные обёртки в хендлерах ради единственного `try/except` — снимать без потери поведения.
- Импорт `from satellite.analytics_service import ...` — canonical путь теперь [`satellite.analytics.service`](satellite/analytics/service.py); shim оставлен только для back-compat.

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
python -m ruff check satellite tests              # make lint
python -m ruff format satellite tests             # make format
python -m mypy satellite                          # make typecheck (информативно)
find satellite tests -name '*.py' ! -name '._*' -print0 | xargs -0 python -m py_compile  # make compile
make check                                        # lint + typecheck + compile + test (full)
python telegram_test_command.py                   # make run
```

Опционально: `pre-commit install` подтянет ruff/ruff-format/mypy в git-hook
(см. [`.pre-commit-config.yaml`](.pre-commit-config.yaml)).

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
| `GET /connect` | SPA [`connect.html`](satellite/web/static/connect.html) |
| `GET /share`, `GET /share/{token}` | SPA [`share.html`](satellite/web/static/share.html) |
| `GET /api/share/card?kind=&mode=&days=` | PNG-карточка (`kind`: `plan` \| `upcoming` \| `analytics`; для `plan` — `mode`: `today` \| `tomorrow` \| `day_after_tomorrow`) |
| `GET /api/calendar/status` | Проверка подключения |
| `POST /api/calendar/connect` | Сохранить credentials (Fernet через `TokenVault`) |
| `DELETE /api/calendar/disconnect` | Сбросить подключение |
| `GET /api/calendar/events?from=&to=` | Список событий |
| `POST /api/calendar/events` | Создать событие |
| `DELETE /api/calendar/events/{uid}?url=` | Удалить событие |

HTTPS не делает сам сервер — это задача reverse proxy (Traefik в
production, ngrok/Cloudflare Tunnel в dev). Проксируйте `/connect`, `/share`
и префиксы `/api/calendar/`, `/api/share/` (см. [operations.md](docs/operations.md)).

## Runtime-артефакты

| Файл | Назначение |
|------|------------|
| `logs/bot.log` | Production-логи |
| `logs/bot.lock` | Единственный инстанс |
| `logs/telegram-offset.json` | Watermark long-polling |
| `logs/subscriptions.json` | Per-user дайджест |
| `logs/users.json` | Доступ + зашифрованные CalDAV-credentials |
| `logs/backups/` | Снапшоты `users.json`/`subscriptions.json` на каждый старт ([`backup.py`](satellite/backup.py)) — last 20, имя `<file>.YYYYMMDD-HHMMSSZ.bak` |
| `.env` | См. [`.env.example`](.env.example); должен быть `chmod 600` |

Все в `.gitignore`.

### Сохранность данных между деплоями

`logs/` и `.env` не коммитятся и не трогаются ни одним из скриптов
([`scripts/install.sh`](scripts/install.sh) / [`scripts/install-server.sh`](scripts/install-server.sh) / `make deploy`).
Стандартный апдейт-цикл (`git pull && systemctl restart satellite-bot.service`
или `make deploy`) сохраняет per-user настройки: `users.json` и
`subscriptions.json` живут в `logs/`, на старте бот снапшотит их в
`logs/backups/`. В журнале при старте появляется строка
`Persistence loaded: users total=… approved=… connected=… subscriptions total=… active=… key_fingerprint=…` —
по `key_fingerprint` (sha256[0:8]) видно, что `TOKEN_ENCRYPTION_KEY` не сменился.
Если хоть один approved-пользователь не расшифровывается текущим ключом,
[`bot.py`](satellite/telegram_bot/bot.py) пишет `CRITICAL Encryption self-check failed`.
