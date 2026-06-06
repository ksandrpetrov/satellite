# Test coverage audit (release-blocking business flows)

Карта бизнес-сценариев Satellite → их реализация → существующее покрытие → дыры → тесты, добавленные в рамках этого аудита.

Цель документа: ни один из перечисленных сценариев не должен незаметно сломаться на релизе. Если строка в колонке **Тесты после аудита** упоминает файл, упавший в нём тест означает блок релиза.

**См. также:** [карта документов](README.md) · [testing.md](testing.md) ·
[telegram-ux.md](telegram-ux.md) · [AGENTS.md](../AGENTS.md)

## Содержание

- [Легенда](#легенда)
- [1. Доступ и onboarding](#1-доступ-и-onboarding)
- [2. Web App](#2-подключение-календаря-через-web-app)
- [3. План дня](#3-план-дня-td-tm-dat-today-tomorrow-aftertomorrow-after_tomorrow)
- [4. `/upcoming`](#4-upcoming)
- [5. `/invitations`](#5-invitations)
- [6. `/manage`](#6-manage)
- [7. `/create`](#7-create-fsm-создания-события)
- [8–17. Настройки, scheduler, analytics…](#8-settings-hub)
- [Release-blocking сводка](#release-blocking-файлы-сводка)
- [Что не покрыто](#что-сознательно-не-покрыто)

---

Источники инвариантов:

- [AGENTS.md](../AGENTS.md) — карта проекта и инварианты.
- [docs/architecture.md](architecture.md) — слои.
- [docs/telegram-ux.md](telegram-ux.md) — публичный контракт команд/кнопок.
- [docs/testing.md](testing.md) — как запускать.

## Легенда

- **Реализация** — где живёт бизнес-логика.
- **Покрытие до аудита** — что уже было.
- **Что не хватало** — конкретные дыры, найденные при аудите.
- **Тесты после аудита** — файлы, добавленные/расширенные в этом проходе. Файл с пометкой *(new)* создан этим аудитом; *(ext)* — расширен.

## 1. Доступ и onboarding

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Новый `/start` создаёт `pending` запись, уведомляет админа, не спамит повторно | [handlers/access.py](../satellite/telegram_bot/handlers/access.py), [users/store.py](../satellite/users/store.py) | [tests/test_user_access.py](../tests/test_user_access.py) `test_start_opens_access_request_and_notifies_admin`, `test_second_start_does_not_spam_admin` | OK | без изменений |
| `/help` доступен всем, удаляет старую reply-клавиатуру | `handle_start_or_help` | `test_help_opens_request_for_pending_user_without_prior_start`, `test_help_sends_help_text_even_when_user_is_new` | Нет явной проверки `REPLY_KEYBOARD_REMOVE` в kwargs `send_message` | [test_business_flows_access.py](../tests/test_business_flows_access.py) *(new)* |
| `/pending` только для админов | `handlers/admin.py::handle_pending_command` | `test_pending_command_lists_open_requests` | Нет теста, что `/pending` от обычного пользователя ничего не делает | [test_business_flows_access.py](../tests/test_business_flows_access.py) *(new)* |
| Approve / reject меняют статус и уведомляют пользователя | `handlers/admin.py::route_admin_callback` | `test_admin_approve_notifies_user`, `test_admin_reject_notifies_user`, `test_non_admin_cannot_approve` | OK | без изменений |
| Rejected/blocked пользователь не может выполнять календарные команды | `handlers/access.py::ensure_calendar_access` | косвенно через handler-тесты | Прямых юнит-тестов на rejected/blocked/unknown ветви не было | [test_business_flows_access.py](../tests/test_business_flows_access.py) *(new)* |
| Approved, но без календаря, получает `CALENDAR_NOT_CONNECTED_HTML` с web-app-клавиатурой | `handlers/access.py::ensure_calendar_connected` | косвенно | Прямого юнит-теста с `webapp_connect_url` keyboard не было | [test_business_flows_access.py](../tests/test_business_flows_access.py) *(new)* |
| Admin первым `/start` авто-апрувится | `handle_start_or_help` | косвенно (через `is_admin`) | Не было явной проверки `USER_STATUS_APPROVED` для admin user | [test_business_flows_access.py](../tests/test_business_flows_access.py) *(new)* |
| Атомарная запись `users.json` (OSError → PersistenceError) | [users/store.py](../satellite/users/store.py) | `test_save_raises_persistence_error_on_disk_failure` | OK | без изменений |

## 2. Подключение календаря через Web App

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `GET /healthz` без auth | [web/server.py](../satellite/web/server.py) | `test_healthz_does_not_require_auth` | OK | без изменений |
| `GET /connect` и `/connect/<token>` отдают HTML с security headers | `web/static_pages.py` | `test_connect_html_served_with_security_headers` | OK | без изменений |
| `initData` через `X-Telegram-Init-Data`, JSON body, query fallback | `web/parsing.py`, `web/auth.py` | `test_status_accepts_init_data_in_query_without_header`, `test_init_data_invalid_signature_returns_401` | Нет таблицы кодов ошибок (`no_init_data`, `bad_signature`, `expired`) | [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(new)* |
| Connect-token fallback (когда нет initData) | `web/connect_token.py`, `web/auth.py` | `test_status_with_connect_token_without_init_data` | Нет теста на просроченный connect-token в HTTP-контексте | [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(new)* |
| Persistence connect-токенов (`logs/connect-tokens.json`) | `web/connect_token.py::ConnectTokenStore` | `test_issue_and_resolve`, `test_expired_token_returns_none` (in-memory only) | Нет round-trip через файл, нет recovery от битого JSON, нет purge-on-save | [test_connect_token.py](../tests/test_connect_token.py) *(ext)* |
| Не-approved пользователь не может вызвать `/api/calendar/*` | `web/auth.py::validated_user` | `test_status_for_pending_user_returns_403` | Только для `status`; нет таблицы по каждому endpoint | [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(new)* |
| Approved + не-подключённый видит `connected=False` | `web/api/calendar.py::handle_status` | `test_status_for_approved_without_calendar` | OK | без изменений |
| `POST /api/calendar/connect` happy / bad provider / yandex `PROVIDER_NOT_IMPLEMENTED` / провайдер-ошибка | `web/api/calendar.py::handle_connect` | `test_connect_happy_path`, `test_connect_invalid_provider_returns_400`, `test_connect_provider_error_propagates_code`, `test_connect_rejects_pending_user` | Не проверено, что сырой пароль не уходит в `users.json`; yandex disabled | [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(ext)* |
| `DELETE /api/calendar/disconnect` | `handle_disconnect` | `test_disconnect_endpoint` | OK | без изменений |
| `GET /api/calendar/events?from=&to=` | `handle_list_events` | `test_list_events_when_not_connected`, `test_list_events_upcoming_view`, `test_list_events_serializes_payload` | Нет проверки явных `from`/`to` query | [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(new)* |
| `POST /api/calendar/events` | `handle_create_event` | `test_create_event_validates_dates`, `test_create_event_with_duration_minutes`, `test_create_event_happy_path` | OK | без изменений |
| `DELETE /api/calendar/events/{uid}?url=` | `handle_delete_event` | `test_delete_event_passes_url_query` | Нет теста без `?url=` | [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(new)* |
| Unknown path → 404 JSON | `web/server.py` | `test_unknown_path_returns_404` | OK | без изменений |
| Все API-routes требуют auth и не валятся 500 | `web/server.py::API_ROUTES` | OK для каждого вручную | Нет контрактного теста, что итерация по `API_ROUTES` не даёт 500 без auth | [test_business_routes_contract.py](../tests/test_business_routes_contract.py) *(new)* |

## 3. План дня (`/td`, `/tm`, `/dat`, `/today`, `/tomorrow`, `/aftertomorrow`, `/after_tomorrow`)

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Все алиасы распознаются | [handlers/routing.py](../satellite/telegram_bot/handlers/routing.py) | `test_parse_command_mode_*`, частичный parametrize в `test_recognize_message_covers_dispatch_commands` | Не было параметризации по полному списку из telegram-ux.md | [test_business_routes_contract.py](../tests/test_business_routes_contract.py) *(new)* |
| Команда вызывает `PlanBuilder.build_text` на корректную дату | [plan_service.py](../satellite/plan_service.py), [handlers/plan.py](../satellite/telegram_bot/handlers/plan.py) | `test_long_menu_commands_invoke_correct_day_offset`, `test_short_aliases_still_work_after_migration` | OK | без изменений |
| ActionGuard 30 с блокирует повтор плана | [handlers/plan.py::_plan_run_guard](../satellite/telegram_bot/handlers/plan.py) | `test_plan_dedup_blocks_second_call_within_cooldown` | Нет теста, что guard сбрасывается после исключения CalDAV (риск: одна ошибка → 30 c глухой блокировки) | [test_business_flows_plan.py](../tests/test_business_flows_plan.py) *(new)* |
| Streaming reply (draft → finish), legacy fallback | `streaming_delivery.py`, `handlers/delivery.py` | `test_plan_uses_send_message_draft_when_supported`, `test_plan_legacy_*`, `test_plan_replaces_loading_with_caldav_error_text` | OK | без изменений |
| Pending invitations не считаются занятостью | `seagull/render.py`, `calendar/events/_partstat.py` | `test_digest_marks_pending_*` в `test_seagull_digest.py` | Нет интеграционного теста через `PlanBuilder.build_text` со смоктнутым CalDAV | [test_business_flows_plan.py](../tests/test_business_flows_plan.py) *(new)* |
| `HIDE_ALL_DAY_EVENTS=true` скрывает all-day | `calendar/events/_filters.py` | `test_filter_events_for_user_removes_declined_lunch_allday` | Нет регрессии на флаг с фронтального хендлера | покрыто косвенно `test_calendar_stats` |

## 4. `/upcoming`

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `/upcoming`, `/events`, кнопка → `handle_upcoming_events` | [handlers/calendar_list.py](../satellite/telegram_bot/handlers/calendar_list.py) | в `test_handlers.py` через `test_recognize_message_covers_dispatch_commands` | Нет тестов, что service вызывается и список рендерится | [test_business_flows_upcoming.py](../tests/test_business_flows_upcoming.py) *(new)* |
| 7-дневный горизонт | `calendar_list.py` | косвенно | Не было прямой проверки `start_date`/`end_date` в kwargs | [test_business_flows_upcoming.py](../tests/test_business_flows_upcoming.py) *(new)* |
| Лимит 30 событий, нумерация emoji | `calendar/events/_collectors.py`, `_filters.py` | `test_format_upcoming_events_lines_skips_cancelled_and_respects_limit` | OK | без изменений |
| Пустой результат + CalDAV error | `handle_upcoming_events` | – | Нет покрытия | [test_business_flows_upcoming.py](../tests/test_business_flows_upcoming.py) *(new)* |
| 15 с cooldown ActionGuard | `_upcoming_guard` | – | Нет теста | [test_business_flows_upcoming.py](../tests/test_business_flows_upcoming.py) *(new)* |

## 5. `/invitations`

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Распознаются `/invitations`, `/invites`, `/respond`, кнопка | `handlers/routing.py` | `test_recognize_invitations_command` | OK | покрыто `test_business_routes_contract.py` |
| Горизонт 60 дней вперёд / 14 назад / лимит 12 | `calendar/events/_collectors.py::collect_pending_invitations` | `test_collect_pending_invitations_*`, `test_event_relevant_uses_end_date_for_multiday_lookback` | Нет проверки лимита 12 в полной интеграции | [test_business_flows_invitations.py](../tests/test_business_flows_invitations.py) *(new)* |
| NEEDS-ACTION / DELEGATED включены, ACCEPTED/DECLINED исключены | `_partstat.py::is_pending_invitation_for_user` | `test_is_pending_*` | OK | без изменений |
| PARTSTAT ответ (принять/отклонить/может быть) → CalDAV update | `handlers/partstat_flow.py`, `calendar/caldav_client.py::set_attendee_partstat` | `test_set_attendee_partstat_updates_ics`, и другие | OK | без изменений |
| Refresh через `edit_callback_message` + fallback на send | `delivery.py::edit_or_send_message` | `test_message_editing.py` | OK | без изменений |
| `_invitations_open_guard` 10 с (cooldown + release on failure) | `calendar_invitations.py` | – | Не было cooldown и release on failure | [test_business_flows_invitations.py](../tests/test_business_flows_invitations.py) *(ext)* |
| Из settings hub → CB_SETTINGS_INVITATIONS | `settings_hub.py` | косвенно | Нет специального теста, что entry-point работает | [test_business_flows_invitations.py](../tests/test_business_flows_invitations.py) *(new)* |

## 6. `/manage`

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Распознаются `/manage`, `/edit`, `/status`, кнопка | `routing.py` | `test_recognize_manage_command` | OK | покрыто `test_business_routes_contract.py` |
| Сбор manageable (на 7 дней, любой PARTSTAT) | `_collectors.py::collect_manageable_events` | `test_collect_manageable_events_*` | OK | без изменений |
| Detail screen + change PARTSTAT | `handlers/calendar_manage.py` | `test_manage_pick_opens_detail_with_action_buttons`, `test_manage_respond_*` | OK | без изменений |
| Access guard (не-подключённый) | `calendar_manage.py::handle_open_manage_events` | – | Не было теста, что guard срабатывает | [test_calendar_manage.py](../tests/test_calendar_manage.py) *(ext)* |
| Guard 10 с cooldown + release after CalDAV failure | `_manage_open_guard` | – | Не было cooldown | [test_calendar_manage.py](../tests/test_calendar_manage.py) *(ext)* |

## 7. `/create` (FSM создания события)

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| start → запрос названия | [calendar_create.py](../satellite/telegram_bot/handlers/calendar_create.py) | – | Нет тестов FSM | [test_business_flows_create.py](../tests/test_business_flows_create.py) *(new)* |
| title (пустой → re-ask) | `handle_create_text_input` STATE_CREATE_TITLE | – | – | то же |
| date: `сегодня`/`today`/`завтра`/`tomorrow`/`DD.MM.YYYY`/`DD.MM.YY`/`YYYY-MM-DD` / invalid | `_parse_target_date` | – | – | то же |
| date callbacks (`CB_CREATE_DATE_*`) + state guard | `_apply_date_preset` | – | – | то же |
| time: `09:30`/`9:30`/`9 30`/`18 25`; invalid `утром`/`900`/`09-00`/`25:00`/`12:99` | `normalize_hhmm_input` | `test_normalize_hhmm_input_*` в `test_digest_settings` | Не было end-to-end через `handle_create_text_input` | то же |
| duration: positive int / zero / negative / >24h / non-int | `STATE_CREATE_DURATION` | – | – | то же |
| duration callback `CB_CREATE_DURATION_PREFIX` + state guard | `_apply_duration_preset` | – | – | то же |
| confirm success (CREATE_EVENT_SUCCESS + party effect) | `_confirm_create` | – | – | то же |
| confirm error mapping (CREATE_FAILED / NO_CALENDAR / CALDAV_UNAVAILABLE / unknown) | `_create_failure_text` | `test_create_failure_text_maps_*` в `test_mailru_create.py` | Не было e2e | то же |
| cancel → CREATE_EVENT_CANCELLED_HTML, state cleared | `route_create_callback` | – | – | то же |
| FSM-exit на любую recognized команду | `dispatch.py::_route_message` clears state | – | – | то же |
| digest_state vs calendar_state precedence | `dispatch.py:121` (digest first) | – | – | то же |

## 8. Settings hub

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `/settings` + кнопка → хаб | `handlers/settings_hub.py::handle_open_settings_hub` | `test_settings_button_opens_hub`, `test_settings_command_clears_create_fsm_and_opens_hub` | OK | без изменений |
| Структура хаба (digest/analytics/calendar menu) | `build_settings_hub_keyboard` | `test_settings_hub_keyboard_*` | OK | без изменений |
| Disconnect → confirmation → actual disconnect | `route_settings_hub_callback` | `test_disconnect_first_click_shows_confirmation_only`, `test_disconnect_confirm_actually_disconnects` | OK | без изменений |
| Каждый CB_SETTINGS_* / CB_ANALYTICS_* / CB_DIGEST_* / CB_PENDING_DIGEST_* имеет router | `_CALLBACK_ROUTERS` | частично | Нет таблицы | [test_business_routes_contract.py](../tests/test_business_routes_contract.py) *(new)*, [test_business_flows_settings.py](../tests/test_business_flows_settings.py) *(new)* |
| Unknown callback → safe answer без crash | `dispatch.py::_route_callback` | косвенно | Прямой тест — в `test_digest_settings.py::test_unknown_callback_is_answered_and_ignored` | OK |

## 9. Digest settings (план и pending)

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `/digest` включает подписку | `handlers/subscription.py::handle_subscription_action` | `test_digest_command_enables_subscription_without_resetting_settings`, `test_digest_command_does_not_open_settings_screen` | OK | без изменений |
| `/stopdigest` отключает, запись сохраняется | – | `test_stopdigest_command_disables_but_keeps_days_and_time` | OK | без изменений |
| Время отправки (валидное сохраняется, invalid — нет, state очищается) | `handlers/settings.py::handle_digest_time_input` | `test_valid_time_input_*`, `test_invalid_time_input_keeps_state_*` | OK | без изменений |
| State чистится кнопками Назад/Закрыть | – | `test_back_to_settings_clears_state`, `test_callback_close_clears_state` | OK | без изменений |
| Команда выходит из state | `dispatch.py::_route_message` | косвенно через `recognize_message` | OK | без изменений |
| Дни недели (план: 2 пресета; pending: bitmask 7 дней) | `digest_utils.py`, `subscriptions.py` | `test_pending_digest_days_*`, `test_is_day_allowed_*`, `test_toggle_digest_days_bitmask_requires_at_least_one_day` | OK | без изменений |

## 10. Scheduler

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Тик отправляет только дозревших подписчиков, помечает `last_sent` | [scheduler.py](../satellite/scheduler.py) | `test_tick_*` (множество) | OK | без изменений |
| Не отправляет дважды в одном tick | – | `test_tick_does_not_double_send_within_same_tick_cycle` | OK | без изменений |
| Один упавший пользователь не блокирует других | – | `test_tick_one_failed_user_does_not_block_others` | Нет явной проверки, что `last_digest_sent_date` упавшего НЕ продвигается | [test_scheduler.py](../tests/test_scheduler.py) *(ext)* |
| Catch-up после пропущенной минуты | – | `test_tick_catches_up_after_missed_scheduled_minute` | OK | без изменений |
| Pending-digest (отправка + skip when empty + bitmask) | `_deliver_pending` | `test_tick_pending_*` | Нет специального теста с маской "Только среда" и `1111100` | [test_scheduler.py](../tests/test_scheduler.py) *(ext)* |
| Резолв пользователя через `telegram_user_id`, не username | – | косвенно | Не было прямой проверки subscription без username | [test_scheduler.py](../tests/test_scheduler.py) *(ext)* |
| TZ minute boundary | `resolve_target_date`, `_deliver_daily` | `test_resolve_target_date` | OK | без изменений |

## 11. Analytics

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Вход из settings hub | `handlers/analytics.py::handle_open_analytics` | косвенно | – | [test_business_flows_settings.py](../tests/test_business_flows_settings.py) *(new)* |
| Сборка отчёта + PNG | `analytics/service.py`, `analytics/render_card.py` | `test_analytics_card.py`, `test_analytics_caption.py`, `test_period_stats.py`, `test_event_kinds.py` | OK | без изменений |
| Error path (CalDAV, not-connected, send_photo) | `analytics.py` | `test_calendar_provider_error_uses_caldav_text`, `test_not_connected_error_uses_caldav_text`, `test_send_photo_failure_replaces_loading_message` | OK | без изменений |
| ActionGuard 45 с + toast «уже строю» | `_analytics_run_guard` | `test_duplicate_run_within_cooldown_skips_second_photo` | OK | без изменений |

## 12. Calendar sources

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `/calendars` / `/calendar_sources` распознаны | `routing.py` | `test_calendar_sources_request_recognized` | OK | покрыто `test_business_routes_contract.py` |
| Пустой `enabled_calendar_urls` → primary | `calendar/selection.py::effective_enabled_calendar_urls` | `test_effective_urls_*` | OK | без изменений |
| Toggle on/off, нельзя отключить последний | `calendar_sources.py` | `test_toggle_disables_secondary_calendar`, `test_cannot_disable_last_calendar` | OK | без изменений |
| Один календарь → hint, без списка | – | `test_single_calendar_shows_hint` | OK | без изменений |

## 13. Foreign / shared calendars

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `/foreign`, `/shared_calendars`, `/foreign_calendars`, кнопка распознаны | `routing.py` | `test_button_and_command_routing` | OK | покрыто `test_business_routes_contract.py` |
| Список без primary | `calendar/selection.py::foreign_calendar_entries` | `test_foreign_calendar_entries_excludes_primary` | OK | без изменений |
| Day picker (today/tomorrow/day_after) | `messages_ru` | `test_foreign_day_keyboard_offers_today_tomorrow_and_day_after` | OK | без изменений |
| Callback flow (pick → day → events) | `calendar_foreign.py::route_foreign_calendars_callback` | `test_foreign_calendars_callback_flow` | OK | без изменений |
| CalDAV error / empty state / refresh-fail | `calendar_foreign.py` | – | Не было прямого теста | покрыто косвенно (cb_flow) — оставлено как известное упрощение, основной риск-репорт через `test_calendar_view_helpers` |

## 14. Telegram API resilience

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Не утечка bot token в логах | `telegram_bot/api.py` | `test_network_error_does_not_leak_bot_token` | OK | без изменений |
| Retry без message effect / без `<tg-emoji>` | `api.py::_set_my`, send_message wrappers | `test_send_message_retries_without_effect_on_premium_required`, `test_send_message_retries_without_tg_emoji_on_*` | OK | без изменений |
| `setMyCommands` / chat menu button | `bot.py`, `visual.py` | `test_setup_bot_identity_*`, `test_set_webapp_menu_button_*` | OK | без изменений |
| Menu commands matches docs | `commands.py` | `test_bot_commands_list_matches_spec` | OK | без изменений |

## 15. Runtime state / persistence / security

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| TokenVault encrypt/decrypt + invalid key + key rotation | [security/token_vault.py](../satellite/security/token_vault.py) | – (только через `test_user_calendar_service.py`) | Не было прямых тестов TokenVault, key rotation, corrupted blob | [test_business_flows_runtime_state.py](../tests/test_business_flows_runtime_state.py) *(new)* |
| Сырой пароль никогда не попадает в `users.json` | `users/store.py`, `web/api/calendar.py::handle_connect` | косвенно | Не было grep-теста | [test_business_flows_runtime_state.py](../tests/test_business_flows_runtime_state.py) *(new)*, [test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) *(new)* |
| `subscriptions.json` атомарная запись + recovery | [subscriptions.py](../satellite/subscriptions.py) | `test_subscriptions.py::test_persistence_*`, `test_load_from_corrupt_file_does_not_crash` | OK | без изменений |
| `users.json` атомарная запись | – | `test_save_raises_persistence_error_on_disk_failure` | OK | без изменений |
| Backup на старте + retention 20 | [backup.py](../satellite/backup.py) | `test_backup.py` (snapshot, prune, retention) | OK | без изменений |
| Persistence warning при пустом сторе с бэкапами | `bot.py::_warn_if_users_lost` | `test_persistence_warning.py` | OK | без изменений |
| Offset watermark не регрессит | `offset_store.py` | `test_polling_offset_does_not_regress` | OK | без изменений |
| bot.lock единственный инстанс | `instance_lock.py` | `test_instance_lock.py` | OK | без изменений |
| Лог hygiene (нет сырого пароля/токена) | – | – | Нет регрессии | [test_business_flows_runtime_state.py](../tests/test_business_flows_runtime_state.py) *(new)* |

## 16. Config validation

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| Reject placeholder bot token / username as admin id / non-HTTPS WEBAPP_BASE_URL | [config.py](../satellite/config.py) | `test_load_settings_rejects_placeholder_bot_token`, `test_load_settings_rejects_username_as_admin_id`, `test_load_settings_rejects_invalid_webapp_url` | OK | без изменений |
| Truthy/falsy parsing (`HIDE_ALL_DAY_EVENTS`, …) | – | `test_parse_bool_env_*` | Не было тестов на конкретные HIDE_* поля | [test_config.py](../tests/test_config.py) *(ext)* |
| `WEBAPP_HOST` 127.0.0.1 vs 0.0.0.0 | – | – | Не было | [test_config.py](../tests/test_config.py) *(ext)* |
| `CALDAV_CACHE_TTL_SEC` parsing | – | – | Не было | [test_config.py](../tests/test_config.py) *(ext)* |

## 17. Smoke / deploy / runtime safety

| Сценарий | Реализация | Покрытие до аудита | Что не хватало | Тесты после аудита |
|---|---|---|---|---|
| `smoke_container.py` импортирует все модули satellite | [scripts/smoke_container.py](../scripts/smoke_container.py) | – (запускается только в Docker smoke) | Нет регрессии в pytest, что список модулей актуален | [test_business_flows_smoke.py](../tests/test_business_flows_smoke.py) *(new)* |
| `WebAppServer` поднимает `/healthz` на random port | `web/server.py` | `test_healthz_does_not_require_auth` (через started_server) | OK | покрыто также `test_business_flows_smoke.py` |
| Migration guard (systemd → Docker logs volume) | [scripts/ci-deploy-remote.sh](../scripts/ci-deploy-remote.sh), `scripts/migrate-legacy-logs.sh` | – (bash) | shell-скрипты в pytest не покрывает, тестируем последнюю линию защиты в Python | покрыто `test_persistence_warning.py` |

## Release-blocking файлы (сводка)

После аудита следующий список тестов фиксирует, что любой регрессионный pull request блокируется при поломке ключевого сценария:

- [tests/test_business_routes_contract.py](../tests/test_business_routes_contract.py) — алиасы команд, меню, dispatch coverage, callback coverage, web routes
- [tests/test_business_flows_access.py](../tests/test_business_flows_access.py) — access guards и onboarding edge cases
- [tests/test_business_flows_plan.py](../tests/test_business_flows_plan.py) — план дня, ActionGuard release on failure
- [tests/test_business_flows_upcoming.py](../tests/test_business_flows_upcoming.py) — `/upcoming` полный flow
- [tests/test_business_flows_invitations.py](../tests/test_business_flows_invitations.py) — `/invitations` 60d/14d/12cap + PARTSTAT
- [tests/test_business_flows_create.py](../tests/test_business_flows_create.py) — `/create` FSM целиком
- [tests/test_business_flows_settings.py](../tests/test_business_flows_settings.py) — настройки навигация
- [tests/test_business_flows_webapp.py](../tests/test_business_flows_webapp.py) — Web App auth/credentials secrets
- [tests/test_business_flows_runtime_state.py](../tests/test_business_flows_runtime_state.py) — TokenVault, persistence, log hygiene
- [tests/test_business_flows_smoke.py](../tests/test_business_flows_smoke.py) — smoke-контракт импортов

## Что сознательно не покрыто

- Реальные сетевые запросы к Mail.ru / Yandex CalDAV и Telegram Bot API — не делаем по требованию инвариантов.
- Полная end-to-end интеграция бота через long-polling — поведение покрывается на уровне dispatch + handlers + scheduler по отдельности.
- Bash-скрипты деплоя (`scripts/ci-deploy-remote.sh`, `scripts/migrate-legacy-logs.sh`) — последняя линия защиты протестирована в Python (`test_persistence_warning.py`).
- Внешний рендер PNG через PIL — покрывается `tests/test_analytics_card.py`; пиксельные snapshot-сравнения не делаем умышленно.

---

**Далее:** [testing.md](testing.md) · [telegram-ux.md](telegram-ux.md) ·
[refactor-log.md](refactor-log.md)
