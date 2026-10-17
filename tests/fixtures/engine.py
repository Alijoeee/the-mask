"""The detection engine, loaded once per test session: loading the language model takes seconds."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from themask.detect.engine import Engine


@pytest.fixture(scope="session")
def engine() -> Engine:
    """The detection engine with its default English model."""
    # Imported here, not at the top: every fixture module is loaded for every test run, and a test
    # that never asks for the engine should not pay for importing Presidio and spaCy.
    from themask.detect.engine import Engine

    return Engine()
