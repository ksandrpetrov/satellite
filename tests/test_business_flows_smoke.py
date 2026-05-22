"""Smoke-контракт: импорты satellite + /healthz на random port."""

from __future__ import annotations

import importlib
import pkgutil
import urllib.request
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock

import satellite
from satellite.users import UserStore
from satellite.web.server import WebAppServer, WebAppServerConfig

from .conftest import free_tcp_port


def test_smoke_container_module_list_imports() -> None:
    """Каждый подмодуль ``satellite.*`` должен импортироваться (как smoke_container)."""
    failures: list[str] = []
    for mod in pkgutil.walk_packages(satellite.__path__, prefix="satellite."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{mod.name}: {exc!r}")
    assert not failures, "import failures:\n" + "\n".join(failures)


def test_webapp_server_healthz_on_random_port(tmp_path: Path) -> None:
    users = UserStore(tmp_path / "users.json")
    port = free_tcp_port()
    server = WebAppServer(
        config=WebAppServerConfig(
            host="127.0.0.1",
            port=port,
            bot_token="test-token:12345",
            tz_name="Europe/Moscow",
        ),
        calendar_service=MagicMock(),
        users=users,
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2.0) as resp:
            assert resp.status == HTTPStatus.OK
            body = resp.read().decode("utf-8")
            assert '"ok"' in body or "ok" in body
    finally:
        server.stop()
