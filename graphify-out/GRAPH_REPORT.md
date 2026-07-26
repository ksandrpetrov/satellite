# Graph Report - .  (2026-07-26)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 3601 nodes · 10557 edges · 166 communities (146 shown, 20 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 385 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c8561a51`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- period_stats.py
- CalDAVService
- handlers/access.py
- render_rich.py
- TelegramClient
- conftest.py
- SubscriptionStore
- caldav_client.py
- NormalizedEvent
- handle_callback_query
- stats.py
- providers/base.py
- UserStore
- IncomingCallback
- ProviderCredentials
- UserCalendarService
- test_scheduler.py
- test_conference_url.py
- calendar_lists.py
- test_business_flows_plan.py
- HandlerContext
- CalDAVPartstatMixin
- settings_callbacks.py
- IncomingMessage
- test_weather.py
- CalendarNotConnectedError
- OffsetStore
- session.py
- TelegramError
- test_streaming_delivery.py
- test_calendar_manage.py
- test_architecture_boundaries.py
- is_pending_invitation_for_user
- settings_hub.py
- StreamingReply
- handle_message
- CalendarProviderError
- WeatherForecastClient
- test_web_server.py
- ConnectTokenStore
- test_events.py
- test_handlers.py
- DigestSettings
- plan.py
- _time.py
- server.py
- bot.py
- event_kinds.py
- buttons.py
- InstanceLock
- services.py
- parse_calendar_events
- calculate_day_stats
- test_seagull_render.py
- test_telegram_api.py
- FakeCalendarService
- event_token_cache.py
- handlers/__init__.py
- _collectors.py
- SubscriptionStorePersistenceError
- analyzer.py
- UpdateDispatcher
- CalendarHandle
- TelegramBot
- test_settings_hub.py
- test_calendar_invitations.py
- calendar_foreign.py
- config.py
- auth.py
- WebAppServer
- test_business_flows_invitations.py
- CalendarListEntry
- normalize_caldav_event
- digest_ui.py
- html.py
- build_seagull_digest
- weather/__init__.py
- Runtime Dependency Set
- snapshot
- test_calendar_selection.py
- run_streaming_caldav_message
- PlanBuilder
- messages_ru/__init__.py
- should_fire_for_user
- format_upcoming_day_header
- load_settings
- edit_or_send_message
- users/record.py
- test_business_flows_webapp.py
- styled_button
- digest_utils.py
- test_user_access.py
- respond_callback_nav
- TypingIndicator
- make_callback
- git-github-auth.sh
- JsonStoreBase
- test_messages.py
- scheduler_policy.py
- build_seagull_texts
- CalendarApiService
- parsing.py
- Satellite Testing Strategy
- Satellite Architecture
- recognize_message
- scheduler.py
- user_partstat
- calendar_ui.py
- meetings_ui.py
- test_every_cb_constant_has_a_router
- test_requirements.py
- Operations and Deployment Guide
- Satellite Agent Guide
- invitations_view.py
- validate_init_data
- DigestStateStore
- test_analytics_handler.py
- event_callback_token
- warn_if_users_lost
- test_kto_est_kto_in_pending_after_enrich_phase1
- test_invitations_partstat_regression.py
- _reset_action_guards
- selection.py
- settings_ui.py
- ci-deploy-remote.sh
- ensure-nginx-satellite.sh
- smoke-prod.sh
- test_business_flows_smoke.py
- Satellite Docker Deployment Playbook
- Architecture Refactor Log
- is_lunch_event
- caldav_discovery.py
- build_settings_hub_keyboard
- serve_html
- migrate-legacy-logs.sh
- Checks Job
- Reproducible Dependency Lock Invariant
- instance_lock.py
- .update
- install.sh
- effective_enabled_calendar_urls
- build_manage_detail_keyboard
- notify_handler_failure
- digest_settings_screen_text
- docker-smoke-image.sh
- users
- Legacy Traefik and Systemd Migration
- Local Logs Bind Mount
- presentation/__init__.py
- telegram_bot/__init__.py
- presenters/__init__.py
- testing/__init__.py
- visual_cards/__init__.py
- Reusable Checks Workflow
- Pull Request Test Workflow
- External Proxy and Host Port Configuration
- Encryption Key Preservation
- External Nginx TLS Boundary
- Graphify as a Development-Only Tool
- Portable Committed Graph Artifacts
- Role-Based Documentation Navigation
- Behavior-Preserving Refactoring Contract
- Release-Blocking Regression Gate
- satellite

## God Nodes (most connected - your core abstractions)
1. `UserStore` - 177 edges
2. `HandlerContext` - 176 edges
3. `IncomingCallback` - 141 edges
4. `IncomingMessage` - 131 edges
5. `handle_message()` - 88 edges
6. `handle_callback_query()` - 81 edges
7. `TelegramClient` - 78 edges
8. `CalendarProviderError` - 69 edges
9. `CalDAVService` - 68 edges
10. `SubscriptionStore` - 65 edges

## Surprising Connections (you probably didn't know these)
- `Transactional JSON Store Invariant` --rationale_for--> `JsonStoreBase`  [EXTRACTED]
  AGENTS.md → satellite/json_store.py
- `Telegram Web App and Data Flow` --references--> `PlanBuilder`  [EXTRACTED]
  docs/README.md → satellite/plan_service.py
- `Daily and Pending Digest Configuration` --references--> `DigestScheduler`  [EXTRACTED]
  docs/configuration.md → satellite/scheduler.py
- `Canonical Paths and Shared Infrastructure` --references--> `ActionGuard`  [EXTRACTED]
  docs/refactor-log.md → satellite/telegram_bot/handlers/action_guard.py
- `Bounded Telegram Update Dispatch` --references--> `UpdateDispatcher`  [EXTRACTED]
  AGENTS.md → satellite/telegram_bot/update_dispatcher.py

## Import Cycles
- 3-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render.py -> satellite/seagull/__init__.py`
- 3-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render_rich.py -> satellite/seagull/__init__.py`
- 3-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/rules.py -> satellite/seagull/__init__.py`
- 4-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render.py -> satellite/seagull/conference.py -> satellite/seagull/__init__.py`
- 4-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render_rich.py -> satellite/seagull/conference.py -> satellite/seagull/__init__.py`
- 4-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render_rich.py -> satellite/seagull/render.py -> satellite/seagull/__init__.py`
- 4-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render.py -> satellite/seagull/rules.py -> satellite/seagull/__init__.py`
- 4-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render_rich.py -> satellite/seagull/rules.py -> satellite/seagull/__init__.py`
- 5-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render_rich.py -> satellite/seagull/render.py -> satellite/seagull/conference.py -> satellite/seagull/__init__.py`
- 5-file cycle: `satellite/seagull/__init__.py -> satellite/seagull/digest.py -> satellite/seagull/render_rich.py -> satellite/seagull/render.py -> satellite/seagull/rules.py -> satellite/seagull/__init__.py`

## Hyperedges (group relationships)
- **Stability Hardening Contract** — docs_architecture_transactional_json_persistence, docs_architecture_scheduler_processing_checkpoint, docs_architecture_bounded_update_backpressure, docs_architecture_best_effort_shutdown [EXTRACTED 1.00]
- **Checks Build Smoke and Rolling Deploy** — _github_workflows_deploy_workflow, _github_workflows__checks_checks_job, _github_workflows_deploy_build_job, _github_workflows_deploy_deploy_job [EXTRACTED 1.00]

## Communities (166 total, 20 thin omitted)

### Community 0 - "period_stats.py"
Cohesion: 0.07
Nodes (71): FreeTypeFont, Image, ImageFont, build_analytics_caption(), _compare_line(), Подпись к PNG недельной аналитики (Telegram HTML)., _trend_line(), _week_tone() (+63 more)

### Community 1 - "CalDAVService"
Cohesion: 0.05
Nodes (43): DAVClient, CalDAVService, Any, date, Event, Response, tzinfo, Возвращает (события на день, использованный эндпоинт).          Если `target_cal (+35 more)

### Community 2 - "handlers/access.py"
Cohesion: 0.05
Nodes (61): build_week_analytics(), date, tzinfo, build_approved_main_keyboard(), build_webapp_connect_keyboard(), Inline-кнопка Web App для подключения календаря.      Reply-клавиатура с ``web_a, Главная клавиатура.      Сгруппирована по смыслу: верхний ряд — план дня (сегодн, Plain HTML fallback без ``<blockquote>`` — не мигает с rich ``<details>``. (+53 more)

### Community 3 - "render_rich.py"
Cohesion: 0.06
Nodes (64): Тексты и хелперы потоковой доставки (``sendRichMessageDraft``)., Rich draft-кадр со статусом (``<tg-thinking>``)., rich_thinking_status(), _day_header_rich(), anchor(), anchor_link(), blockquote(), datetime_link() (+56 more)

### Community 4 - "TelegramClient"
Cohesion: 0.06
Nodes (34): Any, Response, Session, Повтор send/edit без ``<tg-emoji>`` и expandable blockquote., ``_call`` с деградацией на отказах Telegram.          1. ``message_effect_id`` о, Закрывает «часики» на inline-кнопке. Best-effort: тайм-аут короткий.          Te, ``sendMessageDraft``: потоковый черновик в поле ввода.          Bot API 9.3 (31, ``sendRichMessage``: структурированное сообщение (Bot API 10.1). (+26 more)

### Community 5 - "conftest.py"
Cohesion: 0.08
Nodes (58): ensure_calendar_access(), ensure_calendar_connected(), True если пользователь approved и может выполнять календарные действия.      При, _resolve_chat_user(), CalendarFlowState, CalendarStateStore, CreateEventDraft, FSM для создания/редактирования событий и dedup callback (отдельно от digest). (+50 more)

### Community 6 - "SubscriptionStore"
Cohesion: 0.06
Nodes (44): date, Гарантирует запись с дефолтами; обновляет username, если поменялся.          Пол, Точечное обновление полей. Создаёт запись, если её ещё нет.          Невалидные, Записывает дату последней успешной автоотправки (YYYY-MM-DD)., Дата последней успешной обработки pending-дайджеста., Атомарно применяет ``build(existing|None) -> новая запись``.          Сохраняет, JSON-файл `{str(chat_id): { ...fields... }}`.      Все мутации атомарны (tmp + o, Тонкая обёртка над ``update_settings(digest_enabled=True)``.          Возвращает (+36 more)

### Community 7 - "caldav_client.py"
Cohesion: 0.08
Nodes (42): datetime, CalDAV service facade: discovery, cache, CRUD, and mixin-based fetch/PARTSTAT., Создаёт VEVENT. Возвращает (uid, event_url).          DTSTAMP обязателен по RFC, CalDAV range search and event collection., CalDAV PARTSTAT refresh and attendee updates., Обновляет PARTSTAT текущего пользователя в ATTENDEE события.          Загрузка/с, _add_vevent_attendee(), _bump_vevent_dtstamp() (+34 more)

### Community 8 - "NormalizedEvent"
Cohesion: 0.08
Nodes (41): DayCalendarStats, NormalizedEvent, Interval, Метрики дня. Тексты не хранит — это задача ``seagull.rules``.      Хранит только, Событие, приведённое к минутам от полуночи. Внутренний инвариант: end > start., date, Сервис сборки плана дня: CalDAV → фильтр → текст «чайки».  Единая точка истины д, external_link() (+33 more)

### Community 9 - "handle_callback_query"
Cohesion: 0.13
Nodes (51): pending_digest_day_callback_data(), handle_callback_query(), callback_edit_html(), HTML после edit callback (rich или legacy)., _callback(), _ctx(), MonkeyPatch, Path (+43 more)

### Community 10 - "stats.py"
Cohesion: 0.07
Nodes (42): _event_location(), _event_title(), _partstat_flags(), Расчёт статистики дня для аналитики «чайки» (без LLM).  Чистые функции: получают, Возвращает ``(is_pending, is_tentative)`` для пользователя в событии.      Состо, Минуты рабочего дня вне обеда — база для расчёта свободного времени., _WorkdayMinutes, clip_interval() (+34 more)

### Community 11 - "providers/base.py"
Cohesion: 0.11
Nodes (21): Protocol, CalendarConnectionStatus, CalendarEventPayload, CalendarEventRef, CalendarProvider, ProviderNotImplementedError, date, Event (+13 more)

### Community 12 - "UserStore"
Cohesion: 0.08
Nodes (22): Any, Один Telegram-пользователь.      Не хранит PII календаря: ни названий событий, н, UserRecord, Any, Path, Помечает заявку как ``pending`` (если не уже).          Возвращает ``(record, wa, Гарантирует, что админ заведён и сразу ``approved``.          Нужно для бутстрап, Атомарно применяет статические поля поверх существующей записи.          Подходи (+14 more)

### Community 13 - "IncomingCallback"
Cohesion: 0.11
Nodes (43): get_event_token_cache(), _edit_invitations_screen(), _fetch_all_for_token_lookup(), _invitations_from_settings_hub(), _load_screen(), _on_fail(), _on_not_found(), open_invitations_from_settings() (+35 more)

### Community 14 - "ProviderCredentials"
Cohesion: 0.08
Nodes (35): Encrypted Per-User Credentials, Business Flow Coverage Matrix, Configuration and Runtime Diagnostics, Проверяет credentials. Возвращает (ok, primary_calendar_url, error_code)., Криптографические утилиты приложения.  В отдельный пакет вынесено всё, что касае, InvalidEncryptionKeyError, ProviderCredentials, RuntimeError (+27 more)

### Community 15 - "UserCalendarService"
Cohesion: 0.09
Nodes (28): CalendarOperationLog, Path, Append-only audit log календарных операций (без PII)., Пишет одну JSON-строку на операцию в ``calendar_ops.jsonl``., ConnectedCalendar, date, tzinfo, Единственная точка доступа handlers/plan/scheduler к календарю. (+20 more)

### Community 16 - "test_scheduler.py"
Cohesion: 0.13
Nodes (44): InvitationsScreen, Результат загрузки pending-приглашений: текст, клавиатура, метаданные., _at(), _make_scheduler(), datetime, Path, Тесты планировщика per-user дайджеста.  Старый ``should_fire``/``_LastFiredStore, 09:00 МСК: alice scheduled на 09:00 — стреляет; bob на 09:30 — рано. (+36 more)

### Community 17 - "test_conference_url.py"
Cohesion: 0.09
Nodes (41): _append_candidate(), conference_provider(), display_room_location(), extract_conference_url(), _is_calendar_event_permalink(), is_conference_call_url(), _is_safe_http_url(), _normalize_url() (+33 more)

### Community 18 - "calendar_lists.py"
Cohesion: 0.16
Nodes (39): format_digest_days_label(), Человекочитаемая подпись для экрана настроек., _event_start_unix(), _events_by_url(), _invitation_items_rich(), invitations_list_rich_html(), manage_detail_rich_html(), manage_list_rich_html() (+31 more)

### Community 19 - "test_business_flows_plan.py"
Cohesion: 0.09
Nodes (41): PlanTextBundle, Пара rich + legacy HTML для доставки плана., freeze_now(), make_user_store(), datetime, MonkeyPatch, Path, UserStore с пред-заполненными статусами для разных user_id.      Возвращает экзе (+33 more)

### Community 20 - "HandlerContext"
Cohesion: 0.13
Nodes (39): _handle_approve(), _handle_reject(), _parse_target_id(), Admin approve/reject pending users., route_admin_callback(), build_connected_login_keyboard(), calendar_check_result(), disconnect_calendar_action() (+31 more)

### Community 21 - "CalDAVPartstatMixin"
Cohesion: 0.10
Nodes (22): CalDAVPartstatMixin, Any, date, datetime, Event, Response, tzinfo, Нужен ли GET на ресурс события для достоверного PARTSTAT. (+14 more)

### Community 22 - "settings_callbacks.py"
Cohesion: 0.16
Nodes (35): _DigestKind, effective_username_from_callback(), Очень лёгкий FSM поверх chat_id и dedup для callback_query.  Назначение:  - Сцен, bindings_for(), build_days_screen_bundle(), build_settings_screen_bundle(), build_time_screen_bundle(), days_value() (+27 more)

### Community 23 - "IncomingMessage"
Cohesion: 0.14
Nodes (37): handle_pending_command(), IncomingMessage, _dispatch_recognized(), _handle_unknown(), _MessageRoute, _pending(), RecognizedCommand, Точки входа для апдейтов Telegram: routing → конкретный сценарий.  `handle_messa (+29 more)

### Community 24 - "test_weather.py"
Cohesion: 0.21
Nodes (37): Окна рабочего дня и обеда в формате "HH:MM" (локальное время)., WorkdayOptions, summarize_for_digest_day(), build_weather_message(), Одна-две строки для вставки в дайджест или None., _digest_now_may_12_14h(), _hour(), date (+29 more)

### Community 25 - "CalendarNotConnectedError"
Cohesion: 0.11
Nodes (34): CalendarNotConnectedError, handle_open_calendar_sources(), _handle_toggle(), Выбор календарей, которые учитываются в плане и дайджесте., _sources_bundle(), build_calendar_sources_screen(), CalendarListResult, CalendarListStatus (+26 more)

### Community 26 - "OffsetStore"
Cohesion: 0.11
Nodes (28): OffsetStore, Path, Хранит offset на диске. Запись атомарна (tmp + os.replace), потокобезопасна., OffsetTracker, Persisted offset — низкий водяной знак для восстановления после рестарта., Offset для следующего ``getUpdates`` — «не переотдавай ниже этого».          Сдв, Возвращает ``True``, если update нужно обработать; ``False`` — пропуск., Path (+20 more)

### Community 27 - "session.py"
Cohesion: 0.08
Nodes (34): _close_open_tags(), Префикс длиной ≤ ``length`` без разрыва HTML-тегов и сущностей., _safe_html_prefix(), _append_growing(), _clip_telegram_text(), _clip_text(), _evenly_capped(), _RevealMode (+26 more)

### Community 28 - "TelegramError"
Cohesion: 0.11
Nodes (30): deliver_rich_or_html(), edit_rich_or_html(), Any, Доставка сообщений: rich с fallback на legacy HTML., ``sendRichMessage`` с fallback на legacy ``sendMessage`` HTML., ``editMessageText`` с rich_message и fallback на legacy HTML., input_rich_message(), ``InputRichMessage`` для ``sendRichMessage`` / draft. (+22 more)

### Community 29 - "test_streaming_delivery.py"
Cohesion: 0.10
Nodes (32): open_streaming_reply(), Streaming delivery facade., Удобная фабрика (без ``HandlerContext`` — меньше связности).      Пустой ``initi, _close_open_tags(), Закрывает незакрытые парные теги (``<b>foo`` → ``<b>foo</b>``).      Telegram па, Префикс длиной ≤ ``length``, не рвущий HTML-теги и сущности.      Если внутри ``, _safe_slice(), Юнит-тесты потоковой доставки ``sendMessageDraft`` + legacy fallback. (+24 more)

### Community 30 - "test_calendar_manage.py"
Cohesion: 0.12
Nodes (34): _approved_user(), _cb(), _ctx(), _ev(), Раздел «Изменить статус встречи»: фильтрация, роутинг, callbacks., Без url мы не сможем обновить PARTSTAT на сервере — такие не показываем., `/manage` шлёт loading и редактирует его в список встреч., Тап по строке встречи → детальный экран с действиями. (+26 more)

### Community 31 - "test_architecture_boundaries.py"
Cohesion: 0.12
Nodes (32): AST, Domain and Telegram Import Layering, _docstring_line_numbers(), _forbidden_import_violations(), _handler_py_files(), _import_from_modules(), _literal_cyrillic_violations(), _literal_html_violations() (+24 more)

### Community 32 - "is_pending_invitation_for_user"
Cohesion: 0.13
Nodes (29): is_pending_invitation_for_user(), True, если пользователю нужно ответить на приглашение (NEEDS-ACTION / DELEGATED), _event(), _ics_needs_action(), _ics_without_attendees(), _MultigetCalendarStub, _MultigetResponse, _prime_discovery() (+21 more)

### Community 33 - "settings_hub.py"
Cohesion: 0.10
Nodes (28): Параметры встроенного HTTP-сервера для Telegram Web App.      ``base_url`` — пуб, WebAppConfig, weather_in_plan_toggle_notice_text(), Плоский DI-контейнер хендлеров и DTO Telegram updates., open_streaming_reply(), Низкоуровневые Telegram-операции: streaming/edit-callback/answer-callback.  Здес, Ack-first навигация с rich HTML экраном., Публичный URL страницы ``/connect`` без персонального токена (menu Web App). (+20 more)

### Community 34 - "StreamingReply"
Cohesion: 0.11
Nodes (15): _draft_unavailable(), _empty_text_rejected(), BaseException, Any, _RevealMode, Статус в rich-draft через ``<tg-thinking>`` (или plain в legacy)., Промежуточное обновление: throttle по времени и приросту., Завершить сессию без финального текста (например, перед sendPhoto).          В l (+7 more)

### Community 35 - "handle_message"
Cohesion: 0.09
Nodes (32): handle_message(), Точка входа для сообщений. Все исключения логируются и не пробрасываются., _enable_draft_telegram(), _plan_handler_context(), LogCaptureFixture, parametrize, При поддержке API — rich-черновик + финальный sendRichMessage, без edit., Два /td подряд → два плана: post-success cooldown снят (см. plan.py).      Реаль (+24 more)

### Community 36 - "CalendarProviderError"
Cohesion: 0.14
Nodes (17): CalendarProviderError, RuntimeError, Безопасная ошибка провайдера (без сырых stack trace для пользователя)., _CachedServicePair, MailruCalendarProvider, date, Event, tzinfo (+9 more)

### Community 37 - "WeatherForecastClient"
Cohesion: 0.14
Nodes (18): Event, _cache_key(), _parse_current_payload(), _parse_hourly_payload(), Any, date, Session, HTTP-клиент Open-Meteo с простым in-memory кэшем по месту и дате. (+10 more)

### Community 38 - "test_web_server.py"
Cohesion: 0.17
Nodes (30): _approve_user(), _free_port(), _http(), _make_init_data(), fixture, Path, Тесты embedded Web App HTTP-сервера: healthz, approval gate, events CRUD., nginx иногда не проксирует X-Telegram-Init-Data — дублируем initData в query. (+22 more)

### Community 39 - "ConnectTokenStore"
Cohesion: 0.10
Nodes (20): Web App Runtime Configuration, Web App Calendar Connection UX, Web App Authentication Failure Diagnosis, HandlerFn, ConnectTokenStore, Path, Краткоживущие токены для Web App, когда Telegram не передаёт initData., find_route() (+12 more)

### Community 40 - "test_events.py"
Cohesion: 0.13
Nodes (30): format_upcoming_events_lines(), Строки тела «Ближайшие события»: заголовки дней и пункты встреч (HTML)., is_all_day_event(), tzinfo, _ev(), test_build_upcoming_events_groups_matches_lines(), test_event_duration_minutes(), test_event_local_start_date_from_datetime_and_date() (+22 more)

### Community 41 - "test_handlers.py"
Cohesion: 0.10
Nodes (30): _display_name(), extract_message(), parse_command_mode(), parse_subscription_action(), PlanMode, SubscriptionAction, _access_ctx(), Длинные алиасы из меню Telegram — рядом с короткими td/tm/dat. (+22 more)

### Community 42 - "DigestSettings"
Cohesion: 0.11
Nodes (14): Telegram Web App and Data Flow, DigestScheduler, date, tzinfo, Один логический шаг. Возвращает число успешно отправленных дайджестов., Результаты ``_maybe_deliver`` по всем подписчикам через общий пул.          ``No, (daily_due, daily_sent, daily_fail, pending_due, pending_sent, pending_fail)., Тикающий планировщик. Запускается отдельным потоком. (+6 more)

### Community 43 - "plan.py"
Cohesion: 0.10
Nodes (23): Streaming Delivery and ActionGuard, ActionGuard, _Key, Дедуп длинных пользовательских действий (per chat + action key).  Зачем нужно: т, Потокобезопасный пер-чат дедуп долгих действий с cooldown'ом., ``True``, если действие можно запускать; ``False`` — занято/cooldown., Снять лок. ``sent=True`` — фиксирует cooldown после успешной отправки., Полный сброс — для изоляции в тестах между прогонами. (+15 more)

### Community 44 - "_time.py"
Cohesion: 0.20
Nodes (25): Доменные константы календарного слоя.  Эти строки используются и для фильтрации, Предикаты-фильтры событий: cancelled, all-day, lunch + index marker.  Все функци, Чистые функции над словарём события: парсинг времени, фильтры, сортировка.  Паке, day_bounds(), event_datetime_bounds(), event_duration_minutes(), event_ends_after(), event_local_end_date() (+17 more)

### Community 45 - "server.py"
Cohesion: 0.18
Nodes (27): handle_connect(), handle_create_event(), handle_delete_event(), handle_disconnect(), handle_list_events(), handle_status(), BaseHTTPRequestHandler, REST-хендлеры календаря: connect / disconnect / status / events CRUD. (+19 more)

### Community 46 - "bot.py"
Cohesion: 0.12
Nodes (18): Lock, Цикл long-polling Telegram-бота с пулом воркеров и graceful shutdown., ChatLockManager, Маленькие потокобезопасные примитивы для бот-цикла.  Назначение: - `ChatLockMana, Возвращает один и тот же `threading.Lock` для одного `chat_id`.      Для отсутст, Атомарное хранилище offset для long-polling Telegram-бота., Отслеживание прогресса обработки update'ов с двумя offset'ами.  В Telegram-семан, Worker/executor orchestration for Telegram updates. (+10 more)

### Community 47 - "event_kinds.py"
Cohesion: 0.14
Nodes (26): EventKind, classify_event_kind(), _event_title(), filter_meetings_for_analytics(), is_system_event(), is_system_event_title(), is_unconfirmed_for_analytics(), Event (+18 more)

### Community 48 - "buttons.py"
Cohesion: 0.12
Nodes (27): button_text_is_calendar_sources(), button_text_is_check_calendar(), button_text_is_connect_calendar(), button_text_is_create_event(), button_text_is_digest_settings(), button_text_is_disconnect_calendar(), button_text_is_foreign_calendars(), button_text_is_invitations() (+19 more)

### Community 49 - "InstanceLock"
Cohesion: 0.14
Nodes (19): InstanceLock, BaseException, Path, Эксклюзивный файловый lock через `fcntl.flock(LOCK_EX | LOCK_NB)`., _hold_lock_in_child(), Path, Захватывает lock в дочернем процессе и ждёт сигнала на выход., Главное свойство: другой процесс не может взять lock, пока первый держит. (+11 more)

### Community 50 - "services.py"
Cohesion: 0.10
Nodes (22): Canonical Project Module Map, Logger, LogRecord, assert_telegram_bot_token_valid(), Проверяет токен через Bot API ``getMe`` (сеть). Вызывать перед long-polling., Settings, _CalDAVNoiseFilter, Path (+14 more)

### Community 51 - "parse_calendar_events"
Cohesion: 0.15
Nodes (24): add_vevent_attendee(), attendee_matches_login_variants(), bump_vevent_dtstamp(), bump_vevent_sequence(), Any, Pure helpers for ATTENDEE/PARTSTAT mutation in ICS components., update_vevent_attendee_partstat(), update_vevent_pending_attendee_partstat() (+16 more)

### Community 52 - "calculate_day_stats"
Cohesion: 0.15
Nodes (24): calculate_day_stats(), date, Считает метрики дня. Отменённые встречи отбрасываются.      Принимает только уже, make_event(), Удобный конструктор NormalizedEvent из ``HH:MM`` для тестов.      Production-пут, Юнит-тесты на расчёт ``DayCalendarStats``.  Покрытие основных продуктовых сценар, test_cancelled_events_are_ignored(), test_empty_day_has_no_meetings_and_only_lunch_subtracted() (+16 more)

### Community 53 - "test_seagull_render.py"
Cohesion: 0.20
Nodes (26): _ev(), date, Снимковые тесты на финальное сообщение «чайки» (раздел 6 и 12 ТЗ)., Удалены все фразы 5.6 — про количество встреч., Удалены все фразы 5.7 — про большой остров / короткие окна / сцепку., Формат как в примере пользователя (дата в заголовке 11.09.2026)., От 4 встреч расписание оборачивается в blockquote (развёрнутый)., Удалены все три фразы про обед-комментарий (свободен/частично/захвачен). (+18 more)

### Community 54 - "test_telegram_api.py"
Cohesion: 0.09
Nodes (26): _capture_call_snapshots(), _ok_response(), Юнит-тесты Telegram API клиента., Mock ``_call`` так, чтобы сохранять снимок ``data`` на момент каждого вызова., Telegram отвечает ``PREMIUM_ACCOUNT_REQUIRED`` — повторяем без эффекта.      Рег, ``sendMessage`` тоже должен переотправляться без эффекта (тот же кейс)., Также реагируем на старое сообщение Telegram про сам `message_effect_id`., Ошибки, не связанные с эффектом, наружу — не маскируем. (+18 more)

### Community 55 - "FakeCalendarService"
Cohesion: 0.16
Nodes (19): FakeCalendarService, FakeCalendarService, Any, Exception, tzinfo, Лёгкий заместитель ``UserCalendarService`` для handler-тестов.      Контракт сов, fixture, MonkeyPatch (+11 more)

### Community 56 - "event_token_cache.py"
Cohesion: 0.14
Nodes (16): apply_user_partstat_to_event(), CachedEventRef, EventTokenCache, InvitationsScreenSnapshot, ManageScreenSnapshot, Any, datetime, Event (+8 more)

### Community 57 - "handlers/__init__.py"
Cohesion: 0.11
Nodes (24): Pattern, Telegram-хендлеры: routing, сценарии и Telegram delivery.  Публичный API (стабил, _button_or_command(), _command_part(), extract_callback_query(), is_check_calendar_request(), is_connect_calendar_request(), is_create_event_request() (+16 more)

### Community 58 - "_collectors.py"
Cohesion: 0.17
Nodes (26): build_upcoming_events_groups(), collect_manageable_events(), collect_pending_invitations(), _day_busy_minutes(), event_relevant_for_invitations(), filter_events_for_user(), format_invitation_list_lines(), format_single_day_events_lines() (+18 more)

### Community 59 - "SubscriptionStorePersistenceError"
Cohesion: 0.11
Nodes (18): JsonStoreLoadError, RuntimeError, Общая транзакционная persistence-логика для JSON-сторов., Durable JSON-store нельзя безопасно загрузить., Per-user digest subscription settings (``logs/subscriptions.json``).  Фасад паке, _coerce_bool(), is_valid_pending_digest_days(), _normalize_digest_time() (+10 more)

### Community 60 - "analyzer.py"
Cohesion: 0.14
Nodes (24): aggregate_hourly(), _avg(), build_weather_summary(), collect_warnings(), filter_hours_in_window(), future_day_start_minutes(), _hour_to_datetime(), _max_v() (+16 more)

### Community 61 - "UpdateDispatcher"
Cohesion: 0.16
Nodes (17): Future, Any, Event, Owns update fan-out into executor workers., UpdateDispatcher, dispatcher_ctx(), fixture, MonkeyPatch (+9 more)

### Community 62 - "CalendarHandle"
Cohesion: 0.19
Nodes (11): CalDAVFetchMixin, Any, date, datetime, Event, tzinfo, REPORT по одному или нескольким календарям; при N>1 — параллельно., REPORT/поиск событий в диапазоне; при битом RRULE — fallback expand=False. (+3 more)

### Community 63 - "TelegramBot"
Cohesion: 0.13
Nodes (12): Any, Long-polling Telegram-бот. Управляет жизненным циклом и оркеструет компоненты., TelegramBot, ``users.json`` повреждён или недоступен., UserStoreLoadError, _bare_bot(), LogCaptureFixture, parametrize (+4 more)

### Community 64 - "test_settings_hub.py"
Cohesion: 0.18
Nodes (23): callback_edit_markup(), ``reply_markup`` из callback-edit (rich или legacy)., _approved_user(), _cb(), _ctx(), Path, Тесты на новую структуру хаба настроек: разделы и двухшаговый disconnect.  Иерар, Заголовок хаба упоминает Чайку и кратко перечисляет разделы. (+15 more)

### Community 65 - "test_calendar_invitations.py"
Cohesion: 0.11
Nodes (19): setter, _ev(), Приглашения: фильтрация NEEDS-ACTION и CalDAV PARTSTAT update., Имитирует ``caldav.Event`` в нужном объёме.      ``data`` — property (getter/set, Кнопка привязана к URL; при ответе событие может выпасть из pending без PARTSTAT, Lookback по дате окончания: длинная встреча с концом 26.05 остаётся после 26.05., Вчерашняя NEEDS-ACTION не должна пропадать сразу после окончания встречи., Mail.ru: PARTSTAT на mailto-алиасе без совпадения с логином CalDAV. (+11 more)

### Community 66 - "calendar_foreign.py"
Cohesion: 0.19
Nodes (21): find_calendar_entry_by_token(), build_foreign_calendars_keyboard(), Убирает парные ``<b>`` — для plain fallback в foreign calendars., strip_bold_tags(), _foreign_calendars(), _foreign_calendars_cached(), _foreign_pairs(), _ForeignResult (+13 more)

### Community 67 - "config.py"
Cohesion: 0.13
Nodes (21): BotConfig, default_weather_config(), _env_value_from_file(), _load_digest_config(), _load_weather_config(), parse_bool_env(), parse_digest_mode(), _parse_float() (+13 more)

### Community 68 - "auth.py"
Cohesion: 0.19
Nodes (14): AuthResolver, Any, BaseHTTPRequestHandler, Валидация Telegram ``initData`` и connect-token'а для Web App.  Авторизованный п, Single source of truth for Web App auth resolution., ResolvedWebUser, error_payload(), Русские сообщения для кодов ошибок Web App API. (+6 more)

### Community 69 - "WebAppServer"
Cohesion: 0.17
Nodes (17): tzinfo, Управляет жизненным циклом HTTP-сервера в фоновом потоке., _safe_zone(), WebAppServer, WebAppServerConfig, _check_caldav_import_paths(), _check_caldav_pin(), _check_healthz_http() (+9 more)

### Community 70 - "test_business_flows_invitations.py"
Cohesion: 0.24
Nodes (21): _ctx(), _ev(), _keyboard_callback_data(), Exception, MonkeyPatch, `/invitations`: горизонт 60d/14d, лимит 12, PARTSTAT, guard release., Стартовый rich-draft — ``<tg-thinking>`` со статусом, не plain HTML., Без прогретого кэша respond делает один fallback-fetch, без post-refresh. (+13 more)

### Community 71 - "CalendarListEntry"
Cohesion: 0.18
Nodes (20): calendar_callback_token(), CalendarListEntry, foreign_calendar_entries(), Календари, пошаренные в аккаунт (все, кроме основного)., clear_foreign_list_cache(), screen_lines(), calendar_source_toggle_lines(), Строки toggle-списка календарей для legacy HTML. (+12 more)

### Community 72 - "normalize_caldav_event"
Cohesion: 0.27
Nodes (20): normalize_caldav_event(), tzinfo, Адаптер из CalDAV-словаря: учитывает зону, клипит к границам дня.      Если собы, _ev(), datetime, Тесты на ``normalize_caldav_event`` — единственный production-путь нормализации, 22:00 предыдущего дня → 03:00 целевого дня → видим только 00:00–03:00., CalDAV отдаёт UTC; нормализатор обязан переводить в локальный TZ. (+12 more)

### Community 73 - "digest_ui.py"
Cohesion: 0.11
Nodes (14): build_digest_days_keyboard(), build_digest_settings_keyboard(), digest_days_screen_text(), digest_time_applied_text(), digest_time_screen_text(), _pending_digest_days_label(), pending_digest_days_screen_text(), pending_digest_settings_screen_text() (+6 more)

### Community 74 - "html.py"
Cohesion: 0.15
Nodes (18): blockquote(), build_copy_text_button(), HTML-разметка для Telegram Bot API (parse_mode=HTML).  Централизует ``<blockquot, Inline-кнопка ``copy_text`` (Bot API 8.0)., Обычный blockquote (Bot API 7.2). ``text`` — без HTML-тегов снаружи., Оборачивает один символ в ``<tg-emoji emoji-id="…">`` для Premium-анимации., Убирает ``<tg-emoji>`` — fallback при отказе Telegram., Убирает атрибут ``expandable`` — fallback для старых серверов.      Сейчас ``exp (+10 more)

### Community 75 - "build_seagull_digest"
Cohesion: 0.21
Nodes (19): build_seagull_digest(), Сборка сообщения «чайки» из проектных событий на конкретную дату.      Семантика, _ev(), Интеграционные тесты high-level дайджеста с CalDAV-словарями., Скрытые «🍕 Обед» не в расписании, но интервал внизу сообщения есть., End-to-end: ICS → парсер → digest. PARTSTAT не должен теряться по дороге., test_digest_clips_multi_day_event_to_workday(), test_digest_drops_caldav_event_with_status_cancelled() (+11 more)

### Community 76 - "weather/__init__.py"
Cohesion: 0.12
Nodes (23): Публичные точки входа погодного слоя., CurrentWeatherSnapshot, Модели данных для погодного блока (без HTTP и без календарной логики)., Мгновенные условия из блока ``current`` ответа Open-Meteo (≈15‑минутная модель)., WeatherSummary, build_weather_details(), build_weather_details_text(), format_surface_pressure_mmhg() (+15 more)

### Community 77 - "Runtime Dependency Set"
Cohesion: 0.13
Nodes (19): Cryptography Typing Dependency 49.0.0, Mypy Pre-commit 2.3.0, Ruff Pre-commit 0.16.0, CalDAV 3.2.1 Container Smoke, Dependency Update Workflow, Exact Dependency Pin Contract, CalDAV 3.2.1 Image Smoke Contract, caldav 3.2.1 (+11 more)

### Community 78 - "snapshot"
Cohesion: 0.20
Nodes (17): _prune_old_snapshots(), datetime, Path, Снапшоты per-user стора на каждом старте бота.  `UserStore`/`SubscriptionStore`, Снимает копию ``path`` в `<parent>/backups/<name>.<timestamp>.bak`.      Возвращ, Снимает копии нескольких файлов; ошибки логируются и не прерывают цикл., Оставляет ``max_snapshots`` самых свежих бэкапов с указанным префиксом., snapshot() (+9 more)

### Community 79 - "test_calendar_selection.py"
Cohesion: 0.24
Nodes (18): final_reply_markup(), ``reply_markup`` из финальной доставки (rich или legacy)., _approved_user(), _assert_no_generic_error(), _ctx(), Path, Тесты выбора календарей для плана., Регрессия: индекс в callback_data ломался при другом порядке CalDAV. (+10 more)

### Community 80 - "run_streaming_caldav_message"
Cohesion: 0.19
Nodes (17): FetchFn, handle_open_invitations(), handle_open_manage_events(), Успешный fetch: rich + fallback HTML и опциональная клавиатура., Потоковый CalDAV-экран для message-команд. ``True`` — ответ доставлен., run_streaming_caldav_message(), StreamingCaldavResult, pick_invitations_effect() (+9 more)

### Community 81 - "PlanBuilder"
Cohesion: 0.27
Nodes (14): PlanConfig, PlanBuilder, Чистая обёртка над «достать → отфильтровать → собрать текст»., _caldav_ev(), _FakeCalendarService, _open_meteo_payload(), date, Юнит-тесты на satellite.plan_service. (+6 more)

### Community 82 - "messages_ru/__init__.py"
Cohesion: 0.12
Nodes (11): User-facing strings — доступ и подключение календаря., User-facing strings — форматирование длительности на русском., _build_bot_help_html(), _build_bot_welcome_html(), User-facing strings — имя бота, welcome/help, подсказка клавиатуры., Пользовательские тексты на русском (фасад).  Все строки и хелперы UI живут в под, User-facing strings — план дня: статусы загрузки и шаблоны строк для seagull., Визуальные токены дизайн-системы: эмодзи-маркеры и чекбоксы. (+3 more)

### Community 83 - "should_fire_for_user"
Cohesion: 0.18
Nodes (18): Дайджест на сегодня (план дня)., should_fire_for_user(), Догон не превращается в дубль: last_sent_iso защищает., До scheduled-минуты — молчим., После scheduled, в тот же день — стреляем (догон после рестарта/сбоя)., _settings(), test_does_not_fire_after_scheduled_if_already_sent_today(), test_does_not_fire_before_scheduled_time() (+10 more)

### Community 84 - "format_upcoming_day_header"
Cohesion: 0.14
Nodes (15): format_duration_long_ru(), _plural_ru(), Форматирование длительности на русском (домен, без UI-текстов)., Длинная форма длительности со склонением: «1 час», «2 часа 30 минут»., Русское склонение по правилам gettext nplurals=3., format_upcoming_day_header(), Заголовок дня в /upcoming: «Сегодня, ср 20.05 (занято 1 час)» / «Пт, 22.05»., manage_list_body_lines() (+7 more)

### Community 85 - "load_settings"
Cohesion: 0.27
Nodes (16): is_valid_webapp_base_url(), load_settings(), Читает .env, валидирует обязательные поля, возвращает иммутабельные настройки., Публичный HTTPS URL для кнопки Web App, не путь к файлу в репозитории., Path, test_digest_mode_from_env_file_overrides_process_env(), test_is_valid_webapp_base_url(), test_load_settings_caldav_cache_ttl_sec() (+8 more)

### Community 86 - "edit_or_send_message"
Cohesion: 0.25
Nodes (15): edit_or_send_message(), Any, Безопасное редактирование сообщений с fallback на отправку нового.  Пользователь, Пытается отредактировать сообщение; если не вышло — шлёт новое.      ``message_i, _fake_telegram(), LogCaptureFixture, Юнит-тесты ``edit_or_send_message``: попытка редактирования и fallback на send., test_edit_fails_then_falls_back_to_send() (+7 more)

### Community 87 - "users/record.py"
Cohesion: 0.18
Nodes (12): admin_id_set(), parse_admin_ids(), Парсинг списка админов из env (``ADMIN_TELEGRAM_IDS``).  Здесь сознательно нет з, Парсит ``ADMIN_TELEGRAM_IDS`` (`,`/`;` разделитель) в кортеж id., Хранилище Telegram-пользователей и их подключений календаря.  JSON-store ``logs/, _coerce_optional_int(), _normalize_calendar_url_list(), _parse_analytics_workday() (+4 more)

### Community 88 - "test_business_flows_webapp.py"
Cohesion: 0.27
Nodes (16): _approve(), _http(), _make_init_data(), fixture, Path, Web App: initData errors, credentials hygiene, API coverage., Yandex в UI «скоро»; API отклоняет с PROVIDER_NOT_IMPLEMENTED., DELETE без ?url= передаёт ``url=None`` в CalendarEventRef (контракт API). (+8 more)

### Community 89 - "styled_button"
Cohesion: 0.14
Nodes (14): ButtonStyle, admin_access_request_html(), admin_pending_list_html(), build_admin_access_keyboard(), User-facing strings — админ: заявки и /pending., Inline-кнопка с опциональным цветом (Bot API: primary / success / danger)., styled_button(), build_create_confirm_keyboard() (+6 more)

### Community 90 - "digest_utils.py"
Cohesion: 0.15
Nodes (15): Daily and Pending Digest Configuration, digest_days_to_bitmask(), is_digest_day_allowed(), is_digest_days_bitmask(), Общие чистые хелперы для доменной логики дайджеста.  Используются и Telegram-хен, Маска из ровно 7 символов ``0``/``1`` (индекс 0 = понедельник)., Нормализует legacy ``weekdays``/``all_days`` и маску в 7-символьную строку., Переключает день в маске. ``None``, если после снятия галочки дней не останется. (+7 more)

### Community 91 - "test_user_access.py"
Cohesion: 0.27
Nodes (14): AdminConfig, Список Telegram id админов, которые могут одобрять заявки., handle_start_or_help(), _admin_cb(), _ctx(), Интеграционные тесты заявок на доступ: UserStore + access/admin handlers., test_admin_approve_notifies_user(), test_admin_reject_notifies_user() (+6 more)

### Community 92 - "respond_callback_nav"
Cohesion: 0.18
Nodes (15): build_analytics_options_keyboard(), handle_open_analytics(), handle_set_analytics_workday(), Экран выбора рабочего дня перед построением отчёта., Ack-first навигация по inline-экранам без тяжёлой работы., respond_callback_nav(), _analytics_workday_10(), _analytics_workday_9() (+7 more)

### Community 93 - "TypingIndicator"
Cohesion: 0.17
Nodes (10): pick_plan_message_effect(), Фоновый ``sendChatAction`` пока идёт долгая операция.      Telegram сбрасывает с, Подбирает эффект финального дайджеста по фразам из ``seagull.templates``., TypingIndicator, Юнит-тесты визуального слоя Telegram., test_is_private_chat(), test_pick_plan_effect_default(), test_pick_plan_effect_empty() (+2 more)

### Community 94 - "make_callback"
Cohesion: 0.18
Nodes (15): callback_edit_was_called(), make_callback(), IncomingCallback с уникальным id (важно: dispatcher dedup'ит по id)., ctx(), fixture, parametrize, Path, Settings hub: callback routing и навигация назад. (+7 more)

### Community 95 - "git-github-auth.sh"
Cohesion: 0.19
Nodes (10): die(), log(), bootstrap-server.sh script, github_ensure_safe_directory(), github_git(), git-github-auth.sh script, die(), log() (+2 more)

### Community 96 - "JsonStoreBase"
Cohesion: 0.19
Nodes (8): Mandatory Architectural Invariants, Canonical Paths and Shared Infrastructure, RecordT, JsonStoreBase, Any, Path, Один lock и commit ``candidate -> disk -> memory``.      Подклассы задают типы п, Записывает candidate и публикует его только после успешного replace.          Ca

### Community 97 - "test_messages.py"
Cohesion: 0.20
Nodes (14): Секции «Ближайшие события» по одному дню (заголовок + события)., HTML тела «Ближайшие события» со сворачиванием по дням., upcoming_events_day_sections(), upcoming_events_html(), _ev(), Заголовок «Ближайшие события» отделён от первого дня одной пустой строкой., Раскладка главной клавиатуры: план дня в первом ряду, виды во втором,     действ, Дневной блок встреч оборачивается в обычный blockquote (развёрнутый). (+6 more)

### Community 98 - "scheduler_policy.py"
Cohesion: 0.20
Nodes (13): datetime, Политика «пора ли стрелять» для per-user дайджестов., Чистый решатель «пора ли стрелять» для одного вида дайджеста., Дайджест непринятых встреч (экран /invitations)., should_fire_at(), should_fire_pending_for_user(), Unit tests for satellite.scheduler_policy., _settings() (+5 more)

### Community 99 - "build_seagull_texts"
Cohesion: 0.32
Nodes (14): build_seagull_texts(), Юнит-тесты на выбор текстов «чайки» по DayCalendarStats., Удалены поля 5.2–5.7; остаются только main и overlaps., _stats(), test_main_dense_at_upper_bound(), test_main_empty_when_no_busy(), test_main_light_for_120_minutes(), test_main_normal_at_upper_bound() (+6 more)

### Community 100 - "CalendarApiService"
Cohesion: 0.30
Nodes (6): ApiResult, CalendarApiService, Any, HTTPStatus, tzinfo, Thin application service shared by Web handlers.

### Community 101 - "parsing.py"
Cohesion: 0.18
Nodes (14): extract_connect_token(), extract_init_data(), parse_date(), parse_datetime(), parse_positive_int(), Any, BaseHTTPRequestHandler, date (+6 more)

### Community 102 - "Satellite Testing Strategy"
Cohesion: 0.18
Nodes (14): Pre-commit Quality Hooks, Full Quality Gate, Release-blocking Business Scenarios, Ruff Mypy and Compile Checks, Targeted Mypy Strict Mode, Shared Test Fixtures, Satellite Testing Strategy, Calendar Digest Capabilities (+6 more)

### Community 103 - "Satellite Architecture"
Cohesion: 0.18
Nodes (14): Best-effort Bot Shutdown, Data-driven Routing, Single-thread Digest Scheduler Model, Encrypted Calendar Credentials, Fail-fast Durable Store Startup, Layered Service Architecture, Per-user Calendar Service, Transport-agnostic Presentation Boundary (+6 more)

### Community 104 - "recognize_message"
Cohesion: 0.14
Nodes (14): Command and Callback Routing Contract, RecognizedCommand, Распознаёт команду или текст reply-кнопки. None — свободный ввод / unknown., recognize_message(), parametrize, Список в BOT_COMMANDS должен полностью совпадать с длинными алиасами роутера., recognize_message не должна иметь side-effect (никаких глобалов с состоянием)., test_bot_commands_list_matches_menu_spec() (+6 more)

### Community 105 - "scheduler.py"
Cohesion: 0.16
Nodes (12): Enum, DigestConfig, Глобальные параметры дайджеста (legacy).      Время и дни недели — в ``Subscript, date, День плана по режиму (команды /today, /tomorrow, …).      Авто-дайджест в ``Dige, resolve_target_date(), Satellite: Mail.ru CalDAV + Telegram daily plan bot., _PendingDeliveryOutcome (+4 more)

### Community 106 - "user_partstat"
Cohesion: 0.23
Nodes (10): Namespace, is_declined_event_for_user(), _partstat_from_attendee_line(), Event, Работа с ATTENDEE/PARTSTAT: declined, pending, лучший статус пользователя.  PART, PARTSTAT из одной строки ATTENDEE или None, если параметра нет., Возвращает PARTSTAT пользователя в событии (верхним регистром) или None.      Ес, user_partstat() (+2 more)

### Community 107 - "calendar_ui.py"
Cohesion: 0.14
Nodes (12): build_calendar_sources_keyboard(), build_create_date_keyboard(), build_create_duration_keyboard(), build_foreign_day_keyboard(), calendar_sources_screen_text(), foreign_calendars_pick_day_text(), User-facing strings — календарные сценарии: upcoming, create, sources, foreign,, Inline-кнопки 15/30/45/60 минут для шага длительности в /create.      Подписи в (+4 more)

### Community 108 - "meetings_ui.py"
Cohesion: 0.18
Nodes (13): build_manage_list_keyboard(), invitations_list_html(), manage_detail_html(), manage_list_html(), manage_partstat_label(), User-facing strings — ответы на встречи: /invitations и /manage (PARTSTAT)., rows: [(token, label like '1️⃣ 14:00 — Standup')]., expandable_blockquote() (+5 more)

### Community 109 - "test_every_cb_constant_has_a_router"
Cohesion: 0.14
Nodes (14): _all_cb_constants(), _fully_mocked_ctx(), Собираем все ``CB_*`` константы из фасада ``messages_ru``.      Возвращаем ``{na, Если CB — префикс, дописываем sample-suffix; иначе оставляем как есть.      Испо, Прогоняет cb через цепочку routers; ловит исключения (мокированный ctx     может, ctx, в котором ВСЕ методы — MagicMock; не зависим от make_ctx., Если константа из allowlist исчезла из messages_ru — allowlist чистим., handle_message без chat_id ничего не отправляет. (+6 more)

### Community 110 - "test_requirements.py"
Cohesion: 0.29
Nodes (12): _active_lines(), _locked_requirement_lines(), parametrize, Path, Контракт human-edited inputs и generated dependency locks., test_dependency_inputs_contain_only_direct_pins(), test_dev_direct_pin_is_present_in_dev_lock(), test_dev_input_dependency_is_exactly_pinned() (+4 more)

### Community 111 - "Operations and Deployment Guide"
Cohesion: 0.21
Nodes (13): Build and Deploy Workflow, GitHub Actions Rolling Deploy, Production Deployment Pipeline, Single Deployment Mode per Bot Token, Docker Deployment, Idempotent Server Update, Legacy Logs Migration Guard, Operations and Deployment Guide (+5 more)

### Community 112 - "Satellite Agent Guide"
Cohesion: 0.21
Nodes (13): Bounded Telegram Update Dispatch, Satellite Agent Guide, Explicit Graphify Update Workflow, Transactional JSON Store Invariant, Docker Deployment Guide, Satellite Configuration Reference, Graphify Developer Guide, Codex Semantic Graph Update (+5 more)

### Community 113 - "invitations_view.py"
Cohesion: 0.32
Nodes (12): collect_pending_from_events(), fetch_invitation_events(), load_pending_invitations_screen(), date, datetime, Event, tzinfo, Общая сборка экрана «непринятые приглашения» для /invitations и scheduler. (+4 more)

### Community 114 - "validate_init_data"
Cohesion: 0.24
Nodes (10): InitDataError, InitDataUser, ValueError, Telegram Web App initData validation., initData не прошла проверку подписи или устарела., HMAC-SHA256 validation per Telegram WebApp docs., validate_init_data(), ValidatedInitData (+2 more)

### Community 115 - "DigestStateStore"
Cohesion: 0.21
Nodes (6): DigestStateStore, Потокобезопасный per-chat state + LRU-dedup для callback_query_id., Атомарно достаёт и удаляет state. Возвращает прошлое состояние или None., True — этот callback_id мы видим впервые и берём в работу.          False — уже, WaitingState, test_digest_state_store_basic_flow()

### Community 116 - "test_analytics_handler.py"
Cohesion: 0.45
Nodes (11): _approved_user(), _ctx(), Path, Регрессия handlers.analytics: непредвиденная ошибка не оставляет «🌀 сводит недел, _run_analytics_callback(), test_calendar_provider_error_uses_caldav_text(), test_duplicate_run_within_cooldown_skips_second_photo(), test_not_connected_error_uses_caldav_text() (+3 more)

### Community 117 - "event_callback_token"
Cohesion: 0.36
Nodes (9): event_callback_token(), Короткие стабильные токены для Telegram ``callback_data`` (≤64 байт)., _ev(), Unit-тесты in-memory кэша token→URL для PARTSTAT respond., test_apply_user_partstat_to_event_updates_matching_login(), test_register_and_lookup_invitations_token(), test_remove_invitations_pending_updates_snapshot(), test_token_expires_after_ttl() (+1 more)

### Community 118 - "warn_if_users_lost"
Cohesion: 0.40
Nodes (10): log_persistence_summary(), Path, warn_if_users_lost(), _make_backup(), Path, Регрессия: warning, когда users/subs пустые, а снапшоты есть.  Реальный сценарий, test_no_warning_when_first_ever_start(), test_no_warning_when_store_is_populated() (+2 more)

### Community 119 - "test_kto_est_kto_in_pending_after_enrich_phase1"
Cohesion: 0.24
Nodes (11): _accepted_fillers(), _kto_est_kto_may26(), MonkeyPatch, До GET: пустые attendees → не pending (почему встреча «пропадала» из списка)., После фазы 1 GET: NEEDS-ACTION → встреча в collect_pending (регрессия 26.05)., invitation_verify=True всегда запускает фазу 1 (_enrich_invitation_missing_atten, 15 ложных ACCEPTED + phase2 limit=1: фаза 1 всё равно подтягивает 26.05., test_enrich_invitation_verify_calls_missing_attendees_phase() (+3 more)

### Community 120 - "test_invitations_partstat_regression.py"
Cohesion: 0.24
Nodes (6): _mailru_context(), parametrize, Регрессии /invitations: Mail.ru REPORT без ATTENDEE и урезанный GET-бюджет.  Сце, Контракт: _service_for_invitations не должен снова стать «5s / 20 GET / 1s timeo, test_mailru_invitations_partstat_refresh_contract(), test_mailru_list_events_for_invitations_enables_partstat_verify()

### Community 121 - "_reset_action_guards"
Cohesion: 0.22
Nodes (8): reset_event_token_cache(), clear_calendar_list_cache(), Сброс трекера между тестами., reset_settings_hub_message_tracker(), fixture, Сбрасывает module-level ``ActionGuard``-синглтоны между тестами.      Назначение, _reset_action_guards(), setup_function()

### Community 122 - "selection.py"
Cohesion: 0.31
Nodes (7): _normalize_url(), Выбор календарей для отображения плана, дайджеста и /upcoming., Фиксированный порядок списка в UI (CalDAV может отдавать календари вразнобой)., sort_calendar_entries(), normalize_calendar_url(), URL helpers без зависимостей от CalDAV/providers (избегаем циклов импорта)., test_sort_calendar_entries_is_stable_by_url()

### Community 123 - "settings_ui.py"
Cohesion: 0.25
Nodes (8): analytics_options_screen_text(), build_settings_calendar_menu_keyboard(), build_settings_disconnect_confirm_keyboard(), User-facing strings — хаб настроек, аналитика, подэкран «Календарь», ошибки hand, settings_hub_status_bits(), settings_hub_text(), test_disconnect_confirm_keyboard_only_has_two_buttons(), test_settings_calendar_menu_groups_all_calendar_actions()

### Community 124 - "ci-deploy-remote.sh"
Cohesion: 0.42
Nodes (7): log(), main(), remote_smoke_public(), remote_update(), setup_ssh(), ci-deploy-remote.sh script, upload_ensure_nginx_script()

### Community 125 - "ensure-nginx-satellite.sh"
Cohesion: 0.57
Nodes (7): ensure_site_include(), log(), main(), reload_nginx(), require_root(), ensure-nginx-satellite.sh script, write_snippet()

### Community 126 - "smoke-prod.sh"
Cohesion: 0.64
Nodes (7): check_api_unauthorized(), check_connect(), check_healthz(), err(), log(), main(), smoke-prod.sh script

### Community 127 - "test_business_flows_smoke.py"
Cohesion: 0.29
Nodes (7): free_tcp_port(), Возвращает свободный TCP порт на 127.0.0.1 — для started_server-фикстур., Path, Smoke-контракт: импорты satellite + /healthz на random port., Каждый подмодуль ``satellite.*`` должен импортироваться (как smoke_container)., test_smoke_container_module_list_imports(), test_webapp_server_healthz_on_random_port()

### Community 128 - "Satellite Docker Deployment Playbook"
Cohesion: 0.29
Nodes (7): Ansible Deployment Configuration, Production Satellite Host, Satellite Docker Deployment Playbook, Satellite Container Deployment, Production Satellite Logs Volume, Production Satellite Service, Single-Container Production Deployment

### Community 129 - "Architecture Refactor Log"
Cohesion: 0.29
Nodes (7): Bounded Telegram Update Backpressure, Transactional JSON Persistence, Architectural Hardening 2026-07-26, Architecture Refactor Log, Lifecycle and Backpressure Hardening, Reproducible Tooling Hardening, Transactional Store Hardening

### Community 130 - "is_lunch_event"
Cohesion: 0.33
Nodes (6): PizzaMealKind, is_lunch_event(), pizza_meal_kind(), Event, 🍕 и одно из слов «завтрак» / «обед» / «ужин» (без учёта регистра)., True для встреч, которые отфильтровывает ``HIDE_LUNCH_EVENTS``.

### Community 131 - "caldav_discovery.py"
Cohesion: 0.40
Nodes (3): build_candidate_urls(), normalize_url(), Pure helpers for CalDAV endpoint discovery and calendar matching.

### Community 132 - "build_settings_hub_keyboard"
Cohesion: 0.33
Nodes (6): build_settings_hub_keyboard(), Главный экран настроек.      Структура: три раздела (Дайджест, Аналитика, Календ, С подключённым календарём в хабе видны оба дайджеста, аналитика, календарь., Без календаря единственное календарное действие — подключиться., test_settings_hub_keyboard_digest_and_calendar_when_connected(), test_settings_hub_keyboard_offers_connect_when_no_calendar()

### Community 133 - "serve_html"
Cohesion: 0.40
Nodes (5): BaseHTTPRequestHandler, Описание SPA-страницы, отдаваемой Web App-сервером., Отдаёт SPA-страницу с инжектом ``window.__SATELLITE_CONNECT_TOKEN__``.      Пара, serve_html(), StaticPage

### Community 134 - "migrate-legacy-logs.sh"
Cohesion: 0.47
Nodes (3): err(), log(), migrate-legacy-logs.sh script

### Community 135 - "Checks Job"
Cohesion: 0.40
Nodes (5): Checks Job, Docker Image Build Job, Rolling Deploy Job, Deploy Pipeline Test Job, Pull Request Checks Job

### Community 136 - "Reproducible Dependency Lock Invariant"
Cohesion: 0.50
Nodes (5): Reproducible Dependency Lock Invariant, Generated Dependency Lock Workflow, UV Generated Lock Contract, Development Direct Dependency Pins, Runtime Direct Dependency Pins

### Community 137 - "instance_lock.py"
Cohesion: 0.40
Nodes (4): InstanceLockError, RuntimeError, Single-instance guard через эксклюзивный `fcntl.flock` на файле.  Гарантирует, ч, Lock уже занят другим процессом.

### Community 139 - "install.sh"
Cohesion: 0.70
Nodes (4): die(), log(), install.sh script, warn()

### Community 140 - "effective_enabled_calendar_urls"
Cohesion: 0.50
Nodes (4): effective_enabled_calendar_urls(), URL календарей для ``UserRecord``., test_effective_urls_falls_back_to_primary(), test_effective_urls_prefers_explicit_list()

### Community 141 - "build_manage_detail_keyboard"
Cohesion: 0.50
Nodes (4): build_manage_detail_keyboard(), Текущий статус помечается ✓, чтобы пользователь видел исходное состояние., test_manage_detail_keyboard_back_to_list(), test_manage_detail_keyboard_marks_current_partstat()

### Community 142 - "notify_handler_failure"
Cohesion: 0.50
Nodes (4): notify_handler_failure(), Best-effort отправка нейтрального текста при необработанной ошибке хендлера., Единая обёртка: TelegramError и прочие исключения не валят процесс бота., _safe_message_run()

### Community 144 - "digest_settings_screen_text"
Cohesion: 0.67
Nodes (3): digest_settings_screen_text(), test_digest_settings_screen_text_disabled(), test_digest_settings_screen_text_enabled()

### Community 146 - "users"
Cohesion: 0.67
Nodes (3): fixture, Path, users()

## Knowledge Gaps
- **35 isolated node(s):** `satellite`, `git-github-auth.sh script`, `Reusable Checks Workflow`, `Build and Deploy Workflow`, `Rolling Deploy Job` (+30 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UserStore` connect `UserStore` to `period_stats.py`, `handlers/access.py`, `conftest.py`, `handle_callback_query`, `providers/base.py`, `ProviderCredentials`, `UserCalendarService`, `test_scheduler.py`, `users`, `test_business_flows_plan.py`, `IncomingMessage`, `CalendarNotConnectedError`, `settings_hub.py`, `WeatherForecastClient`, `test_web_server.py`, `ConnectTokenStore`, `server.py`, `bot.py`, `FakeCalendarService`, `TelegramBot`, `test_settings_hub.py`, `auth.py`, `WebAppServer`, `CalendarListEntry`, `test_calendar_selection.py`, `users/record.py`, `test_business_flows_webapp.py`, `test_user_access.py`, `CalendarApiService`, `scheduler.py`, `user_partstat`, `test_analytics_handler.py`, `warn_if_users_lost`, `test_business_flows_smoke.py`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Why does `HandlerContext` connect `HandlerContext` to `handlers/access.py`, `conftest.py`, `handle_callback_query`, `IncomingCallback`, `notify_handler_failure`, `settings_callbacks.py`, `IncomingMessage`, `CalendarNotConnectedError`, `settings_hub.py`, `handle_message`, `test_handlers.py`, `plan.py`, `bot.py`, `services.py`, `handlers/__init__.py`, `UpdateDispatcher`, `TelegramBot`, `calendar_foreign.py`, `CalendarListEntry`, `run_streaming_caldav_message`, `PlanBuilder`, `format_upcoming_day_header`, `test_user_access.py`, `respond_callback_nav`, `DigestStateStore`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Why does `CalDAVService` connect `CalDAVService` to `is_pending_invitation_for_user`, `test_calendar_invitations.py`, `CalendarProviderError`, `caldav_client.py`, `user_partstat`, `test_calendar_selection.py`, `CalDAVPartstatMixin`, `test_kto_est_kto_in_pending_after_enrich_phase1`, `test_invitations_partstat_regression.py`, `CalendarHandle`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `HandlerContext` (e.g. with `_ForeignResult` and `CalendarListResult`) actually correct?**
  _`HandlerContext` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `IncomingCallback` (e.g. with `_ForeignResult` and `CalendarStateStore`) actually correct?**
  _`IncomingCallback` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `IncomingMessage` (e.g. with `_ForeignResult` and `CalendarStateStore`) actually correct?**
  _`IncomingMessage` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `satellite`, `git-github-auth.sh script`, `Reusable Checks Workflow` to the rest of the system?**
  _35 weakly-connected nodes found - possible documentation gaps or missing edges._