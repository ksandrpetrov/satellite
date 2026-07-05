# AGENTS.md

Карта проекта для AI-агентов и людей, которые правят код впервые. Цель —
сократить стоимость «вкатывания» и не дать агенту переоткрывать одни и те же
файлы каждую сессию.

Подробная архитектура: [docs/architecture.md](docs/architecture.md).
Полный индекс документации: [docs/README.md](docs/README.md).

## Содержание

- [Что это](#что-это)
- [Точки входа](#точки-входа)
- [Карта модулей](#карта-модулей)
- [Где менять что](#где-менять-что-типичные-правки)
- [Инварианты](#инварианты--не-нарушать)
- [Тесты и регрессии](#тесты-и-регрессии-для-агентов)
- [Антипаттерны](#антипаттерны)
- [Команды разработки](#команды-разработки)
- [Web App](#web-app)
- [Runtime-артефакты](#runtime-артефакты)

---

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
  backup.py              # снапшоты users.json / subscriptions.json при старте
  config.py              # load_settings; SecurityConfig, AdminConfig, WebAppConfig
  json_store.py          # JsonStoreBase — общая атомарная persistence для JSON-сторов
  users/                 # пакет: фасад + record (UserRecord) + store (UserStore) + admin (parse_admin_ids)
    __init__.py          # re-export публичного API (UserStore, UserRecord, USER_STATUS_*, …)
    record.py            # UserRecord (dataclass) + enum-константы + helpers парсинга
    store.py             # UserStore + UserStorePersistenceError (наследует JsonStoreBase)
    admin.py             # parse_admin_ids / admin_id_set (env → tuple[int])
  security/
    token_vault.py       # Fernet encrypt/decrypt ProviderCredentials
  digest_utils.py        # resolve_target_date, is_digest_day_allowed, маски дней
  invitations_view.py  # load_pending_invitations_screen (/invitations + scheduler)
  plan_service.py        # PlanBuilder (не читает users.json)
  visual_cards/
    base.py              # палитра, шрифты, примитивы PNG (аналитика)
  scheduler.py           # DigestScheduler lifecycle
  scheduler_policy.py    # should_fire_at / should_fire_for_user (чистая политика)
  subscriptions/           # пакет: фасад + record (DigestSettings) + store (SubscriptionStore)
    __init__.py
    record.py
    store.py             # SubscriptionStore (наследует JsonStoreBase)
  presentation/            # transport-agnostic HTML/Rich; canonical, шимов больше нет
    html.py              # legacy HTML: blockquote, tg-emoji, copy-кнопки, strip_*
    rich.py              # Rich Message HTML (Bot API 10.1)
    calendar_lists.py    # rich-списки /upcoming, /invitations, /manage
    delivery.py          # deliver/edit rich + fallback; единственный домен→telegram_bot.api
  logging_setup.py
  testing/               # хелперы для тестов (delivery_helpers)
  messages_ru/           # ВСЕ user-facing тексты (пакет: __init__ = фасад, подмодули по сценарию)
    __init__.py          # реэкспорт публичного API; импорты не меняются
    buttons.py, identity.py, access.py, admin_messages.py
    calendar_ui.py       # upcoming, create, sources, foreign
    settings_ui.py       # хаб настроек, аналитика, подэкран «Календарь», ERR_*
    digest_ui.py         # настройки дайджестов: daily + pending
    meetings_ui.py       # /invitations + /manage (PARTSTAT UI)
    plan_strings.py, duration.py, streaming_ui.py, tokens.py, webapp_ui.py

  analytics/             # недельная аналитика
    service.py           # build_week_analytics (raw → отчёт → PNG + подпись)
    caption.py, render_card.py, period_stats — см. calendar/

  calendar/
    duration_format.py # format_duration_long_ru (домен, без messages_ru)
    providers/             # Mail.ru + Yandex, registry
    user_calendar_service.py  # единый фасад для handlers/plan/scheduler/Web App
    operation_log.py       # audit CalDAV-операций
    caldav_client.py       # CalDAVService facade (discovery, CRUD)
    caldav_shared.py       # types, constants, helpers
    caldav_fetch_mixin.py  # range search / REPORT
    caldav_partstat_mixin.py  # PARTSTAT refresh + set_attendee_partstat
    conference_url.py    # извлечение ссылок на видеоконференции из CalDAV-события
    events/                # пакет: facade __init__ + _types + _time + _partstat + _filters + _collectors
    stats.py, selection.py, time_utils.py, ical_parser.py, constants.py

  web/                   # пакет: тонкий router + per-endpoint модули
    server.py            # WebAppServer (lifecycle), делегирует роутинг
    routing.py           # таблица (method, path) → handler
    responses.py         # json_response / AbortRequest
    parsing.py           # read_json, extract_init_data, *_token, parse_*
    auth.py              # validated_user (initData или connect-token + UserStore)
    connect_token.py     # ConnectTokenStore — краткоживущие токены Web App
    static_pages.py      # serve_html для /connect
    init_data.py         # HMAC validate_init_data
    api/
      calendar.py        # /api/calendar/* (status/connect/disconnect/events)
    static/connect.html

  seagull/               # digest, rules, render, templates
    conference.py        # подписи кнопок «Подключиться» (Meet/Zoom/Teams/…)
  weather/               # client, analyzer, templates, models

  telegram_bot/
    bot.py               # lifecycle, scheduler, WebAppServer
    update_dispatcher.py # worker pool + per-chat locks для updates
    startup_checks.py    # self-check шифрования и persistence на старте
    commands.py          # setup_bot_identity, меню команд
    visual.py            # TypingIndicator, message effects, menu button
    handlers/
      dispatch.py        # data-driven routing + access gating (см. _MESSAGE_ROUTES)
      routing.py         # recognize_message — таблица матчеров _RECOGNIZERS
      partstat_flow.py   # общий PARTSTAT-флоу для invitations и manage
      streaming_caldav.py # ActionGuard → streaming → CalDAV fetch (invitations, manage)
      action_guard.py    # ActionGuard — дедуп долгих действий (plan/upcoming/analytics/…)
      calendar_view.py   # общие хелперы списка календарей (sources/foreign/hub)
      delivery.py, context.py  # context.py: HandlerContext + role-based views
      access.py, access_notifications.py, admin.py
      settings_hub.py    # inline-хаб «Настройки» (роутер CB_SETTINGS_* / CB_ANALYTICS_*)
      settings.py        # фасад: re-export settings_bindings + settings_callbacks
      settings_bindings.py   # BINDINGS: daily/pending дайджест как data-driven таблица
      settings_callbacks.py  # экраны и колбэки настроек дайджестов
      settings_actions.py    # действия хаба (weather toggle, …)
      calendar_setup.py  # connect / check / disconnect
      calendar_actions.py # переиспользуемые calendar-действия (check, disconnect)
      calendar_list.py   # /upcoming
      calendar_sources.py # календари в плане/дайджесте
      calendar_foreign.py   # чужие (пошаренные) календари
      calendar_invitations.py # /invitations — тонкий адаптер над partstat_flow
      calendar_manage.py    # /manage — тонкий адаптер над partstat_flow
      calendar_create.py    # /create FSM
      digest_state.py, calendar_state.py  # FSM-сторы (in-memory)
      plan.py, subscription.py, analytics.py
    presenters/            # ScreenBundle (rich + fallback) для экранов бота
      bundle.py            # dataclass ScreenBundle
      settings_screens.py  # бандлы хаба/дайджестов/аналитики
      calendar_screens.py  # бандлы calendar sources / foreign
    api/                   # TelegramClient (client.py) + errors (errors.py); фасад __init__.py
    streaming/             # helpers.py + session.py (StreamingReply)
    streaming_delivery.py  # open_streaming_reply facade
    message_editing.py
    offset_store.py, offset_tracker.py
    concurrency.py, instance_lock.py
```

## Где менять что (типичные правки)

| Хочу поменять | Куда смотреть |
|---------------|---------------|
| Текст любого сообщения пользователю | [`messages_ru/`](satellite/messages_ru/) (фасад `__init__.py`; сценарий — `buttons.py`, `settings_ui.py`, `digest_ui.py`, `meetings_ui.py`, …), [`seagull/templates.py`](satellite/seagull/templates.py) |
| Логику дайджеста (метрики) | [`calendar/stats.py`](satellite/calendar/stats.py) |
| Финальный рендер | [`seagull/render.py`](satellite/seagull/render.py), [`seagull/rules.py`](satellite/seagull/rules.py) |
| Команду / кнопку | [`recognize_message`](satellite/telegram_bot/handlers/routing.py) → запись в `_RECOGNIZERS`; маршрутизация — [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py) (`_MESSAGE_ROUTES`, `_CALLBACK_ROUTERS`) |
| Хаб настроек / дайджест | [`handlers/settings_hub.py`](satellite/telegram_bot/handlers/settings_hub.py) (роутер всех `CB_SETTINGS_*` / `CB_ANALYTICS_*`), [`handlers/settings_callbacks.py`](satellite/telegram_bot/handlers/settings_callbacks.py) + [`handlers/settings_bindings.py`](satellite/telegram_bot/handlers/settings_bindings.py) (экраны «на сегодня» и «непринятых встреч», таблица `BINDINGS`) |
| Дайджест непринятых встреч (расписание + автоотправка) | [`scheduler.py`](satellite/scheduler.py) `_deliver_pending`, [`invitations_view.py`](satellite/invitations_view.py) `load_pending_invitations_screen`; настройки — `pending_digest_*` в [`subscriptions/`](satellite/subscriptions/) (дни: legacy + 7-bit mask), UI — [`messages_ru/digest_ui.py`](satellite/messages_ru/digest_ui.py) `CB_PENDING_DIGEST_*`, `mark_pending_digest_sent` |
| Дни отправки дайджестов (маска, подпись) | [`digest_utils.py`](satellite/digest_utils.py) — `is_digest_day_allowed`, `digest_days_to_bitmask`, `format_digest_days_label`, `toggle_digest_days_bitmask` |
| Чужие (пошаренные) календари | [`handlers/calendar_foreign.py`](satellite/telegram_bot/handlers/calendar_foreign.py) |
| Список CalDAV-календарей в UI | [`handlers/calendar_view.py`](satellite/telegram_bot/handlers/calendar_view.py) — `fetch_calendars` (→ `CalendarListResult`) и `build_calendar_sources_screen` |
| Какие календари в плане | [`handlers/calendar_sources.py`](satellite/telegram_bot/handlers/calendar_sources.py), поле `enabled_calendar_urls` в [`users/record.py`](satellite/users/record.py) |
| URL Web App connect | [`handlers/delivery.py`](satellite/telegram_bot/handlers/delivery.py) — `webapp_connect_url(ctx)` (персональный `/connect/<token>`); store — [`web/connect_token.py`](satellite/web/connect_token.py) |
| Потоковый ответ (черновик + финал) | [`streaming_delivery.py`](satellite/telegram_bot/streaming_delivery.py), [`handlers/delivery.py`](satellite/telegram_bot/handlers/delivery.py) — `open_streaming_reply` (plan, upcoming, invitations, manage, analytics) |
| Визуал Telegram (typing, effects, меню) | [`visual.py`](satellite/telegram_bot/visual.py) — `TypingIndicator`, `pick_plan_message_effect`, `set_default_menu_button_for_chat`; legacy HTML — [`presentation/html.py`](satellite/presentation/html.py); Rich Messages — [`presentation/rich.py`](satellite/presentation/rich.py) + [`presentation/delivery.py`](satellite/presentation/delivery.py); профиль бота на старте — [`commands.py`](satellite/telegram_bot/commands.py) `setup_bot_identity` |
| Расписание дайджеста на сегодня | [`scheduler.py`](satellite/scheduler.py) `_deliver_daily` + [`subscriptions/`](satellite/subscriptions/) (`digest_*`, `mark_digest_sent`) |
| Доступ, заявки, календарь пользователя | [`users/store.py`](satellite/users/store.py) (UserStore) + [`users/record.py`](satellite/users/record.py) (UserRecord, статусы), шифрование — [`security/token_vault.py`](satellite/security/token_vault.py) |
| Web App connect | handlers + HTTP в [`bot.py`](satellite/telegram_bot/bot.py); env — [`config.py`](satellite/config.py) |
| Дату плана по команде (today/tomorrow/…) | [`digest_utils.py`](satellite/digest_utils.py) `resolve_target_date`; авто-дайджест — всегда today в [`scheduler.py`](satellite/scheduler.py) |
| Парсинг .env | [`config.py`](satellite/config.py), образец [`.env.example`](.env.example) |
| CalDAV / провайдеры | [`calendar/caldav_client.py`](satellite/calendar/caldav_client.py), [`calendar/providers/`](satellite/calendar/providers/), [`user_calendar_service.py`](satellite/calendar/user_calendar_service.py) |
| Список / создание событий в боте | [`handlers/calendar_list.py`](satellite/telegram_bot/handlers/calendar_list.py), [`calendar_create.py`](satellite/telegram_bot/handlers/calendar_create.py); формат строк — [`events/_collectors.py`](satellite/calendar/events/_collectors.py) (импорт через фасад `satellite.calendar.events`) |
| Приглашения (NEEDS-ACTION, ответ в CalDAV) | [`handlers/calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py) (горизонт 60 дней вперёд / 14 назад), [`events/_collectors.py`](satellite/calendar/events/_collectors.py) (`collect_pending_invitations`, `event_relevant_for_invitations`) + [`events/_partstat.py`](satellite/calendar/events/_partstat.py) (`is_pending_invitation_for_user`), [`user_calendar_service.py`](satellite/calendar/user_calendar_service.py) (`list_events_for_invitations`, `set_attendee_partstat`), [`caldav_client.py`](satellite/calendar/caldav_client.py) (PARTSTAT refresh/update) |
| «Изменить статус встречи» (любой PARTSTAT) | [`handlers/calendar_manage.py`](satellite/telegram_bot/handlers/calendar_manage.py), [`events/_collectors.py`](satellite/calendar/events/_collectors.py) (`collect_manageable_events`) — список + детальный экран по встрече, действия завязаны на тот же `set_attendee_partstat` |
| Ввод времени (дайджест, /create) | [`time_utils.py`](satellite/calendar/time_utils.py); подсказки — [`messages_ru/`](satellite/messages_ru/) |
| Нумерация встреч (дайджест, /upcoming) | [`event_index_marker`](satellite/calendar/events/_filters.py) (импорт через фасад `satellite.calendar.events`) |
| Web App REST API | [`web/api/calendar.py`](satellite/web/api/calendar.py); регистрация маршрута — [`web/routing.py`](satellite/web/routing.py); сам сервер — [`web/server.py`](satellite/web/server.py) |
| Ссылки на видеозвонки в плане/дайджесте | [`calendar/conference_url.py`](satellite/calendar/conference_url.py) (извлечение URL), [`seagull/conference.py`](satellite/seagull/conference.py) (подписи кнопок), рендер — [`seagull/render.py`](satellite/seagull/render.py) / [`seagull/render_rich.py`](satellite/seagull/render_rich.py) |
| Сборку текста плана | [`plan_service.py`](satellite/plan_service.py) — callers передают calendar identity |
| Недельную аналитику (PNG + подпись) | [`analytics/service.py`](satellite/analytics/service.py), [`calendar/period_stats.py`](satellite/calendar/period_stats.py), [`calendar/event_kinds.py`](satellite/calendar/event_kinds.py), [`handlers/analytics.py`](satellite/telegram_bot/handlers/analytics.py) (`ActionGuard`, cooldown 45 с) |
| Дедуп повторных команд/кнопок (два PNG, два плана…) | [`handlers/action_guard.py`](satellite/telegram_bot/handlers/action_guard.py) — `try_acquire` / `release`; синглтоны сбрасывает `tests/conftest.py::_reset_action_guards` |
| Ответ на встречу (PARTSTAT) | [`handlers/partstat_flow.py`](satellite/telegram_bot/handlers/partstat_flow.py) — общий флоу; [`calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py) и [`calendar_manage.py`](satellite/telegram_bot/handlers/calendar_manage.py) — тонкие адаптеры |
| PNG недельной аналитики | [`analytics/render_card.py`](satellite/analytics/render_card.py), примитивы — [`visual_cards/base.py`](satellite/visual_cards/base.py) |
| JSON-store мутацию (users / subscriptions) | [`json_store.py`](satellite/json_store.py) (`JsonStoreBase`), [`users/store.py`](satellite/users/store.py) и [`subscriptions/store.py`](satellite/subscriptions/store.py) (`_upsert_locked`, `DigestSettings.{to,from}_json`); прямой `replace()` не использовать |
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
5. **Дата и дни дайджеста** — команды плана: `resolve_target_date`; авто-дайджест
   плана: всегда today в scheduler; допустимость дня: `is_digest_day_allowed`
   (для `pending_digest_days` — и 7-bit mask).
6. **Тексты** — [`messages_ru/`](satellite/messages_ru/) / шаблоны seagull/weather.
7. **Хендлеры не пробрасывают исключения** — safe text из `messages_ru`.
8. **Атомарная запись JSON-store** — общая логика в [`json_store.py`](satellite/json_store.py) (`JsonStoreBase`: tmp + fsync + `os.replace`); `UserStore` и `SubscriptionStore` наследуют её.
9. **`logs/`, `.env`, `venv/`** — не коммитим.
10. **Команды и кнопки** — только [`recognize_message`](satellite/telegram_bot/handlers/routing.py); любая распознанная команда сбрасывает FSM (`digest_state`, `calendar_state`) в [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py).
11. **Подписка на дайджест** — `DigestSettings.telegram_user_id` в [`subscriptions/record.py`](satellite/subscriptions/record.py); scheduler резолвит пользователя через `UserStore.get`, не через `username`.
12. **Навигация настроек** — кросс-экранные `CB_SETTINGS_*` / `CB_ANALYTICS_*` обрабатывает только [`settings_hub.py`](satellite/telegram_bot/handlers/settings_hub.py); `settings.py` и `analytics.py` не импортируют друг друга и не имеют lazy-back-импортов в хаб.
13. **Сбой `UserStore._save_locked`** — поднимает [`UserStorePersistenceError`](satellite/users/store.py); caller (handler / Web App) ловит на границе и показывает безопасный текст.
14. **Перед коммитом** — `make check` (ruff lint + `ruff format --check` + mypy + py_compile + pytest). Стиль/форматирование — только [`ruff`](pyproject.toml) (lint + format); blackd/isort не используем. Поведение при падении тестов — см. раздел **«Тесты и регрессии»** ниже.
15. **Слои импортов** — домен (`calendar/`, `seagull/`, `weather/`, `analytics/`, `messages_ru/`, `presentation/`, `scheduler.py`, `plan_service.py`, …) не импортирует `telegram_bot`; единственное исключение — `presentation/delivery.py → telegram_bot.api`. Закреплено в [`tests/test_import_layers.py`](tests/test_import_layers.py).

## Тесты и регрессии (для агентов)

**Перед завершением работ — всегда полный прогон тестов.** Не отдавай задачу
пользователю (не пишь финальное сообщение, не предлагай коммит), пока не запущен
весь набор: `make check` (ruff lint + format-check + mypy + py_compile + pytest)
или минимум `make test` (полный `pytest`). Точечный `pytest tests/test_foo.py -q`
допустим только как промежуточная проверка по ходу правок — он **не заменяет**
финальный полный прогон. Не сдавай задачу с красным pytest/ruff/mypy без явного
объяснения пользователю, что именно красное и почему ты считаешь это допустимым.

**Тесты — страж регрессий, а не способ сделать CI зелёным.** Никогда не «чинить» тест
вслепую под новый код, если не уверен, что изменение поведения **намеренное и верное**.

| Ситуация | Действие |
|----------|----------|
| Упали тесты, которые **прямо покрывают** твои изменения, и новое поведение **ожидаемо** (контракт, текст, API) | Обнови тест под новый контракт; в ответе пользователю кратко зафиксируй, *что* изменилось и *почему* тест легитимен. |
| Упали тесты **вне** зоны задачи или поведение выглядит **сломанным** | Считай это багом: разберись в продуктовой логике, **чинь код**, не ослабляй/assert не выкидывай проверки ради зелёного прогона. |
| Непонятно — баг это, устаревший тест или намеренное изменение контракта | **Спроси пользователя явно**, не угадывай. Не коммить «на авось». |

Запрещено без согласования с пользователем:

- ослаблять assertions, удалять проверки, ставить `pytest.mark.skip`, `xfail`, `continue-on-error` «чтобы прошло»;
- подменять жёсткие даты/моки на «что угодно», если это скрывает реальный баг (пример антипаттерна: зафиксировать вчерашнюю дату в тесте «сегодня», когда сломался расчёт `day_offset`);
- менять ожидаемые тексты/числа в тесте, не прочитав, **что** должен делать сценарий по [`messages_ru/`](satellite/messages_ru/) и доменной логике.

Допустимо обновлять тест, когда ты **осознанно** меняешь контракт (новая фича, рефакторинг
без смены смысла для пользователя, переименование). В сомнительных случаях — сначала
воспроизведи падение, потом код или вопрос пользователю.

Подробнее про написание тестов: [docs/testing.md](docs/testing.md).

## Антипаттерны

- Глобальные `MAIL_LOGIN` / `USER_CALENDAR_MAP` — удалены из `config.py`.
- Свой парсер времени — только [`normalize_hhmm_input`](satellite/calendar/time_utils.py)
  (UI) и [`parse_hhmm`](satellite/calendar/time_utils.py) (минуты от полуночи;
  внутри делегирует в `normalize_hhmm_input`).
- Свои маркеры номеров встреч — только [`event_index_marker`](satellite/calendar/events/_filters.py)
 (дайджест и `/upcoming`); импортировать через фасад `satellite.calendar.events`.
- Inline render дайджеста вне [`seagull/digest.py`](satellite/seagull/digest.py).
- Fallback `edit` → `send` в callback-хендлерах — дубли ([`delivery.py`](satellite/telegram_bot/handlers/delivery.py)).
- Дублировать списки `is_*_request` / `parse_*` в `bot.py` или `dispatch.py` — только `recognize_message`.
- Импорт `_fetch_calendars` из `calendar_sources` в другие хендлеры — только [`calendar_view.py`](satellite/telegram_bot/handlers/calendar_view.py).
- Второй путь нормализации событий — только `normalize_caldav_event`.
- `DIGEST_TIME` / `DIGEST_WEEKDAYS_ONLY` в env — удалены; время в `subscriptions.json`.
- Прямые строки в хендлерах — все user-facing тексты в [`messages_ru/`](satellite/messages_ru/) (импорт через корневой фасад `satellite.messages_ru`, не `messages_ru.<submodule>`; закреплено в [`test_import_layers.py`](tests/test_import_layers.py)).
- Свой `_webapp_url` в хендлерах — только [`delivery.webapp_connect_url`](satellite/telegram_bot/handlers/delivery.py).
- Lazy-back-импорты `settings_hub` из `settings`/`analytics` для «Назад» — навигация только в хабе (см. инвариант 12).
- Прямой `<blockquote>` / `<tg-emoji>` в хендлерах — только [`presentation/html.py`](satellite/presentation/html.py); Rich HTML — [`presentation/rich.py`](satellite/presentation/rich.py) / [`presentation/calendar_lists.py`](satellite/presentation/calendar_lists.py); доставка rich — [`presentation/delivery.py`](satellite/presentation/delivery.py); fallback при отказе Telegram — в [`api/client.py`](satellite/telegram_bot/api/client.py). Шимы `telegram_bot/{html_format,rich_message,message_delivery}.py`, `telegram_bot/presenters/calendar_lists.py`, пакет `formatters/` и `messages_ru/_core.py` **удалены** — не воссоздавать.
- Свой retry без `<tg-emoji>` в хендлерах — только `TelegramClient.send_message` / `edit_message_text`.
- Дублирование PARTSTAT-логики в [`calendar_invitations.py`](satellite/telegram_bot/handlers/calendar_invitations.py) / [`calendar_manage.py`](satellite/telegram_bot/handlers/calendar_manage.py) — общий флоу только в [`partstat_flow.py`](satellite/telegram_bot/handlers/partstat_flow.py).
- Свой cooldown/дедуп долгих команд — только [`ActionGuard`](satellite/telegram_bot/handlers/action_guard.py) (не дублировать `_running` set в хендлерах).
- Повторяющийся streaming+CalDAV scaffold — [`streaming_caldav.run_streaming_caldav_message`](satellite/telegram_bot/handlers/streaming_caldav.py); PARTSTAT — [`partstat_flow`](satellite/telegram_bot/handlers/partstat_flow.py).
- `calendar/` не импортирует `messages_ru` (длительность — [`duration_format.py`](satellite/calendar/duration_format.py)); политика дайджеста — [`scheduler_policy.py`](satellite/scheduler_policy.py) (`should_fire_*`, не re-export из `scheduler.py`); `inv:back` обрабатывает invitations router, из хаба — `CB_SETTINGS_CALENDAR_BACK`.
- Параллельный PNG-render (своя палитра/шрифты/`_load_font`/`_paste_brand_logo`) — все примитивы только в [`visual_cards/base.py`](satellite/visual_cards/base.py).
- Прямой mutate `UserRecord`/`DigestSettings` в `users.json`/`subscriptions.json` без `_update_locked` / `_upsert_locked` — атомарность теряется.
- `isinstance(..., RecognizedFoo)` / `if/elif` для роутинга команд и callback'ов — только таблицы `_MESSAGE_ROUTES` / `_CALLBACK_ROUTERS` в [`dispatch.py`](satellite/telegram_bot/handlers/dispatch.py).
- `_msg_from_cb` или фабрикация `IncomingMessage` ради `ensure_calendar_connected` — функция принимает `chat_id` / `user_id` напрямую.
- `do_create()` или подобные обёртки в хендлерах ради единственного `try/except` — снимать без потери поведения.
- Импорт `from satellite.analytics_service import ...` — canonical путь теперь [`satellite.analytics.service`](satellite/analytics/service.py); shim удалён, обновите импорт.
- Подгонять тест под код «чтобы pytest прошёл», не разобравшись в ожидаемом поведении — см. **«Тесты и регрессии»**; тесты для ловли багов, не для зелёного CI.
- Lazy-import «на всякий случай» — импорты на top-level; допустим только при реальном цикле с комментарием, какой цикл разрывается (пример: `messages_ru/calendar_ui.py` → `calendar.selection`).
- Дублировать daily/pending-ветки в настройках дайджестов — расширяй таблицу [`BINDINGS`](satellite/telegram_bot/handlers/settings_bindings.py), не пиши парные `if kind == …` в хендлерах.

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
python -m mypy satellite                          # make typecheck (блокирующий гейт)
find satellite tests -name '*.py' ! -name '._*' -print0 | xargs -0 python -m py_compile  # make compile
make check                                        # lint + format-check + typecheck + compile + test (full)
make docker-smoke                                 # smoke образа: импорты + /healthz (см. docs/testing.md)
make smoke-prod                                   # curl публичного /healthz, /connect, /api/… после деплоя
python telegram_test_command.py                   # make run
```

Опционально: `pre-commit install` подтянет ruff/ruff-format/mypy в git-hook
(см. [`.pre-commit-config.yaml`](.pre-commit-config.yaml)).

Сервер: **systemd** — `sudo bash scripts/install-server.sh`;
**Docker (prod)** — `make deploy` (см. [docs/operations.md](docs/operations.md#запуск-на-сервере),
[deploy/README.md](deploy/README.md));
**Docker (local)** — `make env && make docker-up` (см. корневой `docker-compose.yml`).

CI: reusable [`.github/workflows/_checks.yml`](.github/workflows/_checks.yml) (ruff lint + format check, mypy, py_compile, pytest);
[`.github/workflows/test.yml`](.github/workflows/test.yml) — только PR; [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) — push в `main` или тег `v*`: checks → образ в GHCR → **docker smoke** → deploy (healthy + smoke-prod);
rolling deploy по SSH (`scripts/ci-deploy-remote.sh`) — только для `main` и `workflow_dispatch`
(тег `v*` лишь пушит semver-образ). Первичный деплой (`.env`, `docker-compose.yml`, образ) — `make deploy` (Ansible);
TLS и reverse proxy на 443 — ваш существующий nginx на хосте, не из стека.
см. [`deploy/README.md`](deploy/README.md).

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| [`scripts/install.sh`](scripts/install.sh) | venv, зависимости, `.env` + Fernet, `logs/` |
| [`scripts/install-server.sh`](scripts/install-server.sh) | systemd на VPS (`/opt/satellite`) |
| [`scripts/bootstrap-server.sh`](scripts/bootstrap-server.sh) | apt + clone + `install-server.sh` на чистом хосте |
| [`scripts/diagnose_caldav.py`](scripts/diagnose_caldav.py) | CalDAV с сервера без Telegram (см. troubleshooting) |
| [`scripts/diagnose_invitation.py`](scripts/diagnose_invitation.py) | PARTSTAT / pending без Telegram (`--user-id`, `--summary`, опц. `--accept`; lookback 14 д — как в боте) |
| [`scripts/ci-deploy-remote.sh`](scripts/ci-deploy-remote.sh) | Rolling deploy: trim секретов SSH/host → stop/disable legacy `satellite-bot.service` → детект legacy `logs/users.json` vs пустой volume → `SATELLITE_IMAGE` в `.env` → `compose pull/up` → wait healthy + host `/healthz` → опц. [`smoke-prod.sh`](scripts/smoke-prod.sh) |
| [`scripts/migrate-legacy-logs.sh`](scripts/migrate-legacy-logs.sh) | Однократный перенос `/opt/satellite/logs/` (systemd) в volume `satellite_satellite-logs` (Docker) с `chown` под satellite uid внутри образа; идемпотентен, делает rescue-копию |
| [`scripts/docker-smoke-image.sh`](scripts/docker-smoke-image.sh) | CI/local: `docker run` → [`smoke_container.py`](scripts/smoke_container.py) (импорты, caldav≥3, HTTP /healthz) |
| [`scripts/smoke-prod.sh`](scripts/smoke-prod.sh) | Публичные curl-проверки `/healthz`, `/connect`, `/api/calendar/status` после деплоя |

## Web App

[`satellite/web/server.py`](satellite/web/server.py) — встроенный
`ThreadingHTTPServer`, поднимаемый из [`bot.py`](satellite/telegram_bot/bot.py).
Валидация сессии — [`init_data.py`](satellite/web/init_data.py).

Все запросы под `/api/calendar/*` авторизуются через [`auth.validated_user`](satellite/web/auth.py):
сначала Telegram `initData` (HMAC), иначе **connect-token** (когда WebView не
передаёт `initData`). Пользователь должен быть `approved` в `UserStore`.

`initData` — заголовок `X-Telegram-Init-Data`, JSON-тело или query `?initData=...`
(см. `extract_init_data` в [`parsing.py`](satellite/web/parsing.py)).

**Connect-token:** кнопки в чате ведут на `/connect/<token>#t=...` (см.
`webapp_connect_url` в [`delivery.py`](satellite/telegram_bot/handlers/delivery.py));
TTL 15 мин, store в `logs/connect-tokens.json` ([`ConnectTokenStore`](satellite/web/connect_token.py)).
Токен дублируется в path, hash, JSON (`t` / `connect_token`) и query — Telegram
иногда срезает query у `web_app`-кнопок. Menu Button без `telegram_user_id` —
только `WEBAPP_BASE_URL` (нужен рабочий `initData`).

`WEBAPP_BASE_URL` — только публичный HTTPS (проверка `is_valid_webapp_base_url`
в [`config.py`](satellite/config.py)); не путь к `connect.html` в репозитории.

Endpoint-ы:

| Метод/путь | Назначение |
|------------|------------|
| `GET /healthz` | Docker HEALTHCHECK; без auth |
| `GET /connect`, `GET /connect/<token>` | SPA [`connect.html`](satellite/web/static/connect.html) |
| `GET /api/calendar/status` | Проверка подключения |
| `POST /api/calendar/connect` | Сохранить credentials (Fernet через `TokenVault`) |
| `DELETE /api/calendar/disconnect` | Сбросить подключение |
| `GET /api/calendar/events?from=&to=` | Список событий |
| `POST /api/calendar/events` | Создать событие |
| `DELETE /api/calendar/events/{uid}?url=` | Удалить событие |

HTTPS не делает сам сервер — это задача reverse proxy (nginx на хосте в
production, ngrok/Cloudflare Tunnel в dev). Проксируйте `/connect` и
префикс `/api/calendar/` на `127.0.0.1:<satellite_host_port>` (см.
[deploy/nginx/satellite-webapp.conf.example](deploy/nginx/satellite-webapp.conf.example),
[operations.md](docs/operations.md)).

## Runtime-артефакты

| Файл | Назначение |
|------|------------|
| `logs/bot.log` | Production-логи |
| `logs/bot.lock` | Единственный инстанс |
| `logs/telegram-offset.json` | Watermark long-polling |
| `logs/subscriptions.json` | Per-user дайджест |
| `logs/users.json` | Доступ + зашифрованные CalDAV-credentials |
| `logs/connect-tokens.json` | Краткоживущие Web App connect-токены (переживают рестарт) |
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
Если стор пустой (`users=0, subs=0`), но в `logs/backups/` уже есть `users.json.*.bak`,
[`bot.py::_warn_if_users_lost`](satellite/telegram_bot/bot.py) кричит `WARNING Persistence is empty …` —
скорее всего, это миграция systemd→Docker без переноса данных в volume (см. ниже).

#### Миграция systemd → Docker (один раз)

systemd-сетап ([`scripts/install-server.sh`](scripts/install-server.sh)) хранил
`users.json` / `subscriptions.json` / `backups/` в `/opt/satellite/logs/` **на хосте**.
Docker-compose ([`deploy/docker-compose.yml`](deploy/docker-compose.yml)) маунтит
именованный volume `satellite_satellite-logs` → `/app/logs`. При первом `compose up`
volume пустой — контейнер не видит legacy-данные, юзеры «пропадают».

Защита:

1. [`scripts/ci-deploy-remote.sh`](scripts/ci-deploy-remote.sh) перед `compose up` сравнивает
   количество юзеров на хосте и в volume; если host > volume — **валит deploy** с указателем
   на `scripts/migrate-legacy-logs.sh`.
2. [`scripts/migrate-legacy-logs.sh`](scripts/migrate-legacy-logs.sh) — одношаговый перенос:
   rescue-копия volume в `/root/satellite-rescue-<ts>/`, `cp` из `/opt/satellite/logs/` в volume,
   `chown` под uid пользователя `satellite` внутри образа, `compose up` + ожидание healthy.
   Идемпотентен; `FORCE=1` чтобы перетереть непустой volume.
3. [`bot.py::_warn_if_users_lost`](satellite/telegram_bot/bot.py) ловит сценарий «volume
   пустой, но backups уже есть» — последняя линия защиты, если детектор в (1) обойдут.
