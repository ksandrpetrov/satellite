#!/usr/bin/env bash
# Rolling deploy для GitHub Actions: обновить SATELLITE_IMAGE на сервере,
# pull нового образа из GHCR и перезапуск контейнера бота.
#
# Вызывается из .github/workflows/deploy.yml; можно запускать локально,
# если заданы все нужные переменные окружения.
#
# Обязательные:
#   DEPLOY_HOST       — IP/hostname сервера
#   DEPLOY_USER       — SSH-пользователь
#   SSH_PRIVATE_KEY   — приватный ключ SSH (как многострочная строка)
#   SATELLITE_IMAGE   — полный ref образа (ghcr.io/owner/repo:sha-abc1234)
#
# Опциональные:
#   DEPLOY_DIR             (default /opt/satellite)
#   COMPOSE_PROJECT_NAME   (default satellite)
#   SSH_KNOWN_HOSTS        — содержимое known_hosts; без него — accept-new
#   GHCR_USER, GHCR_TOKEN  — для приватного пакета: docker login ghcr.io
#                            на сервере перед pull

set -euo pipefail

# Срезает CR/LF и пробелы по краям — Actions-секреты часто приезжают с
# trailing '\n', из-за чего ssh падает с "hostname contains invalid characters".
strip_ws() { printf '%s' "${1-}" | tr -d '\r\n\t' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

DEPLOY_HOST="$(strip_ws "${DEPLOY_HOST:?set DEPLOY_HOST}")"
DEPLOY_USER="$(strip_ws "${DEPLOY_USER:?set DEPLOY_USER}")"
SATELLITE_IMAGE="$(strip_ws "${SATELLITE_IMAGE:?set SATELLITE_IMAGE}")"
: "${SSH_PRIVATE_KEY:?set SSH_PRIVATE_KEY}"

DEPLOY_DIR="$(strip_ws "${DEPLOY_DIR:-/opt/satellite}")"
COMPOSE_PROJECT_NAME="$(strip_ws "${COMPOSE_PROJECT_NAME:-satellite}")"
GHCR_USER="$(strip_ws "${GHCR_USER:-}")"
# GHCR_TOKEN читаем как есть — токен не должен ломаться из-за пробелов внутри,
# но обрезаем хвостовые перевод-строки от paste.
GHCR_TOKEN="$(printf '%s' "${GHCR_TOKEN:-}" | tr -d '\r\n')"

if [[ -z "${DEPLOY_HOST}" || -z "${DEPLOY_USER}" ]]; then
    echo "::error::DEPLOY_HOST / DEPLOY_USER пустые после нормализации" >&2
    exit 1
fi

if [[ ! "${DEPLOY_HOST}" =~ ^[A-Za-z0-9.:_-]+$ ]]; then
    echo "::error::DEPLOY_HOST содержит недопустимые символы: '${DEPLOY_HOST}'" >&2
    exit 1
fi

log() { printf '[ci-deploy] %s\n' "$*"; }

DEPLOY_SSH_KEY=""

setup_ssh() {
    DEPLOY_SSH_KEY="$(mktemp)"
    trap 'rm -f "${DEPLOY_SSH_KEY}"' EXIT
    printf '%s\n' "${SSH_PRIVATE_KEY}" | tr -d '\r' >"${DEPLOY_SSH_KEY}"
    chmod 600 "${DEPLOY_SSH_KEY}"

    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"
    if [[ -n "${SSH_KNOWN_HOSTS:-}" ]]; then
        printf '%s\n' "${SSH_KNOWN_HOSTS}" >>"${HOME}/.ssh/known_hosts"
    fi
}

remote_update() {
    ssh -i "${DEPLOY_SSH_KEY}" \
        -o IdentitiesOnly=yes \
        -o BatchMode=yes \
        "${SSH_OPTS[@]}" \
        "${DEPLOY_USER}@${DEPLOY_HOST}" \
        "DEPLOY_DIR=${DEPLOY_DIR}" \
        "COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}" \
        "SATELLITE_IMAGE=${SATELLITE_IMAGE}" \
        "GHCR_USER=${GHCR_USER:-}" \
        "GHCR_TOKEN=${GHCR_TOKEN:-}" \
        'bash -s' <<'REMOTE'
set -euo pipefail

cd "${DEPLOY_DIR}"

# Освободить 127.0.0.1:8080, если бот ещё крутится через systemd (install-server.sh).
if command -v systemctl >/dev/null 2>&1 && systemctl cat satellite-bot.service >/dev/null 2>&1; then
    if systemctl is-active --quiet satellite-bot.service; then
        echo "Stopping legacy satellite-bot.service (frees host port for Docker)…" >&2
        systemctl stop satellite-bot.service
    fi
    systemctl disable satellite-bot.service 2>/dev/null || true
fi

if [[ ! -f docker-compose.yml ]]; then
    echo "docker-compose.yml not found in ${DEPLOY_DIR}" >&2
    echo "Сначала выполните первичный деплой с ноутбука: make deploy (Ansible)." >&2
    exit 1
fi

if [[ -n "${GHCR_USER:-}" && -n "${GHCR_TOKEN:-}" ]]; then
    printf '%s' "${GHCR_TOKEN}" | docker login -u "${GHCR_USER}" --password-stdin ghcr.io
fi

if [[ ! -f .env ]]; then
    touch .env
    chmod 600 .env
fi

if grep -q '^SATELLITE_IMAGE=' .env; then
    sed -i "s|^SATELLITE_IMAGE=.*|SATELLITE_IMAGE=${SATELLITE_IMAGE}|" .env
else
    printf '\nSATELLITE_IMAGE=%s\n' "${SATELLITE_IMAGE}" >>.env
fi

export COMPOSE_PROJECT_NAME
docker compose pull satellite
docker compose up -d satellite
docker compose ps satellite
REMOTE
}

main() {
    SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
    if [[ -n "${SSH_KNOWN_HOSTS:-}" ]]; then
        SSH_OPTS=(-o StrictHostKeyChecking=yes)
    fi

    setup_ssh
    log "Deploy ${SATELLITE_IMAGE} → ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_DIR}"
    remote_update
    log "Done"
}

main "$@"
