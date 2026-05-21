# Чайка

Production Telegram-бот для календарных дайджестов из Mail.ru Calendar.

Чайка показывает встречи на сегодня, завтра и послезавтра, умеет отправлять
автоматический дайджест по персональному расписанию, добавляет погодный блок и
говорит с пользователем короткими текстами в своем стиле.

Каждый пользователь подключает свой календарь через Telegram Web App; доступ
к боту выдаётся админом после заявки. Глобальных Mail.ru-паролей и карты
`USER_CALENDAR_MAP` больше нет.

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
- Подключение календаря Mail.ru через Telegram Web App (per-user credentials).
- Inline-хаб настроек: дайджест, выбор календарей для плана, connect/check/disconnect.
- Выбор нескольких CalDAV-календарей для плана и автодайджеста (`enabled_calendar_urls`).
- Просмотр пошаренных («чужих») календарей — `/foreign`, кнопка на главной клавиатуре.
- Web App REST API: список, создание и удаление событий.
- Недельная аналитика (PNG + подпись) из хаба настроек.
- Подписка и отключение дайджеста (`/digest`, `/stopdigest` и экран дайджеста).
- Настройки дайджеста через inline-кнопки (дни, время, вкл/выкл).
- Дни отправки: `weekdays` или `all_days`.
- Время отправки дайджеста (ввод: `09:30`, `9:30`, `9 30` и т.п.), по умолчанию
  `09:00 Europe/Moscow`.
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

Один из вариантов на выбор.

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
`main` (теги `:sha-<short>` и `:latest`); rolling update на сервер — автоматически
по SSH. Подробности: [deploy/README.md](deploy/README.md),
[docs/operations.md](docs/operations.md#docker).

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

- [Архитектура](docs/architecture.md)
- [Конфигурация](docs/configuration.md)
- [Telegram UX](docs/telegram-ux.md)
- [Эксплуатация и деплой](docs/operations.md)
- [Docker-деплой (Ansible)](deploy/README.md)
- [Тестирование](docs/testing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [AGENTS.md](AGENTS.md) — карта модулей, инварианты и скрипты для правок кода и AI-агентов

Скрипты установки и диагностики: `scripts/install.sh`, `install-server.sh`,
`bootstrap-server.sh`, `diagnose_caldav.py`, `diagnose_invitation.py`,
`ci-deploy-remote.sh` — см. [AGENTS.md](AGENTS.md#скрипты)
и [operations.md](docs/operations.md#запуск-на-сервере).

CI/CD:

- [test.yml](.github/workflows/test.yml) — ruff, mypy, py_compile, pytest (PR + push).
- [deploy.yml](.github/workflows/deploy.yml) — push в `main` или тег `v*`: test → образ в GHCR
  (`:sha-<short>`, на main ещё `:latest`, на теге — semver). Rolling deploy по SSH — только
  для `main` и ручного **Run workflow**; тег `v*` только публикует образ. Секреты и
  первичный деплой (Ansible) — [deploy/README.md](deploy/README.md).

## Runtime-файлы

Все состояние процесса лежит в `logs/`:

- `bot.log`;
- `bot.lock`;
- `telegram-offset.json`;
- `subscriptions.json` — настройки дайджеста;
- `users.json` — статус доступа и зашифрованные CalDAV-credentials;
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
  `logs/subscriptions.json`.

Подробнее: [docs/troubleshooting.md](docs/troubleshooting.md).
