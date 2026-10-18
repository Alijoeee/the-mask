"""The owner's lists, and a data folder of its own for every test.

``private_data_dir`` is used by every test without asking: it points THEMASK_DATA_DIR at the
test's own empty ``data_dir``, so no test reads or writes the real data folder. ``lists`` is an
empty set of the owner's lists, saved where the app keeps them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from themask.detect.lists import UserLists

# The variable themask.paths reads. Spelled out here rather than imported: this module is loaded
# as a plugin for the whole suite, so an import error in the code under test would stop every
# test from being collected, not just the ones that need it.
DATA_DIR_VARIABLE = "THEMASK_DATA_DIR"


@pytest.fixture(autouse=True)
def private_data_dir(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The test's own data folder, where THEMASK_DATA_DIR points for the whole test."""
    monkeypatch.setenv(DATA_DIR_VARIABLE, str(data_dir))
    return data_dir


@pytest.fixture
def lists(private_data_dir: Path) -> UserLists:
    """The owner's lists, both empty, saved as lists.json in the test's data folder."""
    from themask.detect.lists import UserLists
    from themask.paths import lists_path

    user_lists = UserLists([], [])
    user_lists.save(lists_path())
    return user_lists
