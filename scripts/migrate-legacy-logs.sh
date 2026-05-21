#!/usr/bin/env bash
# Перенос legacy /opt/satellite/logs/ → Docker volume satellite_satellite-logs.
#
# Когда нужен: один раз, при переходе с systemd (install-server.sh) на Docker
# (deploy via Ansible / ci-deploy-remote.sh). systemd хранил per-user state
# прямо в каталоге на хосте; Docker-compose маунтит именованный volume
# (см. deploy/docker-compose.yml). Если просто запустить контейнер — он увидит
# **пустой** volume, начнёт новую жизнь и юзеры «пропадут».
#
# Скрипт безопасен: останавливает контейнер, делает rescue-копию текущего
# volume в /root/satellite-rescue-<timestamp>/, копирует users.json /
# subscriptions.json / backups/ / calendar_ops.jsonl / telegram-offset.json
# из host-папки в volume, выставляет права под пользователя satellite внутри
# образа (uid из `id satellite`), затем поднимает контейнер.
#
# Usage:
#   sudo bash scripts/migrate-legacy-logs.sh
#   sudo HOST_LOGS_DIR=/opt/satellite/logs \
#        DEPLOY_DIR=/opt/satellite \
#        COMPOSE_PROJECT_NAME=satellite \
#        bash scripts/migrate-legacy-logs.sh
#
# Идемпотентен: если в volume уже больше пользователей, чем на хосте, скрипт
# отказывается перезаписывать (нечего восстанавливать). Принудительно —
# FORCE=1 (тогда volume полностью замещается host-копией; используйте
# осознанно).

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/satellite}"
HOST_LOGS_DIR="${HOST_LOGS_DIR:-${DEPLOY_DIR}/logs}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-satellite}"
VOLUME_NAME="${VOLUME_NAME:-${COMPOSE_PROJECT_NAME}_satellite-logs}"
FORCE="${FORCE:-0}"

log() { printf '[migrate] %s\n' "$*"; }
err() { printf '[migrate] FAIL %s\n' "$*" >&2; exit 1; }

[[ -d "${DEPLOY_DIR}" ]] || err "DEPLOY_DIR not found: ${DEPLOY_DIR}"
[[ -f "${DEPLOY_DIR}/docker-compose.yml" ]] || err "docker-compose.yml missing in ${DEPLOY_DIR}"
[[ -d "${HOST_LOGS_DIR}" ]] || err "HOST_LOGS_DIR not found: ${HOST_LOGS_DIR}"
[[ -f "${HOST_LOGS_DIR}/users.json" ]] || err "${HOST_LOGS_DIR}/users.json not found — nothing to migrate"

command -v docker >/dev/null 2>&1 || err "docker not in PATH"

if ! docker volume inspect "${VOLUME_NAME}" >/dev/null 2>&1; then
    err "docker volume ${VOLUME_NAME} not found. Запустите сначала: cd ${DEPLOY_DIR} && docker compose up -d satellite, затем повторите."
fi

cd "${DEPLOY_DIR}"
export COMPOSE_PROJECT_NAME

host_users_count() {
    python3 -c "
import json, sys
try:
    d = json.load(open('${HOST_LOGS_DIR}/users.json'))
    print(len(d) if isinstance(d, dict) else 0)
except Exception as exc:
    print('0', end='')
    sys.exit(0)
"
}

volume_users_count() {
    docker run --rm -v "${VOLUME_NAME}:/v:ro" python:3.12-alpine python -c "
import json, os, sys
p = '/v/users.json'
if not os.path.isfile(p):
    print(0); sys.exit(0)
try:
    d = json.load(open(p))
    print(len(d) if isinstance(d, dict) else 0)
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

HOST_N="$(host_users_count)"
VOL_N="$(volume_users_count)"
log "users.json on host: ${HOST_N}, in volume ${VOLUME_NAME}: ${VOL_N}"

if [[ "${HOST_N}" -le 0 ]]; then
    err "Host users.json не содержит пользователей — миграция не нужна."
fi

if [[ "${VOL_N}" -ge "${HOST_N}" && "${FORCE}" != "1" ]]; then
    log "В volume уже >= пользователей (${VOL_N} >= ${HOST_N}). Нечего восстанавливать."
    log "Если уверены, что хост-данные новее — повторите с FORCE=1."
    exit 0
fi

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESCUE_DIR="/root/satellite-rescue-${STAMP}"
mkdir -p "${RESCUE_DIR}"
log "Rescue copy: ${RESCUE_DIR}"
docker run --rm \
    -v "${VOLUME_NAME}:/from:ro" \
    -v "${RESCUE_DIR}:/to" \
    alpine cp -a /from/. /to/ || err "rescue copy failed"

log "Stop satellite container"
docker compose stop satellite || true

log "Discover satellite uid/gid inside image"
IMAGE_REF="$(grep -E '^SATELLITE_IMAGE=' "${DEPLOY_DIR}/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')"
if [[ -z "${IMAGE_REF}" ]]; then
    IMAGE_REF="$(docker compose config --images satellite 2>/dev/null | head -n1)"
fi
[[ -n "${IMAGE_REF}" ]] || err "Не удалось определить образ satellite (SATELLITE_IMAGE в .env)"

SAT_UID="$(docker run --rm --entrypoint id "${IMAGE_REF}" satellite -u 2>/dev/null || echo "")"
SAT_GID="$(docker run --rm --entrypoint id "${IMAGE_REF}" satellite -g 2>/dev/null || echo "")"
if [[ -z "${SAT_UID}" || -z "${SAT_GID}" ]]; then
    log "Не удалось получить id satellite из образа, fallback uid:gid=999:999"
    SAT_UID=999
    SAT_GID=999
fi
log "satellite uid=${SAT_UID} gid=${SAT_GID}"

log "Copy host logs → volume (атомарно, под нужным uid)"
docker run --rm \
    -v "${HOST_LOGS_DIR}:/old:ro" \
    -v "${VOLUME_NAME}:/new" \
    alpine sh -c "
        set -e
        cp -f /old/users.json /new/users.json
        if [ -f /old/subscriptions.json ]; then cp -f /old/subscriptions.json /new/subscriptions.json; fi
        if [ -d /old/backups ]; then
            rm -rf /new/backups
            cp -a /old/backups /new/backups
        fi
        for f in calendar_ops.jsonl telegram-offset.json connect-tokens.json; do
            if [ -f /old/\$f ]; then cp -f /old/\$f /new/\$f; fi
        done
        chown -R ${SAT_UID}:${SAT_GID} /new
        ls -la /new/
    " || err "копирование в volume не удалось"

log "Start satellite container"
docker compose up -d satellite

log "Wait for healthy (up to 120s)…"
healthy=0
for _ in $(seq 1 60); do
    if docker compose ps satellite 2>/dev/null | grep -q '(healthy)'; then
        healthy=1
        break
    fi
    if docker compose ps satellite 2>/dev/null | grep -qE 'Restarting|unhealthy|Exited'; then
        echo "Container has issues:" >&2
        docker compose ps satellite >&2 || true
        docker compose logs --tail=80 satellite >&2 || true
        err "контейнер не поднялся; rescue в ${RESCUE_DIR}"
    fi
    sleep 2
done
[[ "${healthy}" -eq 1 ]] || err "Таймаут ожидания healthy; rescue в ${RESCUE_DIR}"

log "Persistence summary:"
docker compose logs satellite 2>&1 | grep -E 'Persistence loaded|Encryption self-check' | tail -5 || true

log "Done. Rescue copy: ${RESCUE_DIR} — удалите вручную, когда убедитесь, что всё ок."
