"""Layer boundary tests: domain modules must not import telegram handlers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PREFIXES = (
    "satellite.telegram_bot.handlers",
    "telegram_bot.handlers",
)


def _py_files_under(rel: str) -> list[Path]:
    base = ROOT / rel
    return sorted(p for p in base.rglob("*.py") if p.is_file())


def _import_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
    return modules


def _violations(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    bad: list[str] = []
    for module in _import_modules(path):
        for prefix in FORBIDDEN_PREFIXES:
            if module == prefix or module.startswith(prefix + "."):
                bad.append(f"{rel} imports {module}")
    return bad


@pytest.mark.parametrize(
    "package",
    [
        "satellite/presentation",
        "satellite/calendar",
        "satellite/seagull",
        "satellite/invitations_view.py",
        "satellite/scheduler.py",
    ],
)
def test_domain_packages_do_not_import_telegram_handlers(package: str) -> None:
    path = ROOT / package
    files = [path] if path.is_file() else _py_files_under(package)
    violations: list[str] = []
    for file_path in files:
        violations.extend(_violations(file_path))
    assert not violations, "; ".join(violations)
