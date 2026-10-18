"""The review state over the brief's example contract, for the tests of ``themask.review``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.review import ReviewState

# Three named values, a code name the language model takes for a company (twice), and a short
# name. With the real engine the analysis gives four groups, in this order: [COMPANY_1] Acme
# Supplies Ltd (twice), [COMPANY_2] Northwind Trading B.V., [PERSON_1] John Smith, and
# [COMPANY_3] Project Falcon, which is marked to check (a model guess at 0.6).
REVIEW_TEXT = (
    "Acme Supplies Ltd and Northwind Trading B.V. appoint John Smith. "
    "Project Falcon starts now; Project Falcon ends later. Acme signs."
)


@pytest.fixture
def review(engine: Engine, lists: UserLists) -> ReviewState:
    """A review of ``REVIEW_TEXT``, analysed with the real engine and the owner's empty lists."""
    # Imported here, not at the top: this module is loaded as a plugin for the whole suite, so an
    # import error in the code under test would stop every test from being collected.
    from themask.detect.lists import CaseLists
    from themask.detect.pipeline import CombinedText, analyze
    from themask.review import ReviewState

    analysis = analyze(CombinedText.join([("x", REVIEW_TEXT)]), engine, lists)
    return ReviewState.from_analysis(analysis, lists, CaseLists([], [], set()))
