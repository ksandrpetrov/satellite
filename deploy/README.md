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
| `traefik` | HTTPS, маршрут `/connect` → Web App бота |
| `nginx-acme` | Webroot для ACME challenge |
| `certbot` | Выпуск и продление Let's Encrypt |
| `satellite` | Бот; данные в volume `satellite-logs` |

Каталог на сервере: `/opt/satellite` (меняется через `deploy_dir` в `group_vars`).

## Обновление после нового релиза

1. В `group_vars/all.yml` выставьте `image_tag` на версию релиза (без `v`).
2. Снова: `make deploy`.

## Локальный compose (без Ansible)

Для отладки стека на сервере вручную — см. [`docker-compose.yml`](docker-compose.yml)
и `.env` по образцу [`.env.example`](../.env.example) (`WEBAPP_HOST=0.0.0.0`).
