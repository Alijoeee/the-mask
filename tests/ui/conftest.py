"""Guards for the tests of the interface.

A modal dialog that nobody can answer would hang the whole run. Every test here starts with the
dialogs replaced by a function that fails the test; a test that expects a dialog replaces it with
a recorder of its own (``monkeypatch``) and says what it expects.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import NoReturn

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox


def _refuse(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("The test opened a dialog that nobody can answer.")


@pytest.fixture(autouse=True)
def no_unanswerable_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Message boxes and file dialogs fail the test instead of waiting for a click."""
    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(_refuse))
    for name in ("getOpenFileNames", "getExistingDirectory", "getSaveFileName"):
        monkeypatch.setattr(QFileDialog, name, staticmethod(_refuse))


@pytest.fixture(autouse=True)
def no_real_finder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening a folder in Finder fails the test; one that clicks "Show in Finder" replaces the
    screen's ``reveal`` with a recorder.
    """
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(_refuse))


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """setup_logging changes loggers that live as long as the process: put them back afterwards.

    The windows' code starts the log (``app.main``) and the threads write to it.
    """
    app = logging.getLogger("themask")
    presidio = logging.getLogger("presidio-analyzer")
    handlers, level, presidio_level = list(app.handlers), app.level, presidio.level
    yield
    for handler in list(app.handlers):
        if handler not in handlers:
            app.removeHandler(handler)
            handler.close()
    app.setLevel(level)
    presidio.setLevel(presidio_level)
