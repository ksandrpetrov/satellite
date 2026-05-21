# Эксплуатация и деплой

Репозиторий: <https://github.com/ksandrpetrov/satellite>.

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

Два поддерживаемых варианта:

| Вариант | Когда удобно | Обновление |
|---------|--------------|------------|
| **systemd** (`install-server.sh`) | один процесс Python на VPS, свой nginx/Caddy | повторный `install-server.sh` |
| **Docker** (`make deploy`) | бот в контейнере, внешний nginx на хосте берёт TLS | push в `main` → [deploy.yml](../.github/workflows/deploy.yml) (rolling update по SSH); стек/секреты — снова `make deploy` |

Общее: один `TELEGRAM_BOT_TOKEN`, один каталог `logs/` с `users.json` и
`subscriptions.json`. Не смешивайте два варианта на одном сервере с одним токеном.

### Развертывание одной командой (systemd)

На чистом Debian/Ubuntu с systemd (без предварительного клона репозитория).
Скрипт берётся через `git clone`, а не через `curl` к
`raw.githubusercontent.com` — для приватного репозитория raw-URL всегда даёт
404, даже если `git clone` по SSH или с токеном работает.

Приватный репозиторий — передайте **PAT** (`GITHUB_TOKEN` или
`SATELLITE_GITHUB_TOKEN`). GitHub не принимает пароль по HTTPS:
`fatal: Authentication failed ... Password authentication is not supported`.
PAT создаётся в [GitHub → Settings → Developer settings → Personal access
tokens](https://github.com/settings/tokens) (classic-токен с областью `repo`
или fine-grained с правом read-only на репозиторий).

> В команде ниже **замените `ghp_xxxxxxxx` на ваш реальный токен** (`ghp_…` или
> `github_pat_…`). Не вставляйте плейсхолдер дословно.

**Короткий путь** — [`scripts/bootstrap-server.sh`](../scripts/bootstrap-server.sh)
(apt + clone в `/opt/satellite` + `install-server.sh`):

```bash
sudo GITHUB_TOKEN=ghp_xxxxxxxx bash scripts/bootstrap-server.sh
```

Запускайте из клона репозитория на сервере или после ручного `git clone` в
`/opt/satellite`. Для приватного repo без предварительного клона используйте
inline-команду ниже.

Bootstrap-команда (клонирует репо во временный каталог, дальше всё делает
`install-server.sh`; временный каталог удаляется автоматически по `trap`):

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

Команду можно запускать повторно — `install-server.sh` идемпотентен: при
наличии `/opt/satellite/.git` он делает `git pull --ff-only` вместо клона. Это
же и обновление сервера.

Если репозиторий уже на сервере (например, склонирован вручную или предыдущим
запуском), достаточно одного шага без bootstrap:

```bash
sudo GITHUB_TOKEN=ghp_xxxxxxxx bash /opt/satellite/scripts/install-server.sh
```

SSH вместо PAT (для приватного repo нужен ключ, который добавлен в GitHub):

```bash
sudo apt update && sudo apt install -y git
sudo git clone git@github.com:ksandrpetrov/satellite.git /opt/satellite
sudo bash /opt/satellite/scripts/install-server.sh
```

Или передайте SSH-URL через переменную окружения:

```bash
sudo SATELLITE_REPO=git@github.com:ksandrpetrov/satellite.git \
  bash /opt/satellite/scripts/install-server.sh
```

#### Если bootstrap уже падал

- **`Password authentication is not supported`** — клон шёл без токена. Задайте
  `GITHUB_TOKEN=ghp_…` перед `bash -c` и запустите команду заново.
  Если в терминале сохранилась интерактивная подсказка `Username for ...` —
  нажмите `Ctrl+C` и не вводите пароль GitHub: он не сработает.
- **`fatal: destination path '/opt/satellite' already exists and is not an
  empty directory`** — каталог остался от прошлой попытки и не содержит
  валидного клона. Удалите и повторите:

  ```bash
  sudo rm -rf /opt/satellite
  ```

  Затем снова запустите bootstrap-команду выше. Скрипт сам решит: клонировать
  заново или сделать `git pull`. Пустой каталог `/opt/satellite` (без
  содержимого) скрипт удалит автоматически.
- **`/opt/satellite/scripts/install-server.sh: No such file or directory`** —
  в `/opt/satellite` нет клона репозитория (только пустой каталог или мусор).
  Не запускайте `install-server.sh` напрямую — используйте bootstrap-команду
  выше: она склонирует во временный каталог и оттуда запустит скрипт, который
  сам положит код в `/opt/satellite`.

Что делает скрипт (идемпотентно):

1. ставит системные пакеты (`git`, `python3-venv`, `python3-pip`, `ca-certificates`);
2. создаёт системного пользователя `satellite`;
3. клонирует репозиторий в `/opt/satellite` (или делает `git pull --ff-only`,
   если уже клонирован);
4. поднимает `venv`, ставит prod-зависимости через `scripts/install.sh`;
5. генерирует `.env` с автоматическим `TOKEN_ENCRYPTION_KEY` (существующий
   `.env` не трогает);
6. пишет unit `/etc/systemd/system/satellite-bot.service` и запускает его через
   `systemctl enable --now`.

После выполнения остаётся только:

```bash
sudo nano /opt/satellite/.env                     # TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEBAPP_BASE_URL
sudo systemctl restart satellite-bot.service
journalctl -u satellite-bot.service -f
```

Та же команда — это и обновление: повторный запуск делает `git pull` +
переустановку зависимостей + `systemctl restart`. Существующий `.env`
сохраняется.

Если репозиторий уже на сервере (например, склонирован вручную):

```bash
sudo bash /opt/satellite/scripts/install-server.sh
```

Переменные окружения, которыми можно управлять путём установки (все опциональные):

| Переменная | Default | Назначение |
|------------|---------|------------|
| `SATELLITE_DIR` | `/opt/satellite` | Куда клонировать |
| `SATELLITE_USER` | `satellite` | От кого запускать сервис |
| `SATELLITE_GROUP` | `${SATELLITE_USER}` | Группа |
| `SATELLITE_REPO` | `https://github.com/ksandrpetrov/satellite.git` | URL репозитория |
| `SATELLITE_BRANCH` | `main` | Ветка |
| `GITHUB_TOKEN` / `SATELLITE_GITHUB_TOKEN` | — | PAT для HTTPS-клона приватного repo |

Пример с переопределением:

```bash
sudo SATELLITE_DIR=/srv/satellite SATELLITE_BRANCH=stable \
  bash /opt/satellite/scripts/install-server.sh
```

> Reverse proxy для Web App настраивается отдельно — см. раздел
> [Reverse proxy для Web App](#reverse-proxy-для-web-app) ниже.

### Docker

Альтернатива systemd: бот живёт в контейнере, образ собирает GitHub Actions
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
задайте секрет `GHCR_PULL_TOKEN`, см. [deploy/README.md](../deploy/README.md)).

Образ собирается на **Python 3.12** (`Dockerfile`); CI-тесты — на 3.11.

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

#### Автодеплой из GitHub Actions

Перед merge в `main` тесты на PR гоняет отдельный workflow
[`.github/workflows/test.yml`](../.github/workflows/test.yml) (ruff + mypy + pytest);
push в `main` — только [`deploy.yml`](../.github/workflows/deploy.yml) (test + build + deploy).

Push в `main`, ручной запуск workflow `deploy` (`Actions → deploy → Run workflow`)
или merge в `main` после релизного тега делает rolling update без `make deploy`.
Тег `v*` запускает тот же workflow (test + build + semver в GHCR), но job **deploy**
на сервер **не** выполняется — для выката semver-образа на prod используйте
**Run workflow** на ветке `main` или дождитесь push в `main`.

Скрипт [`ci-deploy-remote.sh`](../scripts/ci-deploy-remote.sh) (тот же, что в Actions):
при наличии legacy `satellite-bot.service` останавливает и отключает unit, чтобы
освободить `127.0.0.1:<satellite_host_port>`; затем перезаписывает `SATELLITE_IMAGE`
в `/opt/satellite/.env` на сборку `:sha-<short>`, выполняет `docker compose pull satellite`
и `docker compose up -d satellite`. Job **deploy** перед SSH проверяет наличие
секретов `DEPLOY_HOST`, `DEPLOY_USER`, `SSH_PRIVATE_KEY` (без GitHub Environment).

Секреты репозитория (`Settings → Secrets and variables → Actions`):

| Секрет | Назначение |
|--------|------------|
| `DEPLOY_HOST` | IP/hostname сервера |
| `DEPLOY_USER` | SSH-пользователь |
| `SSH_PRIVATE_KEY` | приватный ключ SSH (публичный — в `authorized_keys` на сервере) |
| `SSH_KNOWN_HOSTS` | опционально: `ssh-keyscan -H $DEPLOY_HOST` |
| `GHCR_PULL_TOKEN` | опционально: PAT с `read:packages` для приватного GHCR-пакета |

`logs/` (volume `satellite-logs`), `TOKEN_ENCRYPTION_KEY` и nginx на хосте этот
путь не трогает — только тег образа бота.

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

Резервная копия перед переносом: volume `satellite-logs` (или каталог после
`docker volume inspect`) и файл `/opt/satellite/.env` (включая `TOKEN_ENCRYPTION_KEY`).

#### Локальный compose (без Ansible)

Эталонный стек: [`deploy/docker-compose.yml`](../deploy/docker-compose.yml).
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

Проверка вручную перед systemd:

```bash
cd /opt/satellite
source venv/bin/activate
python telegram_test_command.py
```

В Telegram отправьте боту `/start`. Остановить тестовый запуск: `Ctrl+C`.

### systemd (если ставили вручную)

Создайте unit-файл `/etc/systemd/system/satellite-bot.service`:

```ini
[Unit]
Description=Satellite Telegram calendar bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=satellite
Group=satellite
WorkingDirectory=/opt/satellite
EnvironmentFile=/opt/satellite/.env
ExecStart=/opt/satellite/venv/bin/python /opt/satellite/telegram_test_command.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Замените `User`/`Group` и пути, если проект лежит не в `/opt/satellite`.
`.env` дополнительно читается процессом через `python-dotenv` из
`WorkingDirectory`, так что обе конструкции (`EnvironmentFile` и dotenv) дают
один и тот же набор переменных.

Включить и запустить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now satellite-bot.service
sudo systemctl status satellite-bot.service
```

Остановить бота:

```bash
sudo systemctl stop satellite-bot.service
```

После изменения unit-файла:

```bash
sudo systemctl daemon-reload
sudo systemctl restart satellite-bot.service
```

Логи:

```bash
journalctl -u satellite-bot.service -f
tail -f /opt/satellite/logs/bot.log
```

После обновления кода достаточно перезапустить сервис:

```bash
sudo systemctl restart satellite-bot.service
```

Полное «обновись и перезапустись» одной командой (идемпотентно: `git pull` +
переустановка зависимостей + перезапуск сервиса, существующий `.env` не
трогает):

```bash
sudo bash /opt/satellite/scripts/install-server.sh
```

Если бот не стартует с ошибкой про lock — уже работает другой процесс с тем же
токеном. Найдите и остановите лишний: `pgrep -af telegram_test_command`.

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

На чистом VPS вместо длинной bootstrap-команды из README можно:

```bash
sudo GITHUB_TOKEN=ghp_xxx bash scripts/bootstrap-server.sh
```

(скрипт из клона репозитория или после `curl` не сработает для приватного repo —
сначала clone с PAT, затем `bash /opt/satellite/scripts/bootstrap-server.sh`).

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

## Scheduler Lifecycle

Scheduler стартует вместе с `TelegramBot` и останавливается при shutdown.

Он не создает отдельные per-user jobs. Вместо этого один thread раз в 30 секунд
проверяет активных подписчиков. Это проще и устойчивее для небольшого числа
пользователей.

## Обновление

**Локально:**

```bash
cd /path/to/satellite
make update                       # git pull + pip install -r requirements.txt
make test                         # опционально
make run
```

Эквивалент без Makefile:

```bash
git pull --ff-only
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
python telegram_test_command.py
```

**На сервере (systemd):**

```bash
sudo bash /opt/satellite/scripts/install-server.sh
```

Скрипт идемпотентен: подтянет код через `git pull --ff-only`, переустановит
зависимости и перезапустит `satellite-bot.service`. Существующий `.env`
сохраняется как есть.

Быстрый ручной апдейт без `install-server.sh` (когда не нужно трогать
systemd-unit и системные пакеты — только код и зависимости):

```bash
cd /opt/satellite && git pull
source venv/bin/activate && pip install -r requirements.txt -q
sudo systemctl restart satellite-bot.service
```

Для production достаточно `requirements.txt`; dev-зависимости нужны только
для локальной разработки и CI.

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
