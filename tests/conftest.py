import os
from pathlib import Path

import pytest

# Tests never open a real window: Qt renders offscreen (set before any QApplication exists).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An empty directory that stands in for the application's data folder."""
    return tmp_path
