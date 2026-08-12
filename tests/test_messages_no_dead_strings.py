"""Страж: в ``messages_ru`` не должно накапливаться неиспользуемых строк.

Пакет реэкспортируется через ``from .<submodule> import *`` без ``__all__``,
поэтому ни ruff, ни mypy не видят «экспортируемую, но никем не читаемую»
константу. За время жизни проекта так набралось 19 мёртвых текстов — удалять
их приходилось отдельным аудитом. Этот тест ловит следующий такой случай сразу.

Правило: у каждой публичной константы верхнего уровня в
``satellite/messages_ru`` должна быть хотя бы одна ссылка помимо самого
определения — в ``satellite/`` или в ``tests/``. Ссылка изнутри своего же
модуля засчитывается: такие константы собирают из себя другие тексты
(``SETTINGS_HUB_TITLE`` → ``settings_hub_text()``), и это нормально.

Если константа временно не нужна — её надо удалить, а не заносить в
``_ALLOWED_UNUSED``: список ниже только для случаев, когда строка обязана
существовать по внешней причине.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES_DIR = ROOT / "satellite" / "messages_ru"

# Константа -> почему она живёт без внешних ссылок.
_ALLOWED_UNUSED: dict[str, str] = {}


def _public_constants(module: Path) -> list[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and not target.id.startswith("_"):
                names.append(target.id)
    return names


def _search_corpus() -> list[tuple[Path, str]]:
    corpus: list[tuple[Path, str]] = []
    for base in (ROOT / "satellite", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            corpus.append((path, path.read_text(encoding="utf-8")))
    return corpus


def test_no_unused_public_strings_in_messages_ru() -> None:
    corpus = _search_corpus()
    dead: list[str] = []

    for module in sorted(MESSAGES_DIR.glob("*.py")):
        if module.name == "__init__.py":
            continue
        for name in _public_constants(module):
            if name in _ALLOWED_UNUSED:
                continue
            pattern = re.compile(rf"\b{re.escape(name)}\b")
            # Определение даёт ровно одно вхождение; всё сверх него — ссылка.
            occurrences = sum(len(pattern.findall(text)) for _, text in corpus)
            if occurrences <= 1:
                dead.append(f"{module.relative_to(ROOT)}: {name}")

    assert not dead, (
        "Неиспользуемые строки в messages_ru — удалите их "
        "(или обоснуйте в _ALLOWED_UNUSED):\n  " + "\n  ".join(dead)
    )
