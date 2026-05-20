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
- `/start`, `/help`, `/settings`.
- Заявка на доступ и одобрение админом (`ADMIN_TELEGRAM_IDS`, `/pending`).
- Подключение календаря Mail.ru через Telegram Web App (per-user credentials).
- Подписка и отключение дайджеста.
- Настройки дайджеста через inline-кнопки.
- Дни отправки: `weekdays` или `all_days`.
- Время отправки в формате `HH:MM`, по умолчанию `09:00 Europe/Moscow`.
- CalDAV per-user с шифрованием токенов (Fernet).
- Расчет занятости, свободного времени, пересечений и обеда.
- Open-Meteo погода с кэшем и безопасным fallback.
- `sendChatAction` во время долгих операций.
- Паттерн `loading message -> editMessageText`.
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

Прогон тестов:

```bash
python -m pytest
# или: make test
```

## Запуск на сервере

Два варианта: **systemd** (Python на VPS + свой reverse proxy) или **Docker**
(Traefik + Certbot + образ из GHCR). Подробнее — [docs/operations.md](docs/operations.md#запуск-на-сервере).

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
кладёт код в `/opt/satellite` — это безопасно повторять при ошибках.

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

### Альтернатива: Docker (Traefik + Certbot)

Образ публикуется в GHCR на GitHub Release. Деплой одной командой после правки
`deploy/ansible/inventory.yml` и `deploy/ansible/group_vars/all.yml`:

```bash
make deploy
```

Подробности и ручной вариант: [deploy/README.md](deploy/README.md),
[docs/operations.md](docs/operations.md#запуск-на-сервере).

## Главное про конфиг

Минимум для interactive-бота:

```env
TELEGRAM_BOT_TOKEN=123456:your-bot-token
TOKEN_ENCRYPTION_KEY=<fernet-key>
ADMIN_TELEGRAM_IDS=111111111
WEBAPP_BASE_URL=https://cassinilab.ru/connect
```

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
- [AGENTS.md](AGENTS.md) — карта модулей и инварианты для правок кода и AI-агентов

CI: [test.yml](.github/workflows/test.yml) (Python 3.11, `pytest`, compile-check);
образ в GHCR: [release-docker.yml](.github/workflows/release-docker.yml) (на GitHub Release).

## Runtime-файлы

Все состояние процесса лежит в `logs/`:

- `bot.log`;
- `bot.lock`;
- `telegram-offset.json`;
- `subscriptions.json` — настройки дайджеста;
- `users.json` — статус доступа и зашифрованные CalDAV-credentials.

`logs/`, `.env`, `venv/` не должны попадать в репозиторий.

## Короткая диагностика

- Бот не стартует: проверьте `TELEGRAM_BOT_TOKEN`, `TOKEN_ENCRYPTION_KEY`,
  `ADMIN_TELEGRAM_IDS`, `WEBAPP_BASE_URL`.
- Команды не работают: пользователь должен быть `approved` и подключить календарь
  (`calendar_status=connected` в `logs/users.json`).
- Нет погоды: `WEATHER_ENABLED=true` и координаты.
- Дайджест не приходит: `/settings`, `digest_enabled`, день недели, время,
  `logs/subscriptions.json`.

Подробнее: [docs/troubleshooting.md](docs/troubleshooting.md).
