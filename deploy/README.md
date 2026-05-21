# Docker-деплой (GHCR + Traefik + Certbot)

## CI/CD: GitHub Actions под ключ

Workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) на каждый push в `main`
или тег `v*`:

1. **test** — ruff (lint + format check), py_compile, pytest.
2. **build** — Docker-образ в GHCR: `:sha-<short>` (всегда), `:latest` (только `main`),
   semver-теги (только `v*`).
3. **deploy** — SSH на сервер: обновить `SATELLITE_IMAGE` в `.env`, `docker compose pull satellite`,
   `docker compose up -d satellite`. **Только** для push в `main` и ручного `workflow_dispatch`
   (тег `v*` образ публикует, на сервер не катит — для релиза на prod используйте **Run workflow**
   или дождитесь merge в `main`).

Пакет в GHCR после первой сборки сделайте **public** (или задайте `GHCR_PULL_TOKEN`, см. ниже):
`Settings → Packages → satellite → Package settings → Change visibility`.

### Первый деплой без образа в GHCR

В [`ansible/group_vars/all.yml`](ansible/group_vars/all.yml) по умолчанию
`satellite_image_source: build` — playbook **собирает образ на сервере** из
исходников репозитория (не тянет `ghcr.io/.../satellite:latest`).

После того как GitHub Actions хотя бы раз запушил образ в GHCR, переключите:

```yaml
satellite_image_source: ghcr
```

и снова `make deploy` (или дальше только push в `main` — Actions сам обновит бота).

### Секреты для деплоя (Settings → Secrets and variables → Actions)

| Секрет | Назначение |
|--------|------------|
| `DEPLOY_HOST` | IP или hostname сервера |
| `DEPLOY_USER` | SSH-пользователь (`root` или deploy-user) |
| `SSH_PRIVATE_KEY` | приватный ключ SSH (публичный — в `authorized_keys` на сервере) |
| `SSH_KNOWN_HOSTS` | опционально: вывод `ssh-keyscan -H <DEPLOY_HOST>` |
| `GHCR_PULL_TOKEN` | опционально: PAT с `read:packages` для приватного пакета GHCR |

## Перед деплоем

1. Отредактируйте [`ansible/inventory.yml`](ansible/inventory.yml) — IP и SSH-пользователь.
2. Отредактируйте [`ansible/group_vars/all.yml`](ansible/group_vars/all.yml):
   - `domain`, `certbot_email`
   - `telegram_bot_token`, `admin_telegram_ids`
   - `image_tag` для первичного деплоя (`latest`, semver или `sha-<commit>`)
3. DNS: A-запись `domain` → IP сервера, порты **80** и **443** открыты.
4. На машине, с которой запускаете Ansible: `ansible` и SSH-доступ на сервер.

## Деплой одной командой

Из корня репозитория:

```bash
make deploy
```

Эквивалент:

```bash
cd deploy/ansible && ansible-playbook site.yml
```

Параметры на командной строке не нужны — всё в `inventory.yml` и `group_vars/all.yml`.

## Что поднимается на сервере

| Сервис | Назначение |
|--------|------------|
| `traefik` | HTTPS: `/connect`, `/api/calendar/*` → Web App бота |
| `nginx-acme` | Webroot для ACME challenge |
| `certbot` | Выпуск и продление Let's Encrypt |
| `satellite` | Бот; данные в volume `satellite-logs` |

Каталог на сервере: `/opt/satellite` (меняется через `deploy_dir` в `group_vars`).

## Обновление образа после первичного деплоя

**Автоматически (рекомендуется):** push в `main` → GitHub Actions сам собирает и катит образ,
делает `docker compose pull/up -d satellite` на сервере. Запустить тот же rolling update
без коммита — Actions → workflow `deploy` → **Run workflow**.

**Вручную локально** (тот же `scripts/ci-deploy-remote.sh`):

```bash
DEPLOY_HOST=91.201.114.159 \
DEPLOY_USER=root \
SSH_PRIVATE_KEY="$(cat ~/.ssh/satellite_deploy)" \
SATELLITE_IMAGE=ghcr.io/ksandrpetrov/satellite:sha-abc1234 \
  bash scripts/ci-deploy-remote.sh
```

**Полный playbook (Ansible)** нужен только когда меняется стек: домен, Traefik,
секреты в `.env`, версия Certbot. Тогда: правим `group_vars/all.yml` (при необходимости
`image_tag` на конкретный semver) и снова `make deploy`.

## Переменные Ansible (`group_vars/all.yml`)

| Переменная | Назначение |
|------------|------------|
| `domain` | Публичный хост; `WEBAPP_BASE_URL` = `https://<domain>/connect` |
| `certbot_email` | Email для Let's Encrypt |
| `certbot_staging` | `true` — staging-сертификаты (отладка) |
| `image_tag` | Тег образа GHCR для **первичного** `make deploy` (`latest` или semver); дальше Actions пишет `SATELLITE_IMAGE` в `.env` |
| `telegram_bot_token`, `admin_telegram_ids` | Секреты бота |
| `token_encryption_key` | Пусто при первом деплое — ключ сгенерируется; при повторном сохранится с сервера |
| `deploy_dir` | Каталог на сервере (default `/opt/satellite`) |

Полный список env приложения после деплоя — в сгенерированном `.env` на сервере;
шаблон: [`ansible/templates/env.j2`](ansible/templates/env.j2).

## Локальный compose (без Ansible)

Для отладки на сервере вручную — см. серверный [`docker-compose.yml`](docker-compose.yml)
и `.env` по образцу [`.env.example`](.env.example) (`WEBAPP_HOST=0.0.0.0`).

Локальный запуск на ноутбуке (один контейнер бота, без Traefik) — в
корневом репо: `docker-compose.yml`. Шаги:

```bash
make env          # создаст .env и сгенерирует TOKEN_ENCRYPTION_KEY
make docker-up    # docker compose up -d --build
make docker-logs  # docker compose logs -f satellite
```

Health: `curl http://127.0.0.1:8080/healthz`. Чтобы Telegram WebApp работал
снаружи, поверх 8080 нужен HTTPS-туннель (`ngrok http 8080` или Cloudflare
Tunnel) и `WEBAPP_BASE_URL=https://<публичный-домен>/connect` в `.env`.

Диагностика: [docs/troubleshooting.md](../docs/troubleshooting.md),
эксплуатация: [docs/operations.md](../docs/operations.md#docker-ghcr--traefik--certbot).
