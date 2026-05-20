#!/usr/bin/env bash
# Локальный bootstrap «Чайки».
#
# Идемпотентно: создаёт venv, ставит зависимости, готовит .env (с авто-
# сгенерированным TOKEN_ENCRYPTION_KEY) и папку logs/. Безопасно запускать
# повторно — существующие .env и venv не перезаписываются.
#
# Использование (из корня репозитория):
#   bash scripts/install.sh              # prod (только runtime-зависимости)
#   bash scripts/install.sh --dev        # + requirements-dev.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

INSTALL_DEV=0
for arg in "$@"; do
    case "${arg}" in
        --dev) INSTALL_DEV=1 ;;
        -h|--help)
            sed -n '2,11p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: ${arg}" >&2
            exit 2
            ;;
    esac
done

log() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Python ---
PYTHON_BIN="${PYTHON:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        die "python3 не найден. Установите Python 3.11+ и повторите."
    fi
fi

PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "Python: ${PYTHON_BIN} (${PY_VERSION})"

PY_OK="$("${PYTHON_BIN}" -c 'import sys; print(1 if sys.version_info >= (3, 9) else 0)')"
if [[ "${PY_OK}" != "1" ]]; then
    die "Нужен Python 3.9+ (CI и продакшен — 3.11). Текущая: ${PY_VERSION}."
fi

# --- venv ---
if [[ ! -d "venv" ]]; then
    log "Создаю venv/"
    "${PYTHON_BIN}" -m venv venv
else
    log "venv/ уже существует — переиспользую"
fi

# shellcheck disable=SC1091
source venv/bin/activate

log "Обновляю pip"
python -m pip install --upgrade pip >/dev/null

log "Устанавливаю requirements.txt"
pip install -r requirements.txt

if [[ "${INSTALL_DEV}" == "1" ]]; then
    log "Устанавливаю requirements-dev.txt"
    pip install -r requirements-dev.txt
fi

# --- logs/ ---
mkdir -p logs
log "logs/ готов"

# --- .env ---
if [[ ! -f ".env" ]]; then
    if [[ ! -f ".env.example" ]]; then
        die ".env.example не найден — не из чего собирать .env"
    fi
    log "Собираю .env из .env.example"
    cp .env.example .env

    FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    # macOS sed требует пустой суффикс отдельным аргументом.
    if sed --version >/dev/null 2>&1; then
        sed -i "s|^TOKEN_ENCRYPTION_KEY=.*|TOKEN_ENCRYPTION_KEY=${FERNET_KEY}|" .env
    else
        sed -i '' "s|^TOKEN_ENCRYPTION_KEY=.*|TOKEN_ENCRYPTION_KEY=${FERNET_KEY}|" .env
    fi

    log ".env создан. Сгенерирован TOKEN_ENCRYPTION_KEY."
    warn "Откройте .env и впишите TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEBAPP_BASE_URL."
else
    log ".env уже существует — не трогаю"
fi

cat <<'EOF'

Готово. Дальше:

  1) Отредактируйте .env: TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEBAPP_BASE_URL.
  2) Активируйте окружение:        source venv/bin/activate
  3) Запустите бота:               python telegram_test_command.py
     или прогон тестов:            python -m pytest

Полная установка на сервере с systemd: scripts/install-server.sh
EOF
