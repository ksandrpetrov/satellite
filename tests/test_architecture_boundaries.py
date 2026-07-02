from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLERS_DIR = ROOT / "satellite" / "telegram_bot" / "handlers"
MESSAGES_RU_DIR = ROOT / "satellite" / "messages_ru"
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
HTML_TAG_RE = re.compile(r"<[a-z]")
FORBIDDEN_HANDLER_IMPORTS = frozenset(
    {
        "satellite.telegram_bot.html_format",
        "satellite.telegram_bot.rich_message",
        "html_format",
        "rich_message",
    }
)


def _import_from_modules(path: str) -> list[tuple[int, str | None]]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return [
        (node.level, node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]


def _handler_py_files() -> list[Path]:
    return sorted(HANDLERS_DIR.rglob("*.py"))


def _docstring_line_numbers(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.add(first.value.lineno)
    return lines


def _literal_cyrillic_violations(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_lines = _docstring_line_numbers(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.lineno in doc_lines:
            continue
        if CYRILLIC_RE.search(node.value):
            violations.append(f"{rel}:{node.lineno}")
    return violations


def _literal_html_violations(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_lines = _docstring_line_numbers(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.lineno in doc_lines:
            continue
        if HTML_TAG_RE.search(node.value):
            violations.append(f"{rel}:{node.lineno}")
    return violations


def _forbidden_import_violations(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in FORBIDDEN_HANDLER_IMPORTS or module.endswith(
                (".html_format", ".rich_message")
            ):
                violations.append(f"{rel}:{node.lineno} imports {module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_HANDLER_IMPORTS:
                    violations.append(f"{rel}:{node.lineno} imports {alias.name}")
    return violations


def test_access_and_admin_do_not_import_each_other() -> None:
    access_imports = _import_from_modules("satellite/telegram_bot/handlers/access.py")
    admin_imports = _import_from_modules("satellite/telegram_bot/handlers/admin.py")

    assert (1, "admin") not in access_imports
    assert (1, "access") not in admin_imports
    assert all(
        module != "satellite.telegram_bot.handlers.admin" for _level, module in access_imports
    )
    assert all(
        module != "satellite.telegram_bot.handlers.access" for _level, module in admin_imports
    )


def test_messages_calendar_ui_does_not_import_calendar_events() -> None:
    imports = _import_from_modules("satellite/messages_ru/calendar_ui.py")

    assert (2, "calendar.events") not in imports
    assert all(module != "satellite.calendar.events" for _level, module in imports)


def test_messages_ru_does_not_import_telegram_bot_layer() -> None:
    for rel_path in sorted(MESSAGES_RU_DIR.rglob("*.py")):
        if rel_path.name.startswith("_"):
            continue
        imports = _import_from_modules(str(rel_path.relative_to(ROOT)))
        assert all(
            not (module or "").startswith("satellite.telegram_bot") for _level, module in imports
        ), f"{rel_path} imports telegram_bot layer"
        assert all(
            not ((module or "").startswith("telegram_bot"))
            for _level, module in imports
            if _level == 0
        ), f"{rel_path} imports telegram_bot layer"


@pytest.mark.parametrize("handler_path", _handler_py_files(), ids=lambda p: p.name)
def test_handlers_do_not_contain_cyrillic_literals(handler_path: Path) -> None:
    violations = _literal_cyrillic_violations(handler_path)
    assert not violations, "Cyrillic string literals in handlers: " + ", ".join(violations)


@pytest.mark.parametrize("handler_path", _handler_py_files(), ids=lambda p: p.name)
def test_handlers_do_not_contain_html_literals(handler_path: Path) -> None:
    violations = _literal_html_violations(handler_path)
    assert not violations, "HTML tag literals in handlers: " + ", ".join(violations)


@pytest.mark.parametrize("handler_path", _handler_py_files(), ids=lambda p: p.name)
def test_handlers_do_not_import_markup_layers_directly(handler_path: Path) -> None:
    violations = _forbidden_import_violations(handler_path)
    assert not violations, "Forbidden imports in handlers: " + ", ".join(violations)


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        (
            "settings_hub_bundle",
            "satellite.telegram_bot.presenters.settings_screens.settings_hub_bundle",
        ),
        (
            "calendar_sources_bundle",
            "satellite.telegram_bot.presenters.calendar_screens.calendar_sources_bundle",
        ),
    ],
)
def test_screen_bundle_factories_return_nonempty_pair(factory_name: str, factory: str) -> None:
    import importlib

    module_path, func_name = factory.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    fn = getattr(mod, func_name)
    if func_name == "settings_hub_bundle":
        bundle = fn(has_calendar=True, reply_markup=None)
    else:
        from satellite.calendar.providers.base import CalendarListEntry

        bundle = fn(
            calendars=[CalendarListEntry(name="Work", url="https://cal.example/work")],
            enabled_urls=set(),
            reply_markup=None,
        )
    assert bundle.rich_html.strip(), f"{factory_name} rich_html is empty"
    assert bundle.fallback_html.strip(), f"{factory_name} fallback_html is empty"
