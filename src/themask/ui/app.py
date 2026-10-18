"""Starting the app: what the windows share, the owner's settings, and ``main``.

``main`` is what ``python -m themask`` runs: the network guard first, then the log, then the
window. The detection engine is not made here; the window loads it in a thread while it shows
"Loading…" (``AppContext.engine`` is None until then).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

from themask.about import APP_NAME, VERSION
from themask.detect.lists import UserLists
from themask.errors import MaskError
from themask.keystore.cases import CaseStore
from themask.keystore.secrets import KeychainKeyStore
from themask.logging_setup import setup_logging
from themask.netguard import install_network_guard
from themask.paths import cases_dir, data_dir, lists_path
from themask.ui.main_window import MainWindow, show_error
from themask.ui.theme import apply_theme

if TYPE_CHECKING:
    from themask.detect.engine import Engine

DEFAULT_RETENTION_DAYS = 30
RETENTION_DAYS = range(1, 366)  # what the settings screen offers: a day to a year


def default_out_dir() -> Path:
    """Where the masked files go unless the owner says otherwise: ~/Documents/The MASK."""
    return Path.home() / "Documents" / APP_NAME


def settings_path() -> Path:
    """The file the settings are kept in (it may not exist yet)."""
    return data_dir() / "settings.json"


def _retention(value: object) -> int:
    """``value`` if it is a number of days the settings allow, else the default."""
    # A bool is a kind of int in Python, but "true" is not a number of days.
    if isinstance(value, int) and not isinstance(value, bool) and value in RETENTION_DAYS:
        return value
    return DEFAULT_RETENTION_DAYS


def _folder(value: object) -> Path:
    """The folder ``value`` names if it is text that names one, else the default."""
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return default_out_dir()


@dataclass
class Settings:
    """The owner's choices: how many days a case is kept, and the folder the masked files go in."""

    retention_days: int = DEFAULT_RETENTION_DAYS
    out_dir: Path = field(default_factory=default_out_dir)

    @classmethod
    def load(cls, path: Path) -> Settings:
        """The settings saved at ``path``. A missing, unreadable or damaged file, and any value
        that makes no sense (a retention of no days, a folder that is not text), gives the
        default for it: settings are never worth stopping the app for.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # no file, no access, not UTF-8 and not JSON are all this
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(_retention(data.get("retention_days")), _folder(data.get("out_dir")))

    def save(self, path: Path) -> None:
        """Write the settings to ``path`` as JSON, readable by the owner only.

        They go to a temporary file next to ``path`` first, which then replaces it, so a crash or
        a full disk never leaves half a file in place of the settings.
        """
        content = json.dumps(
            {"retention_days": self.retention_days, "out_dir": str(self.out_dir)},
            ensure_ascii=False,
            indent=2,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp makes the file readable and writable by its owner only.
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".settings-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


@dataclass
class AppContext:
    """What every screen shares: the detection engine (None while it loads), the owner's lists,
    the stored cases and the settings.
    """

    engine: Engine | None
    user_lists: UserLists
    case_store: CaseStore
    settings: Settings


def build_context() -> AppContext:
    """The context of a start: everything from the data folder, and no engine yet.

    Raises MaskError when the owner's lists cannot be read (they are never taken for empty ones:
    the owner's always-hide values would quietly stop being hidden) and OSError when the data
    folder cannot be used. The Keychain is not asked: the key is fetched when a case is first
    opened or saved.
    """
    return AppContext(
        engine=None,
        user_lists=UserLists.load(lists_path()),
        case_store=CaseStore(cases_dir(), KeychainKeyStore()),
        settings=Settings.load(settings_path()),
    )


def main() -> int:
    """Run the app: the network guard, the log, the window; returns the exit status."""
    install_network_guard()
    setup_logging()
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(VERSION)
    apply_theme(application)
    try:
        ctx = build_context()
    except MaskError as error:
        show_error(None, error.user_message)
        return 1
    except OSError as error:
        show_error(None, f"The MASK could not open its data folder: {error.strerror or error}")
        return 1
    window = MainWindow(ctx)
    window.show()
    status = application.exec()
    window.wait_for_workers()  # no thread may outlive the application
    return status
