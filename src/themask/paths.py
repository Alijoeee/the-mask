"""Where The MASK keeps its own files: the data folder, and in it the cases, the logs and the lists.

The data folder is the one the operating system gives an app for its data; on a Mac that is
``~/Library/Application Support/The MASK``. When the environment variable THEMASK_DATA_DIR is set
(and not blank), the data folder is the folder it names instead: every test points it at a folder
of its own, so that no test reads or writes the real one.

Each function that returns a folder creates it when it is missing, readable by its owner only.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

from themask.about import APP_NAME

DATA_DIR_VARIABLE = "THEMASK_DATA_DIR"

# Only the user who runs The MASK may look into its folders: they hold the encrypted keys, the
# logs and the owner's always-hide list.
_PRIVATE = 0o700


def data_dir() -> Path:
    """The app's data folder."""
    override = os.environ.get(DATA_DIR_VARIABLE, "").strip()
    if override:
        path = Path(override)
    else:
        path = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(mode=_PRIVATE, parents=True, exist_ok=True)
    return path


def cases_dir() -> Path:
    """The folder of the encrypted case files."""
    return _folder("cases")


def log_dir() -> Path:
    """The folder of the app's log, which never holds document content."""
    return _folder("logs")


def lists_path() -> Path:
    """The file that holds the owner's always-hide and never-hide lists (it may not exist yet)."""
    return data_dir() / "lists.json"


def _folder(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(mode=_PRIVATE, exist_ok=True)
    return path
