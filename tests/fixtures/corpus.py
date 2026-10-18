"""The made-up contract corpus, generated once per test session."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A folder with every corpus file: the Word and PDF contracts, their truth files, the manifest."""
    # Imported here, not at the top: this module is loaded as a plugin for the whole suite, and
    # the generator (Faker, Pillow, python-docx, reportlab, schwifty) is only needed by tests that
    # use it.
    from tools.make_corpus import generate

    out = tmp_path_factory.mktemp("corpus")
    generate(out)
    return out
