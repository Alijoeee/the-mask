"""Restoring pasted text: what is put back, what waits for the owner, and what is left alone.

The brief's three tests for text come first. The rest pin the controller's decisions for Task 18:
the banner line removed with one blank line after it however its whitespace is written, and the
instruction for the AI removed the same way (decision 3, ruling R76); an unknown placeholder left
and listed once however often it stands in the text; placeholders that touch; each kind of change
an AI makes to a placeholder (spec 8.7) restored only once confirmed; a changed form whose number
is a real key entry's never swapped silently (R44); and an identifier with the shape of a changed
placeholder left as it is (decision 6). Ruling R78: a banner the AI rewrote (italics, a quote, a
byte order mark, escaped brackets, other spacing) is still removed, but a line with more on it
stays. Ruling R79: a bracket on one side of a changed placeholder only is the surrounding text's
and survives the restore.
"""

from __future__ import annotations

import pytest

from tests.fixtures.restore import CASE, NOW
from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.restore.text import restore_text

PERSON = CASE.entries[0]
NBSP = "\N{NO-BREAK SPACE}"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"  # the byte order mark, U+FEFF
FULL_OPEN = "\N{FULLWIDTH LEFT SQUARE BRACKET}"
FULL_CLOSE = "\N{FULLWIDTH RIGHT SQUARE BRACKET}"

# The instruction for the AI with its brackets escaped, as markdown writes them.
ESCAPED_INSTRUCTION = AI_INSTRUCTION.replace("[", r"\[").replace("]", r"\]")

# The changes an AI is known to make to "[PERSON_1]" (spec 8.7), each as the whole token.
ALTERED_FORMS = ["PERSON_1", "[PERSON 1]", "[person_1]", r"\[PERSON_1\]", "**[PERSON_1]**"]


def test_text_exact_and_altered() -> None:
    out, rep = restore_text(
        "Dear [PERSON_1], [COMPANY_1]'s fee is **[AMOUNT_1]**. See [PERSON_9].",
        CASE,
        confirm_altered=False,
    )
    assert out == "Dear John Smith, Acme Supplies Ltd's fee is **[AMOUNT_1]**. See [PERSON_9]."
    assert rep.restored == 2 and len(rep.needs_check) == 1 and rep.unknown == ["[PERSON_9]"]
    assert rep.summary() == "2 placeholders restored, 1 need your check."
    out2, rep2 = restore_text("fee **[AMOUNT_1]** and PERSON_1", CASE, confirm_altered=True)
    assert out2 == "fee EUR 1,250,000 and John Smith" and rep2.altered_restored == 2
    assert rep2.summary() == "2 placeholders restored, 0 need your check."


def test_banner_removed() -> None:
    out, rep = restore_text(BANNER_TEXT + "\n\nHello [PERSON_1]", CASE, True)
    assert out == "Hello John Smith" and rep.banner_removed


def test_template_brackets_untouched() -> None:
    out, rep = restore_text("[Name] signs for [COMPANY_1] on [Date]", CASE, True)
    assert out == "[Name] signs for Acme Supplies Ltd on [Date]" and rep.unknown == []


def test_nothing_to_restore() -> None:
    for text in ("", "No placeholders here, only Company 1 and [Name].\n"):
        out, rep = restore_text(text, CASE, confirm_altered=True)
        assert out == text
        assert (rep.restored, rep.altered_restored, rep.needs_check, rep.unknown) == (0, 0, [], [])
        assert not rep.banner_removed
        assert rep.summary() == "0 placeholders restored, 0 need your check."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Runs of whitespace in the line do not matter, nor do Windows line breaks.
        (f"  {BANNER_TEXT.replace(' ', '   ')} \r\n\r\nHello [PERSON_1]", "Hello John Smith"),
        (BANNER_TEXT.replace(" ", NBSP) + "\n\nHello [PERSON_1]", "Hello John Smith"),
        # One blank line goes with the banner; the lines round it stay as they are.
        (f"Intro\n\n{BANNER_TEXT}\n\n\nHello [PERSON_1]", "Intro\n\n\nHello John Smith"),
        (f"Intro\n{BANNER_TEXT}\nHello [PERSON_1]", "Intro\nHello John Smith"),
        (f"Hello [PERSON_1]\n{BANNER_TEXT}", "Hello John Smith\n"),
        # The instruction for the AI goes the same way, alone or with the banner (R76).
        (f"{AI_INSTRUCTION}\n\nHello [PERSON_1]", "Hello John Smith"),
        (f"{AI_INSTRUCTION}\n{BANNER_TEXT}\n\nHello [PERSON_1]", "Hello John Smith"),
    ],
    ids=[
        "spaces-and-windows-breaks",
        "no-break-spaces",
        "blank-lines-round-it",
        "no-blank-line-after-it",
        "last-line",
        "instruction",
        "instruction-and-banner",
    ],
)
def test_the_banner_line_goes_with_one_blank_line_after_it(text: str, expected: str) -> None:
    out, rep = restore_text(text, CASE, confirm_altered=False)
    assert out == expected and rep.banner_removed
    # The examples on those lines ([COMPANY_1], [PERSON_1], [AMOUNT_2]) were neither restored
    # nor listed: only the one placeholder after them was.
    assert (rep.restored, rep.needs_check, rep.unknown) == (1, [], [])


@pytest.mark.parametrize(
    "line",
    [
        f"*{BANNER_TEXT}*",
        f"> {BANNER_TEXT}",
        f"{BOM}{BANNER_TEXT}",
        BANNER_TEXT.replace("[COMPANY_1]", r"\[COMPANY_1\]"),
        BANNER_TEXT.replace(". ", ".").replace("[COMPANY_1]", "[ Company_1 ]"),
        f"{BOM}> _{ESCAPED_INSTRUCTION}_",
    ],
    ids=["italic", "quoted", "byte-order-mark", "escaped-brackets", "spacing", "instruction"],
)
def test_a_banner_the_ai_rewrote_is_still_removed(line: str) -> None:
    # R78: the line is compared by its letters and digits alone, case folded.
    out, rep = restore_text(f"{line}\n\nHello [PERSON_1]", CASE, confirm_altered=False)
    assert out == "Hello John Smith" and rep.banner_removed
    assert (rep.restored, rep.needs_check, rep.unknown) == (1, [], [])


def test_a_line_with_more_than_the_banner_on_it_stays() -> None:
    # R78: only a line that is the banner and nothing else is The MASK's. Here the AI put a word
    # of its own on it, so the line stays and its [COMPANY_1] is restored like any other.
    text = f"Note: {BANNER_TEXT}\n\nHello [PERSON_1]"
    out, rep = restore_text(text, CASE, confirm_altered=False)
    banner = BANNER_TEXT.replace("[COMPANY_1]", "Acme Supplies Ltd")
    assert out == f"Note: {banner}\n\nHello John Smith"
    assert not rep.banner_removed and rep.restored == 2


def test_the_instruction_for_the_ai_is_not_restored() -> None:
    # R76: restoring its examples would write a real name into the instruction and list an
    # [AMOUNT_2] the key never had.
    out, rep = restore_text(f"{AI_INSTRUCTION}\n\nThe fee is [AMOUNT_1].", CASE, True)
    assert out == "The fee is EUR 1,250,000."
    assert rep.banner_removed and (rep.restored, rep.unknown) == (1, [])


def test_an_unknown_placeholder_is_left_and_listed_once() -> None:
    text = "[PERSON_9] wrote to [COMPANY_7]; [PERSON_9] signed for [PERSON_1]."
    out, rep = restore_text(text, CASE, confirm_altered=True)
    assert out == "[PERSON_9] wrote to [COMPANY_7]; [PERSON_9] signed for John Smith."
    assert rep.unknown == ["[PERSON_9]", "[COMPANY_7]"]
    assert (rep.restored, rep.needs_check) == (1, [])


@pytest.mark.parametrize(
    ("text", "confirm_altered", "expected"),
    [
        ("[PERSON_1][COMPANY_1]", False, "John SmithAcme Supplies Ltd"),
        ("[AMOUNT_1][PERSON_1]**[COMPANY_1]**.", True, "EUR 1,250,000John SmithAcme Supplies Ltd."),
        ("[COMPANY_1][PERSON_1]**[AMOUNT_1]**", False, "Acme Supplies LtdJohn Smith**[AMOUNT_1]**"),
    ],
)
def test_placeholders_that_touch_are_each_replaced(
    text: str, confirm_altered: bool, expected: str
) -> None:
    out, _ = restore_text(text, CASE, confirm_altered)
    assert out == expected


@pytest.mark.parametrize("raw", ALTERED_FORMS)
def test_a_changed_placeholder_is_listed_until_confirmed(raw: str) -> None:
    text = f"Signed by {raw} today."
    out, rep = restore_text(text, CASE, confirm_altered=False)
    assert out == text
    (item,) = rep.needs_check
    assert (item.match.raw, item.status, item.entry) == (raw, "altered", PERSON)
    assert (rep.restored, rep.altered_restored, rep.unknown) == (0, 0, [])
    assert rep.summary() == "0 placeholders restored, 1 need your check."


@pytest.mark.parametrize("raw", ALTERED_FORMS)
def test_a_changed_placeholder_is_restored_once_confirmed(raw: str) -> None:
    out, rep = restore_text(f"Signed by {raw} today.", CASE, confirm_altered=True)
    assert out == "Signed by John Smith today."
    assert (rep.restored, rep.altered_restored, rep.needs_check) == (1, 1, [])


@pytest.mark.parametrize(
    ("text", "raw", "expected"),
    [
        ("For [Buyer, PERSON_1] now.", "PERSON_1]", "For [Buyer, John Smith] now."),
        ("[PERSON_1, the Buyer] signs.", "[PERSON_1", "[John Smith, the Buyer] signs."),
        # The bracket keeps its escape, its width and the spaces next to it.
        (r"(see \[PERSON_1)", r"\[PERSON_1", r"(see \[John Smith)"),
        ("[Buyer: PERSON_1 ]", "PERSON_1 ]", "[Buyer: John Smith ]"),
        (
            f"{FULL_OPEN}PERSON_1, Buyer{FULL_CLOSE}",
            f"{FULL_OPEN}PERSON_1",
            f"{FULL_OPEN}John Smith, Buyer{FULL_CLOSE}",
        ),
        # Markers round a placeholder and a bracket of the text are the text's: they stay too.
        ("[Buyer, **PERSON_1]**", "**PERSON_1]**", "[Buyer, **John Smith]**"),
    ],
    ids=["closing", "opening", "escaped", "spaced", "full-width", "bold"],
)
def test_a_bracket_on_one_side_only_belongs_to_the_text_round_it(
    text: str, raw: str, expected: str
) -> None:
    # R79: "[Buyer, PERSON_1]" holds the changed placeholder "PERSON_1]"; its "]" closes the
    # text's own bracket, so a confirmed restore keeps it and replaces the name and number only.
    out, rep = restore_text(text, CASE, confirm_altered=False)
    assert out == text and [item.match.raw for item in rep.needs_check] == [raw]
    out, rep = restore_text(text, CASE, confirm_altered=True)
    assert out == expected and (rep.restored, rep.altered_restored) == (1, 1)


def test_a_changed_form_that_shares_a_real_number_is_never_swapped_silently() -> None:
    # R44: a source may hold a token such as "company_2" (here a field name) while the export
    # gave a real company the number 2. Only the exact placeholder is put back unasked.
    company_2 = KeyEntry("[COMPANY_2]", PlaceholderType.COMPANY, "Brightwater Logistics BV", [])
    case = Case("R44X", NOW, [], [], [company_2])
    out, rep = restore_text("Map the field company_2 to [COMPANY_2].", case, confirm_altered=False)
    assert out == "Map the field company_2 to Brightwater Logistics BV."
    assert [(item.match.raw, item.entry) for item in rep.needs_check] == [("company_2", company_2)]
    assert rep.summary() == "1 placeholders restored, 1 need your check."


def test_an_identifier_shaped_like_a_placeholder_is_left_as_it_is() -> None:
    # "ID-4711" reads as a changed [ID_4711]; the key has no such entry, so even a confirmed
    # restore leaves it and lists it as unknown.
    out, rep = restore_text("Order ID-4711 is for [PERSON_1].", CASE, confirm_altered=True)
    assert out == "Order ID-4711 is for John Smith."
    assert rep.unknown == ["ID-4711"] and (rep.restored, rep.needs_check) == (1, [])
