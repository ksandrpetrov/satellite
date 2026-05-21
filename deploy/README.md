# Docker-деплой (бот в контейнере, nginx — внешний)

Reverse proxy и TLS для `cassinilab.ru` — ваш существующий **nginx на хосте** (он же
обслуживает другие сайты и Telegram Web App). В Docker крутится **только бот**,
слушает `127.0.0.1:<satellite_host_port>` (по умолчанию `8080`); nginx проксирует
туда `/connect`, `/api/calendar/*` и `/healthz` — см.
[`deploy/nginx/satellite-webapp.conf.example`](nginx/satellite-webapp.conf.example).

Никаких Traefik/Certbot/nginx-acme в стеке нет — они конфликтовали бы с вашим nginx за порт 443.

## CI/CD: GitHub Actions под ключ

Workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) на каждый push в `main`
или тег `v*` (отдельный workflow [`test.yml`](../.github/workflows/test.yml) — только на PR):

1. **test** — ruff (lint + format check), py_compile, pytest.
2. **build** — Docker-образ в GHCR: `:sha-<short>` (всегда), `:latest` (только `main`),
   semver-теги (только `v*`).
3. **deploy** — SSH на сервер (`scripts/ci-deploy-remote.sh`): нормализация
   `DEPLOY_HOST`/`DEPLOY_USER`/`SATELLITE_IMAGE`; при наличии legacy
   `satellite-bot.service` — остановить и отключить unit (освободить порт на хосте);
   обновить `SATELLITE_IMAGE` в `.env`, `docker compose pull satellite`,
   `docker compose up -d satellite`. Только для push в `main` и ручного `workflow_dispatch`.
   Перед SSH job проверяет, что заданы секреты `DEPLOY_HOST`, `DEPLOY_USER`, `SSH_PRIVATE_KEY`.
   Тег `v*` job **deploy** не запускает — см. [troubleshooting](../docs/troubleshooting.md#автодеплой-github-actions-и-docker-на-сервере).

Пакет в GHCR после первой сборки сделайте **public** (или задайте `GHCR_PULL_TOKEN`, см. ниже):
`Settings → Packages → satellite → Package settings → Change visibility`.

### Первый деплой без образа в GHCR

В [`ansible/group_vars/all.yml`](ansible/group_vars/all.yml) по умолчанию
`satellite_image_source: build` — playbook **собирает образ на сервере** из
исходников (не тянет `ghcr.io/.../satellite:latest`).

После того как GitHub Actions хотя бы раз запушил образ в GHCR, переключите:

```yaml
satellite_image_source: ghcr
```

и снова `make deploy` (или дальше — только push в `main`, Actions сам обновит бота).

### Секреты для деплоя (Settings → Secrets and variables → Actions)

| Секрет | Назначение |
|--------|------------|
| `DEPLOY_HOST` | IP или hostname сервера (без `https://`, без хвостового перевода строки) |
| `DEPLOY_USER` | SSH-пользователь (`root` или deploy-user) |
| `SSH_PRIVATE_KEY` | приватный ключ SSH (публичный — в `authorized_keys` на сервере) |
| `SSH_KNOWN_HOSTS` | опционально: вывод `ssh-keyscan -H <DEPLOY_HOST>` |
| `GHCR_PULL_TOKEN` | опционально: PAT с `read:packages` для приватного пакета GHCR |

## Перед деплоем

1. Отредактируйте [`ansible/inventory.yml`](ansible/inventory.yml) — IP и SSH-пользователь.
2. Отредактируйте [`ansible/group_vars/all.yml`](ansible/group_vars/all.yml):
   - `domain` — используется только в `WEBAPP_BASE_URL` в `.env`;
   - `satellite_host_port` — порт на хосте, на который проксирует nginx (default `8080`);
   - `telegram_bot_token`, `admin_telegram_ids`;
   - `image_tag` для первичного деплоя (`latest`, semver или `sha-<commit>`).
3. На вашем nginx добавьте `location`-блоки из
   [`deploy/nginx/satellite-webapp.conf.example`](nginx/satellite-webapp.conf.example) внутрь
   существующего `server { listen 443 ssl; server_name cassinilab.ru; ... }` и сделайте
   `sudo nginx -t && sudo systemctl reload nginx`. TLS-сертификат у вашего nginx уже есть.
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

Если в `/opt/satellite/docker-compose.yml` остался старый стек с Traefik —
playbook сам сделает `docker compose down` и удалит `traefik/` перед накатом нового.
Подробнее: [operations.md — миграция](../docs/operations.md#миграция-со-стека-traefik).

Если раньше бот работал через **systemd** (`satellite-bot.service` из
`install-server.sh`), playbook **останавливает и отключает** этот unit, чтобы
освободить `127.0.0.1:8080` для Docker. Иначе `docker compose up` падает с
`bind: address already in use`.

## Что поднимается на сервере

| Сервис | Назначение |
|--------|------------|
| `satellite` | Бот; данные в volume `satellite-logs`; порт `127.0.0.1:8080` на хосте |

Каталог на сервере: `/opt/satellite` (меняется через `deploy_dir` в `group_vars`).
TLS, домен и проксирование — на вашем хостовом nginx, playbook их не трогает.

## Обновление образа после первичного деплоя

**Автоматически (рекомендуется):** push в `main` → GitHub Actions сам собирает и катит образ,
делает `docker compose pull/up -d satellite` на сервере. Запустить тот же rolling update
без коммита — Actions → workflow `deploy` → **Run workflow**.

**Вручную локально** (тот же `scripts/ci-deploy-remote.sh`):

```bash
DEPLOY_HOST=<IP-или-hostname-сервера> \
DEPLOY_USER=root \
SSH_PRIVATE_KEY="$(cat ~/.ssh/satellite_deploy)" \
SATELLITE_IMAGE=ghcr.io/ksandrpetrov/satellite:sha-abc1234 \
  bash scripts/ci-deploy-remote.sh
```

**Полный playbook** нужен только когда меняются переменные `.env`
(токены, `WEBAPP_BASE_URL`, погода и т.п.) или `docker-compose.yml` бота.

## Переменные Ansible (`group_vars/all.yml`)

| Переменная | Назначение |
|------------|------------|
| `domain` | Публичный хост; `WEBAPP_BASE_URL` = `https://<domain>/connect` |
| `satellite_host_port` | Порт на хосте (`127.0.0.1:<port>:8080`); сюда проксирует ваш nginx |
| `satellite_image_source` | `build` (собрать на сервере) или `ghcr` (тянуть из GHCR) |
| `image_tag` | Тег образа GHCR для первичного `make deploy` |
| `telegram_bot_token`, `admin_telegram_ids` | Секреты бота |
| `token_encryption_key` | Пусто при первом деплое — ключ сгенерируется; при повторном сохранится |
| `deploy_dir` | Каталог на сервере (default `/opt/satellite`) |
| `ghcr_pull_user`, `ghcr_pull_token` | Опционально: PAT для приватного пакета GHCR |

Полный список env приложения после деплоя — в сгенерированном `.env` на сервере;
шаблон: [`ansible/templates/env.j2`](ansible/templates/env.j2).

## Локальный запуск на ноутбуке

```bash
make env          # создаст .env и сгенерирует TOKEN_ENCRYPTION_KEY
make docker-up    # docker compose up -d --build
make docker-logs  # docker compose logs -f satellite
```

Health: `curl http://127.0.0.1:8080/healthz`. Чтобы Telegram WebApp работал
снаружи, поверх 8080 нужен HTTPS-туннель (`ngrok http 8080` или Cloudflare Tunnel)
и `WEBAPP_BASE_URL=https://<публичный-домен>/connect` в `.env`.

Диагностика: [docs/troubleshooting.md](../docs/troubleshooting.md)
(сбои Actions/deploy — [автодеплой](../docs/troubleshooting.md#автодеплой-github-actions-и-docker-на-сервере)),
эксплуатация: [docs/operations.md](../docs/operations.md).
