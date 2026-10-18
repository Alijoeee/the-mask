"""Fixtures for the tests of the interface (tests/ui): the application's context."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.keystore.cases import CaseStore
    from themask.ui.app import AppContext


@pytest.fixture
def app_ctx(engine: Engine, lists: UserLists, case_store: CaseStore, tmp_path: Path) -> AppContext:
    """What the windows share: the session's engine, empty lists, an empty case store with its key
    in memory, and the default settings with the output folder inside the test's own folder.
    """
    # Imported here, not at the top: this module is loaded as a plugin for the whole suite, so an
    # import error in the code under test would stop every test from being collected.
    from themask.ui.app import AppContext, Settings

    return AppContext(engine, lists, case_store, Settings(out_dir=tmp_path / "masked"))
