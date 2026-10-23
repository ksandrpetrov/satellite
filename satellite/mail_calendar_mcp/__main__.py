"""Run or initialize the independent Mail calendar MCP service."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet

from .server import build_app
from .settings import load_mcp_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Mail calendar connection for ChatGPT")
    parser.add_argument("--env-file", type=Path, default=Path("logs/mail-calendar/.env"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Create a separate configuration; do not enter a Mail password here"
    )
    init.add_argument("--login", required=True)
    init.add_argument("--base-url", default="http://127.0.0.1:8765")
    commands.add_parser("serve", help="Serve authenticated Streamable HTTP at /mcp")
    package = commands.add_parser(
        "package", help="Export a portable plugin for a deployed HTTPS server"
    )
    package.add_argument("--base-url", required=True)
    package.add_argument("--output-dir", type=Path, default=Path("dist/mail-calendar"))
    args = parser.parse_args()
    if args.command == "package":
        from .package import package_plugin

        print(f"Plugin archive created: {package_plugin(args.base_url, args.output_dir)}")
        return
    if args.command == "init":
        from .settings import McpSettings

        key = Fernet.generate_key().decode()
        login = args.login.strip().casefold()
        settings = McpSettings(
            args.base_url.rstrip("/"), key, frozenset({login}), args.env_file.parent
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        content = (
            f"MCP_BASE_URL={settings.base_url}\nMCP_ALLOWED_LOGINS={login}\n"
            f"MCP_ENCRYPTION_KEY={key}\nMCP_DATA_DIR={settings.data_dir}\n"
            "MCP_TIMEZONE=Europe/Moscow\nMCP_HOST=127.0.0.1\nMCP_PORT=8765\n"
        )
        # Never overwrite an existing encryption key or a calendar connection.
        fd = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        print(f"Configuration created: {args.env_file}. Run the serve command next.")
        return
    settings = load_mcp_settings(args.env_file)
    # CalDAV/library tracebacks can contain credentials or OAuth request data.
    # The service returns safe typed errors; do not enable their debug logging.
    for name in ("caldav", "satellite.calendar", "mcp.server"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
    uvicorn.run(
        build_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
