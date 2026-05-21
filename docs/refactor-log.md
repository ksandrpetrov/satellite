# Refactor log

Кратко — какие архитектурные фазы прошли через кодовую базу, чтобы будущие
агенты и люди не переоткрывали одни и те же файлы и понимали, какие инварианты
держим. Каждая фаза была behaviour-preserving: внешний контракт (тексты,
callback_data, HTTP-ответы) не менялся; baseline pytest-набора оставался
зелёным с теми же двумя историческими failing-кейсами
(`test_calendar_foreign.py::test_foreign_calendars_callback_flow`,
`test_handlers.py::test_plan_legacy_falls_back_to_new_message_when_edit_fails`).

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
    (`visual_cards/base`, `partstat_flow`,
    single mutator, data-driven routing, `messages_ru/`, `analytics/service`,
    `make check`, `logs/backups/`). Этот файл — чек-лист для будущих
    рефакторингов.

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
