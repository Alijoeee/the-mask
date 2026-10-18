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
