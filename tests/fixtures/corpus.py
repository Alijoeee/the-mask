"""The made-up contract corpus, generated once per test session."""

from pathlib import Path

import pytest

from tools.make_corpus import generate


@pytest.fixture(scope="session")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A folder with every corpus file: the Word contracts, their truth files and the manifest."""
    out = tmp_path_factory.mktemp("corpus")
    generate(out)
    return out
