#!/usr/bin/env bash
# Проверка, что Чайка жива снаружи (после деплоя или вручную).
#
# Usage:
#   bash scripts/smoke-prod.sh
#   SATELLITE_BASE_URL=https://cassinilab.ru bash scripts/smoke-prod.sh
#
# Ожидается:
#   GET /healthz     -> 200, JSON {"status":"ok"}  (nginx должен проксировать на бота)
#   GET /connect     -> 200, text/html
#   GET /api/calendar/status -> 401 (бот жив, без initData)

set -euo pipefail

BASE="${SATELLITE_BASE_URL:-https://cassinilab.ru}"
BASE="${BASE%/}"
BASE="${BASE%/connect}"

CURL=(curl -fsS --max-time 15 --retry 2 --retry-delay 1)
fail=0

log() { printf '[smoke-prod] %s\n' "$*"; }
err() { printf '[smoke-prod] FAIL %s\n' "$*" >&2; fail=1; }

check_healthz() {
    local url="${BASE}/healthz"
    local code body
    code="$("${CURL[@]}" -o /tmp/smoke-healthz.json -w '%{http_code}' "${url}" 2>/dev/null || echo "000")"
    if [[ "${code}" != "200" ]]; then
        err "${url} -> HTTP ${code} (ожидался 200; если 200 HTML главной — nginx не проксирует /healthz на бота)"
        return
    fi
    body="$(tr -d '\n' < /tmp/smoke-healthz.json)"
    if [[ "${body}" != *'"status"'* || "${body}" != *'"ok"'* ]]; then
        err "${url} -> 200, но тело не похоже на бота: ${body:0:120}"
        return
    fi
    log "OK ${url}"
}

check_connect() {
    local url="${BASE}/connect"
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "${url}" || echo "000")"
    if [[ "${code}" != "200" ]]; then
        err "${url} -> HTTP ${code} (ожидался 200; 502 = контейнер бота не слушает)"
        return
    fi
    log "OK ${url}"
}

check_api_unauthorized() {
    local url="${BASE}/api/calendar/status"
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "${url}" || echo "000")"
    if [[ "${code}" == "401" ]]; then
        log "OK ${url} -> 401 (бот отвечает)"
        return
    fi
    if [[ "${code}" == "200" ]]; then
        err "${url} -> 200 без auth (неожиданно открытый API?)"
        return
    fi
    err "${url} -> HTTP ${code} (ожидался 401 или 502 диагностика)"
}

main() {
    log "Base URL: ${BASE}"
    check_healthz
    check_connect
    check_api_unauthorized
    if [[ "${fail}" -ne 0 ]]; then
        echo >&2
        echo "Подсказка: на сервере сначала curl http://127.0.0.1:8080/healthz" >&2
        echo "См. docs/troubleshooting.md и deploy/nginx/satellite-webapp.conf.example" >&2
        exit 1
    fi
    log "All checks passed"
}

main "$@"
