#!/usr/bin/env python3
"""Smoke-проверка собранного Docker-образа без Telegram и CalDAV.

Запускается в CI после build (см. scripts/docker-smoke-image.sh) и локально:
  docker build -t satellite:dev . && docker run --rm satellite:dev python scripts/smoke_container.py

Падает при сломанных импортах, caldav <3 или недоступном /healthz.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import satellite  # noqa: E402

_REQUIREMENTS = _APP_ROOT / "requirements.txt"
_CALDAV_IMPORTS = (
    "caldav",
    "caldav.davclient",
    "caldav.calendarobjectresource",
    "caldav.lib.error",
)


def _fail(msg: str) -> None:
    print(f"smoke_container: FAIL {msg}", file=sys.stderr)
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"smoke_container: OK {msg}")


def _check_caldav_pin() -> None:
    if not _REQUIREMENTS.is_file():
        _fail(f"requirements not found at {_REQUIREMENTS}")
    text = _REQUIREMENTS.read_text(encoding="utf-8")
    if not re.search(r"^caldav\s*>=\s*3\.\d+\s*,\s*<\s*4\s*$", text, re.MULTILINE):
        _fail("requirements.txt must pin caldav>=3.x,<4")
    import caldav

    version = getattr(caldav, "__version__", "")
    if version:
        major = int(version.split(".", maxsplit=1)[0])
        if major < 3:
            _fail(f"installed caldav {version} is <3 (need 3.x)")
    _ok(f"caldav pin + installed {version or 'unknown'}")


def _check_caldav_import_paths() -> None:
    for name in _CALDAV_IMPORTS:
        importlib.import_module(name)
    from caldav import DAVClient, Event as CaldavEvent

    if CaldavEvent is object or DAVClient is object:
        _fail("caldav namespace exports resolved to object")
    if not isinstance(DAVClient, type) or not isinstance(CaldavEvent, type):
        _fail("caldav DAVClient/Event are not classes")
    _ok("caldav imports (namespace + submodules)")


def _check_satellite_imports() -> None:
    bad: list[str] = []
    for mod in pkgutil.walk_packages(satellite.__path__, prefix="satellite."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{mod.name}: {exc!r}")
    if bad:
        _fail("import errors:\n  " + "\n  ".join(bad[:10]))
    _ok("all satellite modules import")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _check_healthz_http() -> None:
    from unittest.mock import MagicMock

    from satellite.users import UserStore
    from satellite.web.server import WebAppServer, WebAppServerConfig

    port = _free_port()
    users = UserStore(Path("/tmp/smoke-users.json"))
    server = WebAppServer(
        config=WebAppServerConfig(
            host="127.0.0.1",
            port=port,
            bot_token="smoke:token",
            tz_name="Europe/Moscow",
        ),
        calendar_service=MagicMock(),
        users=users,
    )
    server.start()
    try:
        url = f"http://127.0.0.1:{port}/healthz"
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            if resp.status != 200:
                _fail(f"GET /healthz -> {resp.status}")
            body = json.loads(resp.read().decode("utf-8"))
        if body != {"status": "ok"}:
            _fail(f"unexpected healthz body: {body!r}")
    except urllib.error.URLError as exc:
        _fail(f"GET /healthz failed: {exc}")
    finally:
        server.stop()
    _ok("GET /healthz")


def main() -> None:
    _check_caldav_pin()
    _check_caldav_import_paths()
    _check_satellite_imports()
    _check_healthz_http()
    print("smoke_container: all checks passed")


if __name__ == "__main__":
    main()
