"""Pure helpers for CalDAV endpoint discovery and calendar matching."""

from __future__ import annotations

DEFAULT_CALDAV_URL = "https://calendar.mail.ru/"


def normalize_url(url: str) -> str:
    return url.rstrip("/")


def login_variants_for_caldav(login: str) -> list[str]:
    normalized = (login or "").strip()
    if not normalized:
        return [""]
    variants = [normalized]
    local, sep, _domain = normalized.partition("@")
    if sep and local and local not in variants:
        variants.append(local)
    return variants


def build_candidate_urls(caldav_url: str | None, login: str) -> list[str]:
    login_name, _, domain = (login or "").partition("@")
    domain = domain or "mail.ru"

    seed = normalize_url(caldav_url) if caldav_url else normalize_url(DEFAULT_CALDAV_URL)
    roots = [seed]
    if seed.startswith("https://calendar.mail.ru"):
        default_root = normalize_url(DEFAULT_CALDAV_URL)
        if default_root not in roots:
            roots.append(default_root)

    direct_mailru_principal = (
        f"https://calendar.mail.ru/principals/{domain}/{login_name}" if login_name else ""
    )
    candidates: list[str] = []
    if seed.startswith("https://calendar.mail.ru") and direct_mailru_principal:
        candidates.append(direct_mailru_principal)
        candidates.append(f"{direct_mailru_principal}/")
    for root in roots:
        candidates.extend(
            [
                root,
                f"{root}/.well-known/caldav",
                f"{root}/caldav",
                f"{root}/dav",
                f"{root}/principals/{domain}/{login_name}",
                f"{root}/principals/{domain}/{login_name}/",
                f"{root}/calendars/{domain}/{login_name}",
                f"{root}/calendars/{domain}/{login_name}/",
            ]
        )

    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        key = item.rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def calendar_matches(cal_name: str | None, target: str | None) -> bool:
    target_norm = (target or "").strip().casefold()
    if not target_norm:
        return True
    return (cal_name or "").strip().casefold() == target_norm
