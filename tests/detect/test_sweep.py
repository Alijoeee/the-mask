"""The sweep: every further occurrence of a group's variants joins the group."""

import uuid

from themask.detect.sweep import sweep
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
    txt = "[COMPANY_1] and company_2 are not the Company."
    g = G(C, ["Company"])
    sweep(txt, [g])
    assert [(f.text, f.start) for f in g.findings] == [("Company", txt.rindex("Company"))]


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
