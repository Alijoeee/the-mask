import os
from pathlib import Path

import pytest

from themask.netguard import install_network_guard

# Tests never open a real window: Qt renders offscreen (set before any QApplication exists).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The whole suite runs with the network guard on, which proves that the app needs no network.
# It goes on as this file is imported, before any fixture module is loaded.
install_network_guard()

# Every module in tests/fixtures/ is loaded as a pytest plugin, so a task that needs new fixtures
# adds a file there instead of editing this one.
pytest_plugins = sorted(
    f"tests.fixtures.{p.stem}"
    for p in Path(__file__).parent.joinpath("fixtures").glob("*.py")
    if p.stem != "__init__"
)


@pytest.fixture
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An empty directory that stands in for the application's data folder.

    THEMASK_DATA_DIR points at it in every test (tests/fixtures/lists.py). It is a fresh folder
    beside the test's ``tmp_path``, not in it, so what the app writes there never mixes with a
    test's own files.
    """
    return tmp_path_factory.mktemp("data")
