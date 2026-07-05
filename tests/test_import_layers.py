"""Layer boundary tests: домен не знает о transport-слое Telegram.

Правила:

1. Чистый домен (тексты, календарь, рендеры, сторы) не импортирует
   ``telegram_bot`` вообще. Единственное исключение —
   ``presentation/delivery.py``: доставка rich-сообщений по определению
   работает через ``telegram_bot.api`` (и только через него).
2. Оркестраторы (``scheduler.py``) шлют сообщения через ``telegram_bot.api``
   / ``presentation.delivery``, но не лезут в ``telegram_bot.handlers``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Пакеты и модули, которым запрещён любой импорт telegram_bot.
PURE_DOMAIN = (
    "satellite/analytics",
    "satellite/backup.py",
    "satellite/calendar",
    "satellite/config.py",
    "satellite/digest_utils.py",
    "satellite/invitations_view.py",
    "satellite/logging_setup.py",
    "satellite/messages_ru",
    "satellite/plan_service.py",
    "satellite/presentation",
    "satellite/seagull",
    "satellite/security",
    "satellite/subscriptions",
    "satellite/testing",
    "satellite/users",
    "satellite/visual_cards",
    "satellite/weather",
)

# Оркестраторы доставки: telegram_bot.api / visual разрешены, handlers — нет.
ORCHESTRATORS = (
    "satellite/scheduler.py",
    "satellite/web",
)

_TELEGRAM_BOT_PREFIXES = ("satellite.telegram_bot", "telegram_bot")
_HANDLERS_PREFIXES = (
    "satellite.telegram_bot.handlers",
    "telegram_bot.handlers",
)

# file (relative to ROOT) -> модули, которые ему разрешены сверх правила.
_ALLOWLIST: dict[str, frozenset[str]] = {
    # Доставка rich с fallback — транспортный край presentation.
    "satellite/presentation/delivery.py": frozenset(
        {"satellite.telegram_bot.api", "telegram_bot.api"}
    ),
}


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


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _violations(path: Path, prefixes: tuple[str, ...]) -> list[str]:
    rel = path.relative_to(ROOT)
    allowed = _ALLOWLIST.get(str(rel), frozenset())
    bad: list[str] = []
    for module in _import_modules(path):
        if module in allowed:
            continue
        if _matches(module, prefixes):
            bad.append(f"{rel} imports {module}")
    return bad


def _collect_violations(package: str, prefixes: tuple[str, ...]) -> list[str]:
    path = ROOT / package
    files = [path] if path.is_file() else _py_files_under(package)
    violations: list[str] = []
    for file_path in files:
        violations.extend(_violations(file_path, prefixes))
    return violations


_MESSAGES_RU_PREFIXES = ("satellite.messages_ru", "messages_ru")
_MESSAGES_RU_FACADE_ONLY = frozenset(_MESSAGES_RU_PREFIXES)


def _messages_ru_violations(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    bad: list[str] = []
    for module in _import_modules(path):
        if _matches(module, _MESSAGES_RU_PREFIXES):
            bad.append(f"{rel} imports {module}")
    return bad


def _messages_ru_submodule_violations(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    if str(rel).startswith("satellite/messages_ru/"):
        return []
    bad: list[str] = []
    for module in _import_modules(path):
        if module in _MESSAGES_RU_FACADE_ONLY:
            continue
        if _matches(module, _MESSAGES_RU_PREFIXES):
            bad.append(f"{rel} imports {module} (use satellite.messages_ru facade)")
    return bad


@pytest.mark.parametrize("package", ("satellite/calendar",))
def test_calendar_does_not_import_messages_ru(package: str) -> None:
    path = ROOT / package
    files = [path] if path.is_file() else _py_files_under(package)
    violations: list[str] = []
    for file_path in files:
        violations.extend(_messages_ru_violations(file_path))
    assert not violations, "; ".join(violations)


def test_messages_ru_submodules_imported_only_via_facade() -> None:
    """Вне пакета messages_ru — только ``from satellite.messages_ru import …``."""
    violations: list[str] = []
    for file_path in sorted((ROOT / "satellite").rglob("*.py")):
        if not file_path.is_file():
            continue
        violations.extend(_messages_ru_submodule_violations(file_path))
    for file_path in sorted((ROOT / "tests").rglob("*.py")):
        if not file_path.is_file():
            continue
        violations.extend(_messages_ru_submodule_violations(file_path))
    assert not violations, "; ".join(violations)


@pytest.mark.parametrize("package", PURE_DOMAIN)
def test_pure_domain_does_not_import_telegram_bot(package: str) -> None:
    violations = _collect_violations(package, _TELEGRAM_BOT_PREFIXES)
    assert not violations, "; ".join(violations)


@pytest.mark.parametrize("package", ORCHESTRATORS)
def test_orchestrators_do_not_import_telegram_handlers(package: str) -> None:
    violations = _collect_violations(package, _HANDLERS_PREFIXES)
    assert not violations, "; ".join(violations)
