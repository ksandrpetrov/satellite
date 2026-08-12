# Конфигурация

Настройки читаются из `.env` и переменных окружения.

**См. также:** [карта документов](README.md) · [архитектура](architecture.md) ·
[troubleshooting.md](troubleshooting.md) · [.env.example](../.env.example)

## Содержание

- [Обязательные переменные](#обязательные-переменные-для-production-бота)
- [Telegram Web App](#telegram-web-app-встроенный-http)
- [Валидация при старте](#валидация-при-старте)
- [План и CalDAV](#план-и-caldav-глобальные-флаги-фильтрации)
- [Пользователи (`users.json`)](#пользователи-и-доступ-logsusersjson)
- [Digest](#digest)
- [Weather](#weather)
- [Connect-токены](#web-app-connect-токены)
- [Smoke и CI](#smoke-и-ci-не-в-env-бота)

---

Файл по умолчанию:

```text
.env
```

Создать из примера:

```bash
cp .env.example .env
```

Альтернатива — `bash scripts/install.sh` (или `make install`). Скрипт
скопирует `.env.example`, подставит сгенерированный `TOKEN_ENCRYPTION_KEY`
и создаст `venv/` и `logs/`. Существующий `.env` не перезаписывается.

## Обязательные переменные для production-бота

```env
TELEGRAM_BOT_TOKEN=replace-me
TOKEN_ENCRYPTION_KEY=replace-with-fernet-key
ADMIN_TELEGRAM_IDS=111111111
WEBAPP_BASE_URL=https://cassinilab.ru/connect
```

После `scripts/install.sh` или `make env` в `.env` уже будет сгенерированный
`TOKEN_ENCRYPTION_KEY`; `TELEGRAM_BOT_TOKEN` и `WEBAPP_BASE_URL` всё равно нужно
заполнить вручную.

- `TELEGRAM_BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather).
- `TOKEN_ENCRYPTION_KEY` — симметричный ключ Fernet для шифрования
  пользовательских CalDAV-credentials в `logs/users.json`.

  Если вы ставили проект через `scripts/install.sh` или `make env`,
  ключ уже сгенерирован и записан в `.env`. Если собираете `.env` руками:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  При смене ключа старые записи в `users.json` перестанут расшифровываться —
  пользователям нужно подключить календарь заново. Сохраняйте резервную копию
  `.env` вместе с `users.json`.
- `ADMIN_TELEGRAM_IDS` — Telegram user id админов через запятую или `;`.
  Только они одобряют заявки на доступ и видят `/pending`.
- `WEBAPP_BASE_URL` — публичный HTTPS URL страницы «Подключение календаря»
  (Telegram Web App). Клиент открывает этот адрес; reverse proxy проксирует
  на локальный сервер бота (`WEBAPP_HOST` / `WEBAPP_PORT`).

Глобальные `MAIL_LOGIN`, `MAIL_APP_PASSWORD`, `USER_CALENDAR_MAP` и
`TARGET_CALENDAR_NAME` **больше не читаются**. Учётные данные Mail.ru и URL
календаря хранятся per-user в `logs/users.json` (зашифрованный blob).

## Telegram Web App (встроенный HTTP)

```env
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8080
```

- `WEBAPP_HOST` / `WEBAPP_PORT` — bind встроенного HTTP-сервера в процессе бота
  (отдельный поток). Снаружи доступ только через reverse proxy по
  `WEBAPP_BASE_URL`; прямой проброс порта в интернет не нужен.

**Локально и systemd:** оставьте `WEBAPP_HOST=127.0.0.1` — внешний nginx/Caddy
проксирует на `127.0.0.1:8080`.

**Docker (Ansible / compose):** в контейнере нужен `WEBAPP_HOST=0.0.0.0`, иначе
порт не отдастся наружу; контейнер биндится на `127.0.0.1:<satellite_host_port>`
хоста, и наружу его проксирует ваш nginx (см.
[`deploy/nginx/satellite-webapp.conf.example`](../deploy/nginx/satellite-webapp.conf.example)).
Playbook и [`deploy/.env.example`](../deploy/.env.example) выставляют
`WEBAPP_HOST=0.0.0.0` автоматически; `WEBAPP_BASE_URL` собирается как
`https://<domain>/connect`.

Порт публикации на хосте (`127.0.0.1:<port>:8080` в compose) задаётся только в
Ansible — `satellite_host_port` в
[`deploy/ansible/group_vars/all.yml`](../deploy/ansible/group_vars/all.yml), не
отдельной переменной в `.env`. nginx на сервере должен проксировать на этот порт.

**Образ бота на сервере** задаётся переменной `SATELLITE_IMAGE` в `.env` рядом с
`docker-compose.yml` (сервис `satellite` использует `image: ${SATELLITE_IMAGE}`):

```env
SATELLITE_IMAGE=ghcr.io/ksandrpetrov/satellite:latest
```

При первичном `make deploy` Ansible записывает тег из `image_tag` в
`group_vars/all.yml`. После этого rolling update из GitHub Actions
([`deploy.yml`](../.github/workflows/deploy.yml)) перезаписывает
`SATELLITE_IMAGE` на immutable `:sha-<short>` и делает `docker compose pull/up`.
Остальные ключи в `.env` (включая `TOKEN_ENCRYPTION_KEY`) pipeline не трогает.

## Валидация при старте

Production-бот (`run_bot` → `load_settings` с `require_*`) перед long-polling:

1. Отклоняет пустой `TOKEN_ENCRYPTION_KEY` и заглушки токена/Web App:
   `123456:your-bot-token` (и любой токен с подстрокой `your-bot-token`),
   `https://your-domain.example/connect`, `https://satellite.example.com/connect`.
   `TELEGRAM_BOT_TOKEN=replace-me` из `.env.example` **не** попадает в этот список,
   но `getMe` упадёт при старте — замените на реальный токен от @BotFather.
   Строка `replace-with-fernet-key` тоже проходит проверку длины, но шифрование
   credentials не заработает — используйте ключ из `install.sh` / `make env`.
2. Проверяет `WEBAPP_BASE_URL` функцией `is_valid_webapp_base_url` в
   `satellite/config.py`:
   - только `https://`;
   - не путь к файлу в репозитории (`connect.html`, `/static/`, `satellite/web/`).
   - типичная ошибка: `satellite/web/static/connect.html` — бот допишет `/connect`,
     Telegram отклонит URL (`Only HTTPS links are allowed`).
   - эталон production: `https://cassinilab.ru/connect` (домен из
     `deploy/ansible/group_vars/all.yml`).
3. Требует хотя бы один **числовой** id в `ADMIN_TELEGRAM_IDS` (не `@username`).
4. Вызывает Telegram `getMe` — при неверном токене процесс падает с понятным
   текстом (сеть на сервере должна быть доступна).

Сообщения вида `Invalid .env:` или `TELEGRAM_BOT_TOKEN: Telegram отклонил токен`
— см. [troubleshooting.md](troubleshooting.md).

## План и CalDAV (глобальные флаги фильтрации)

```env
TZ_NAME=Europe/Moscow
HIDE_ALL_DAY_EVENTS=true
HIDE_LUNCH_EVENTS=true
CALDAV_CACHE_TTL_SEC=300
```

- `HIDE_ALL_DAY_EVENTS` скрывает all-day события из расписания.
- `HIDE_LUNCH_EVENTS` скрывает события с `🍕` и словами `завтрак`, `обед`,
  `ужин`; они остаются в нижней строке приёма пищи в дайджесте.
- `TZ_NAME` задаёт локальную зону календарного плана и дефолт для новых
  подписок на дайджест.
- Окно рабочего дня и обед для метрик busy/free **не** настраиваются через env:
  дефолты в коде — `10:00–19:00`, обед `13:00–14:00`
  (`satellite/calendar/stats.py`, `WorkdayOptions`).
- `CALDAV_CACHE_TTL_SEC` — TTL кэша discovery principal+calendars (0 = без кэша).

Опциональный `CALDAV_URL` в `.env` больше не используется конфигом бота:
endpoint выбирается при подключении календаря пользователя.

## Telegram (тюнинг бота)

```env
BOT_WORKERS=4
BOT_LONG_POLL_SEC=30
```

- `BOT_WORKERS` — размер worker pool для обработки updates.
- `BOT_LONG_POLL_SEC` — timeout `getUpdates`.

`TELEGRAM_CHAT_ID` не нужен основному боту — каждый пользователь общается с ботом
в своём личном чате, и `chat_id` берётся из апдейта или из `logs/users.json`.

## Пользователи и доступ (`logs/users.json`)

Единственный источник правды по авторизации — JSON-store
`satellite/users/` (пакет: `record.py` / `store.py` / `admin.py`) → `logs/users.json`.

Поля записи (`UserRecord`):

```text
telegram_user_id   # ключ в JSON (int)
chat_id            # последний известный chat
username           # Telegram @username (нормализован)
display_name       # имя из Telegram
status             # pending | approved | rejected | blocked
access_request_*   # состояние заявки на доступ
calendar_provider  # mailru | yandex
encrypted_credentials  # Fernet-blob (login + app password)
calendar_status    # disconnected | connected | invalid | error
primary_calendar_url   # CalDAV URL календаря (без display name — PII)
enabled_calendar_urls  # tuple URL — какие календари в плане/дайджесте;
                       # пусто = только primary_calendar_url
```

Поток для нового пользователя:

1. `/start` — создаётся или обновляется запись, при необходимости открывается
   заявка `access_request_status=pending`.
2. Админы из `ADMIN_TELEGRAM_IDS` одобряют через `/pending` (или отклоняют).
3. После `status=approved` пользователь подключает календарь через Web App;
   выбирает провайдер (`mailru` — production; `yandex` — backend готов, в UI
   пока disabled). Credentials шифруются `TokenVault` и сохраняются в store.
4. Команды плана и дайджест доступны только при `has_calendar` (approved +
   connected + непустые credentials).

Запись на диск атомарная: `tmp + fsync + os.replace` (как у `subscriptions.json`).

## Digest

Новые подписчики получают дефолты в `logs/subscriptions.json`:

```text
digest_enabled = false
digest_days = weekdays
digest_time = 09:00
digest_timezone = Europe/Moscow
```

Персональные значения меняются через `/settings` в хабе настроек:

- **🔔 Дайджест на сегодня** — план дня (`digest_*`);
- **📨 Дайджест непринятых встреч** — напоминание о `NEEDS-ACTION` / `DELEGATED`
  (`pending_digest_*`; тот же экран, что `/invitations`, без streaming).

Дефолты для `pending_digest_*` при создании записи:

```text
pending_digest_enabled = false
pending_digest_days = weekdays
pending_digest_time = 10:00
pending_digest_timezone = Europe/Moscow
```

Поля записи в JSON (ключ — `chat_id`):

```text
chat_id
telegram_user_id   # для резолва UserRecord в шедулере (не @username)
username
digest_enabled
digest_days        # weekdays | all_days (UI — два пресета)
digest_time        # HH:MM
digest_timezone    # IANA, напр. Europe/Moscow
subscribed_at
last_digest_sent_date
pending_digest_enabled
pending_digest_days  # weekdays | all_days | 7-битная маска (Пн=0…Вс=6, ≥1 «1»)
pending_digest_time         # default 10:00 при отсутствии в JSON
pending_digest_timezone
last_pending_digest_sent_date
```

Шедулер (`scheduler.py`) опрашивает оба расписания независимо; допустимость
дня недели — `is_digest_day_allowed` в [`digest_utils.py`](../satellite/digest_utils.py)
(для `pending_digest_days` поддерживается и маска). Дайджест непринятых
отправляется только если в момент срабатывания есть хотя бы одно неотвеченное
приглашение; иначе тик молча пропускается (без сообщения и без обновления
`last_pending_digest_sent_date`).

Автоматический **дайджест плана** («🔔 Дайджест на сегодня») всегда строится
на **текущий день** в часовом поясе пользователя. Режимы «завтра»/«послезавтра»
— только у команд `/tomorrow`, `/dayafter` и кнопок плана. Время и дни отправки
— per-user в `logs/subscriptions.json`, не в env.

Глобальных env-переменных для дайджеста нет: `DIGEST_MODE`, `DIGEST_TIME`,
`DIGEST_WEEKDAYS_ONLY` и `DIGEST_CATCHUP_WINDOW_HOURS` удалены.

## Weather

Погода выключена по умолчанию.

```env
WEATHER_ENABLED=true
WEATHER_LOCATION={"name": "Москва", "latitude": 55.7558, "longitude": 37.6173, "timezone": "Europe/Moscow"}
WEATHER_SHOW_NORMAL=true
WEATHER_CACHE_TTL_MINUTES=30
```

Можно задать location отдельными переменными:

```env
WEATHER_LOCATION_NAME=Москва
WEATHER_LATITUDE=55.7558
WEATHER_LONGITUDE=37.6173
WEATHER_TIMEZONE=Europe/Moscow
```

`WEATHER_SHOW_NORMAL=false` скрывает строку погоды, если нет предупреждений.

## Logging

```env
LOG_LEVEL=INFO
```

Допустимые практические значения: `DEBUG`, `INFO`, `WARNING`, `ERROR`.

## Web App connect-токены

Кнопки «Подключить календарь» в чате выдают персональный URL
`/connect/<token>` (см. [`webapp_connect_url`](../satellite/telegram_bot/handlers/delivery.py)).
Токены хранятся в `logs/connect-tokens.json` (TTL **900 с**, атомарная запись).
Отдельных env-переменных нет. Menu Button в BotFather использует только
`WEBAPP_BASE_URL` без токена — там авторизация идёт через `initData`.

## Smoke и CI (не в `.env` бота)

Эти переменные **не** читает `load_settings` и не нужны в production `.env` на сервере.

| Переменная | Где | Назначение |
|------------|-----|------------|
| `SATELLITE_BASE_URL` | локально, `scripts/smoke-prod.sh` | Публичный origin без `/connect` (default `https://cassinilab.ru`). Проверяет `/healthz`, `/connect`, `/api/calendar/status`. |
| `SMOKE_PUBLIC_BASE_URL` | GitHub Actions variable, `ci-deploy-remote.sh` | То же для post-deploy smoke после rolling deploy. Пустое значение — public smoke пропускается. В [`deploy.yml`](../.github/workflows/deploy.yml) default `https://cassinilab.ru`. |

Локально: `make smoke-prod`, `SATELLITE_BASE_URL=https://… make smoke-prod`.
Образ после сборки: `make docker-smoke` — см. [testing.md](testing.md#smoke-образ-и-production-url).

## Файлы, которые нельзя коммитить

- `.env`;
- `logs/` (включая `users.json`, `subscriptions.json`, `connect-tokens.json`,
  `backups/`, `bot.log`, lock, offset);
- `venv/`.

---

**Далее:** [operations.md](operations.md) · [troubleshooting.md](troubleshooting.md) ·
[telegram-ux.md](telegram-ux.md)
