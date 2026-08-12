# Эксплуатация и деплой

Репозиторий: <https://github.com/ksandrpetrov/satellite>.

**См. также:** [карта документов](README.md) · [deploy/README.md](../deploy/README.md) ·
[configuration.md](configuration.md) · [troubleshooting.md](troubleshooting.md)

## Содержание

- [Локальный запуск](#локальный-запуск)
- [Запуск на сервере](#запуск-на-сервере)
  - [Docker](#docker)
  - [Ручная установка](#ручная-установка)
- [Production-процесс](#production-процесс)
- [Reverse proxy](#reverse-proxy-для-web-app)
- [Runtime State](#runtime-state)
- [Scheduler Lifecycle](#scheduler-lifecycle)
- [Обновление](#обновление)
- [Наблюдение](#наблюдение)

---

## Локальный запуск

Из корня репозитория:

```bash
bash scripts/install.sh --dev          # один раз
source venv/bin/activate
python telegram_test_command.py
```

Эквивалент через Makefile: `make install-dev && make run`.

Остановить: `Ctrl+C`.

## Запуск на сервере

Поддерживаемый способ один — **Docker** (`make deploy`): бот в контейнере,
внешний nginx на хосте берёт TLS. Обновление — push в `main` →
[deploy.yml](../.github/workflows/deploy.yml) (rolling update по SSH);
стек и секреты — снова `make deploy`.

Не запускайте два процесса с одним `TELEGRAM_BOT_TOKEN`: они будут
конкурировать за Telegram updates.

> **Про старый systemd-деплой.** До августа 2026 поддерживался второй путь —
> `scripts/install-server.sh` ставил unit `satellite-bot.service` с venv в
> `/opt/satellite`. Скрипты удалены. Если на сервере остался этот unit,
> деплой погасит его сам: [`scripts/ci-deploy-remote.sh`](../scripts/ci-deploy-remote.sh)
> и Ansible-плейбук делают `systemctl stop` + `disable` перед `compose up`.
> Данные из `/opt/satellite/logs/` переносит
> [`scripts/migrate-legacy-logs.sh`](../scripts/migrate-legacy-logs.sh) — см.
> [«Миграция systemd → Docker»](#миграция-systemd--docker-logs-в-volume) ниже.

### Docker

Бот живёт в контейнере, образ собирает GitHub Actions
и кладёт в GHCR, на сервере `docker compose up -d satellite` поднимает один
контейнер на `127.0.0.1:<satellite_host_port>`. TLS и проксирование
`/connect` / `/api/calendar/*` — ваш существующий nginx на хосте
(см. [`deploy/nginx/satellite-webapp.conf.example`](../deploy/nginx/satellite-webapp.conf.example)).

#### Образ

Workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) на push в `main`
или тег `v*` собирает образ и пушит в GHCR:

```text
ghcr.io/ksandrpetrov/satellite:sha-<short>   # immutable per-commit
ghcr.io/ksandrpetrov/satellite:latest        # только для main
ghcr.io/ksandrpetrov/satellite:<semver>      # для тега vX.Y.Z
```

Для push в main тот же workflow дальше делает rolling deploy на сервер по SSH —
см. раздел [Автодеплой из GitHub Actions](#автодеплой-из-github-actions) ниже.

После первого push сделайте пакет **public**:
`Settings → Packages → satellite → Package settings → Change visibility` (или
задайте секрет `GHCR_PULL_TOKEN` — опционально: без него rolling deploy логинится
через `github.token` job'а, см. [deploy/README.md](../deploy/README.md)).

Образ собирается на **Python 3.12** (`Dockerfile`); CI-тесты идут на 3.11 и 3.12.

#### Подготовка

1. [`deploy/ansible/inventory.yml`](../deploy/ansible/inventory.yml) — IP и SSH-пользователь.
2. [`deploy/ansible/group_vars/all.yml`](../deploy/ansible/group_vars/all.yml):
   - `domain` — пишется в `WEBAPP_BASE_URL`;
   - `satellite_host_port` — порт на хосте (default `8080`), на который проксирует nginx;
   - `telegram_bot_token`, `admin_telegram_ids`;
   - `satellite_image_source: build` для первого деплоя, потом `ghcr`;
   - `token_encryption_key` — пусто при первом деплое (playbook сгенерирует Fernet-ключ; при повторном деплое ключ из существующего `.env` сохраняется).
3. В вашем nginx добавьте `location`-блоки из
   [`deploy/nginx/satellite-webapp.conf.example`](../deploy/nginx/satellite-webapp.conf.example)
   внутрь `server { listen 443 ssl; server_name <domain>; ... }`, затем
   `sudo nginx -t && sudo systemctl reload nginx`.
4. На машине деплоя: `ansible`, SSH-доступ на сервер.

#### Деплой

```bash
make deploy
```

Эквивалент: `cd deploy/ansible && ansible-playbook site.yml`.

Playbook ставит Docker Engine, кладёт `docker-compose.yml` и `.env` в `deploy_dir`
(по умолчанию `/opt/satellite`), поднимает compose-проект `satellite`. nginx
на хосте и его сертификаты playbook не трогает.

| Сервис | Назначение |
|--------|------------|
| `satellite` | Бот; `logs/` в volume `satellite-logs`; порт `127.0.0.1:<satellite_host_port>` |

В `.env` на сервере Ansible прописывает `WEBAPP_HOST=0.0.0.0` (внутри контейнера)
и `WEBAPP_BASE_URL=https://<domain>/connect` — см. [configuration.md](configuration.md).

Порт на хосте задаётся в Ansible (`satellite_host_port` в
[`group_vars/all.yml`](../deploy/ansible/group_vars/all.yml), по умолчанию `8080`),
не в `.env`. nginx должен проксировать на `http://127.0.0.1:<satellite_host_port>`.

#### Миграция со стека Traefik

Раньше `make deploy` поднимал Traefik, Certbot и `nginx-acme`. Сейчас в compose
остался только `satellite`. Повторный `make deploy`:

1. Останавливает старый compose, если в `docker-compose.yml` ещё есть `traefik:`.
2. Удаляет каталог `traefik/` в `deploy_dir`.
3. Накатывает новый `docker-compose.yml` и перезапускает бота.

`logs/` (volume `satellite-logs`) и `TOKEN_ENCRYPTION_KEY` в `.env` сохраняются.
После миграции обязательно добавьте `location` в **ваш** nginx — TLS больше не
выдаёт playbook (см. [Reverse proxy](#reverse-proxy-для-web-app)).

#### Миграция systemd → Docker (logs в volume)

systemd хранил `users.json` / `subscriptions.json` в `/opt/satellite/logs/` **на
хосте**. Compose маунтит volume `satellite_satellite-logs` → `/app/logs`; при
первом `compose up` volume пустой — бот стартует без пользователей, хотя legacy-файлы
целы на диске.

Перед `compose up` [`ci-deploy-remote.sh`](../scripts/ci-deploy-remote.sh) сравнивает
число пользователей на хосте и в volume; если на хосте больше — deploy **падает**
с указателем на миграцию (контейнер с пустым стором не поднимется поверх живых данных).

Однократный перенос:

```bash
sudo bash /opt/satellite/scripts/migrate-legacy-logs.sh
```

Скрипт делает rescue-копию volume в `/root/satellite-rescue-<timestamp>/`, копирует
legacy-логи, `chown` под uid `satellite` внутри образа, поднимает контейнер и ждёт
`healthy`. Идемпотентен; `FORCE=1` — перетереть непустой volume. Подробнее —
[troubleshooting.md — пропали юзеры после Docker](troubleshooting.md#после-деплоя-пропали-юзеры--авторизация--календари-systemd--docker).

#### Автодеплой из GitHub Actions

Перед merge в `main` на PR гоняется
[`.github/workflows/test.yml`](../.github/workflows/test.yml) → reusable
[`_checks.yml`](../.github/workflows/_checks.yml). Push в `main` — тот же
`_checks.yml` внутри [`deploy.yml`](../.github/workflows/deploy.yml), затем build + deploy.

Push в `main`, ручной запуск workflow `deploy` (`Actions → deploy → Run workflow`)
или merge в `main` после релизного тега делает rolling update без `make deploy`.
Тег `v*` запускает тот же workflow (test + build + semver в GHCR), но job **deploy**
на сервер **не** выполняется — для выката semver-образа на prod используйте
**Run workflow** на ветке `main` или дождитесь push в `main`.

Pipeline [`deploy.yml`](../.github/workflows/deploy.yml) после сборки образа гоняет
[`docker-smoke-image.sh`](../scripts/docker-smoke-image.sh) (импорт всех модулей `satellite`,
пин `caldav==3.2.1`, HTTP `/healthz` внутри контейнера через
[`smoke_container.py`](../scripts/smoke_container.py)). Локально: `make docker-smoke`.

Скрипт [`ci-deploy-remote.sh`](../scripts/ci-deploy-remote.sh) (тот же, что в Actions):
нормализует `DEPLOY_HOST` / `DEPLOY_USER` / `SATELLITE_IMAGE` (обрезка CR/LF и
пробелов по краям — иначе SSH: `hostname contains invalid characters`); при наличии
legacy `satellite-bot.service` останавливает и отключает unit, чтобы
освободить `127.0.0.1:<satellite_host_port>`; затем перезаписывает `SATELLITE_IMAGE`
в `/opt/satellite/.env` на сборку `:sha-<short>`, выполняет `docker compose pull satellite`
перед `compose up` — детект legacy `users.json` на хосте vs пустой volume (см.
[миграцию](#миграция-systemd--docker-logs-в-volume)); затем `docker compose up -d satellite`,
ждёт `healthy`, проверяет host `/healthz` (тело парсится как JSON, допустим
`{"status": "ok"}` с пробелами — как отдаёт `json.dumps`) и [`smoke-prod.sh`](../scripts/smoke-prod.sh) с runner (если
`SMOKE_PUBLIC_BASE_URL` не пустой; в Actions по умолчанию `https://cassinilab.ru`) —
публичные `/healthz`, `/connect`, `/api/calendar/status`. Job **deploy** перед SSH
проверяет наличие секретов `DEPLOY_HOST`, `DEPLOY_USER`, `SSH_PRIVATE_KEY`
(без GitHub Environment). База для post-deploy smoke: repository variable
`SMOKE_PUBLIC_BASE_URL` (default `https://cassinilab.ru`); локально —
`make smoke-prod` или `SATELLITE_BASE_URL=https://… make smoke-prod`.

Секреты репозитория (`Settings → Secrets and variables → Actions`):

| Секрет | Назначение |
|--------|------------|
| `DEPLOY_HOST` | IP или hostname (без `https://`, без хвостового `\n` в значении) |
| `DEPLOY_USER` | SSH-пользователь |
| `SSH_PRIVATE_KEY` | приватный ключ SSH (публичный — в `authorized_keys` на сервере) |
| `SSH_KNOWN_HOSTS` | опционально: `ssh-keyscan -H $DEPLOY_HOST` |
| `GHCR_PULL_TOKEN` | опционально: PAT с `read:packages`; если не задан, deploy передаёт на сервер `github.token` (достаточно для пакета этого репозитория) |

**Variables → Actions** (опционально): `SMOKE_PUBLIC_BASE_URL` — база для post-deploy
smoke (default `https://cassinilab.ru`).

`logs/` (volume `satellite-logs`), `TOKEN_ENCRYPTION_KEY` и nginx на хосте этот
путь не трогает — только тег образа бота.

Типичные сбои deploy job (секреты, GHCR, занятый порт 8080, отсутствие compose) —
[troubleshooting.md — автодеплой](troubleshooting.md#автодеплой-github-actions-и-docker-на-сервере).

#### Полный playbook (когда нужен)

Только при изменении конфигурации `.env` (токены, `WEBAPP_BASE_URL`, погода)
или `docker-compose.yml` бота:

1. При необходимости выставьте `image_tag` в `group_vars/all.yml` на конкретный semver.
2. `make deploy` (playbook сделает `docker compose pull` и перезапуск).

#### Наблюдение и данные

```bash
cd /opt/satellite
docker compose logs -f satellite
docker compose ps
```

Логи приложения внутри volume: `docker compose exec satellite tail -f /app/logs/bot.log`.

Проверка с сервера и снаружи после деплоя:

```bash
curl -sS http://127.0.0.1:8080/healthz   # на хосте
make smoke-prod                          # с ноутбука (SATELLITE_BASE_URL при другом домене)
```

См. [testing.md — Smoke](testing.md#smoke-образ-и-production-url), [troubleshooting.md](troubleshooting.md#упал-docker-smoke-job-build-или-smoke-prod-job-deploy).

Резервная копия перед переносом: volume `satellite-logs` (или каталог после
`docker volume inspect`) и файл `/opt/satellite/.env` (включая `TOKEN_ENCRYPTION_KEY`).

#### Локальный compose (без Ansible)

Эталонный стек — шаблон, который Ansible рендерит на сервере:
[`deploy/ansible/templates/docker-compose.yml.j2`](../deploy/ansible/templates/docker-compose.yml.j2).
На сервере после Ansible живёт сгенерированная копия в `deploy_dir`. Для ручной
отладки — `.env` по [`deploy/.env.example`](../deploy/.env.example).

Краткая шпаргалка и CI: [deploy/README.md](../deploy/README.md).

### Ручная установка

Если нужен полный контроль:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip

sudo mkdir -p /opt/satellite
sudo chown "$USER":"$USER" /opt/satellite
git clone https://github.com/ksandrpetrov/satellite.git /opt/satellite
cd /opt/satellite

bash scripts/install.sh
# .env уже создан с автосгенерированным TOKEN_ENCRYPTION_KEY.
# Впишите TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEBAPP_BASE_URL.
```

Проверка вручную:

```bash
cd /opt/satellite
source venv/bin/activate
python telegram_test_command.py
```

В Telegram отправьте боту `/start`. Остановить тестовый запуск: `Ctrl+C`.

## Production-процесс

Основной процесс — один long-polling экземпляр бота. Не запускайте два процесса
с одним `TELEGRAM_BOT_TOKEN`: они будут конкурировать за Telegram updates.

Защита от второго экземпляра:

```text
logs/bot.lock
```

Если lock занят, бот завершится с ошибкой и напишет причину в лог.

## Reverse proxy для Web App

Telegram открывает только публичный HTTPS URL из `WEBAPP_BASE_URL`. Типичная схема:

```text
Internet → nginx/Caddy (TLS) → 127.0.0.1:<порт на хосте>
```

| Вариант | Порт на хосте | `WEBAPP_HOST` в `.env` |
|---------|---------------|------------------------|
| **systemd** | `WEBAPP_PORT` (обычно `8080`) | `127.0.0.1` |
| **Docker** | `satellite_host_port` в Ansible (обычно `8080`) | `0.0.0.0` (внутри контейнера слушает `8080`) |

Готовый фрагмент nginx: [`deploy/nginx/satellite-webapp.conf.example`](../deploy/nginx/satellite-webapp.conf.example).
В `proxy_pass` подставьте тот же порт, что слушает бот на loopback (для Docker —
значение `satellite_host_port` из `group_vars`).

**Проверка, что бот слушает Web App** (на сервере):

```bash
curl -sS http://127.0.0.1:8080/healthz
# ожидается HTTP 200 и {"status":"ok"}
# для Docker с другим satellite_host_port — замените 8080
```

**systemd:** если connection refused — в `/opt/satellite/.env` должны быть
`WEBAPP_HOST=127.0.0.1`, `WEBAPP_PORT=8080`, сервис запущен:
`systemctl status satellite-bot.service`.

**Docker:** `docker compose ps` → `healthy`; в `.env` — `WEBAPP_HOST=0.0.0.0`;
на хосте порт из `docker compose port satellite 8080` или из
`satellite_host_port` в Ansible. Логи: `docker compose logs satellite`.

**nginx (systemd или Docker, домен cassinilab.ru):** внутрь существующего `server { listen 443 ssl; ... }`
добавьте прокси на `/connect` и `/api/calendar/` (без `/api/calendar/` форма
подключения откроется, но сохранение пароля вернёт 404):

```nginx
location /connect {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Telegram-Init-Data $http_x_telegram_init_data;
}
location /api/calendar/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Telegram-Init-Data $http_x_telegram_init_data;
}
location = /healthz {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -sS -o /dev/null -w '%{http_code}\n' https://cassinilab.ru/connect
curl -sS -o /dev/null -w '%{http_code}\n' https://cassinilab.ru/healthz
```

Оба URL должны вернуть **200**, не 404. После этого повторите открытие Web App в Telegram.

Если nginx не проксирует `X-Telegram-Init-Data`, актуальный клиент и сервер всё равно
передают `initData` в query (`?initData=...`) — см. [troubleshooting.md](troubleshooting.md#web-app-сессия-telegram-недействительна--unauthorized).

## Runtime State

```text
logs/bot.log
logs/bot.lock
logs/telegram-offset.json
logs/subscriptions.json
logs/users.json
logs/connect-tokens.json   # краткоживущие Web App connect-токены
logs/backups/          # снапшоты users.json и subscriptions.json
```

- `telegram-offset.json` — offset long-polling.
- `subscriptions.json` — настройки дайджеста.
- `users.json` — статусы доступа и зашифрованные CalDAV-credentials.
- `connect-tokens.json` — персональные токены для `/connect/<token>` (TTL 15 мин;
  переживает рестарт бота, не коммитится).
- `backups/` — при каждом старте бота копии `users.json` и `subscriptions.json`
  (`satellite/backup.py`, последние 20, имя `<file>.YYYYMMDD-HHMMSSZ.bak`).
- `bot.log` — runtime-логи.

Эти файлы не коммитятся. При старте в журнале появляется строка
`Persistence loaded: users total=… approved=… connected=… subscriptions total=…
active=… key_fingerprint=…` — по `key_fingerprint` (sha256[0:8]) видно, что
`TOKEN_ENCRYPTION_KEY` не сменился. Резервное копирование `users.json`, `.env`
(включая `TOKEN_ENCRYPTION_KEY`) и при необходимости `logs/backups/` обязательно
при переносе сервера.

Если `users.json` или `subscriptions.json` содержит невалидный JSON/root/record,
бот после startup-снапшота пишет `CRITICAL` и отказывается запускать scheduler
и Web App. Это намеренная защита от перезаписи повреждённого store пустым
состоянием. Восстановите последний **валидный** файл из `logs/backups/` и
перезапустите процесс; самый свежий snapshot может быть копией уже повреждённого
файла, поэтому проверьте JSON перед восстановлением.

## Scheduler Lifecycle

Scheduler стартует вместе с `TelegramBot` и останавливается при shutdown.

Он не создает отдельные per-user jobs. Вместо этого один thread раз в 30 секунд
проверяет активных подписчиков. Это проще и устойчивее для небольшого числа
пользователей.

Пустая проверка pending-приглашений считается успешно обработанным днём:
сообщение не отправляется, но `last_pending_digest_sent_date` обновляется.
Process-local checkpoint защищает от повторной отправки/проверки в том же
процессе, если durable marker не удалось сохранить.

## Обновление

Docker-деплой на сервере обновляется сам: push в `main` → сборка образа в
GHCR → rolling update по SSH ([deploy.yml](../.github/workflows/deploy.yml)).
Стек и секреты пересобирает `make deploy`.

Локально:

```bash
git pull --ff-only
source venv/bin/activate
pip install -r requirements-dev.txt
make check
make run
```

Прямые пины зависимостей меняют в `requirements.in` / `requirements-dev.in`,
затем `make lock` (`uv==0.11.32`). `make lock-check` проверяет соответствие
локов этим файлам и входит в `make check`.

## Наблюдение

Что смотреть в логах:

- старт и остановка бота;
- ошибки Telegram API;
- ошибки CalDAV;
- ошибки погоды;
- scheduler summary `checked/due/sent/failed`;
- неизвестные callback;
- ошибки валидации времени.

Не должно быть:

- stack trace в сообщениях пользователю;
- токенов в логах TelegramError;
- частых логов каждую секунду без событий.

---

**Далее:** [troubleshooting.md](troubleshooting.md) · [testing.md](testing.md) ·
[deploy/README.md](../deploy/README.md)
