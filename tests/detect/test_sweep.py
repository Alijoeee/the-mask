"""The sweep: every further occurrence of a group's variants joins the group."""

import uuid

import pytest

from themask.detect.sweep import is_bare_name, stands_as_a_name, sweep
from themask.model import Finding, Group, PlaceholderType

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY


def F(t, needle, txt, last=False, score=0.9):
    s = txt.rindex(needle) if last else txt.index(needle)
    return Finding(t, s, s + len(needle), needle, score, "model")


def G(t, variants, *findings):
    return Group(uuid.uuid4().hex, t, max(variants, key=len), set(variants), list(findings), "")


def texts(group):
    return [f.text for f in group.findings]


def test_sweep_finds_every_other_occurrence():
    txt = "Acme Supplies Ltd signs. ACME  SUPPLIES LTD pays.\tacme supplies\N{NO-BREAK SPACE}ltd"
    g = G(C, ["Acme Supplies Ltd"], F(C, "Acme Supplies Ltd", txt))
    sweep(txt, [g])
    assert texts(g) == ["Acme Supplies Ltd", "ACME  SUPPLIES LTD", "acme supplies\xa0ltd"]
    assert all(f.source == "sweep" and f.score == 1.0 and f.type == C for f in g.findings[1:])
    assert all(txt[f.start : f.end] == f.text for f in g.findings)


def test_sweep_never_overlaps_a_finding_of_any_group():
    txt = "John Carter signs for Carter Logistics Ltd; Carter attends."
    company = G(C, ["Carter Logistics Ltd"], F(C, "Carter Logistics Ltd", txt))
    person = G(P, ["John Carter", "Carter"], F(P, "John Carter", txt))
    sweep(txt, [person, company])
    assert texts(company) == ["Carter Logistics Ltd"]
    assert [(f.text, f.start) for f in person.findings] == [
        ("John Carter", 0),
        ("Carter", txt.rindex("Carter")),
    ]


def test_longest_variant_goes_first_across_groups():
    txt = "Acme and Acme Supplies sign."
    short = G(C, ["Acme"])
    long = G(C, ["Acme Supplies"])
    sweep(txt, [short, long])
    assert texts(long) == ["Acme Supplies"] and [f.start for f in short.findings] == [0]


def test_sweep_never_touches_an_existing_placeholder():
    # Ruling R44: only the exact form is a placeholder in a source; "company_2" is text.
    txt = "[COMPANY_1] and company_2 are not the Company."
    g = G(C, ["Company"])
    sweep(txt, [g])
    assert [(f.text, f.start) for f in g.findings] == [
        ("company", txt.index("company_2")),
        ("Company", txt.rindex("Company")),
    ]


def test_sweep_stays_within_one_line():
    txt = "Acme Supplies\nLtd, then Acme Supplies Ltd.\n\f\nAcme Supplies Ltd"
    g = G(C, ["Acme Supplies Ltd"])
    sweep(txt, [g])
    assert [f.start for f in g.findings] == [txt.index("Acme Supplies Ltd"), txt.rindex("Acme")]
    assert all("\n" not in f.text for f in g.findings)


def test_a_rejected_match_does_not_hide_the_next_one():
    # "Acme\nAcme" is rejected (it runs over a line break); "Acme Acme" starts inside it.
    txt = "Acme\nAcme Acme"
    g = G(C, ["Acme Acme"])
    sweep(txt, [g])
    assert [(f.start, f.end) for f in g.findings] == [(5, 14)]


def test_sweep_keeps_to_whole_words():
    txt = "Smith, Smithson and Goldsmith"
    g = G(P, ["Smith"])
    sweep(txt, [g])
    assert texts(g) == ["Smith"]


def test_blank_and_tiny_variants_are_not_searched():
    txt = "A x 5 - Acme"
    g = G(C, ["", "   ", "x", "5", "-", "Acme"])
    sweep(txt, [g])
    assert texts(g) == ["Acme"]


def test_sweep_twice_adds_nothing_and_keeps_the_order():
    txt = "Acme signs. Acme Supplies Ltd pays. Acme invoices."
    g = G(C, ["Acme Supplies Ltd", "Acme"], F(C, "Acme Supplies Ltd", txt))
    sweep(txt, [g])
    first = list(g.findings)
    sweep(txt, [g])
    assert g.findings == first
    assert first[0].text == "Acme Supplies Ltd"  # what was there stays where it was (index 0)
    assert sorted(f.start for f in first[1:]) == [0, txt.rindex("Acme")]


# --- A longer occurrence takes over a shorter find it holds (ruling R35) -----------------------


def L(t, needle, txt, last=False):
    """A find of the owner's always-hide list."""
    s = txt.rindex(needle) if last else txt.index(needle)
    return Finding(t, s, s + len(needle), needle, 1.0, "list")


def test_a_longer_occurrence_takes_over_a_shorter_find():
    txt = "Project Falcon starts now; Project Falcon ends later."
    whole = G(C, ["Project Falcon"], F(C, "Project Falcon", txt, last=True, score=0.6))
    part = G(C, ["Falcon"], F(C, "Falcon", txt, score=0.6))
    sweep(txt, [whole, part])
    assert sorted(f.start for f in whole.findings) == [0, txt.rindex("Project Falcon")]
    assert part.findings == []  # left with nothing: the caller drops the group


def test_a_group_takes_over_its_own_shorter_find():
    txt = "Acme Supplies Ltd signs."
    g = G(C, ["Acme Supplies Ltd", "Acme"], F(C, "Acme", txt))
    sweep(txt, [g])
    assert texts(g) == ["Acme Supplies Ltd"]


def test_every_find_inside_is_taken_over_at_once():
    txt = "Carter Logistics Ltd signs; Carter Logistics Ltd pays."
    company = G(C, ["Carter Logistics Ltd"], F(C, "Carter Logistics Ltd", txt, last=True))
    person = G(P, ["Carter"], F(P, "Carter", txt))
    rest = G(C, ["Logistics Ltd"], F(C, "Logistics Ltd", txt))
    sweep(txt, [company, person, rest])
    assert [f.start for f in sorted(company.findings, key=lambda f: f.start)] == [0, 28]
    assert person.findings == [] and rest.findings == []


def test_the_owners_list_is_never_taken_over():
    txt = "Project Falcon starts now; Project Falcon ends later."
    whole = G(C, ["Project Falcon"], F(C, "Project Falcon", txt, last=True, score=0.6))
    listed = G(PlaceholderType.CUSTOM, ["Falcon"], L(PlaceholderType.CUSTOM, "Falcon", txt))
    sweep(txt, [whole, listed])
    assert texts(whole) == ["Project Falcon"] and whole.findings[0].start > 0
    assert texts(listed) == ["Falcon"] and listed.findings[0].source == "list"


def test_a_fixed_group_is_never_taken_over():
    txt = "Project Falcon starts now; Project Falcon ends later."
    whole = G(C, ["Project Falcon"], F(C, "Project Falcon", txt, last=True, score=0.6))
    seeded = G(PlaceholderType.CUSTOM, ["Falcon"], F(PlaceholderType.CUSTOM, "Falcon", txt))
    sweep(txt, [whole, seeded], fixed=[seeded])
    assert texts(whole) == ["Project Falcon"] and texts(seeded) == ["Falcon"]


def test_what_the_owner_switched_off_is_never_taken_over():
    txt = "Project Falcon starts; Project Falcon ends; Project Falcon again."
    first = txt.index("Falcon")
    second = txt.index("Falcon", first + 1)
    whole = G(C, ["Project Falcon"], F(C, "Project Falcon", txt, last=True))
    occurrence_off = G(C, ["Falcon"], Finding(C, first, first + 6, "Falcon", 0.6, "model"))
    occurrence_off.disabled = {0}
    group_off = G(P, ["Falcon"], Finding(P, second, second + 6, "Falcon", 0.9, "model"))
    group_off.enabled = False
    sweep(txt, [whole, occurrence_off, group_off])
    assert texts(whole) == ["Project Falcon"] and whole.findings[0].start == txt.rindex("Project")
    assert texts(occurrence_off) == ["Falcon"] and occurrence_off.disabled == {0}
    assert texts(group_off) == ["Falcon"]


def test_equal_or_partial_overlaps_keep_the_find_in_place():
    txt = "ACME LTD signs. Acme Ltd pays. Project Falcon starts."
    same = G(C, ["Acme Ltd"], F(C, "Acme Ltd", txt))
    other = G(C, ["ACME LTD"], F(C, "ACME LTD", txt))
    partial = G(C, ["Falcon starts"], F(C, "Falcon starts", txt))
    whole = G(C, ["Project Falcon"])
    sweep(txt, [same, other, partial, whole])
    assert texts(other) == ["ACME LTD"] and texts(same) == ["Acme Ltd"]
    assert texts(partial) == ["Falcon starts"] and whole.findings == []


def test_taking_over_keeps_the_switched_off_indexes_right():
    txt = "Falcon one. Project Falcon two. Falcon three."
    whole = G(C, ["Project Falcon"])
    part = G(C, ["Falcon"])
    part.findings = [
        Finding(C, 0, 6, "Falcon", 0.6, "model"),
        Finding(C, 20, 26, "Falcon", 0.6, "model"),
        Finding(C, 32, 38, "Falcon", 0.6, "model"),
    ]
    part.disabled = {2}
    sweep(txt, [whole, part])
    assert [f.start for f in part.findings] == [0, 32] and part.disabled == {1}
    assert [f.start for f in whole.findings] == [12]


def test_a_group_switched_off_neither_sweeps_nor_takes_over():
    # Raised minor M3
    txt = "Project Falcon starts; Project Falcon ends."
    off = G(C, ["Project Falcon"])
    off.enabled = False
    part = G(C, ["Falcon"], F(C, "Falcon", txt))
    sweep(txt, [off, part])
    assert off.findings == []
    assert [f.start for f in part.findings] == [txt.index("Falcon"), txt.rindex("Falcon")]


def test_a_word_is_whole_in_any_script():
    # Raised minor M5: "Gül" is not found inside "Gülşen", nor "Smith" inside "Smithé".
    txt = "Gülşen Gül signs; Smithé and Smith attend."
    gul, smith = G(C, ["Gül"]), G(C, ["Smith"])  # companies: no name test, only word edges
    sweep(txt, [gul, smith])
    assert [f.start for f in gul.findings] == [txt.index("Gül ")]
    assert [f.start for f in smith.findings] == [txt.rindex("Smith")]


# --- Ruling R50: a person's bare name is swept only where it stands as a name -----------------


def test_a_persons_bare_name_is_swept_only_as_a_name():
    txt = "Mill shall attend. The Mill is old; a Mill too; the mill-race; MILL signs."
    person = G(P, ["Laura Mill", "Mill"])
    sweep(txt, [person])
    assert [f.start for f in person.findings] == [0, txt.index("MILL")]


def test_other_variants_are_swept_wherever_they_stand():
    txt = "Mill shall attend. The Mill is old."
    company = G(C, ["Mill"])
    sweep(txt, [company])
    assert len(company.findings) == 2


def test_what_is_a_bare_name():
    assert is_bare_name(P, "Smith") and is_bare_name(P, "van der Berg")
    assert not is_bare_name(P, "Mr Smith") and not is_bare_name(P, "John Smith")
    assert not is_bare_name(C, "Acme")


def test_what_stands_as_a_name():
    txt = "Smith signs; the Smith file; such Smith; an Ali; smith; Van der Berg; van der Berg."
    for needle, expected in [
        ("Smith signs", True),
        ("Smith file", False),
        ("Smith;", False),
        ("Ali", False),
        ("smith", False),
        ("Van der Berg", True),
        ("van der Berg.", True),
    ]:
        start = txt.index(needle)
        word = needle.rstrip(";. ").replace(" signs", "").replace(" file", "")
        assert stands_as_a_name(txt, start, start + len(word)) is expected, needle


# --- Ruling R54: the name stands alone ----------------------------------------------------------


@pytest.mark.parametrize(
    "text,word,expected",
    [
        ("Delivery is due on the next Business Day after the order.", "Day", False),
        ("Day shall attend.", "Day", True),
        ("registered at Companies House. House shall attend.", "House", False),
        ("2. GRANT OF LICENCE", "GRANT", False),
        ("Long Stop Date: 30 June 2026.", "Long", False),
        ("Disputes go to the High Court of Justice in London.", "Court", False),
        ("Use of the site follows our Terms of Use.", "Terms", False),
        ("The Supplier shall provide a Performance Bond.", "Bond", False),
        ("This Agreement is dated 1 May 2026.", "May", False),
        ("Payment is due by May 30, 2026.", "May", False),
        ("May shall attend.", "May", True),
        ("Signed on 1 June 2026. May shall attend.", "May", True),  # a full stop parts them
        ("Price, Director of Sales, shall attend.", "Price", True),  # the comma separates
        ("as agreed, Mr Price shall attend.", "Price", True),  # an honorific is the name's
    ],
)
def test_a_name_stands_alone(text, word, expected):
    start = text.index(word)
    assert stands_as_a_name(text, start, start + len(word)) is expected


def test_a_name_is_not_part_of_a_term_of_the_callers_lists():
    text = "Unload at Gate area only. Gate shall attend."
    start = text.index("Gate")
    assert stands_as_a_name(text, start, start + 4)  # the defaults know no "Gate area"
    terms = {"gate area"}
    assert not stands_as_a_name(text, start, start + 4, lambda phrase: phrase.casefold() in terms)


# --- Ruling R56: what the engine saw, separators, phrases over a connective --------------------


@pytest.mark.parametrize(
    "text,word,expected",
    [
        ("Dear Price,", "Price", True),  # a salutation separates
        ("To Smith, for signature", "Smith", True),
        ("Smith Director", "Smith", True),  # a job title after the name separates
        ("Approved by Smith Finance Director.", "Smith", True),
        ("Smith Holdings shall deliver.", "Smith", False),
        ("Name:\tSmith\tTitle:\tDirector", "Smith", True),  # a tab separates
        ("Name: Smith Title: Director", "Smith", True),  # so does a label's colon
        ("SMITH", "SMITH", True),  # a line of the name alone is no heading
        ("Signed: ____ SMITH", "SMITH", True),
        ("2. GRANT OF LICENCE", "GRANT", False),
        ("2. Grant of Rights", "Grant", False),  # a phrase over a lowercase connective
        ("Power of Attorney dated 1 March 2026.", "Power", False),
        ("Field of Use: Europe.", "Field", False),
        ("Rights of Grant apply.", "Grant", False),
        ("Price and Smith sign.", "Price", False),  # unless the word beyond is a name found
    ],
)
def test_a_swept_name_stands_alone(text, word, expected):
    start = text.index(word)
    assert stands_as_a_name(text, start, start + len(word)) is expected


def test_a_name_found_beyond_a_connective_is_no_phrase():
    text = "Price and Smith sign."
    names = {"price", "smith"}
    assert stands_as_a_name(text, 0, 5, is_name=lambda word: word.casefold() in names)


def test_where_the_engine_saw_a_name_only_a_determiner_counts():
    text = "Smith Holdings shall deliver; the Smith file; 2. GRANT OF LICENCE; 1 May 2026"
    for word, after_the, expected in [("Smith", False, True), ("Smith", True, False)]:
        start = text.index("the Smith") + 4 if after_the else text.index(word)
        assert stands_as_a_name(text, start, start + len(word), found_by_engine=True) is expected
    for word in ("GRANT", "May"):
        start = text.index(word)
        assert stands_as_a_name(text, start, start + len(word), found_by_engine=True)
