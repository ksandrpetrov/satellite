#!/usr/bin/env bash
# Вспомогательные функции для git по HTTPS к github.com с PAT.
# Использование: source "$(dirname "$0")/git-github-auth.sh"
#
# Токен: GITHUB_TOKEN или SATELLITE_GITHUB_TOKEN (classic / fine-grained PAT
# с доступом к репозиторию). Для SSH задайте SATELLITE_REPO=git@github.com:...

github_token() {
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        printf '%s' "${GITHUB_TOKEN}"
        return 0
    fi
    if [[ -n "${SATELLITE_GITHUB_TOKEN:-}" ]]; then
        printf '%s' "${SATELLITE_GITHUB_TOKEN}"
        return 0
    fi
    return 1
}

# Убирает user:pass@ из https://github.com/... (для идемпотентной подстановки токена).
github_strip_https_auth() {
    local url="$1"
    case "${url}" in
        https://*@github.com/*)
            printf 'https://github.com/%s' "${url#https://*@github.com/}"
            ;;
        *)
            printf '%s' "${url}"
            ;;
    esac
}

# Добавляет x-access-token в HTTPS-URL github.com, если задан токен.
github_authenticated_url() {
    local url token clean
    url="$(github_strip_https_auth "$1")"
    token="$(github_token)" || {
        printf '%s' "${url}"
        return 0
    }
    case "${url}" in
        https://github.com/*)
            printf 'https://x-access-token:%s@github.com/%s' "${token}" "${url#https://github.com/}"
            ;;
        *)
            printf '%s' "${url}"
            ;;
    esac
}

# Git 2.35+ отказывается работать в каталоге с «чужим» владельцем (root vs satellite).
github_ensure_safe_directory() {
    local dir="$1"
    if [[ -z "${dir}" || ! -d "${dir}/.git" ]]; then
        return 0
    fi
    git config --system --add safe.directory "${dir}" 2>/dev/null || true
}

github_git() {
    GIT_TERMINAL_PROMPT=0 git "$@"
}
