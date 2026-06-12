#!/usr/bin/env bash
# Идемпотентно добавляет проксирование Web App бота в хостовой nginx.
#
# Usage (на сервере, от root):
#   bash scripts/ensure-nginx-satellite.sh
#   SATELLITE_HOST_PORT=8080 NGINX_DOMAIN=cassinilab.ru bash scripts/ensure-nginx-satellite.sh
#
# Создаёт /etc/nginx/snippets/satellite-webapp.conf и подключает его в HTTPS
# server {} для NGINX_DOMAIN (перед location /).

set -euo pipefail

SATELLITE_HOST_PORT="${SATELLITE_HOST_PORT:-8080}"
NGINX_DOMAIN="${NGINX_DOMAIN:-cassinilab.ru}"
NGINX_SNIPPET="${NGINX_SNIPPET:-/etc/nginx/snippets/satellite-webapp.conf}"
NGINX_SITE_FILE="${NGINX_SITE_FILE:-/etc/nginx/sites-available/${NGINX_DOMAIN}}"
MARKER="include ${NGINX_SNIPPET};"

log() { printf '[ensure-nginx] %s\n' "$*"; }

require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        echo "Запустите от root (sudo)." >&2
        exit 1
    fi
}

write_snippet() {
    local port="${SATELLITE_HOST_PORT}"
    mkdir -p "$(dirname "${NGINX_SNIPPET}")"
    cat >"${NGINX_SNIPPET}" <<EOF
# Managed by satellite/scripts/ensure-nginx-satellite.sh — do not edit by hand.
location /connect {
    proxy_pass http://127.0.0.1:${port};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Telegram-Init-Data \$http_x_telegram_init_data;
}

location /api/calendar/ {
    proxy_pass http://127.0.0.1:${port};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Telegram-Init-Data \$http_x_telegram_init_data;
}

location = /healthz {
    proxy_pass http://127.0.0.1:${port};
    proxy_set_header Host \$host;
}
EOF
    chmod 644 "${NGINX_SNIPPET}"
    log "Snippet ${NGINX_SNIPPET} (port ${port})"
}

ensure_site_include() {
    if [[ ! -f "${NGINX_SITE_FILE}" ]]; then
        echo "Nginx site file not found: ${NGINX_SITE_FILE}" >&2
        echo "Задайте NGINX_SITE_FILE или добавьте location вручную (deploy/nginx/satellite-webapp.conf.example)." >&2
        exit 1
    fi

    if grep -qF "${MARKER}" "${NGINX_SITE_FILE}"; then
        log "Include already present in ${NGINX_SITE_FILE}"
        return 0
    fi

    local backup="${NGINX_SITE_FILE}.bak-$(date -u +%Y%m%d-%H%M%SZ)"
    cp -a "${NGINX_SITE_FILE}" "${backup}"
    log "Backup ${backup}"

    python3 - "${NGINX_SITE_FILE}" "${NGINX_DOMAIN}" "${MARKER}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
domain = sys.argv[2]
marker = sys.argv[3]
include_line = f"    # satellite-webapp (managed)\n    {marker}\n\n"

lines = path.read_text().splitlines(keepends=True)
out: list[str] = []
in_target = False
depth = 0
inserted = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("server") and "{" in stripped:
        depth = stripped.count("{") - stripped.count("}")
        in_target = False
        out.append(line)
        continue

    if depth > 0:
        if f"server_name {domain};" in stripped:
            in_target = True
        if in_target and not inserted and stripped.startswith("location /"):
            out.append(include_line)
            inserted = True
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            in_target = False
    out.append(line)

if not inserted:
    raise SystemExit(
        f"Could not find 'location /' in server block for server_name {domain}; "
        f"add manually: {marker}"
    )

path.write_text("".join(out))
print(f"Inserted include into {path}")
PY

    log "Updated ${NGINX_SITE_FILE}"
}

reload_nginx() {
    nginx -t
    systemctl reload nginx
    log "nginx reloaded"
}

main() {
    require_root
    write_snippet
    ensure_site_include
    reload_nginx
    log "Done"
}

main "$@"
