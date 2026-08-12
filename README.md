# Чайка

Production Telegram-бот для календарных дайджестов из Mail.ru Calendar.

Чайка показывает встречи на сегодня, завтра и послезавтра, умеет отправлять
автоматический дайджест по персональному расписанию, добавляет погодный блок и
говорит с пользователем короткими текстами в своем стиле.

Каждый пользователь подключает свой календарь через Telegram Web App; доступ
к боту выдаётся админом после заявки. Глобальных Mail.ru-паролей и карты
`USER_CALENDAR_MAP` больше нет.

## Содержание

- [Возможности](#возможности)
- [Быстрый старт](#быстрый-старт)
- [Запуск на сервере](#запуск-на-сервере)
- [Конфигурация](#главное-про-конфиг)
- [Документация](#документация)
- [Runtime-файлы](#runtime-файлы)
- [Диагностика](#короткая-диагностика)

---

## Возможности

- Команды `td`, `tm`, `dat`.
- Команды меню `/today`, `/tomorrow`, `/aftertomorrow`, `/after_tomorrow`.
- `/upcoming` — ближайшие события на 7 дней.
- `/invitations` — ответ на приглашения (`NEEDS-ACTION` / `DELEGATED`; горизонт
  60 дней вперёд и 14 назад, до 12 пунктов; ACCEPTED / DECLINED / TENTATIVE в CalDAV).
- `/manage` — изменить статус встречи на неделе (любой PARTSTAT).
- `/create` — пошаговое создание события в календаре.
- `/start`, `/help`, `/settings`, `/connect`.
- Заявка на доступ и одобрение админом (`ADMIN_TELEGRAM_IDS`, `/pending`).
- Подключение календаря Mail.ru через Telegram Web App (per-user credentials;
  кнопки в чате — персональный `/connect/<token>`, TTL 15 мин).
- Inline-хаб настроек: дайджест, выбор календарей для плана, connect/check/disconnect.
- Выбор нескольких CalDAV-календарей для плана и автодайджеста (`enabled_calendar_urls`).
- Просмотр пошаренных («чужих») календарей — `/foreign`, кнопка на главной клавиатуре.
- Web App REST API: список, создание и удаление событий.
- Недельная аналитика (PNG + подпись) из хаба настроек.
- Подписка и отключение дайджеста (`/digest`, `/stopdigest` и экран дайджеста).
- Настройки дайджеста через inline-кнопки (дни, время, вкл/выкл).
- Автоматический дайджест непринятых приглашений (отдельное расписание в
  `/settings` → «📨 Дайджест непринятых встреч»; тот же список, что `/invitations`).
- Дни отправки плана: `weekdays` или `all_days` (экран «🔔 Дайджест на сегодня»).
  Для непринятых — те же пресеты или маска `1111100` (Пн…Вс, хотя бы один день).
- Автоматический дайджест плана всегда на **сегодня** в `digest_timezone`
  пользователя; `DIGEST_MODE` в `.env` на дату не влияет.
- Время отправки (ввод: `09:30`, `9:30`, `9 30` и т.п.): план — `09:00`,
  непринятые — `10:00` по умолчанию (`Europe/Moscow`).
- CalDAV per-user с шифрованием токенов (Fernet); провайдер `mailru` (Yandex — в backend, UI «скоро»).
- Расчет занятости, свободного времени, пересечений и обеда; неподтверждённые
  приглашения не в метриках, в дайджесте помечаются ⚠️.
- Open-Meteo погода с кэшем и безопасным fallback.
- Потоковая доставка плана, `/upcoming`, `/invitations`, `/manage` и недельной
  аналитики (`sendMessageDraft` → финал; аналитика — отдельный `sendPhoto`).
  Повторные тапы ограничивает `ActionGuard` (см. [architecture.md](docs/architecture.md),
  [telegram-ux.md](docs/telegram-ux.md#streaming-delivery)).
- Компактная reply-клавиатура для одобренных (план, upcoming, чужие календари, настройки).
- Thread-safe JSON storage настроек и пользователей.

## Быстрый старт

Нужен Python 3.11 или 3.12. Один из вариантов установки:

**Через bootstrap-скрипт (рекомендуется).** Создаёт `venv/`, ставит зависимости,
готовит `logs/` и `.env` с автосгенерированным `TOKEN_ENCRYPTION_KEY`:

```bash
git clone https://github.com/ksandrpetrov/satellite.git
cd satellite
bash scripts/install.sh --dev    # без --dev для production-only зависимостей
```

**Через Makefile:**

```bash
git clone https://github.com/ksandrpetrov/satellite.git
cd satellite
make install-dev
```

Затем впишите в `.env` минимум `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_IDS`,
`WEBAPP_BASE_URL` (`TOKEN_ENCRYPTION_KEY` уже сгенерирован). Полный список
переменных — [docs/configuration.md](docs/configuration.md).

Запустить long-polling бота:

```bash
source venv/bin/activate
python telegram_test_command.py
# или: make run
```

Прогон тестов и статические проверки:

```bash
python -m pytest
# или: make test
make check   # ruff + mypy + py_compile + pytest (перед коммитом)
make docker-smoke   # после docker build: импорты + /healthz в образе (см. docs/testing.md)
```

## Запуск на сервере

Два варианта: **systemd** (Python на VPS + свой reverse proxy) или **Docker**
(контейнер бота + внешний nginx на хосте, образ из GHCR). Подробнее — [docs/operations.md](docs/operations.md#запуск-на-сервере).

### Развертывание одной командой (systemd)

На чистом Debian/Ubuntu с systemd — клонирует репозиторий в `/opt/satellite`,
ставит Python-окружение, генерирует `.env` с `TOKEN_ENCRYPTION_KEY`,
регистрирует и запускает `satellite-bot.service`:

```bash
sudo GITHUB_TOKEN=ghp_xxxxxxxx bash -c 'set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y && apt-get install -y git
tmp=$(mktemp -d)
trap "rm -rf \"$tmp\"" EXIT
git clone --depth 1 -b main \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/ksandrpetrov/satellite.git" "$tmp"
GITHUB_TOKEN="${GITHUB_TOKEN}" bash "$tmp/scripts/install-server.sh"'
```

Замените `ghp_xxxxxxxx` на реальный PAT — для приватного repo он обязателен,
пароль GitHub по HTTPS не работает (`Password authentication is not supported`).
Bootstrap клонирует репо во временный каталог, а сам `install-server.sh` уже
кладёт код в `/opt/satellite` — это безопасно повторять при ошибках. Короче:
`sudo GITHUB_TOKEN=ghp_xxx bash scripts/bootstrap-server.sh` (из клона репозитория).

Подробности и troubleshooting: [docs/operations.md](docs/operations.md#запуск-на-сервере).

Скрипт идемпотентен: следующий запуск делает `git pull` + переустановку
зависимостей + `systemctl restart` (это же и обновление сервера). Существующий
`.env` сохраняется.

После первой установки:

```bash
sudo nano /opt/satellite/.env                     # TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEBAPP_BASE_URL
sudo systemctl restart satellite-bot.service
journalctl -u satellite-bot.service -f
```

Если репозиторий уже на сервере — `sudo bash /opt/satellite/scripts/install-server.sh`.

Перед production настройте reverse proxy на `WEBAPP_BASE_URL` →
`WEBAPP_HOST:WEBAPP_PORT` (см. [docs/operations.md](docs/operations.md#reverse-proxy-для-web-app)).

### Альтернатива: Docker (бот в контейнере, ваш nginx — снаружи)

Первичный стек — одной командой после правки `deploy/ansible/inventory.yml` и
`deploy/ansible/group_vars/all.yml`:

```bash
make deploy
```

Образы в GHCR собирает [deploy.yml](.github/workflows/deploy.yml) на каждый push в
`main` (теги `:sha-<short>` и `:latest`); перед деплоем CI гоняет **docker smoke**
в образе, после rolling update — **smoke-prod** с публичного URL. Rolling update
на сервер — автоматически по SSH. Подробности: [deploy/README.md](deploy/README.md),
[docs/operations.md](docs/operations.md#docker), [docs/testing.md](docs/testing.md#smoke-образ-и-production-url).

## Главное про конфиг

Минимум для interactive-бота:

```env
TELEGRAM_BOT_TOKEN=<токен от @BotFather>
TOKEN_ENCRYPTION_KEY=<fernet-key>   # install.sh / make env сгенерируют
ADMIN_TELEGRAM_IDS=111111111
WEBAPP_BASE_URL=https://cassinilab.ru/connect
```

При старте `Invalid .env` дают `123456:your-bot-token`, примеры `your-domain.example` /
`satellite.example.com` и путь к `connect.html` в репозитории. `replace-me` и
`replace-with-fernet-key` из `.env.example` в этот список не входят — замените на
реальный токен и ключ из `install.sh`, иначе упадёт `getMe` или шифрование credentials.
См. [configuration.md](docs/configuration.md#валидация-при-старте).

Полная карта переменных: [docs/configuration.md](docs/configuration.md).

## Основной entrypoint

- `telegram_test_command.py` — production long-polling бот.

Дайджест отправляется фоновым шедулером внутри того же процесса по
персональному расписанию каждого пользователя из `logs/subscriptions.json`.

## Документация

**Полный индекс:** [docs/README.md](docs/README.md) — карта по ролям и темам.

| Раздел | Документ |
|--------|----------|
| Архитектура | [docs/architecture.md](docs/architecture.md) |
| Конфигурация | [docs/configuration.md](docs/configuration.md) |
| Telegram UX | [docs/telegram-ux.md](docs/telegram-ux.md) |
| Эксплуатация и деплой | [docs/operations.md](docs/operations.md) |
| Docker (Ansible) | [deploy/README.md](deploy/README.md) |
| Тестирование | [docs/testing.md](docs/testing.md) ([smoke](docs/testing.md#smoke-образ-и-production-url)) |
| Troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Refactor log | [docs/refactor-log.md](docs/refactor-log.md) |
| Покрытие сценариев | [docs/test-coverage-audit.md](docs/test-coverage-audit.md) |
| Карта кода (агенты) | [AGENTS.md](AGENTS.md) |

Скрипты установки и диагностики: `scripts/install.sh`, `install-server.sh`,
`bootstrap-server.sh`, `diagnose_caldav.py`, `diagnose_invitation.py`,
`ci-deploy-remote.sh`, `migrate-legacy-logs.sh`, `docker-smoke-image.sh`,
`smoke-prod.sh` — см. [AGENTS.md](AGENTS.md#скрипты)
и [operations.md](docs/operations.md#запуск-на-сервере). Локально: `make docker-smoke`, `make smoke-prod`.

CI/CD:

- [_checks.yml](.github/workflows/_checks.yml) — reusable: ruff (lint + format check), mypy, py_compile, pytest.
- [test.yml](.github/workflows/test.yml) — только PR (вызывает `_checks.yml`).
- [deploy.yml](.github/workflows/deploy.yml) — push в `main` или тег `v*`: `_checks.yml` → образ в GHCR →
  **docker smoke** (`scripts/docker-smoke-image.sh`: импорты, `caldav==3.2.1`, `/healthz` в образе) → deploy
  (`:sha-<short>`, на main ещё `:latest`, на теге — semver). Rolling deploy по SSH — только для `main`
  и ручного **Run workflow** (healthy + host `/healthz` + `smoke-prod` с публичного URL); тег `v*`
  только публикует образ. Секреты, variable `SMOKE_PUBLIC_BASE_URL` и первичный деплой (Ansible) —
  [deploy/README.md](deploy/README.md).

## Runtime-файлы

Все состояние процесса лежит в `logs/`:

- `bot.log`;
- `bot.lock`;
- `telegram-offset.json`;
- `subscriptions.json` — настройки дайджеста;
- `users.json` — статус доступа и зашифрованные CalDAV-credentials;
- `connect-tokens.json` — краткоживущие токены для Web App (кнопки в чате);
- `backups/` — снапшоты `users.json` и `subscriptions.json` на каждый старт бота
  (последние 20, см. [`satellite/backup.py`](satellite/backup.py)).

`logs/`, `.env`, `venv/` не должны попадать в репозиторий.

## Короткая диагностика

- Бот не стартует: проверьте `TELEGRAM_BOT_TOKEN`, `TOKEN_ENCRYPTION_KEY`,
  `ADMIN_TELEGRAM_IDS`, `WEBAPP_BASE_URL` (только HTTPS, например
  `https://cassinilab.ru/connect`, не путь к `connect.html` в репозитории).
- Команды не работают: пользователь должен быть `approved` и подключить календарь
  (`calendar_status=connected` в `logs/users.json`).
- Нет погоды: `WEATHER_ENABLED=true` и координаты.
- Дайджест не приходит: `/settings`, `digest_enabled`, день недели, время,
  `logs/subscriptions.json`; для непринятых — `pending_digest_enabled` и наличие
  открытых приглашений в момент отправки.
- После деплоя или правок nginx: `make smoke-prod` (публичные `/healthz`, `/connect`,
  `/api/calendar/status`); на сервере сначала `curl http://127.0.0.1:8080/healthz`.

Подробнее: [docs/troubleshooting.md](docs/troubleshooting.md).
