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

DEPLOY_HOST="${DEPLOY_HOST:?set DEPLOY_HOST}"
DEPLOY_USER="${DEPLOY_USER:?set DEPLOY_USER}"
SATELLITE_IMAGE="${SATELLITE_IMAGE:?set SATELLITE_IMAGE}"
SSH_PRIVATE_KEY="${SSH_PRIVATE_KEY:?set SSH_PRIVATE_KEY}"

DEPLOY_DIR="${DEPLOY_DIR:-/opt/satellite}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-satellite}"

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
