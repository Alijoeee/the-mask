"""The analysis pipeline: from the engine's findings and the owner's lists to numbered groups.

The brief's tests and the review-focus cases use the real engine (the session's ``engine``
fixture). ``FakeEngine`` reports set values wherever they stand, for the tests that pin how the
pipeline treats what an engine reports.
"""

import itertools
import json

import pytest

from themask.detect.lists import CaseLists
from themask.detect.pipeline import CombinedText, analyze
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.model import Finding, KeyEntry, MaskPlan, PlaceholderType, Replacement
from themask.textnorm import normalize

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY
CUSTOM = PlaceholderType.CUSTOM


class FakeEngine:
    """An engine that finds each of its needles wherever it stands, and notes what it was given."""

    def __init__(self, *needles):
        self.needles = needles  # (type, text, score, source)
        self.texts = []

    def analyze(self, text):
        self.texts.append(text)
        found = []
        for kind, needle, score, source in self.needles:
            start = text.find(needle)
            while start >= 0:
                found.append(Finding(kind, start, start + len(needle), needle, score, source))
                start = text.find(needle, start + 1)
        return sorted(found, key=lambda f: (f.start, f.end))


def one(text):
    return CombinedText.join([("x", text)])


def all_findings(a):
    return [f for g in a.groups for f in g.findings]


def assert_one_replacement_each(a):
    """Every finding is the text it says it is, within one line, and no two overlap."""
    for f in all_findings(a):
        assert a.text[f.start : f.end] == f.text and f.text.strip() == f.text
        assert "\n" not in f.text and "\f" not in f.text
    MaskPlan([Replacement(f.start, f.end, g.placeholder) for g in a.groups for f in g.findings])


# --- The brief's tests ---------------------------------------------------------------------------


def test_overlap_longest_wins(engine, lists):
    t = "Write to legal@northwind.example or https://northwind.example/contact?mail=legal@northwind.example"
    a = analyze(CombinedText.join([("x", t)]), engine, lists)
    spans = sorted((f.start, f.end) for g in a.groups for f in g.findings)
    assert all(b[0] >= a_[1] for a_, b in itertools.pairwise(spans))


def test_never_hide_terms_stay(engine, lists):
    t = "The Supplier shall deliver the Goods to the Buyer in March."
    a = analyze(CombinedText.join([("x", t)]), engine, lists)
    assert a.groups == []


def test_always_hide_list(engine, lists):
    lists.add_always("Project Falcon")
    t = "Project Falcon starts in May; PROJECT FALCON ends in June."
    a = analyze(CombinedText.join([("x", t)]), engine, lists)
    (g,) = a.groups
    assert (
        g.type == PlaceholderType.CUSTOM and len(g.findings) == 2 and g.placeholder == "[CUSTOM_1]"
    )


def test_numbering_and_sweep(engine, lists):
    t = 'Acme Supplies Ltd (the "Buyer")… Acme shall pay. Northwind Trading B.V. … Acme Supplies Ltd signs.'
    a = analyze(CombinedText.join([("x", t)]), engine, lists)
    by = {g.canonical: g for g in a.groups}
    assert by["Acme Supplies Ltd"].placeholder == "[COMPANY_1]"
    assert by["Northwind Trading B.V."].placeholder == "[COMPANY_2]"
    assert len(by["Acme Supplies Ltd"].findings) == 3


def test_existing_placeholders_warning(engine, lists):
    a = analyze(
        CombinedText.join([("x", "[PERSON_1] met John Smith. [Name] signs.")]), engine, lists
    )
    (g,) = [g for g in a.groups if g.type == PlaceholderType.PERSON]
    assert g.placeholder == "[PERSON_2]"
    assert any("already contains placeholders" in w for w in a.warnings)


def test_combined_text_locate():
    c = CombinedText.join([("a.docx", "hello"), ("b.docx", "world")])
    assert c.locate(0) == ("a.docx", 0) and c.locate(len("hello\n\f\n") + 2) == ("b.docx", 2)


def test_seed_entries_reuse_placeholders(engine, lists):
    seed = [
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme"]),
        KeyEntry("[COMPANY_2]", PlaceholderType.COMPANY, "Old Partner GmbH", []),
    ]
    t = "Acme shall deliver to Baltic Fasteners GmbH."
    a = analyze(CombinedText.join([("annex", t)]), engine, lists, seed_entries=seed)
    by = {g.canonical: g for g in a.groups}
    assert by["Acme Supplies Ltd"].placeholder == "[COMPANY_1]"
    assert by["Baltic Fasteners GmbH"].placeholder == "[COMPANY_3]"


# --- Several files in one case -------------------------------------------------------------------


def test_combined_text_join_and_parts():
    c = CombinedText.join([("a.docx", "hello"), ("b.docx", ""), ("c.docx", "world")], "|")
    assert c.text == "hello||world"
    assert c.parts == [("a.docx", 0, 5), ("b.docx", 6, 6), ("c.docx", 7, 12)]
    assert c.locate(5) == ("a.docx", 5)  # the end of a part, where a finding may end
    assert c.locate(12) == ("c.docx", 5)


@pytest.mark.parametrize("offset", [-1, 6, 7, 14, 100])
def test_locate_outside_any_part(offset):
    c = CombinedText.join([("a.docx", "hello"), ("b.docx", "world")])  # parts 0-5 and 8-13
    with pytest.raises(ValueError):
        c.locate(offset)


def test_the_engine_reads_each_file_on_its_own(lists):
    c = CombinedText.join(
        [("a.docx", "Acme Supplies Ltd signs."), ("b.docx", "Acme Supplies Ltd pays.")]
    )
    fake = FakeEngine((C, "Acme Supplies Ltd", 0.95, "rule"))
    a = analyze(c, fake, lists)
    assert fake.texts == ["Acme Supplies Ltd signs.", "Acme Supplies Ltd pays."]
    (g,) = a.groups
    assert [c.locate(f.start) for f in g.findings] == [("a.docx", 0), ("b.docx", 0)]
    assert_one_replacement_each(a)


def test_no_finding_runs_from_one_line_into_the_next(lists):
    fake = FakeEngine((C, "Acme\nSupplies Ltd", 0.95, "rule"), (P, "Jane\n\nDoe", 0.85, "model"))
    a = analyze(one("To Acme\nSupplies Ltd from Jane\n\nDoe."), fake, lists)
    assert sorted(f.text for f in all_findings(a)) == ["Acme", "Doe", "Jane", "Supplies Ltd"]
    assert_one_replacement_each(a)


def test_edges_that_belong_to_the_sentence_are_trimmed(lists):
    fake = FakeEngine((C, '"Northwind Trading B.V. …', 0.85, "model"))
    a = analyze(one('See "Northwind Trading B.V. … here.'), fake, lists)
    (g,) = a.groups
    assert (
        g.canonical == "Northwind Trading B.V." and g.findings[0].text == "Northwind Trading B.V."
    )


# --- Defined terms, never-hide and names ------------------------------------------------------


def test_defined_terms_are_collected_into_the_case_lists(engine, lists):
    case = CaseLists([], [], {"Earlier Term"})
    t = 'Acme Supplies Ltd (the "Buyer") orders the Goods (the "Products").'
    a = analyze(one(t), engine, lists, case)
    assert case.defined_terms == {"Earlier Term", "Buyer", "Products"}
    assert {g.canonical for g in a.groups} == {"Acme Supplies Ltd"}


def test_a_term_defined_in_the_document_stays_visible(engine, lists):
    t = 'The Goods go to the Marlow Depot (the "Depot"). The Depot opens at nine. Acme Ltd pays.'
    a = analyze(one(t), engine, lists)
    assert not any(normalize(f.text) == "depot" for f in all_findings(a))
    assert any(f.text == "Acme Ltd" for f in all_findings(a))


@pytest.mark.parametrize(
    "t",
    [
        '"Acme" means Acme Supplies Ltd.\nAcme shall deliver the Goods. ACME will invoice.',
        'Acme Supplies Ltd ("Acme") and Northwind Trading B.V. (the "Supplier"). Acme shall pay.',
    ],
)
def test_names_beat_terms(engine, lists, t):
    a = analyze(one(t), engine, lists)
    (acme,) = [g for g in a.groups if g.canonical == "Acme Supplies Ltd"]
    hidden = sorted(f.start for f in acme.findings)
    every_acme = [i for i in range(len(t)) if t[i : i + 4].casefold() == "acme"]
    assert hidden == every_acme
    assert not any(normalize(f.text) == "supplier" for f in all_findings(a))


def test_the_owners_never_hide_list_beats_names(engine, lists):
    lists.add_never("Acme")
    t = '"Acme" means Acme Supplies Ltd.\nAcme shall deliver the Goods. ACME will invoice.'
    a = analyze(one(t), engine, lists)
    assert not any(normalize(f.text) == "acme" for f in all_findings(a))
    assert "Acme" not in {v for g in a.groups for v in g.variants}  # the leak check skips it too
    assert any(f.text == "Acme Supplies Ltd" for f in all_findings(a))


def test_a_name_longer_than_a_term_is_hidden(engine, lists):
    a = analyze(one("Supplier Logistics Ltd is the Supplier."), engine, lists)
    assert [f.text for f in all_findings(a)] == ["Supplier Logistics Ltd"]


def test_a_variant_that_is_a_term_is_not_swept(lists):
    fake = FakeEngine((C, "Total Logistics Ltd", 0.95, "rule"))
    a = analyze(one("Total Logistics Ltd delivers. The Total is due."), fake, lists)
    (g,) = a.groups
    assert [f.text for f in g.findings] == ["Total Logistics Ltd"]
    assert "Total" not in g.variants and "Total Logistics" in g.variants


def test_what_the_model_finds_in_the_contracts_own_words_stays(lists):
    fake = FakeEngine(
        (C, "GOVERNING LAW", 0.6, "model"),
        (C, "Time", 0.6, "model"),
        (C, "Quality Foods Ltd", 0.95, "rule"),
    )
    t = "12. GOVERNING LAW\nTime is of the essence. Quality Foods Ltd keeps to the quality standards."
    a = analyze(one(t), fake, lists)
    (g,) = a.groups
    assert [f.text for f in g.findings] == ["Quality Foods Ltd"]  # "quality" is not swept
    assert "Quality" not in g.variants


def test_a_name_of_the_contracts_own_words_is_still_swept(lists):
    fake = FakeEngine((C, "General Services Ltd", 0.95, "rule"))
    a = analyze(one("General Services Ltd signs. General Services pays."), fake, lists)
    (g,) = a.groups
    assert [f.text for f in g.findings] == ["General Services Ltd", "General Services"]


def test_a_date_the_model_took_for_a_person_stays(lists):
    fake = FakeEngine((P, "June 2026", 0.85, "model"), (P, "Jane Doe", 0.85, "model"))
    a = analyze(one("Signed on 25 June 2026 by Jane Doe."), fake, lists)
    assert [g.canonical for g in a.groups] == ["Jane Doe"]


# --- The owner's always-hide lists ---------------------------------------------------------------


def test_always_hide_entries_with_a_type_and_from_the_case(lists):
    lists.add_always("COMPANY:Falcon Freight")
    case = CaseLists(["Blue Harbour"], [], set())
    t = "Falcon Freight ships to Blue Harbour; blue  harbour pays."
    a = analyze(one(t), FakeEngine(), lists, case)
    by = {g.canonical: g for g in a.groups}
    assert by["Falcon Freight"].type == C and by["Falcon Freight"].placeholder == "[COMPANY_1]"
    assert by["Blue Harbour"].type == CUSTOM and len(by["Blue Harbour"].findings) == 2


def test_always_hide_beats_a_defined_term(lists):
    lists.add_always("Falcon")
    a = analyze(one('"Falcon" means the new warehouse. Falcon opens in May.'), FakeEngine(), lists)
    (g,) = a.groups
    assert len(g.findings) == 2


def test_a_never_hide_term_beats_always_hide(lists):
    lists.add_always("Schedule")  # the brief: never-hide terms are dropped, whatever found them
    a = analyze(one("See the Schedule."), FakeEngine(), lists)
    assert a.groups == []


# --- Review focus: shared surnames, overlaps, existing placeholders --------------------------


def test_two_people_sharing_a_surname(engine, lists):
    t = "John Smith and Jane Smith sign for the Buyer. Mr Smith shall attend every meeting."
    a = analyze(one(t), engine, lists)
    people = {g.canonical: g for g in a.groups if g.type == P}
    assert set(people) == {"John Smith", "Jane Smith", "Mr Smith"}
    assert people["Mr Smith"].needs_check and len(people["Mr Smith"].findings) == 1
    assert [people[n].placeholder for n in ("John Smith", "Jane Smith", "Mr Smith")] == [
        "[PERSON_1]",
        "[PERSON_2]",
        "[PERSON_3]",
    ]


def test_overlapping_finds_become_one_replacement(engine, lists):
    t = (
        "Account: NL91 ABNA 0417 1643 00\n"
        "John Carter signs for Carter Logistics Ltd. Carter Logistics Ltd shall pay.\n"
        "Write to legal@carter.example or https://carter.example/contact?mail=legal@carter.example"
    )
    a = analyze(one(t), engine, lists)
    assert_one_replacement_each(a)
    texts = [f.text for f in all_findings(a)]
    assert "NL91 ABNA 0417 1643 00" in texts
    assert texts.count("Carter Logistics Ltd") == 2 and "John Carter" in texts
    assert "https://carter.example/contact?mail=legal@carter.example" in texts


def test_altered_placeholders_count_too(engine, lists):
    t = "This document refers to [COMPANY_1] and company_2 and Northwind Trading B.V."
    a = analyze(one(t), engine, lists)
    (g,) = a.groups
    assert g.placeholder == "[COMPANY_3]"
    assert a.warnings == [
        (
            "The document already contains placeholders such as [COMPANY_1];"
            " numbering continues after them."
        )
    ]
    assert all(f.start >= t.index("Northwind") for f in g.findings)


def test_nothing_is_found_inside_an_existing_placeholder(lists):
    lists.add_always("PERSON")
    fake = FakeEngine((P, "PERSON_1", 0.85, "model"))
    a = analyze(one("[PERSON_1] signs; the PERSON named above."), fake, lists)
    (g,) = a.groups
    assert [f.text for f in g.findings] == ["PERSON"] and g.findings[0].start > 10


def test_no_warning_without_placeholders(lists):
    a = analyze(one("Jane Doe signs."), FakeEngine((P, "Jane Doe", 0.85, "model")), lists)
    assert a.warnings == [] and a.groups[0].placeholder == "[PERSON_1]"


# --- Numbering and order -------------------------------------------------------------------------


def test_numbering_per_type_in_order_of_first_appearance(lists):
    t = "Bob Ray met Acme Supplies Ltd. Jane Doe met Northwind B.V. and Bob Ray."
    fake = FakeEngine(
        (P, "Bob Ray", 0.85, "model"),
        (P, "Jane Doe", 0.85, "model"),
        (C, "Acme Supplies Ltd", 0.95, "rule"),
        (C, "Northwind B.V.", 0.95, "rule"),
    )
    a = analyze(one(t), fake, lists)
    assert [(g.canonical, g.placeholder) for g in a.groups] == [
        ("Bob Ray", "[PERSON_1]"),
        ("Acme Supplies Ltd", "[COMPANY_1]"),
        ("Jane Doe", "[PERSON_2]"),
        ("Northwind B.V.", "[COMPANY_2]"),
    ]
    assert all(g.findings == sorted(g.findings, key=lambda f: f.start) for g in a.groups)


def test_a_swept_occurrence_counts_as_the_first_appearance(lists):
    t = "Acme pays Jane Doe. Northwind B.V. and Acme Supplies Ltd sign."
    fake = FakeEngine((C, "Acme Supplies Ltd", 0.95, "rule"), (C, "Northwind B.V.", 0.95, "rule"))
    a = analyze(one(t), fake, lists)
    by = {g.canonical: g.placeholder for g in a.groups}
    assert by == {"Acme Supplies Ltd": "[COMPANY_1]", "Northwind B.V.": "[COMPANY_2]"}


def test_empty_text(engine, lists):
    a = analyze(one(""), engine, lists)
    assert a.groups == [] and a.warnings == [] and a.text == ""


# --- Adding a file to an existing case (seed entries) --------------------------------------------


SEED = [
    KeyEntry("[COMPANY_1]", C, "Acme Supplies Ltd", ["Acme", "ACME SUPPLIES"]),
    KeyEntry("[PERSON_2]", P, "Jane Doe", []),
    KeyEntry("[COMPANY_2]", C, "Old Partner GmbH", []),
]


def test_seeds_keep_their_placeholders_and_are_swept(lists):
    t = "ACME SUPPLIES and Jane Doe meet. Mr Doe of Acme signs for Baltic Fasteners GmbH."
    fake = FakeEngine((C, "Baltic Fasteners GmbH", 0.95, "rule"), (P, "Mr Doe", 0.9, "rule"))
    a = analyze(one(t), fake, lists, seed_entries=SEED)
    by = {g.canonical: g for g in a.groups}
    assert set(by) == {"Acme Supplies Ltd", "Jane Doe", "Baltic Fasteners GmbH"}  # no Old Partner
    assert [f.text for f in by["Acme Supplies Ltd"].findings] == ["ACME SUPPLIES", "Acme"]
    assert [f.text for f in by["Jane Doe"].findings] == ["Jane Doe", "Mr Doe"]
    assert by["Jane Doe"].placeholder == "[PERSON_2]" and not by["Jane Doe"].needs_check
    assert by["Baltic Fasteners GmbH"].placeholder == "[COMPANY_3]"
    assert_one_replacement_each(a)


def test_new_numbers_follow_the_seeds_and_the_text(lists):
    fake = FakeEngine((C, "Baltic Fasteners GmbH", 0.95, "rule"), (P, "Bob Ray", 0.85, "model"))
    t = "Baltic Fasteners GmbH and Bob Ray read [COMPANY_5]."
    a = analyze(one(t), fake, lists, seed_entries=SEED)
    by = {g.canonical: g.placeholder for g in a.groups}
    assert by == {"Baltic Fasteners GmbH": "[COMPANY_6]", "Bob Ray": "[PERSON_3]"}


def test_a_seed_wins_over_the_model_on_the_same_words(lists):
    fake = FakeEngine((P, "Acme", 0.85, "model"))
    a = analyze(one("Acme signs."), fake, lists, seed_entries=SEED)
    (g,) = a.groups
    assert g.placeholder == "[COMPANY_1]" and g.findings[0].type == C


# --- A whole contract ----------------------------------------------------------------------------


def test_a_corpus_contract(corpus, engine, lists):
    """A made-up contract from the corpus: every finding fits the plan, and most truth is found."""
    text = extract_text(DocxPackage.open(corpus / "supply-01.docx")).text
    a = analyze(one(text), engine, lists)
    assert_one_replacement_each(a)
    assert len({g.placeholder for g in a.groups}) == len(a.groups)
    hidden = [(f.start, f.end) for f in all_findings(a)]
    truth = json.loads((corpus / "supply-01.truth.json").read_text())
    found = 0
    for item in truth:
        start = text.find(item["value"])
        if start < 0:
            continue
        end = start + len(item["value"])
        found += any(s <= start and end <= e for s, e in hidden)
    assert found >= 0.9 * len(truth)
