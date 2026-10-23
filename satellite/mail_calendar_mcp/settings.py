"""Explicit, separate configuration for the ChatGPT calendar connection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from pydantic import AnyHttpUrl


def normalize_base_url(value: str, *, allow_local: bool = True) -> str:
    url = urlsplit(value)
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not url.hostname
        or (url.scheme != "https" and not (allow_local and local and url.scheme == "http"))
        or not re.fullmatch(r"(?:/[a-zA-Z0-9_-]+)*/?", url.path)
        or url.query
        or url.fragment
        or url.username
        or url.password
    ):
        raise ValueError("MCP_BASE_URL must be an HTTPS base URL (HTTP only for localhost)")
    return str(AnyHttpUrl(value)).rstrip("/")


@dataclass(frozen=True)
class McpSettings:
    base_url: str
    encryption_key: str
    allowed_logins: frozenset[str]
    data_dir: Path
    timezone: str = "Europe/Moscow"
    host: str = "127.0.0.1"
    port: int = 8765

    def __post_init__(self) -> None:
        base_url = normalize_base_url(self.base_url)
        if not self.allowed_logins or any(
            not re.fullmatch(r"[^\s@]+@[a-zA-Z0-9.-]+", login) for login in self.allowed_logins
        ):
            raise ValueError("MCP_ALLOWED_LOGINS must contain the owner's Mail email address")
        if not 1 <= self.port <= 65535:
            raise ValueError("Invalid MCP_PORT")
        ZoneInfo(self.timezone)
        # OAuth resource matching must use the same URL normalization as the SDK
        # (host case, IDNA and default ports), including behind a TLS proxy.
        object.__setattr__(self, "base_url", base_url)

    @property
    def origin(self) -> str:
        url = urlsplit(self.base_url)
        return f"{url.scheme}://{url.netloc}"

    @property
    def path_prefix(self) -> str:
        return urlsplit(self.base_url).path

    @property
    def connect_path(self) -> str:
        return self.path_prefix + "/connect"

    @property
    def resource_url(self) -> str:
        return self.base_url.rstrip("/") + "/mcp"


def load_mcp_settings(env_path: Path) -> McpSettings:
    values = {**dotenv_values(env_path), **os.environ}
    return McpSettings(
        base_url=str(values.get("MCP_BASE_URL") or "http://127.0.0.1:8765").rstrip("/"),
        encryption_key=str(values.get("MCP_ENCRYPTION_KEY") or ""),
        allowed_logins=frozenset(
            item.strip().casefold()
            for item in str(values.get("MCP_ALLOWED_LOGINS") or "").split(",")
            if item.strip()
        ),
        data_dir=Path(values.get("MCP_DATA_DIR") or "logs/mail-calendar"),
        timezone=str(values.get("MCP_TIMEZONE") or "Europe/Moscow"),
        host=str(values.get("MCP_HOST") or "127.0.0.1"),
        port=int(values.get("MCP_PORT") or "8765"),
    )
