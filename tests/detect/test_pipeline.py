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


def masked(a):
    """The text with every finding replaced by its group's placeholder."""
    out = a.text
    found = sorted(
        ((f, g.placeholder) for g in a.groups for f in g.findings), key=lambda x: -x[0].start
    )
    for f, placeholder in found:
        out = out[: f.start] + placeholder + out[f.end :]
    return out


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


@pytest.mark.parametrize(
    "t",
    [
        "The Supplier shall maintain ISO 9001 and EN 1090 certification.",
        "Regulation (EU) No 1169/2011 applies to the labels.",
        "Prices agreed on 21 July 2026.3 This Agreement is signed.",  # a PDF's footnote mark
        "Deliveries arrive by 1700 CET.",
        "The licence runs for ten thousand (10,000) days.",
    ],
)
def test_references_standards_dates_and_times_stay_visible(engine, lists, t):
    assert analyze(one(t), engine, lists).groups == []


@pytest.mark.parametrize(
    "t",
    [
        "NET WEIGHT KG\tGROSS WEIGHT KG",
        "The UK Corporation Tax rate applies to the Price.",
        'In this Agreement, "Field of Use" means the hotel sector. The Field of Use is limited.',
    ],
)
def test_units_taxes_and_terms_defined_mid_line_stay_visible(engine, lists, t):
    assert analyze(one(t), engine, lists).groups == []


def test_a_word_that_makes_a_role_with_the_next_stays_visible(engine, lists):
    # The parties clause reads "Disclosing" after "(1) The" as a party's name; with "Party" after
    # it, it is a default never-hide term.
    t = (
        "THIS AGREEMENT is made BETWEEN:\n(1) The Disclosing Party, Acme Supplies Ltd; and\n"
        "(2) The Receiving Party, Northwind Trading B.V."
    )
    assert masked(analyze(one(t), engine, lists)) == (
        "THIS AGREEMENT is made BETWEEN:\n(1) The Disclosing Party, [COMPANY_1]; and\n"
        "(2) The Receiving Party, [COMPANY_2]"
    )


def test_the_first_and_second_party_stay_visible(engine, lists):
    t = (
        "THIS AGREEMENT is made BETWEEN:\n(1) The First Party, Acme Supplies Ltd; and\n"
        "(2) The Second Party, Northwind Trading B.V."
    )
    assert masked(analyze(one(t), engine, lists)) == (
        "THIS AGREEMENT is made BETWEEN:\n(1) The First Party, [COMPANY_1]; and\n"
        "(2) The Second Party, [COMPANY_2]"
    )


def test_a_salutation_is_no_part_of_a_name(engine, lists):
    t = "Dear Smith, thank you. John Smith signs."
    assert masked(analyze(one(t), engine, lists)) == "Dear [PERSON_1], thank you. [PERSON_1] signs."


def test_a_label_the_model_takes_with_its_value_stays_visible(engine, lists):
    t = "City: Amsterdam\nAPPENDIX 1A\nCountry: Netherlands"
    assert analyze(one(t), engine, lists).groups == []


def test_an_address_ends_with_its_country(engine, lists):
    t = "Registered office: 10 Downing Street, London SW1A 2AA, United Kingdom, Company Secretary"
    a = analyze(one(t), engine, lists)
    assert masked(a) == "Registered office: [ADDRESS_1], Company Secretary"


# Ruling R97 (b): a running header with spaced hyphens hides its company, not the words round it.
def test_a_hyphenated_running_header_hides_only_its_company(engine, lists):
    t = "Acme Supplies Ltd sells the Goods.\nConfidential - Acme Supplies Ltd - Page 3"
    assert masked(analyze(one(t), engine, lists)) == (
        "[COMPANY_1] sells the Goods.\nConfidential - [COMPANY_1] - Page 3"
    )


# Ruling R97 (d): the Dutch postcode and town after a spaced hyphen are hidden with their street.
def test_a_dutch_postcode_after_a_spaced_hyphen_is_hidden_with_its_street(engine, lists):
    t = "Ship to: Keizersgracht 123 - 1015 CJ Amsterdam"
    a = analyze(one(t), engine, lists)
    assert [(g.type, g.canonical) for g in a.groups] == [
        (PlaceholderType.ADDRESS, "Keizersgracht 123 - 1015 CJ Amsterdam")
    ]
    assert masked(a) == "Ship to: [ADDRESS_1]"


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


def test_a_case_entry_never_takes_a_value_that_differs_only_in_a_point(lists):
    # Ruling R100: the key's "EUR 1.25" is not the annex's "EUR 125".
    seed = [KeyEntry("[AMOUNT_1]", PlaceholderType.AMOUNT, "EUR 1.25", [])]
    fake = FakeEngine((PlaceholderType.AMOUNT, "EUR 125", 0.85, "pattern"))
    a = analyze(one("The fee is EUR 125 per item."), fake, lists, seed_entries=seed)
    assert [(g.placeholder, g.canonical) for g in a.groups] == [("[AMOUNT_2]", "EUR 125")]


def test_values_that_differ_in_a_point_a_symbol_or_a_dot_get_their_own_placeholders(engine, lists):
    # Ruling R100, the reviewer's reproduction: six values, six placeholders.
    t = (
        "The unit fee is EUR 1.25 per item and the annual cap is EUR 125 per customer. "
        "The deposit is $100 and the refund is \N{EURO SIGN}100. "
        "Questions to a.b@example.com or to ab@example.com."
    )
    a = analyze(one(t), engine, lists)
    assert masked(a) == (
        "The unit fee is [AMOUNT_1] per item and the annual cap is [AMOUNT_2] per customer. "
        "The deposit is [AMOUNT_3] and the refund is [AMOUNT_4]. "
        "Questions to [EMAIL_1] or to [EMAIL_2]."
    )
    assert all(len(g.variants) == 1 for g in a.groups)


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


def test_a_finding_is_cut_at_a_note_as_at_a_line_break(lists):
    # Ruling R113: the model read the company and the note that follows it as one name.
    t = "Acme Supplies Ltd[image removed] sells. [embedded object removed]Northwind buys."
    fake = FakeEngine(
        (P, "Acme Supplies Ltd[image", 0.85, "model"),
        (C, "removed]Northwind", 0.7, "model"),
        (C, "Acme Supplies Ltd", 0.95, "rule"),
    )
    a = analyze(one(t), fake, lists)
    assert [(g.type, g.canonical) for g in a.groups] == [(C, "Acme Supplies Ltd"), (C, "Northwind")]
    assert_one_replacement_each(a)
    assert (
        masked(a) == "[COMPANY_1][image removed] sells. [embedded object removed][COMPANY_2] buys."
    )


def test_the_real_engine_reads_a_name_beside_a_note_as_the_name(engine, lists):
    a = analyze(
        one("Acme Supplies Ltd[image removed] sells to Brightwater Foods Ltd."), engine, lists
    )
    assert all("[" not in g.canonical and "[" not in f.text for g in a.groups for f in g.findings)
    (acme,) = [g for g in a.groups if g.canonical == "Acme Supplies Ltd"]
    assert acme.type is C and acme.placeholder == "[COMPANY_1]"


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


# --- The sweep takes over a shorter find it holds (ruling R35) -----------------------------------


class FixedEngine:
    """An engine that reports exactly the findings it was given, wherever they stand."""

    def __init__(self, *found):
        self.found = found

    def analyze(self, text):
        return [f for f in self.found if text[f.start : f.end] == f.text]


FALCON = "Project Falcon starts now; Project Falcon ends later."


def model_find(kind, needle, last=False, score=0.6):
    start = FALCON.rindex(needle) if last else FALCON.index(needle)
    return Finding(kind, start, start + len(needle), needle, score, "model")


def test_one_code_name_found_two_ways_is_one_group(lists):
    # The model finds "Falcon" inside the first "Project Falcon" and "Project Falcon" later on.
    engine = FixedEngine(model_find(C, "Falcon"), model_find(C, "Project Falcon", last=True))
    a = analyze(one(FALCON), engine, lists)
    (g,) = a.groups
    assert g.type == C and g.canonical == "Project Falcon" and g.placeholder == "[COMPANY_1]"
    assert [(f.text, f.start) for f in g.findings] == [
        ("Project Falcon", 0),
        ("Project Falcon", FALCON.rindex("Project Falcon")),
    ]
    assert_one_replacement_each(a)


def test_the_falcon_text_with_the_real_engine(engine, lists):
    t = (
        "Acme Supplies Ltd and Northwind Trading B.V. appoint John Smith. Project Falcon starts"
        " now; Project Falcon ends later. Acme signs."
    )
    a = analyze(one(t), engine, lists)
    falcons = [g for g in a.groups if "falcon" in normalize(g.canonical)]
    (g,) = falcons
    assert g.type == C and [f.text for f in g.findings] == ["Project Falcon", "Project Falcon"]
    assert not any(f.text == "Falcon" for f in all_findings(a))
    assert_one_replacement_each(a)


def test_the_owners_always_hide_find_is_never_taken_over(lists):
    lists.add_always("Falcon")
    engine = FixedEngine(model_find(C, "Project Falcon", last=True))
    a = analyze(one(FALCON), engine, lists)
    by = {g.canonical: g for g in a.groups}
    assert [(f.text, f.start) for f in by["Falcon"].findings] == [
        ("Falcon", FALCON.index("Falcon"))
    ]
    assert by["Falcon"].placeholder == "[CUSTOM_1]" and by["Falcon"].findings[0].source == "list"
    assert [f.start for f in by["Project Falcon"].findings] == [FALCON.rindex("Project Falcon")]
    assert_one_replacement_each(a)


def test_a_case_entry_is_never_taken_over(lists):
    seed = [KeyEntry("[CUSTOM_4]", CUSTOM, "Falcon", [])]
    engine = FixedEngine(model_find(C, "Project Falcon", last=True))
    a = analyze(one(FALCON), engine, lists, seed_entries=seed)
    by = {g.canonical: g for g in a.groups}
    assert by["Falcon"].placeholder == "[CUSTOM_4]"
    assert [f.start for f in by["Falcon"].findings] == [FALCON.index("Falcon")]
    assert by["Project Falcon"].placeholder == "[COMPANY_1]"
    assert_one_replacement_each(a)


# --- Review fix round 1 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "t,expected",
    [
        (
            (
                'Acme Supplies Ltd appoints Jane Doe (the "Consultant", or "Ms Doe").'
                " Ms Doe shall report weekly."
            ),
            (
                '[COMPANY_1] appoints [PERSON_1] (the "Consultant", or "[PERSON_1]").'
                " [PERSON_1] shall report weekly."
            ),
        ),
        (
            'John Smith ("Smith"). Smith shall provide the Services.',
            '[PERSON_1] ("[PERSON_1]"). [PERSON_1] shall provide the Services.',
        ),
        (
            'Mr John Smith ("Mr Smith"). Mr Smith shall attend every meeting.',
            '[PERSON_1] ("[PERSON_1]"). [PERSON_1] shall attend every meeting.',
        ),
    ],
)
def test_a_persons_defined_short_name_is_hidden(engine, lists, t, expected):
    # Important 1: the surname forms of a person found beat the terms the document defines.
    a = analyze(one(t), engine, lists)
    assert masked(a) == expected


def test_a_shared_initial_is_never_given_to_the_stronger_name(lists):
    # Important 2: the model types "Ms Jane Smith" as a company (0.6); J. Smith fits both.
    t = "John Smith and Ms Jane Smith sign. J. Smith attends every meeting."
    fake = FakeEngine((P, "John Smith", 0.85, "model"), (C, "Ms Jane Smith", 0.6, "model"))
    a = analyze(one(t), fake, lists)
    assert masked(a) == "[PERSON_1] and [PERSON_2] sign. [PERSON_3] attends every meeting."
    (shared,) = [g for g in a.groups if g.canonical == "J. Smith"]
    assert shared.needs_check


@pytest.mark.parametrize(
    "t",
    [
        "Özdemir Gıda Ltd. Şti. and Özdemir Gıda Ltd. Sti. sign.",
        "Gıda Sanayi A.Ş. and Gıda Sanayi A.S. sign.",
    ],
)
def test_one_legal_form_spelt_two_ways_is_one_company(engine, lists, t):
    # Important 3
    a = analyze(one(t), engine, lists)
    companies = [g for g in a.groups if g.type == C]
    assert len(companies) == 1 and len(companies[0].findings) == 2
    assert not companies[0].needs_check


def person_at(t, needle, last=False, score=0.85, kind=None):
    start = t.rindex(needle) if last else t.index(needle)
    return Finding(kind or P, start, start + len(needle), needle, score, "model")


@pytest.mark.parametrize(
    "t,full,word",
    [
        ("Katie Price signs for the Supplier. Price shall attend.", "Katie Price", "Price"),
        ("Jo Banks signs for the Buyer. Banks shall be notified.", "Jo Banks", "Banks"),
    ],
)
def test_a_surname_that_is_a_default_term_stays_hidden(lists, t, full, word):
    # Ruling R42: one full name found ends with the word, and no determiner stands before it.
    engine = FixedEngine(person_at(t, full), person_at(t, word, last=True))
    a = analyze(one(t), engine, lists)
    (g,) = a.groups
    assert g.canonical == full and [f.text for f in g.findings] == [full, word]
    assert g.needs_check
    assert word in g.variants  # ruling R50: swept, but only where it stands as a name


def test_a_default_term_after_a_determiner_stays_visible(lists):
    t = "Katie Price signs for the Supplier. Then the Price shall be paid."
    engine = FixedEngine(person_at(t, "Katie Price"), person_at(t, "Price", last=True))
    a = analyze(one(t), engine, lists)
    (g,) = a.groups
    assert [f.text for f in g.findings] == ["Katie Price"] and not g.needs_check
    assert masked(a).endswith("Then the Price shall be paid.")


def test_the_owners_never_hide_list_beats_a_surname(lists):
    lists.add_never("Price")
    t = "Katie Price signs for the Supplier. Price shall attend."
    engine = FixedEngine(person_at(t, "Katie Price"), person_at(t, "Price", last=True))
    a = analyze(one(t), engine, lists)
    assert masked(a) == "[PERSON_1] signs for the Supplier. Price shall attend."


def test_a_default_term_with_an_honorific_is_flagged(engine, lists):
    a = analyze(one("Katie Price signs for the Supplier. Ms Price shall attend."), engine, lists)
    (g,) = a.groups
    assert [f.text for f in g.findings] == ["Katie Price", "Ms Price"] and g.needs_check


# --- Ruling R50: a person's bare surname is swept where it stands as a name (real engine) ---------

LAURA_MILL = (
    'Laura Mill manages the old factory (the "Mill"). The Mill shall be maintained by the'
    " Supplier. Mill shall attend every inspection."
)
LAURA_MILL_MASKED = (
    '[PERSON_1] manages the old factory (the "Mill"). The Mill shall be maintained by the'
    " Supplier. [PERSON_1] shall attend every inspection."
)


@pytest.mark.parametrize(
    "t,expected,flagged",
    [
        (
            "Katie Price signs for the Supplier. Price shall attend.",
            "[PERSON_1] signs for the Supplier. [PERSON_1] shall attend.",
            True,  # "Price" is a default never-hide word
        ),
        (
            "Jo Banks signs for the Buyer. Banks shall be notified.",
            "[PERSON_1] signs for the Buyer. [PERSON_1] shall be notified.",
            True,
        ),
        (
            "Katie Smith signs. Smith shall attend.",
            "[PERSON_1] signs. [PERSON_1] shall attend.",
            False,
        ),
        (
            "Katie Price signs for the Supplier. The Price shall be paid.",
            "[PERSON_1] signs for the Supplier. The Price shall be paid.",
            False,  # after a determiner the word is the price
        ),
        (LAURA_MILL, LAURA_MILL_MASKED, True),  # "Mill" is a term the document defines
        (
            "Jane van der Berg signs for the Supplier; van der Berg shall report monthly.",
            "[PERSON_1] signs for the Supplier; [PERSON_1] shall report monthly.",
            False,
        ),
    ],
)
def test_a_persons_bare_surname_is_hidden_where_it_names_them(engine, lists, t, expected, flagged):
    a = analyze(one(t), engine, lists)
    assert masked(a) == expected
    (person,) = [g for g in a.groups if g.type == P]
    assert person.needs_check == flagged


def test_the_owners_never_hide_list_keeps_a_surname_visible(engine, lists):
    lists.add_never("Price")
    a = analyze(one("Katie Price signs for the Supplier. Price shall attend."), engine, lists)
    assert masked(a) == "[PERSON_1] signs for the Supplier. Price shall attend."


def test_a_surname_two_people_share_is_a_group_to_check(engine, lists):
    t = "John Smith and Jane Smith sign for the Buyer. Smith shall attend."
    a = analyze(one(t), engine, lists)
    assert masked(a) == "[PERSON_1] and [PERSON_2] sign for the Buyer. [PERSON_3] shall attend."
    assert [g.needs_check for g in a.groups] == [False, False, True]


def test_a_default_word_two_people_share_stays_visible(engine, lists):
    # Ruling R42's attribution: a default never-hide word only for one person alone.
    t = "Katie Price and Tom Price sign for the Buyer. Price shall attend."
    a = analyze(one(t), engine, lists)
    assert masked(a) == "[PERSON_1] and [PERSON_2] sign for the Buyer. Price shall attend."


def test_a_surname_with_particles_is_swept_as_a_name(lists):
    # The model finds a bare "van der Berg" on its own; this stub does not, so the sweep must.
    t = "Jane van der Berg signs; van der Berg shall report; the van der Berg file is closed."
    a = analyze(one(t), FixedEngine(person_at(t, "Jane van der Berg")), lists)
    assert (
        masked(a) == "[PERSON_1] signs; [PERSON_1] shall report; the van der Berg file is closed."
    )


def test_a_case_entrys_bare_surname_stays_a_name(lists):
    seed = [KeyEntry("[PERSON_4]", P, "Katie Price", ["Price"])]
    t = "Price shall attend; the Price is fixed."
    a = analyze(one(t), FakeEngine(), lists, seed_entries=seed)
    assert masked(a) == "[PERSON_4] shall attend; the Price is fixed."


def test_a_surname_that_is_a_nationality_is_checked(engine, lists):
    # Ruling R53: "English" is a default word, so hiding it as Tom English's surname marks the
    # group for checking (R42's attribution: one person found ends with it, no determiner).
    t = (
        "Tom English signs for the Supplier. This Agreement is governed by English law and the"
        " parties submit to the English courts."
    )
    a = analyze(one(t), engine, lists)
    assert masked(a) == (
        "[PERSON_1] signs for the Supplier. This Agreement is governed by [PERSON_1] law and the"
        " parties submit to the English courts."
    )
    (person,) = a.groups
    assert person.needs_check


def test_a_nationality_without_a_person_of_that_name_stays(engine, lists):
    a = analyze(one("This Agreement is governed by Dutch law."), engine, lists)
    assert a.groups == []


# --- Ruling R54: a bare surname only where it stands alone as a name (real engine) -----------------


# The reviewer's N1 texts: the term or heading stays, a standalone surname is hidden.
TERMS_AND_HEADINGS = [
    (
        "Doris Day signs for the Supplier. Delivery is due on the next Business Day after the order. Day shall attend.",
        "[PERSON_1] signs for the Supplier. Delivery is due on the next Business Day after the order. [PERSON_1] shall attend.",
    ),
    (
        "Tom House signs for the Buyer, a company registered at Companies House. House shall attend.",
        "[PERSON_1] signs for the Buyer, a company registered at Companies House. [PERSON_1] shall attend.",
    ),
    (
        "Hugh Grant signs for the Licensor.\n2. GRANT OF LICENCE\nGrant shall attend.",
        "[PERSON_1] signs for the Licensor.\n2. GRANT OF LICENCE\n[PERSON_1] shall attend.",
    ),
    (
        "Tom Long signs for the Buyer.\nLong Stop Date: 30 June 2026.\nLong shall attend.",
        "[PERSON_1] signs for the Buyer.\nLong Stop Date: 30 June 2026.\n[PERSON_1] shall attend.",
    ),
    (
        "Ann Court signs for the Buyer. Disputes go to the High Court of Justice in London. Court shall attend.",
        "[PERSON_1] signs for the Buyer. Disputes go to the High Court of Justice in London. [PERSON_1] shall attend.",
    ),
    (
        "Ann Terms signs for the Licensor. Use of the site follows our Terms of Use. Terms shall attend.",
        "[PERSON_1] signs for the Licensor. Use of the site follows our Terms of Use. [PERSON_1] shall attend.",
    ),
    (
        "Rob Bond signs for the Supplier. The Supplier shall provide a Performance Bond. Bond shall attend.",
        "[PERSON_1] signs for the Supplier. The Supplier shall provide a Performance Bond. [PERSON_1] shall attend.",
    ),
    (
        "Katie Price, Director of Sales, signs. Price, Director, shall attend.",
        "[PERSON_1], Director of Sales, signs. [PERSON_1], Director, shall attend.",
    ),
]


@pytest.mark.parametrize("t,expected", TERMS_AND_HEADINGS)
def test_a_surname_inside_a_term_or_heading_stays(engine, lists, t, expected):
    a = analyze(one(t), engine, lists)
    assert masked(a) == expected


def test_a_surname_form_the_model_took_for_a_company_follows_the_guard_too(engine, lists):
    # Reviewer's N2: the model reports COMPANY "Lodge" (0.6); "The Lodge" is the defined term.
    t = 'Sam Lodge manages the site (the "Lodge"). The Lodge shall be kept open daily. Lodge shall attend.'
    a = analyze(one(t), engine, lists)
    assert masked(a) == (
        '[PERSON_1] manages the site (the "Lodge"). The Lodge shall be kept open daily.'
        " [PERSON_1] shall attend."
    )


def test_a_surname_that_is_another_persons_first_name_is_checked(engine, lists):
    # Reviewer's N4
    t = "Sarah James and James Wilson sign for the Buyer. James shall attend."
    a = analyze(one(t), engine, lists)
    assert masked(a) == "[PERSON_1] and [PERSON_2] sign for the Buyer. [PERSON_3] shall attend."
    assert [g.needs_check for g in a.groups] == [False, False, True]


def test_a_month_surname_beside_a_number_is_a_date(lists):
    # Reviewer's N5 (the model reads only "Theresa" here, so a stub reports the full name)
    t = "Theresa May signs. This Agreement is dated 1 May 2026. May shall attend."
    a = analyze(one(t), FixedEngine(person_at(t, "Theresa May")), lists)
    assert (
        masked(a)
        == "[PERSON_1] signs. This Agreement is dated 1 May 2026. [PERSON_1] shall attend."
    )
    assert a.groups[0].needs_check


# --- Ruling R56: where the engine saw a name; separators; phrases over a connective -------------

# Real engine. The flag is R42/R50's own: set where the hidden surname is a default word.
SEEN_AND_SEPARATED = [
    (
        "John Smith signs for the Supplier.\nSmith Director",
        "[PERSON_1] signs for the Supplier.\n[PERSON_1] Director",
        False,
    ),
    (
        "John Smith signs for the Supplier.\nSigned: ____\nSMITH\nDirector",
        "[PERSON_1] signs for the Supplier.\nSigned: ____\n[PERSON_1]\nDirector",
        False,
    ),
    (
        "Katie Price signs for the Supplier.\nDear Price,\nPlease find the order attached.",
        "[PERSON_1] signs for the Supplier.\nDear [PERSON_1],\nPlease find the order attached.",
        True,
    ),
    # hidden before ruling R56 and still so
    (
        "Katie Price signs for the Supplier.\nPrice, Director",
        "[PERSON_1] signs for the Supplier.\n[PERSON_1], Director",
        True,
    ),
    (
        "Katie Price signs for the Supplier.\nPrice\nDirector",
        "[PERSON_1] signs for the Supplier.\n[PERSON_1]\nDirector",
        True,
    ),
    (
        "John Smith signs for the Supplier.\nYours, Smith",
        "[PERSON_1] signs for the Supplier.\nYours, [PERSON_1]",
        False,
    ),
    # the reviewer's NB2: a phrase over a lowercase connective stays, the person is still hidden
    (
        "Hugh Grant signs for the Licensor.\n2. Grant of Rights\nGrant shall attend.",
        "[PERSON_1] signs for the Licensor.\n2. Grant of Rights\n[PERSON_1] shall attend.",
        False,
    ),
    (
        "Ann Power signs for the Buyer.\nPower of Attorney dated 1 March 2026.\nPower shall attend.",
        "[PERSON_1] signs for the Buyer.\nPower of Attorney dated 1 March 2026.\n[PERSON_1] shall attend.",
        False,
    ),
]


@pytest.mark.parametrize("t,expected,flagged", SEEN_AND_SEPARATED)
def test_a_surname_by_a_separator_is_hidden_and_a_phrase_stays(engine, lists, t, expected, flagged):
    a = analyze(one(t), engine, lists)
    assert masked(a) == expected
    (person,) = [g for g in a.groups if g.type == P]
    assert person.needs_check == flagged


def test_a_tab_separated_signature_line_keeps_its_labels(engine, lists):
    # Ruling R58 (real engine): the model's "Smith\tTitle" is cut at the tab.
    t = "John Smith signs for the Supplier.\nName:\tSmith\tTitle:\tDirector"
    a = analyze(one(t), engine, lists)
    assert masked(a) == "[PERSON_1] signs for the Supplier.\nName:\t[PERSON_1]\tTitle:\tDirector"
    (person,) = a.groups
    assert not person.needs_check


def test_names_on_both_sides_of_a_connective_are_both_hidden(engine, lists):
    t = "Katie Price and John Smith sign for the Buyer. Price and Smith sign the annex."
    a = analyze(one(t), engine, lists)
    assert masked(a) == (
        "[PERSON_1] and [PERSON_2] sign for the Buyer. [PERSON_1] and [PERSON_2] sign the annex."
    )


@pytest.mark.parametrize(
    "t,expected",
    [
        (
            "John Smith signs for the Supplier. Approved by Smith Finance Director.",
            "[PERSON_1] signs for the Supplier. Approved by [PERSON_1] Finance Director.",
        ),
        (
            "John Smith signs for the Supplier.\nName:\tSmith\tTitle:\tDirector",
            "[PERSON_1] signs for the Supplier.\nName:\t[PERSON_1]\tTitle:\tDirector",
        ),
        (
            "John Smith signs for the Supplier. Copies go to Smith/Jones.",
            "[PERSON_1] signs for the Supplier. Copies go to [PERSON_1]/Jones.",
        ),
        (
            "Sue Field signs for the Licensor.\nField of Use: Europe.\nField shall attend.",
            "[PERSON_1] signs for the Licensor.\nField of Use: Europe.\n[PERSON_1] shall attend.",
        ),
    ],
)
def test_the_sweep_by_a_separator_where_the_engine_found_only_the_person(lists, t, expected):
    # Stub: the engine finds the full name only, so these spots are the sweep's.
    full = t.split(" signs")[0]
    a = analyze(one(t), FixedEngine(person_at(t, full)), lists)
    assert masked(a) == expected


def test_a_surname_the_engine_found_needs_only_no_determiner(lists):
    # Ruling R56 (a): where the engine saw a name, only a determiner makes it a word.
    t = "John Smith signs. Smith Holdings shall deliver; the Smith file is closed."
    first_bare = t.index("Smith Holdings")
    the_file = t.index("Smith file")
    engine = FixedEngine(
        person_at(t, "John Smith"),
        Finding(P, first_bare, first_bare + 5, "Smith", 0.85, "model"),
        Finding(P, the_file, the_file + 5, "Smith", 0.85, "model"),
    )
    a = analyze(one(t), engine, lists)
    assert (
        masked(a)
        == "[PERSON_1] signs. [PERSON_1] Holdings shall deliver; the Smith file is closed."
    )


# --- Ruling R55: parties that are people, people that are companies (real engine) -------------


def test_a_party_shortened_to_its_surname_is_a_person(engine, lists):
    # Reviewer's O1: the parties rule types John Smith as a company.
    t = (
        'This Agreement is made between Acme Supplies Ltd and John Smith ("Smith"). Smith shall'
        " provide the Services."
    )
    a = analyze(one(t), engine, lists)
    assert masked(a) == (
        'This Agreement is made between [COMPANY_1] and [PERSON_1] ("[PERSON_1]"). [PERSON_1]'
        " shall provide the Services."
    )


def test_a_company_name_without_its_legal_form_joins_the_company(engine, lists):
    # Reviewer's O3: the model types "Gıda Sanayi" as a person.
    a = analyze(
        one("Gıda Sanayi A.Ş. signs the order. Gıda Sanayi invoices monthly."), engine, lists
    )
    assert masked(a) == "[COMPANY_1] signs the order. [COMPANY_1] invoices monthly."


def test_a_rule_name_with_its_legal_form_keeps_its_end(engine, lists):
    # Ruling R45 (and R46 for the passport number): the model ran on into "Passport".
    t = "Name: Jane Doe, for Acme Supplies Ltd. Passport number: 534412786."
    a = analyze(one(t), engine, lists)
    by = {g.canonical: g for g in a.groups}
    assert "Acme Supplies Ltd" in by and "Acme Supplies Ltd. Passport" not in by
    assert by["534412786"].type == PlaceholderType.ID and by["534412786"].placeholder == "[ID_1]"
    assert "Passport number" in masked(a)


def test_a_rule_name_beats_a_longer_model_span_only_with_its_legal_form(lists):
    t = "Signed by Jane Doe Smith for Acme Supplies Ltd. Passport checked."

    def at(kind, needle, score, source):
        start = t.index(needle)
        return Finding(kind, start, start + len(needle), needle, score, source)

    fake = FixedEngine(
        at(C, "Acme Supplies Ltd", 0.95, "rule"),
        at(C, "Acme Supplies Ltd. Passport", 0.85, "model"),
        at(P, "Jane Doe", 0.9, "rule"),  # no legal form: the model's longer name stands
        at(P, "Jane Doe Smith", 0.85, "model"),
    )
    a = analyze(one(t), fake, lists)
    assert sorted(g.canonical for g in a.groups) == ["Acme Supplies Ltd", "Jane Doe Smith"]


@pytest.mark.parametrize(
    "id_score,phone_score,expected",
    [(0.85, 0.75, PlaceholderType.ID), (0.8, 0.75, PlaceholderType.PHONE)],
)
def test_on_one_span_a_clearly_higher_score_wins(lists, id_score, phone_score, expected):
    # Ruling R46: 0.1 or more apart, the score decides; closer, the type order does.
    t = "Passport number: 534412786"
    fake = FixedEngine(
        Finding(PlaceholderType.ID, 17, 26, "534412786", id_score, "pattern"),
        Finding(PlaceholderType.PHONE, 17, 26, "534412786", phone_score, "pattern"),
        Finding(PlaceholderType.AMOUNT, 17, 26, "534412786", 0.4, "pattern"),
    )
    a = analyze(one(t), fake, lists)
    (g,) = a.groups
    assert g.type == expected and g.placeholder == f"[{expected.value}_1]"


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


def test_only_exact_placeholders_count(engine, lists):
    # Ruling R44: in a source document only [TYPE_N] is a placeholder; "company_2" is text.
    t = "This document refers to [COMPANY_1] and company_2 and Northwind Trading B.V."
    a = analyze(one(t), engine, lists)
    (g,) = a.groups
    assert g.placeholder == "[COMPANY_2]"
    assert a.warnings == [
        (
            "The document already contains placeholders such as [COMPANY_1];"
            " numbering continues after them."
        )
    ]
    assert all(f.start >= t.index("Northwind") for f in g.findings)


def test_a_bare_reference_like_id_55821_is_a_value(engine, lists):
    # Ruling R44: "ID-55821" looks like an altered placeholder, but in an original it is a value.
    t = "Customer ID-55821 shall be quoted on every invoice."
    a = analyze(one(t), engine, lists)
    assert a.warnings == []
    assert "55821" not in masked(a)
    fixed = FixedEngine(Finding(PlaceholderType.ID, 12, 17, "55821", 0.85, "pattern"))
    a = analyze(one(t), fixed, lists)
    assert [(g.canonical, g.placeholder) for g in a.groups] == [("55821", "[ID_1]")]
    assert a.warnings == []


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


def test_a_short_form_swept_near_the_top_makes_that_value_number_1(lists):
    # Ruling R34: the engine finds Northwind B.V. first, but the sweep finds "Acme" (of Acme
    # Supplies Ltd) at the very top, so Acme is the first company the masked text shows.
    t = "Acme pays Jane Doe. Northwind B.V. and Acme Supplies Ltd sign."
    fake = FakeEngine((C, "Acme Supplies Ltd", 0.95, "rule"), (C, "Northwind B.V.", 0.95, "rule"))
    a = analyze(one(t), fake, lists)
    first = a.groups[0]
    assert first.canonical == "Acme Supplies Ltd" and first.placeholder == "[COMPANY_1]"
    assert (first.findings[0].text, first.findings[0].start) == ("Acme", 0)
    assert first.findings[0].source == "sweep"
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


# --- Page labels and document references are never names (Task D4) --------------------------------

PAGE_LABELS = [
    "Page PAGE1",
    "Page 1",
    "Page 1 of 3",
    "PAGE1",
    "PAGE",
    "NUMPAGES",
    "Page PAGE of NUMPAGES",
    "Seite 2",
    "Seite 2 von 5",
    "Seite PAGE2",
    "Pagina 3",
    "Pagina PAGE3",
    "Pagina 3 van 7",
    "Bladzijde 4",
    "Bladzijde 4 van 9",
    "Section 3",
    "Article 5",
    "Exhibit A",
    "Schedule 2",
    "Annex",
    "Annex II",
    "Clause 4.1",
    "Appendix B",
    "Table 1",
    "Figure 2",
]


@pytest.mark.parametrize("label", PAGE_LABELS)
@pytest.mark.parametrize("kind", [P, C])
@pytest.mark.parametrize("score", [0.6, 0.85])
def test_a_page_label_or_reference_is_never_hidden_as_a_name(lists, label, kind, score):
    fake = FakeEngine((kind, label, score, "model"))
    a = analyze(one(f"Footer: {label}\n\nSigned for the Buyer."), fake, lists)
    assert a.groups == []


def test_a_person_named_page_is_still_a_person(lists):
    fake = FakeEngine((P, "Page Smith", 0.85, "model"))
    a = analyze(one("Mr Page Smith signs."), fake, lists)
    assert [g.canonical for g in a.groups] == ["Page Smith"]


# --- Guesses made of ordinary words (ruling R122, items 1 and 2) ----------------------------------


def test_a_guess_of_a_never_hide_term_plus_filler_is_dropped(lists):
    phrase = "the Confidential Information of the other"
    fake = FakeEngine((C, phrase, 0.6, "model"))
    a = analyze(one(f"Each party shall protect {phrase} party."), fake, lists)
    assert a.groups == []


@pytest.mark.parametrize(
    "phrase",
    ["the Personal Data of the other", "the Receiving Party and the Disclosing Party"],
)
def test_other_term_plus_filler_guesses_are_dropped_at_low_score(lists, phrase):
    fake = FakeEngine((P, phrase, 0.6, "model"))
    assert analyze(one(f"We regard {phrase} as terms."), fake, lists).groups == []


def test_a_low_confidence_guess_of_ordinary_words_is_shown_and_asked_about(lists):
    fake = FakeEngine((C, "Equipment Services", 0.6, "model"))
    a = analyze(
        one("The Equipment Services start in June. Equipment Services continue."), fake, lists
    )
    (g,) = a.groups
    assert g.canonical == "Equipment Services"
    assert g.enabled is False and g.needs_check is True
    assert len(g.findings) == 2  # every place is kept, so the owner's Hide covers them all


def test_a_low_confidence_guess_with_a_name_shaped_word_stays_hidden(lists):
    fake = FakeEngine((C, "Zorblax Services", 0.6, "model"))
    (g,) = analyze(one("Zorblax Services start in June."), fake, lists).groups
    assert g.enabled is True and g.needs_check is True


def test_a_confident_guess_of_ordinary_words_is_not_asked_about(lists):
    fake = FakeEngine((C, "Equipment Services", 0.85, "model"))
    (g,) = analyze(one("The Equipment Services start in June."), fake, lists).groups
    assert g.enabled is True


def test_a_contract_rule_finding_is_never_turned_off(lists):
    fake = FakeEngine((C, "Equipment Services Ltd", 0.95, "rule"))
    (g,) = analyze(one("Equipment Services Ltd signs."), fake, lists).groups
    assert g.enabled is True and g.needs_check is False


def test_the_owners_always_hide_entry_is_never_turned_off(lists):
    from themask.detect.lists import UserLists

    owner = UserLists(["COMPANY: Equipment Services"], [])
    fake = FakeEngine((C, "Equipment Services", 0.6, "model"))
    (g,) = analyze(one("The Equipment Services start."), fake, owner).groups
    assert g.enabled is True


def test_a_place_in_a_low_confidence_guess_keeps_it_hidden(lists):
    fake = FakeEngine((C, "Bank of Ireland", 0.6, "model"))
    (g,) = analyze(one("Payment to Bank of Ireland follows."), fake, lists).groups
    assert g.enabled is True


def test_page_footers_in_a_real_contract_hide_nobody_but_the_parties(engine, lists):
    t = (
        "This Agreement is made between Acme Supplies Ltd and John Carter.\n"
        "Page PAGE1\nPage 1 of 3\nPAGE1 NUMPAGES\nSeite 2 von 5\nPagina 3\nBladzijde 4\n"
        "Seite PAGE2\nPagina PAGE3\nSee Section 3, Article 5, Exhibit A, Schedule 2, Clause 4.1,\n"
        "Appendix B, Table 1 and Figure 2.\n"
    )
    a = analyze(one(t), engine, lists)
    assert sorted(g.canonical for g in a.groups) == ["Acme Supplies Ltd", "John Carter"]


# --- Review fixes (C1, C2, I1-I3, M2, M4) ----------------------------------------------------------

REAL_COMPANIES = [
    "The Capital Group",
    "The Standard",
    "The Trading Company",
    "Global Payments and Services",
    "Bond and Grant",
]


@pytest.mark.parametrize("name", REAL_COMPANIES)
@pytest.mark.parametrize("score", [0.6, 0.9, 0.95])
def test_real_company_names_of_common_words_are_never_dropped_or_switched_off(lists, name, score):
    fake = FakeEngine((C, name, score, "model"))
    a = analyze(one(f"Do not disclose anything to {name} or to others."), fake, lists)
    assert len(a.groups) == 1
    assert a.groups[0].enabled is True


@pytest.mark.parametrize(
    "name",
    ["Royal Mail", "First Data", "Capital Partners", "General Holdings", "Standard Trading"]
    + ["Central Logistics", "Software Solutions", "Global Services", "Master Supply"],
)
def test_common_word_companies_at_low_confidence_stay_hidden(lists, name):
    fake = FakeEngine((C, name, 0.6, "model"))
    (g,) = analyze(one(f"Payment goes to {name} monthly."), fake, lists).groups
    assert g.enabled is True and g.needs_check is True


@pytest.mark.parametrize("word", ["Bond", "Grant", "Day", "Long", "Holiday", "Personal Data"])
def test_a_person_guess_is_never_switched_off(lists, word):
    fake = FakeEngine((P, word, 0.6, "model"))
    a = analyze(one(f"We met {word} on Tuesday."), fake, lists)
    assert all(g.enabled for g in a.groups)


def test_a_defined_term_code_name_and_its_longer_forms_stay_hidden(lists):
    fake = FakeEngine((C, "Kestrel Group", 0.6, "model"), (C, "Kestrel Holdings", 0.6, "model"))
    t = '"Kestrel" means the target business. Kestrel Group and Kestrel Holdings are excluded.'
    a = analyze(one(t), fake, lists)
    assert a.groups and all(g.enabled for g in a.groups)


def test_a_short_form_of_a_confident_company_is_not_switched_off(lists):
    fake = FakeEngine(
        (C, "Capital Partners Holdings", 0.9, "model"), (C, "Capital Partners", 0.6, "model")
    )
    a = analyze(one("Capital Partners Holdings signs. Capital Partners pays."), fake, lists)
    assert a.groups and all(g.enabled for g in a.groups)


def test_a_guess_inside_a_hidden_name_is_not_switched_off(lists):
    fake = FakeEngine(
        (C, "Equipment Services Ltd", 0.95, "rule"), (C, "Equipment Services", 0.6, "model")
    )
    a = analyze(one("Equipment Services Ltd signs. Equipment Services pays."), fake, lists)
    assert all(g.enabled for g in a.groups)


def test_a_confident_term_plus_filler_guess_is_kept(lists):
    fake = FakeEngine((C, "the Confidential Information of the other", 0.9, "model"))
    a = analyze(one("Protect the Confidential Information of the other."), fake, lists)
    assert len(a.groups) == 1


@pytest.mark.parametrize(
    "label", ["Seite B", "Pagina V", "Page CIVIL", "Seite C", "Pagina L", "Page MIX"]
)
def test_an_unclear_page_label_is_not_a_never_hide_term(lists, label):
    from themask.detect.lists import CaseLists, is_never_hide

    assert not is_never_hide(label, lists, CaseLists([], [], set()))


@pytest.mark.parametrize(
    "label", ["Page PAGE1", "Seite 2 von 5", "Page 1 of 3", "NUMPAGES", "Page XII"]
)
def test_clear_page_labels_remain_never_hide_terms(lists, label):
    from themask.detect.lists import CaseLists, is_never_hide

    assert is_never_hide(label, lists, CaseLists([], [], set()))


def test_real_engine_keeps_capital_group_and_the_trading_company_hidden(engine, lists):
    t = (
        "The Recipient shall not disclose anything to The Capital Group or to Global Services."
        " The Trading Company and Supply and Logistics are excluded."
    )
    a = analyze(one(t), engine, lists)
    names = {g.canonical for g in a.groups}
    assert "Capital Group" in names and any(n.startswith("Trading Company") for n in names)
    assert all(g.enabled for g in a.groups)


# --- Fix round 2: short forms of a hidden company -----------------------------------------------


@pytest.mark.parametrize(
    ("long", "long_score", "short", "text"),
    [
        (
            "Software Services Group Ltd",
            0.9,
            "Software Services",
            "Software Services Group Ltd signs. Software Services shall deliver.",
        ),
        (
            "Bank Services Ltd",
            0.95,
            "Bank Services Group",
            "Bank Services Ltd signs. Bank Services Group pays.",
        ),
        (
            "Bank Services Holdings Ltd",
            0.9,
            "Bank Services",
            "Bank Services Holdings Ltd guarantees; Bank Services pays.",
        ),
    ],
)
def test_a_short_form_beside_a_hidden_company_is_not_switched_off(
    lists, long, long_score, short, text
):
    fake = FakeEngine((C, long, long_score, "model"), (C, short, 0.6, "model"))
    a = analyze(one(text), fake, lists)
    assert {g.canonical for g in a.groups} >= {long}
    assert all(g.enabled for g in a.groups)


def test_real_engine_short_forms_of_hidden_companies_stay_on(engine, lists):
    t = (
        "This Agreement is made between Software Services Group Ltd and John Carter. Software"
        " Services shall deliver the Goods. Bank Services Holdings Ltd guarantees; Bank Services"
        " pays."
    )
    a = analyze(one(t), engine, lists)
    assert all(g.enabled for g in a.groups)
    assert "Software Services shall" not in masked(a) and "Bank Services pays" not in masked(a)


def test_a_term_phrase_that_is_a_short_form_of_a_found_company_is_not_dropped(lists):
    fake = FakeEngine(
        (C, "Equipment and Software Group Ltd", 0.9, "model"),
        (C, "Equipment and Software", 0.6, "model"),
    )
    a = analyze(
        one("Equipment and Software Group Ltd signs. Equipment and Software pays."), fake, lists
    )
    assert "Equipment and Software pays" not in masked(a)
    assert all(g.enabled for g in a.groups)


@pytest.mark.parametrize(
    "label",
    ["Page Vivi", "Page Xi", "Annex Vivi", "Schedule Xi", "Party Xi", "Article Ivi", "Part Vi"],
)
def test_mixed_case_roman_looking_words_are_not_references(lists, label):
    from themask.detect.lists import CaseLists, is_never_hide

    assert not is_never_hide(label, lists, CaseLists([], [], set()))


@pytest.mark.parametrize(
    "label",
    [
        "Article LIV",
        "Schedule XL",
        "Schedule LX",
        "Annex LIV",
        "Schedule CC",
        "Annex IV",
        "Page XII",
    ],
)
def test_valid_roman_references_stay_never_hide(lists, label):
    from themask.detect.lists import CaseLists, is_never_hide

    assert is_never_hide(label, lists, CaseLists([], [], set()))
