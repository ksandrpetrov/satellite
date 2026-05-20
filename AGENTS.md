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
    providers/             # Mail.ru + Yandex skeleton, registry
    user_calendar_service.py
    caldav_client.py       # Mail.ru CalDAV (per-user login/password)
    events.py, stats.py, time_utils.py, ical_parser.py, constants.py

  web/                     # Telegram Web App: initData, HTTP server, connect.html

  seagull/               # digest, rules, render, templates
  weather/               # client, analyzer, templates, models

  telegram_bot/
    bot.py               # lifecycle, scheduler, WebAppServer
    handlers/
      dispatch.py        # routing + access gating
      access.py, admin.py, calendar_*.py
      plan.py, settings.py, subscription.py
    api.py, chat_action.py, message_editing.py, commands.py
    digest_state.py, offset_store.py, offset_tracker.py
    concurrency.py, instance_lock.py
```

## Где менять что (типичные правки)

| Хочу поменять | Куда смотреть |
|---------------|---------------|
| Текст любого сообщения пользователю | [`messages_ru.py`](satellite/messages_ru.py), [`seagull/templates.py`](satellite/seagull/templates.py) |
| Логику дайджеста (метрики) | [`calendar/stats.py`](satellite/calendar/stats.py) |
| Финальный рендер | [`seagull/render.py`](satellite/seagull/render.py), [`seagull/rules.py`](satellite/seagull/rules.py) |
| Команду / кнопку | [`handlers/routing.py`](satellite/telegram_bot/handlers/routing.py) + [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py) |
| Настройки дайджеста | [`handlers/settings.py`](satellite/telegram_bot/handlers/settings.py) |
| Расписание дайджеста | [`scheduler.py`](satellite/scheduler.py) + [`subscriptions.py`](satellite/subscriptions.py) |
| Доступ, заявки, календарь пользователя | [`users.py`](satellite/users.py), шифрование — [`security/token_vault.py`](satellite/security/token_vault.py) |
| Web App connect | handlers + HTTP в [`bot.py`](satellite/telegram_bot/bot.py); env — [`config.py`](satellite/config.py) |
| Дату дайджеста (mode→дата) | [`digest_utils.py`](satellite/digest_utils.py) |
| Парсинг .env | [`config.py`](satellite/config.py), образец [`.env.example`](.env.example) |
| CalDAV | [`calendar/caldav_client.py`](satellite/calendar/caldav_client.py) |
| Сборку текста плана | [`plan_service.py`](satellite/plan_service.py) — callers передают calendar identity |

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

## Антипаттерны

- Глобальные `MAIL_LOGIN` / `USER_CALENDAR_MAP` — удалены из `config.py`.
- Свой парсер `HH:MM` — только [`time_utils.parse_hhmm`](satellite/calendar/time_utils.py)
  / [`normalize_hhmm_input`](satellite/calendar/time_utils.py).
- Inline render дайджеста вне [`seagull/digest.py`](satellite/seagull/digest.py).
- Fallback `edit` → `send` в callback-хендлерах — дубли ([`delivery.py`](satellite/telegram_bot/handlers/delivery.py)).
- Второй путь нормализации событий — только `normalize_caldav_event`.
- `DIGEST_TIME` / `DIGEST_WEEKDAYS_ONLY` в env — удалены; время в `subscriptions.json`.

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

Серверная установка: `sudo bash scripts/install-server.sh`
(см. [docs/operations.md](docs/operations.md#запуск-на-сервере)).

CI: [`.github/workflows/test.yml`](.github/workflows/test.yml). Образ в GHCR:
[`.github/workflows/release-docker.yml`](.github/workflows/release-docker.yml) (на GitHub Release).
Деплой Docker: `make deploy` → [`deploy/README.md`](deploy/README.md).

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
