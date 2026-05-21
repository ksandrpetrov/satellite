#!/usr/bin/env bash
# Smoke собранного Docker-образа (CI после push в GHCR или локально после docker build).
#
# Usage:
#   bash scripts/docker-smoke-image.sh ghcr.io/owner/repo:sha-abc1234
#   bash scripts/docker-smoke-image.sh satellite:dev   # после make docker-build
#
# Переменные:
#   SMOKE_SKIP_PULL=1  — не делать docker pull (локальный тег)

set -euo pipefail

IMAGE="${1:?usage: docker-smoke-image.sh <image-ref>}"

log() { printf '[docker-smoke] %s\n' "$*"; }

if [[ "${SMOKE_SKIP_PULL:-}" != "1" ]]; then
    log "Pull ${IMAGE}…"
    docker pull "${IMAGE}"
fi

log "Run container smoke…"
docker run --rm --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --tmpfs /app/logs:rw,noexec,nosuid,size=8m \
    "${IMAGE}" \
    python scripts/smoke_container.py

log "Done"
