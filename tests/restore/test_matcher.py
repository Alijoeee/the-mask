"""Planning a restore and suggesting the case: what each placeholder is, and which key fits a text.

``test_suggest_cases`` is the brief's. The rest pin the controller's decisions for Task 18: one
item per placeholder in text order with its status (decision 1); The MASK's banner and the
instruction for the AI left out of the plan (decision 3, ruling R76); a changed form whose number
is a real key entry's planned as changed, never as exact (R44); an identifier that has the shape
of a changed placeholder planned as unknown (decision 6); and the ranking of cases by the distinct
placeholders they hold, then by the newest, with cases that hold none still listed (decision 5).
Ruling R78: a banner the AI rewrote is still left out of the plan. Ruling R79: the stretch a
restore replaces leaves out a bracket that stands on one side of a changed placeholder only.
Ruling R103: the code of a case in the name of the file puts that case first, whatever the
placeholders say (placeholder names repeat from case to case, so they cannot tell which
contract a file belongs to).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fixtures.restore import CASE, NOW
from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.restore.matcher import (
    case_in_file_name,
    plan_restore,
    restore_span,
    suggest_cases,
)

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


# ---- the name of the file (ruling R103) ------------------------------------------------------------

# Both cases hold [PERSON_1] (placeholder names repeat from case to case); the newer one holds
# the company as well, so by the placeholders alone it is the better fit for this text.
OLDER = made("K4F7", 5, [PERSON])
NEWER = made("M5N6", 1, [PERSON, COMPANY])
BOTH = "[PERSON_1] signs for [COMPANY_1]."


def test_the_case_whose_code_is_in_the_file_name_comes_first_whatever_the_overlap() -> None:
    assert ids(suggest_cases(BOTH, [OLDER, NEWER])) == ["M5N6", "K4F7"]  # by the text alone
    assert ids(suggest_cases(BOTH, [OLDER, NEWER], "MASKED-K4F7-1.docx")) == ["K4F7", "M5N6"]
    assert ids(suggest_cases(BOTH, [OLDER, NEWER], "MASKED-M5N6.docx")) == ["M5N6", "K4F7"]


@pytest.mark.parametrize(
    "file_name",
    [
        "MASKED-K4F7.docx",
        "MASKED-K4F7-1.docx",
        "MASKED-K4F7-2-after.docx",
        "K4F7.docx",
        "K4F7",
        "masked-k4f7.docx",  # an AI tool that writes names in lower case
        "MASKED-K4F7_edited.docx",
        "answer for K4F7 (1).docx",
        "MASKED-K4F7 \N{EN DASH} restored.docx",
    ],
)
def test_the_code_counts_as_a_whole_word_in_any_case(file_name: str) -> None:
    assert ids(suggest_cases(BOTH, [NEWER, OLDER], file_name)) == ["K4F7", "M5N6"]


@pytest.mark.parametrize(
    "file_name",
    [
        "MASKED-K4F7X.docx",  # inside a longer word it is not the code
        "MASKED-XK4F7.docx",
        "MASKED-K4F78.docx",
        "MASKEDK4F7.docx",
        "MASKED-K4F7\N{LATIN SMALL LETTER E WITH ACUTE}.docx",
        "MASKED-K4F.docx",
        "contract.docx",
        "",
    ],
)
def test_a_code_inside_a_longer_word_is_not_the_code(file_name: str) -> None:
    assert ids(suggest_cases(BOTH, [OLDER, NEWER], file_name)) == ["M5N6", "K4F7"]  # as without


def test_two_codes_in_one_file_name_tell_nothing() -> None:
    assert ids(suggest_cases(BOTH, [OLDER, NEWER], "MASKED-K4F7-M5N6.docx")) == ["M5N6", "K4F7"]


def test_without_a_file_name_the_ranking_is_the_same_as_before() -> None:
    for cases in ([OLDER, NEWER], [NEWER, OLDER]):
        assert suggest_cases(BOTH, cases, None) == suggest_cases(BOTH, cases)
        assert ids(suggest_cases(BOTH, cases, None)) == ["M5N6", "K4F7"]


def test_the_named_case_comes_first_even_if_it_holds_none_of_the_placeholders() -> None:
    none = made("B2C3", 9, [AMOUNT])
    assert ids(suggest_cases(BOTH, [OLDER, NEWER, none], "MASKED-B2C3.docx")) == [
        "B2C3",
        "M5N6",
        "K4F7",
    ]


def test_the_cases_behind_the_named_one_keep_their_order() -> None:
    third = made("B2C3", 3, [PERSON])  # holds the person, like the older one, and is newer
    ranked = suggest_cases(BOTH, [OLDER, third, NEWER], "MASKED-K4F7.docx")
    assert ids(ranked) == ["K4F7", "M5N6", "B2C3"]
    assert ids(suggest_cases(BOTH, [OLDER, third, NEWER])) == ["M5N6", "B2C3", "K4F7"]


def test_the_cases_are_all_still_there_and_not_changed() -> None:
    cases = [OLDER, NEWER]
    ranked = suggest_cases(BOTH, cases, "MASKED-K4F7.docx")
    assert cases == [OLDER, NEWER] and sorted(ids(ranked)) == ["K4F7", "M5N6"]
    assert suggest_cases(BOTH, [], "MASKED-K4F7.docx") == []


def test_case_in_file_name_gives_the_one_case_the_name_holds() -> None:
    assert case_in_file_name("MASKED-K4F7-2.docx", [OLDER, NEWER]) is OLDER
    assert case_in_file_name("masked-m5n6.docx", [OLDER, NEWER]) is NEWER
    assert case_in_file_name("MASKED-K4F7-M5N6.docx", [OLDER, NEWER]) is None  # two codes
    assert case_in_file_name("MASKED-B2C3.docx", [OLDER, NEWER]) is None  # a case that is not here
    assert case_in_file_name("MASKED-K4F7X.docx", [OLDER, NEWER]) is None  # not a whole word
    assert case_in_file_name("MASKED-K4F7.docx", []) is None


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
