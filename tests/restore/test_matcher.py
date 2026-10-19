"""Planning a restore and suggesting the case: what each placeholder is, and which key fits a text.

``test_suggest_cases`` is the brief's. The rest pin the controller's decisions for Task 18: one
item per placeholder in text order with its status (decision 1); The MASK's banner and the
instruction for the AI left out of the plan (decision 3, ruling R76); a changed form whose number
is a real key entry's planned as changed, never as exact (R44); an identifier that has the shape
of a changed placeholder planned as unknown (decision 6); and the ranking of cases by the distinct
placeholders they hold, then by the newest, with cases that hold none still listed (decision 5).
Ruling R78: a banner the AI rewrote is still left out of the plan. Ruling R79: the stretch a
restore replaces leaves out a bracket that stands on one side of a changed placeholder only.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fixtures.restore import CASE, NOW
from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.restore.matcher import plan_restore, restore_span, suggest_cases

PERSON, COMPANY, AMOUNT = CASE.entries


def plan(text: str, case: Case = CASE) -> list[tuple[str, str, KeyEntry | None]]:
    """The plan for ``text`` as (placeholder as written, status, key entry) triples."""
    return [(item.match.raw, item.status, item.entry) for item in plan_restore(text, case)]


def made(case_id: str, days_ago: int, entries: list[KeyEntry]) -> Case:
    """A case made ``days_ago`` days before ``NOW`` with ``entries`` as its key."""
    return Case(case_id, NOW - timedelta(days=days_ago), [], [], entries)


def ids(cases: list[Case]) -> list[str]:
    return [case.id for case in cases]


def test_each_placeholder_is_one_item_in_text_order() -> None:
    text = "[PERSON_1] met person_1 and [PERSON_9] about **[AMOUNT_1]**; person-9 and [COMPANY_1]."
    assert plan(text) == [
        ("[PERSON_1]", "exact", PERSON),
        ("person_1", "altered", PERSON),
        ("[PERSON_9]", "unknown", None),
        ("**[AMOUNT_1]**", "altered", AMOUNT),
        ("person-9", "unknown", None),  # not in the key, whatever its form
        ("[COMPANY_1]", "exact", COMPANY),
    ]


def test_nothing_to_plan() -> None:
    assert plan("") == []
    assert plan("[Name] signs on [Date] for Company 1.") == []


def test_the_banner_and_the_instruction_are_not_planned() -> None:
    # Their [COMPANY_1], [PERSON_1] and [AMOUNT_2] are The MASK's examples: a restore takes the
    # lines out instead (decision 3, R76). What follows them is planned at its place in the text.
    text = f"{AI_INSTRUCTION}\n{BANNER_TEXT}\n\n[COMPANY_1] signs."
    (item,) = plan_restore(text, CASE)
    assert (item.match.raw, item.status, item.entry) == ("[COMPANY_1]", "exact", COMPANY)
    assert item.match.start == text.index("[COMPANY_1] signs.")


def test_a_banner_the_ai_rewrote_is_not_planned() -> None:
    # R78: in italics, quoted and with its brackets escaped it is still The MASK's banner.
    banner = BANNER_TEXT.replace("[COMPANY_1]", r"\[COMPANY_1\]")
    assert plan(f"> *{banner}*\n\nHello [PERSON_1]") == [("[PERSON_1]", "exact", PERSON)]


def test_a_changed_form_with_a_real_key_number_is_planned_as_changed() -> None:
    # R44: a source may hold a token such as "company_2" (here a field name) while the export gave
    # a real company the number 2. As a changed form it waits for the owner's confirmation.
    company_2 = KeyEntry("[COMPANY_2]", PlaceholderType.COMPANY, "Brightwater Logistics BV", [])
    case = made("R44X", 0, [company_2])
    assert plan("Map the field company_2 to [COMPANY_2].", case) == [
        ("company_2", "altered", company_2),
        ("[COMPANY_2]", "exact", company_2),
    ]


def test_an_identifier_shaped_like_a_placeholder_is_unknown() -> None:
    # "ID-4711" reads as a changed [ID_4711]; the key holds no such entry.
    assert plan("Order ID-4711 ships to [PERSON_1].") == [
        ("ID-4711", "unknown", None),
        ("[PERSON_1]", "exact", PERSON),
    ]


def test_suggest_cases() -> None:
    a = Case("A", NOW, [], [], CASE.entries[:2])
    b = Case("B", NOW, [], [], CASE.entries[:1])
    assert [c.id for c in suggest_cases("[PERSON_1] and [COMPANY_1]", [b, a])] == ["A", "B"]


def test_each_placeholder_counts_once_whatever_its_form() -> None:
    # X's one placeholder stands three times in the text, Y's two once each (one of them changed
    # by the AI): Y holds more of the text's placeholders. X is newer, so the count decides.
    x = made("X", 0, [PERSON])
    y = made("Y", 1, [COMPANY, AMOUNT])
    text = "[PERSON_1], person_1 and PERSON-1 met [COMPANY_1] about **[AMOUNT_1]**."
    assert ids(suggest_cases(text, [x, y])) == ["Y", "X"]


def test_a_tie_goes_to_the_newer_case_and_cases_holding_none_come_last() -> None:
    old, new = made("OLD", 2, [PERSON]), made("NEW", 1, [PERSON, AMOUNT])
    newest_none, oldest_none = made("NONE", 0, []), made("NONE-OLD", 3, [COMPANY])
    found = suggest_cases("[PERSON_1] signs.", [old, oldest_none, new, newest_none])
    assert ids(found) == ["NEW", "OLD", "NONE", "NONE-OLD"]


def test_without_placeholders_the_newest_case_comes_first() -> None:
    old, new, newest = made("OLD", 2, [PERSON]), made("NEW", 1, [COMPANY]), made("NOW", 0, [])
    assert ids(suggest_cases("No placeholders here.", [old, newest, new])) == ["NOW", "NEW", "OLD"]
    assert suggest_cases("[PERSON_1]", []) == []


def test_the_banners_example_does_not_count_for_a_case() -> None:
    # The banner's [COMPANY_1] is The MASK's example, not the AI's: counting it would put a case
    # that merely holds a [COMPANY_1] level with the case the text comes from, and win on age.
    company_case, person_case = made("C", 0, [COMPANY]), made("P", 1, [PERSON])
    text = f"{BANNER_TEXT}\n\nHello [PERSON_1]"
    assert ids(suggest_cases(text, [company_case, person_case])) == ["P", "C"]


@pytest.mark.parametrize(
    ("text", "replaced"),
    [
        ("Dear [PERSON_1],", "[PERSON_1]"),
        ("Dear **[PERSON_1]**,", "**[PERSON_1]**"),
        ("Dear [ PERSON_1 ],", "[ PERSON_1 ]"),
        (r"Dear \[PERSON_1\],", r"\[PERSON_1\]"),
        ("Dear person_1,", "person_1"),
        # R79: a bracket on one side only is the surrounding text's.
        ("[Buyer, PERSON_1]", "PERSON_1"),
        ("[PERSON_1, the Buyer]", "PERSON_1"),
        ("[Buyer, **PERSON_1 ]**", "PERSON_1"),
    ],
)
def test_restore_span(text: str, replaced: str) -> None:
    (match,) = [item.match for item in plan_restore(text, CASE)]
    start, end = restore_span(match)
    assert text[start:end] == replaced
