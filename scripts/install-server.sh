#!/usr/bin/env bash
# Установка «Чайки» на Linux-сервер (Debian/Ubuntu).
#
# Что делает (идемпотентно):
#   1) ставит системные пакеты (git, python3-venv, python3-pip);
#   2) клонирует репозиторий в $SATELLITE_DIR (default /opt/satellite);
#   3) запускает scripts/install.sh внутри клона;
#   4) генерирует и регистрирует systemd unit satellite-bot.service.
#
# Использование:
#   sudo bash scripts/install-server.sh
#   sudo SATELLITE_DIR=/srv/satellite SATELLITE_USER=satellite bash scripts/install-server.sh
#
# На пустом сервере (приватный repo требует PAT в GITHUB_TOKEN; пароль GitHub
# по HTTPS не работает). Bootstrap через временный каталог — устойчив к
# повторным запускам, целевой /opt/satellite клонирует уже сам скрипт:
#
#   sudo GITHUB_TOKEN=ghp_xxx bash -c 'set -euo pipefail
#     apt-get update -y && apt-get install -y git
#     tmp=$(mktemp -d); trap "rm -rf \"$tmp\"" EXIT
#     git clone --depth 1 -b main \
#       "https://x-access-token:${GITHUB_TOKEN}@github.com/ksandrpetrov/satellite.git" "$tmp"
#     GITHUB_TOKEN="${GITHUB_TOKEN}" bash "$tmp/scripts/install-server.sh"'
#
# Если репозиторий уже на сервере (например, склонирован вручную):
#   sudo bash /opt/satellite/scripts/install-server.sh
#
# Подробнее: docs/operations.md.
#
# После установки отредактируйте /opt/satellite/.env и выполните:
#   sudo systemctl restart satellite-bot.service
#   journalctl -u satellite-bot.service -f

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=git-github-auth.sh
source "${SCRIPT_DIR}/git-github-auth.sh"

SATELLITE_DIR="${SATELLITE_DIR:-/opt/satellite}"
SATELLITE_USER="${SATELLITE_USER:-satellite}"
SATELLITE_GROUP="${SATELLITE_GROUP:-${SATELLITE_USER}}"
SATELLITE_REPO="${SATELLITE_REPO:-https://github.com/ksandrpetrov/satellite.git}"
SATELLITE_BRANCH="${SATELLITE_BRANCH:-main}"
SERVICE_NAME="satellite-bot.service"

log() { printf '\033[1;34m[server]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[server]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[server]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
    die "Запустите под root (sudo)."
fi

if ! command -v systemctl >/dev/null 2>&1; then
    die "systemd не найден. Этот скрипт рассчитан на Linux с systemd."
fi

# --- system packages ---
if command -v apt-get >/dev/null 2>&1; then
    log "apt-get update / install"
    DEBIAN_FRONTEND=noninteractive apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        git python3 python3-venv python3-pip ca-certificates
else
    warn "apt-get не найден — пропускаю установку пакетов. Убедитесь, что git и python3-venv установлены."
fi

# --- service user ---
if ! id -u "${SATELLITE_USER}" >/dev/null 2>&1; then
    log "Создаю системного пользователя ${SATELLITE_USER}"
    useradd --system --create-home --shell /usr/sbin/nologin "${SATELLITE_USER}"
fi

# --- clone / update repo ---
REPO_URL="$(github_authenticated_url "${SATELLITE_REPO}")"
if [[ ! -d "${SATELLITE_DIR}/.git" ]]; then
    if [[ -d "${SATELLITE_DIR}" ]]; then
        if [[ -z "$(ls -A "${SATELLITE_DIR}" 2>/dev/null || true)" ]]; then
            log "Каталог ${SATELLITE_DIR} существует, но пустой — удаляю перед git clone"
            rmdir "${SATELLITE_DIR}"
        else
            die "Каталог ${SATELLITE_DIR} существует и не пустой, но без .git. Удалите его (sudo rm -rf ${SATELLITE_DIR}) или задайте SATELLITE_DIR= с другим путём и запустите скрипт повторно."
        fi
    fi
    log "Клонирую ${SATELLITE_REPO} -> ${SATELLITE_DIR}"
    mkdir -p "$(dirname "${SATELLITE_DIR}")"
    if ! github_git clone --branch "${SATELLITE_BRANCH}" "${REPO_URL}" "${SATELLITE_DIR}"; then
        die "git clone не удался. Для приватного repo задайте GITHUB_TOKEN (PAT) или SATELLITE_REPO=git@github.com:...."
    fi
else
    log "Репозиторий уже есть, делаю git pull"
    github_ensure_safe_directory "${SATELLITE_DIR}"
    ORIGIN_CLEAN="$(github_strip_https_auth "$(github_git -C "${SATELLITE_DIR}" config --get remote.origin.url)")"
    github_git -C "${SATELLITE_DIR}" remote set-url origin "$(github_authenticated_url "${ORIGIN_CLEAN}")"
    github_git -C "${SATELLITE_DIR}" fetch --prune origin
    github_git -C "${SATELLITE_DIR}" checkout "${SATELLITE_BRANCH}"
    github_git -C "${SATELLITE_DIR}" pull --ff-only origin "${SATELLITE_BRANCH}"
fi

chown -R "${SATELLITE_USER}:${SATELLITE_GROUP}" "${SATELLITE_DIR}"

# --- python deps + .env через install.sh от имени сервисного пользователя ---
log "Устанавливаю Python-окружение от ${SATELLITE_USER}"
sudo -u "${SATELLITE_USER}" --preserve-env=PYTHON \
    bash "${SATELLITE_DIR}/scripts/install.sh"

# --- systemd unit ---
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"
log "Записываю ${UNIT_PATH}"
cat >"${UNIT_PATH}" <<EOF
[Unit]
Description=Satellite Telegram calendar bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SATELLITE_USER}
Group=${SATELLITE_GROUP}
WorkingDirectory=${SATELLITE_DIR}
EnvironmentFile=${SATELLITE_DIR}/.env
ExecStart=${SATELLITE_DIR}/venv/bin/python ${SATELLITE_DIR}/telegram_test_command.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

log "systemctl daemon-reload + enable --now"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null
systemctl restart "${SERVICE_NAME}"
sleep 1
systemctl --no-pager --full status "${SERVICE_NAME}" || true

cat <<EOF

Готово.

Каталог:     ${SATELLITE_DIR}
Пользователь: ${SATELLITE_USER}
Сервис:      ${SERVICE_NAME}

Дальше:
  1) Отредактируйте ${SATELLITE_DIR}/.env:
     TELEGRAM_BOT_TOKEN — от @BotFather;
     ADMIN_TELEGRAM_IDS — числовой user id (узнать: @userinfobot), не @username;
     WEBAPP_BASE_URL — публичный HTTPS (/connect).
     TOKEN_ENCRYPTION_KEY уже сгенерирован.
  2) Перезапустите сервис:   sudo systemctl restart ${SERVICE_NAME}
  3) Логи:                   journalctl -u ${SERVICE_NAME} -f
                             tail -f ${SATELLITE_DIR}/logs/bot.log
  4) Reverse proxy для WEBAPP_BASE_URL -> WEBAPP_HOST:WEBAPP_PORT (см. docs/operations.md).

Обновление:  sudo bash ${SATELLITE_DIR}/scripts/install-server.sh
EOF
