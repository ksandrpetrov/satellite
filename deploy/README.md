# Docker-деплой (GHCR + Traefik + Certbot)

## CI: образ при релизе

Workflow [`.github/workflows/release-docker.yml`](../.github/workflows/release-docker.yml)
срабатывает на **GitHub Release → Published**, собирает образ и пушит в
**GitHub Container Registry**:

```text
ghcr.io/ksandrpetrov/satellite:<semver>
ghcr.io/ksandrpetrov/satellite:latest
```

После первого релиза сделайте пакет **public** в GitHub:
`Settings → Packages → satellite → Package settings → Change visibility`.

## Перед деплоем

1. Отредактируйте [`ansible/inventory.yml`](ansible/inventory.yml) — IP и SSH-пользователь.
2. Отредактируйте [`ansible/group_vars/all.yml`](ansible/group_vars/all.yml):
   - `domain`, `certbot_email`
   - `telegram_bot_token`, `admin_telegram_ids`
   - `image_tag` (например `1.0.0` после релиза или `latest`)
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

## Обновление после нового релиза

1. В `group_vars/all.yml` выставьте `image_tag` на версию релиза (без `v`).
2. Снова: `make deploy`.

## Переменные Ansible (`group_vars/all.yml`)

| Переменная | Назначение |
|------------|------------|
| `domain` | Публичный хост; `WEBAPP_BASE_URL` = `https://<domain>/connect` |
| `certbot_email` | Email для Let's Encrypt |
| `certbot_staging` | `true` — staging-сертификаты (отладка) |
| `image_tag` | Тег образа GHCR (`latest` или semver) |
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
