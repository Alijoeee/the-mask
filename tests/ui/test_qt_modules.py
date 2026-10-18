"""The interface uses QtCore, QtGui and QtWidgets and no other Qt module.

PySide6-Essentials is LGPL, but some of Qt's other modules are GPL only; the licence gate cannot
see an import, so this does (plan: "Qt modules limited to QtCore/QtGui/QtWidgets").
"""

from __future__ import annotations

import ast
from pathlib import Path

import themask

ALLOWED = {"PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_only_the_allowed_qt_modules_are_imported() -> None:
    source = Path(themask.__file__).parent
    files = sorted(source.rglob("*.py"))
    assert any(path.parent.name == "ui" for path in files)
    for path in files:
        for module in imported_modules(path):
            if module.split(".")[0] in {"PySide6", "shiboken6", "PyQt5", "PyQt6", "PySide2"}:
                assert module in ALLOWED, f"{path.name} imports {module}"


def test_no_core_module_imports_qt() -> None:
    # The core stays usable without a screen: only themask.ui may import Qt.
    source = Path(themask.__file__).parent
    for path in sorted(source.rglob("*.py")):
        if path.parent.name == "ui":
            continue
        assert not any(m.startswith(("PySide6", "shiboken6")) for m in imported_modules(path)), path
