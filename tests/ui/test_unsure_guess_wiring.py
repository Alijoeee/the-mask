"""The detection's low-confidence guess of ordinary words reaches the review as a question
(ruling R122, item 1): off in the plan, listed under "Not sure — hide?", counted as to check.
"""

from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import CombinedText, analyze
from themask.model import Finding, PlaceholderType
from themask.review import ReviewState
from themask.ui.review_inspector import NOT_SURE, asks_about, sections


class _Model:
    def __init__(self, *needles):
        self.needles = needles

    def analyze(self, text):
        found = []
        for kind, needle, score in self.needles:
            start = text.find(needle)
            while start >= 0:
                found.append(Finding(kind, start, start + len(needle), needle, score, "model"))
                start = text.find(needle, start + 1)
        return found


def test_the_guess_is_a_question_for_the_review_and_stays_out_of_the_plan(lists):
    text = "Equipment Services start now. Zorblax Services start too."
    C = PlaceholderType.COMPANY
    engine = _Model((C, "Equipment Services", 0.6), (C, "Zorblax Services", 0.6))
    analysis = analyze(CombinedText.join([("x", text)]), engine, lists)
    state = ReviewState.from_analysis(analysis, UserLists([], []), CaseLists([], [], set()))
    asked = [g for g in state.groups if asks_about(g)]
    assert [g.canonical for g in asked] == ["Equipment Services"]
    assert [s.name for s in sections(state.groups) if s.question] == [NOT_SURE]
    hidden = {text[r.start : r.end] for r in state.mask_plan().replacements}
    assert hidden == {"Zorblax Services"}
    state.set_group_enabled(asked[0].id, True)  # the owner's "Hide"
    assert len(state.mask_plan().replacements) == 2
