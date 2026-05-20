#!/usr/bin/env bash
# Первая установка на пустом сервере: apt + клон + install-server.sh.
#
#   sudo GITHUB_TOKEN=ghp_xxx bash scripts/bootstrap-server.sh
#
# Токен: GITHUB_TOKEN или SATELLITE_GITHUB_TOKEN (PAT с доступом к repo).
# Альтернатива: SATELLITE_REPO=git@github.com:ksandrpetrov/satellite.git (SSH).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=git-github-auth.sh
source "${SCRIPT_DIR}/git-github-auth.sh"

SATELLITE_DIR="${SATELLITE_DIR:-/opt/satellite}"
SATELLITE_REPO="${SATELLITE_REPO:-https://github.com/ksandrpetrov/satellite.git}"
SATELLITE_BRANCH="${SATELLITE_BRANCH:-main}"

log() { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
    die "Запустите под root (sudo)."
fi

if command -v apt-get >/dev/null 2>&1; then
    log "apt-get update / install git"
    DEBIAN_FRONTEND=noninteractive apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y git ca-certificates
fi

REPO_URL="$(github_authenticated_url "${SATELLITE_REPO}")"
if [[ ! -d "${SATELLITE_DIR}/.git" ]]; then
    log "Клонирую ${SATELLITE_REPO} -> ${SATELLITE_DIR}"
    mkdir -p "$(dirname "${SATELLITE_DIR}")"
    if ! github_git clone --branch "${SATELLITE_BRANCH}" "${REPO_URL}" "${SATELLITE_DIR}"; then
        die "git clone не удался. Задайте GITHUB_TOKEN или используйте SSH в SATELLITE_REPO."
    fi
else
    log "Уже есть ${SATELLITE_DIR}/.git — пропускаю клон"
fi

exec bash "${SATELLITE_DIR}/scripts/install-server.sh"
