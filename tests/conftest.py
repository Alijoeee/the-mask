import os
from pathlib import Path

import pytest

# Tests never open a real window: Qt renders offscreen (set before any QApplication exists).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Every module in tests/fixtures/ is loaded as a pytest plugin, so a task that needs new fixtures
# adds a file there instead of editing this one.
pytest_plugins = sorted(
    f"tests.fixtures.{p.stem}"
    for p in Path(__file__).parent.joinpath("fixtures").glob("*.py")
    if p.stem != "__init__"
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An empty directory that stands in for the application's data folder."""
    return tmp_path
