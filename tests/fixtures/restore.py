"""The cases of the restore tests: the brief's key, and supply-01 masked the way the app masks it.

``CASE`` is the brief's key: [PERSON_1] John Smith, [COMPANY_1] Acme Supplies Ltd and [AMOUNT_1]
EUR 1,250,000, made at ``NOW``. ``masked_case`` is the corpus's supply-01 exported for its own
review, as (the masked file, its case).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from themask.model import Case, KeyEntry, PlaceholderType

if TYPE_CHECKING:
    from themask.detect.engine import Engine

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)

CASE = Case(
    "K4F7",
    NOW,
    ["c.docx"],
    [],
    [
        KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"]),
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme"]),
        KeyEntry("[AMOUNT_1]", PlaceholderType.AMOUNT, "EUR 1,250,000", []),
    ],
)


@pytest.fixture(scope="module")
def masked_case(
    corpus: Path, engine: Engine, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Case]:
    """supply-01 analysed, reviewed as the app makes the review, and exported: (file, case).

    It is made once for each test module that asks for it, as an export takes a few seconds, so
    a test must change neither the file nor the case, nor write next to the file. The owner's
    lists are empty. The export runs with a data folder of its own: a fixture made once for a
    module comes before the one that gives each test its data folder.
    """
    # Imported here, not at the top: this module is loaded as a plugin for the whole suite.
    from tests.fixtures.lists import DATA_DIR_VARIABLE
    from tests.helpers import reviewed
    from themask.detect.lists import UserLists
    from themask.export import ExportOptions, export_case

    lists = UserLists([], [])
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(DATA_DIR_VARIABLE, str(tmp_path_factory.mktemp("restore-data")))
        sources, review = reviewed([corpus / "supply-01.docx"], engine, lists)
        options = ExportOptions(tmp_path_factory.mktemp("restore-masked"))
        result = export_case(sources, review, options, engine, lists, lambda case: None)
    assert not result.blocked and result.case is not None
    return result.outputs[0], result.case
