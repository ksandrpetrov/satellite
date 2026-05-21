# Refactor log

Кратко — какие архитектурные фазы прошли через кодовую базу, чтобы будущие
агенты и люди не переоткрывали одни и те же файлы и понимали, какие инварианты
держим. Каждая фаза была behaviour-preserving: внешний контракт (тексты,
callback_data, HTTP-ответы) не менялся без явной продуктовой задачи; baseline
pytest оставался зелёным.

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
4. **Single mutator в `users.py` и `subscriptions.py`** — 13 mutator-методов
   повторяли `lock → get → replace(updated_at=now, ...) → save`. Ввели
   `UserStore._update_locked(uid, **fields)` /
   `_update_locked_with(uid, fn)` и `SubscriptionStore._upsert_locked`.
   Сериализация ушла в `UserRecord.{to,from}_json` /
   `DigestSettings.{to,from}_json`.
5. **Data-driven routing** — `handlers/dispatch.py` и `handlers/routing.py`
   перешли с `isinstance`/`if-elif` цепочек на таблицы: `_MESSAGE_ROUTES`,
   `_CALLBACK_ROUTERS`, `_RECOGNIZERS`. Хелпер `_button_or_command`
   объединил все `is_*_request`-проверки. Добавление новой команды теперь
   стоит одну строку в таблице.
6. **`HandlerContext` — role-based views, `ensure_calendar_*` по IDs** —
   `HandlerContext` остался для совместимости, но получил view-свойства
   `.messaging`, `.identity`, `.calendar`, `.scheduling`. `ensure_calendar_access`
   и `ensure_calendar_connected` принимают keyword-only `chat_id`/`user_id` —
   фабрикация `IncomingMessage` (`_msg_from_cb`) удалена.
7. **`messages_ru.py` → пакет** — 1272-строчный файл превращён в пакет
   `satellite/messages_ru/`. `__init__.py` ре-экспортирует публичное API из
   `_core.py`. Старые импорты `from satellite.messages_ru import X`
   продолжают работать без правок.
8. **Чистка `telegram_bot/`** —
   - `api.py`: 3 метода `setMyName/Description/ShortDescription` свелись к
     wrapper'ам над общим `_set_my(method_name, **fields)`.
   - `analytics_service.py` переехал в `analytics/service.py` (back-compat
     shim остался).
   - `telegram_bot/{calendar,digest}_state.py` переехали в `handlers/`;
     старые пути — re-export shim'ы.
   - В `calendar_create.py` удалили синтетическую обёртку `do_create()` —
     `try/except` теперь напрямую вокруг вызова.
9. **Tooling: ruff + mypy + pre-commit + CI** —
    - `pyproject.toml` с конфигом `ruff` (lint + format) и `mypy`.
    - `requirements-dev.txt` дополнен `ruff`, `mypy`, `pre-commit`.
    - `.pre-commit-config.yaml`: ruff (auto-fix), ruff-format, mypy.
    - `Makefile`: `make lint`, `make format`, `make typecheck`,
      `make check` = `lint + typecheck + compile + test`.
    - CI (`.github/workflows/test.yml`): отдельные jobs `ruff` (блокирующий) и
      `mypy` (информативный, `continue-on-error: true`), плюс `pytest`.
      Strict mypy планируется подключать модуль за модулем по мере очистки.
10. **Документация** — AGENTS.md и docs/ синхронизированы с canonical-путями
    (`visual_cards/base`, `partstat_flow`, `action_guard`,
    single mutator, data-driven routing, `messages_ru/`, `analytics/service`,
    `make check`, `logs/backups/`). Этот файл — чек-лист для будущих
    рефакторингов.
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

- mypy strict пока выключен — план: включать модуль за модулем
  (`web/`, `calendar/providers/`, `plan_service.py`, `scheduler.py`),
  предварительно проставив аннотации.
- `messages_ru/_core.py` ещё монолит (1272 строки). Фаза 8 ограничилась
  превращением файла в пакет; разбиение по сценариям (`calendar/`, `digest/`,
  `settings/`, ...) сделано не было — но фасад готов к этому без миграции
  импортов.
- `analytics_service.py`, `telegram_bot/{calendar,digest}_state.py` — shim'ы
  для back-compat. Когда все внешние импорты перейдут на canonical-пути,
  shim'ы можно удалить.

## GitHub Actions автодеплой (2026-05-21)

- `.github/workflows/deploy.yml`: test → образ в GHCR (`:sha-<short>`; `:latest` на main;
  semver на теге `v*`) → SSH rolling deploy (`scripts/ci-deploy-remote.sh`) только для
  `main` и `workflow_dispatch`. Workflow целиком также триггерится тегом `v*`, но job deploy
  на теге не запускается.
- Job deploy: явная проверка секретов `DEPLOY_HOST` / `DEPLOY_USER` / `SSH_PRIVATE_KEY`;
  lowercase имени образа в GHCR (`tr` вместо `${var,,}`).
- `ci-deploy-remote.sh`: stop/disable legacy `satellite-bot.service` перед `compose up`
  (как в Ansible playbook).
- Compose с `image: ${SATELLITE_IMAGE}`; шаблон `env.j2` пишет `SATELLITE_IMAGE` в `.env` при
  первичном `make deploy`, дальше Actions сам перезаписывает значение.
- Старый `release-docker.yml` удалён (заменён `deploy.yml`).

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
