from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_from_modules(path: str) -> list[tuple[int, str | None]]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return [
        (node.level, node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]


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
