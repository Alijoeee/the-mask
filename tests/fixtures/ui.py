"""Fixtures for the tests of the interface (tests/ui): the application's context and a review."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.detect.engine import Engine
    from themask.detect.lists import CaseLists, UserLists
    from themask.detect.pipeline import CombinedText
    from themask.keystore.cases import CaseStore
    from themask.model import Analysis
    from themask.review import ReviewState
    from themask.ui.app import AppContext
    from themask.ui.review_screen import ReviewScreen


@pytest.fixture
def app_ctx(engine: Engine, lists: UserLists, case_store: CaseStore, tmp_path: Path) -> AppContext:
    """What the windows share: the session's engine, empty lists, an empty case store with its key
    in memory, and the default settings with the output folder inside the test's own folder.
    """
    # Imported here, not at the top: this module is loaded as a plugin for the whole suite, so an
    # import error in the code under test would stop every test from being collected.
    from themask.ui.app import AppContext, Settings

    return AppContext(engine, lists, case_store, Settings(out_dir=tmp_path / "masked"))


@pytest.fixture(scope="session")
def supply_08_analysis(engine: Engine, corpus: Path) -> tuple[CombinedText, Analysis, CaseLists]:
    """supply-08.docx analysed once for the whole session: its combined text, the analysis and the
    case lists the analysis filled. supply-08 is the corpus file with a shared surname that also
    names "Project Falcon" twice. A test gets its own review of it (``review_screen``).
    """
    from themask.detect.lists import CaseLists, UserLists
    from themask.detect.pipeline import analyze
    from themask.export import combined_text, load_sources

    combined = combined_text(load_sources([corpus / "supply-08.docx"], False))
    case_lists = CaseLists([], [], set())
    return combined, analyze(combined, engine, UserLists([], []), case_lists), case_lists


@pytest.fixture
def review_screen(
    qtbot: QtBot,
    lists: UserLists,
    supply_08_analysis: tuple[CombinedText, Analysis, CaseLists],
) -> tuple[ReviewScreen, ReviewState]:
    """The review screen showing a review of supply-08.docx, and that review.

    The review is the test's own: ``ReviewState.from_analysis`` copies the groups, so what a test
    switches off or hides does not reach the next test.
    """
    from themask.detect.lists import CaseLists
    from themask.review import ReviewState
    from themask.ui.review_screen import ReviewScreen

    combined, analysis, analysed_lists = supply_08_analysis
    case_lists = CaseLists(
        list(analysed_lists.always_hide),
        list(analysed_lists.never_hide),
        set(analysed_lists.defined_terms),
    )
    review = ReviewState.from_analysis(analysis, lists, case_lists)
    screen = ReviewScreen()
    qtbot.addWidget(screen)
    screen.load(review, combined)
    return screen, review
