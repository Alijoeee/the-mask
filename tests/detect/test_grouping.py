"""Variant grouping: which findings stand for one value, its canonical form, and when to check."""

import uuid

import pytest

from themask.detect.grouping import SurnamePolicy, group_findings
from themask.model import Finding, Group, PlaceholderType

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY


def F(t, needle, txt, last=False, score=0.9):
    s = txt.rindex(needle) if last else txt.index(needle)
    return Finding(t, s, s + len(needle), needle, score, "model")


def by_canonical(groups):
    return {g.canonical: g for g in groups}


# --- The brief's tests ---------------------------------------------------------------------------


def test_variants_merge():
    txt = "John Smith … Mr Smith … J. Smith"
    fs = [F(P, "John Smith", txt), F(P, "Mr Smith", txt), F(P, "J. Smith", txt)]
    (g,) = group_findings(fs, txt)
    assert g.canonical == "John Smith" and len(g.findings) == 3 and not g.needs_check


def test_shared_surname_not_merged():
    txt = "John Smith and Jane Smith … Mr Smith"
    fs = [F(P, "John Smith", txt), F(P, "Jane Smith", txt), F(P, "Mr Smith", txt)]
    gs = group_findings(fs, txt)
    assert len(gs) == 3 and next(g for g in gs if g.canonical == "Mr Smith").needs_check


def test_company_suffix_merge():
    txt = "Acme Supplies Ltd … Acme Supplies … ACME"
    fs = [
        F(C, "Acme Supplies Ltd", txt),
        F(C, "Acme Supplies", txt, last=True),
        F(C, "ACME", txt),
    ]
    (g,) = group_findings(fs, txt)
    assert g.canonical == "Acme Supplies Ltd"


def test_low_score_needs_check():
    txt = "Riverside Partners"
    (g,) = group_findings([F(C, "Riverside Partners", txt, score=0.6)], txt)
    assert g.needs_check


# --- People ------------------------------------------------------------------------------------


def test_honorific_and_capitals_are_the_same_name():
    txt = "Mr John Smith signs. JOHN SMITH. John Smith attends."
    fs = [F(P, "Mr John Smith", txt), F(P, "JOHN SMITH", txt), F(P, "John Smith", txt, True)]
    (g,) = group_findings(fs, txt)
    assert len(g.findings) == 3 and {"John Smith", "J. Smith"} <= g.variants


def test_initial_and_surname_merge_only_when_one_full_name_fits():
    txt = "John Smith and Jane Smith sign. J. Smith attends."
    fs = [F(P, "John Smith", txt), F(P, "Jane Smith", txt), F(P, "J. Smith", txt)]
    gs = by_canonical(group_findings(fs, txt))
    assert set(gs) == {"John Smith", "Jane Smith", "J. Smith"}
    assert gs["J. Smith"].needs_check
    assert not gs["John Smith"].needs_check and not gs["Jane Smith"].needs_check
    # Neither full name may claim "J. Smith", or the sweep would merge it after all.
    assert "J. Smith" not in gs["John Smith"].variants | gs["Jane Smith"].variants


@pytest.mark.parametrize("jane", [(P, "Jane Smith"), (C, "Ms Jane Smith")])
def test_a_weak_name_still_makes_a_shared_initial_a_check(jane):
    # Important 2: John Smith at 0.9, Jane Smith at 0.6 (the model's "company" Ms Jane Smith).
    kind, name = jane
    txt = f"John Smith and {name} sign. J. Smith attends."
    fs = [F(P, "John Smith", txt, score=0.9), F(kind, name, txt, score=0.6)]
    gs = by_canonical(group_findings(fs, txt))
    assert "J. Smith" not in gs["John Smith"].variants | gs[name].variants
    assert gs["J. Smith"].needs_check and gs["J. Smith"].findings[0].source == "sweep"


def test_a_defined_surname_form_is_its_persons_variant():
    txt = 'John Smith ("Smith"). Smith shall provide the Services.'
    (g,) = group_findings([F(P, "John Smith", txt)], txt, aliases={"Smith", "Services"})
    assert "Smith" in g.variants and "Services" not in g.variants


def test_a_defined_surname_two_people_share_is_checked():
    txt = 'John Smith and Jane Smith ("Smith"). Smith shall attend.'
    fs = [F(P, "John Smith", txt), F(P, "Jane Smith", txt)]
    gs = by_canonical(group_findings(fs, txt, aliases={"Smith"}))
    assert "Smith" not in gs["John Smith"].variants | gs["Jane Smith"].variants
    assert gs["Smith"].needs_check and len(gs["Smith"].findings) == 2


SURNAMES = SurnamePolicy(
    allowed=lambda form: form != "Never", only_one=lambda form: form == "Price"
)


def test_a_bare_surname_is_its_persons_variant():
    # Ruling R50: the last word, and for a name with particles all that follows the first name.
    txt = "Jane van der Berg and Katie Price sign."
    fs = [F(P, "Jane van der Berg", txt), F(P, "Katie Price", txt)]
    gs = by_canonical(group_findings(fs, txt, surnames=SURNAMES))
    assert {"Berg", "van der Berg"} <= gs["Jane van der Berg"].variants
    assert "Price" in gs["Katie Price"].variants
    assert "Berg" not in by_canonical(group_findings(fs, txt))["Jane van der Berg"].variants


def test_a_bare_surname_is_never_one_the_policy_refuses():
    txt = "Tom Never signs."
    (g,) = group_findings([F(P, "Tom Never", txt)], txt, surnames=SURNAMES)
    assert "Never" not in g.variants


def test_a_default_word_two_people_end_with_belongs_to_no_one():
    txt = "Katie Price and Tom Price sign. Price attends."
    fs = [F(P, "Katie Price", txt), F(P, "Tom Price", txt)]
    gs = group_findings(fs, txt, surnames=SURNAMES)
    assert len(gs) == 2 and all("Price" not in g.variants for g in gs)


def test_a_surname_two_people_share_is_checked_where_it_stands_as_a_name():
    txt = "John Smith and Jane Smith sign. Smith attends; the Smith file stays."
    fs = [F(P, "John Smith", txt), F(P, "Jane Smith", txt)]
    gs = by_canonical(group_findings(fs, txt, surnames=SURNAMES))
    (found,) = gs["Smith"].findings
    assert found.start == txt.index("Smith attends") and gs["Smith"].needs_check


def test_a_surname_that_is_another_persons_first_name_fits_neither():
    # Ruling R54 (reviewer's N4)
    txt = "Sarah James and James Wilson sign. James shall attend."
    fs = [F(P, "Sarah James", txt), F(P, "James Wilson", txt), F(P, "James", txt, last=True)]
    gs = by_canonical(group_findings(fs, txt, surnames=SURNAMES))
    assert gs["James"].needs_check and len(gs["James"].findings) == 1
    assert "James" not in gs["Sarah James"].variants


def test_a_word_that_joins_a_person_as_their_surname_must_stand_as_a_name():
    # Ruling R54 (reviewer's N2): the model's company "Lodge" after "the" is the term.
    txt = "Sam Lodge manages the site. The Lodge is open. Lodge shall attend."
    the_lodge = txt.index("The Lodge") + 4
    fs = [
        F(P, "Sam Lodge", txt),
        Finding(C, the_lodge, the_lodge + 5, "Lodge", 0.6, "model"),
        F(C, "Lodge", txt, last=True, score=0.6),
    ]
    (g,) = group_findings(fs, txt)
    assert [f.start for f in g.findings] == [0, txt.rindex("Lodge")]


def test_a_surname_the_engine_found_beside_a_capital_still_joins_its_person():
    # Ruling R56 (a): the engine saw a name there; only a determiner would make it a word.
    txt = "John Smith signs. Smith Holdings shall deliver."
    fs = [F(P, "John Smith", txt), F(P, "Smith", txt, last=True)]
    (g,) = group_findings(fs, txt)
    assert [f.text for f in g.findings] == ["John Smith", "Smith"]


def test_a_person_named_like_a_company_without_its_legal_form_joins_it():
    # Ruling R55 (reviewer's O3)
    txt = "Gıda Sanayi A.Ş. signs. Gıda Sanayi invoices."
    fs = [F(C, "Gıda Sanayi A.Ş.", txt, score=0.95), F(P, "Gıda Sanayi", txt, last=True)]
    (g,) = group_findings(fs, txt)
    assert g.type == C and len(g.findings) == 2


def test_a_shared_short_form_in_the_text_gets_a_group_of_its_own():
    txt = "John Smith and Jane Smith sign. J. Smith attends."
    gs = by_canonical(group_findings([F(P, "John Smith", txt), F(P, "Jane Smith", txt)], txt))
    assert set(gs) == {"John Smith", "Jane Smith", "J. Smith"}
    (found,) = gs["J. Smith"].findings
    assert found.start == txt.index("J. Smith") and found.source == "sweep"
    assert gs["J. Smith"].needs_check


def test_surname_with_particles():
    txt = "Jane van der Berg signs. Mrs van der Berg, J. van der Berg and Ms Berg agree."
    fs = [
        F(P, "Jane van der Berg", txt),
        F(P, "Mrs van der Berg", txt),
        F(P, "J. van der Berg", txt),
        F(P, "Ms Berg", txt),
    ]
    (g,) = group_findings(fs, txt)
    assert g.canonical == "Jane van der Berg" and len(g.findings) == 4 and not g.needs_check
    assert "J. van der Berg" in g.variants


def test_last_word_alone_needs_one_full_name_ending_in_it():
    txt = "Jane van der Berg and Tom Berg sign. Mr Berg attends."
    fs = [F(P, "Jane van der Berg", txt), F(P, "Tom Berg", txt), F(P, "Mr Berg", txt)]
    gs = by_canonical(group_findings(fs, txt))
    assert len(gs) == 3 and gs["Mr Berg"].needs_check


def test_a_surname_nobody_has_is_checked():
    txt = "Dear Mr Hartley, Hartley shall reply."
    fs = [F(P, "Mr Hartley", txt), F(P, "Hartley", txt, last=True)]
    gs = group_findings(fs, txt)
    assert all(g.needs_check for g in gs)


def test_a_company_short_name_the_model_took_for_a_person():
    txt = "Acme Supplies Ltd appoints. Acme signs."
    fs = [F(C, "Acme Supplies Ltd", txt), F(P, "Acme", txt, last=True, score=0.85)]
    (g,) = group_findings(fs, txt)
    assert g.type == C and [f.type for f in g.findings] == [C, C]


def test_a_person_the_model_took_for_a_company():
    txt = "Sandra Davies signs. S. Davies and Mr Davies attend. Acme Ltd pays."
    fs = [
        F(P, "Sandra Davies", txt),
        F(C, "S. Davies", txt, score=0.6),
        F(C, "Mr Davies", txt, score=0.6),
        F(P, "Acme Ltd", txt),  # a legal form: a company, whatever the model said
    ]
    gs = by_canonical(group_findings(fs, txt))
    assert [f.text for f in gs["Sandra Davies"].findings] == [
        "Sandra Davies",
        "S. Davies",
        "Mr Davies",
    ]
    assert all(f.type == P for f in gs["Sandra Davies"].findings)
    assert gs["Acme Ltd"].type == C


# --- Companies --------------------------------------------------------------------------------


def test_a_strong_name_wins_its_short_form_over_a_running_header():
    txt = (
        "Westerkade Insurance N.V. signs.\nWesterkade / Liffey — Data Processing Agreement\n"
        "Westerkade pays. Westerkade invoices."
    )
    header = "Westerkade / Liffey — Data Processing Agreement"
    fs = [
        F(C, "Westerkade Insurance N.V.", txt, score=0.95),
        F(C, header, txt, score=0.6),
        F(C, "Westerkade", txt, last=True, score=0.6),
    ]
    gs = by_canonical(group_findings(fs, txt))
    party = gs["Westerkade Insurance N.V."]
    assert [f.text for f in party.findings] == ["Westerkade Insurance N.V.", "Westerkade"]
    assert "Westerkade" in party.variants and "Westerkade" not in gs[header].variants
    assert gs[header].needs_check and not party.needs_check


def test_first_word_shared_by_two_companies_is_checked():
    txt = "Acme Supplies Ltd and Acme Logistics GmbH sign. Acme pays."
    fs = [
        F(C, "Acme Supplies Ltd", txt),
        F(C, "Acme Logistics GmbH", txt),
        F(C, "Acme", txt, last=True),
    ]
    gs = by_canonical(group_findings(fs, txt))
    assert len(gs) == 3 and gs["Acme"].needs_check
    assert "Acme" not in gs["Acme Supplies Ltd"].variants | gs["Acme Logistics GmbH"].variants


def test_two_legal_forms_are_two_companies():
    txt = "Northwind Trading B.V. and Northwind Trading GmbH sign. Northwind Trading pays."
    fs = [
        F(C, "Northwind Trading B.V.", txt),
        F(C, "Northwind Trading GmbH", txt),
        F(C, "Northwind Trading", txt, last=True),
    ]
    gs = by_canonical(group_findings(fs, txt))
    assert len(gs) == 3 and gs["Northwind Trading"].needs_check
    assert not gs["Northwind Trading B.V."].needs_check


@pytest.mark.parametrize(
    "names",
    [
        ("Özdemir Gıda Ltd. Şti.", "Özdemir Gıda Ltd. Sti.", "Özdemir Gıda"),
        ("Gıda Sanayi A.Ş.", "Gıda Sanayi A.S.", "Gıda Sanayi"),
        ("Northwind Trading B.V.", "NORTHWIND TRADING BV", "Northwind Trading"),
    ],
)
def test_one_legal_form_spelt_two_ways_is_one_company(names):
    # Important 3: case, dots, spaces and diacritics do not make another legal form.
    txt = f"{names[0]} signs; {names[1]} pays; {names[2]} delivers."
    (g,) = group_findings([F(C, name, txt) for name in names], txt)
    assert len(g.findings) == 3 and not g.needs_check


def test_a_company_with_a_leading_the_joins_its_name():
    # Raised minor M1: "the Acme" is keyed by its name, not by "theacme".
    txt = "Acme Supplies Ltd signs. the Acme pays."
    fs = [F(C, "Acme Supplies Ltd", txt), F(C, "the Acme", txt, score=0.6)]
    (g,) = group_findings(fs, txt)
    assert len(g.findings) == 2


def test_a_form_too_short_to_search_is_no_variant():
    # Raised minor M10 (decision 6): "5%" normalises to one character.
    percent = PlaceholderType.PERCENT
    txt = "A rebate of 5% and 12.5% applies."
    gs = by_canonical(group_findings([F(percent, "5%", txt), F(percent, "12.5%", txt)], txt))
    assert gs["5%"].variants == set() and gs["12.5%"].variants == {"12.5%"}


def test_ltd_and_limited_are_one_legal_form():
    txt = "Acme Supplies Ltd signs. ACME SUPPLIES LIMITED pays."
    fs = [F(C, "Acme Supplies Ltd", txt), F(C, "ACME SUPPLIES LIMITED", txt)]
    (g,) = group_findings(fs, txt)
    assert g.canonical == "ACME SUPPLIES LIMITED"


def test_a_company_is_named_without_a_leading_the():
    txt = "the Northwind Group signs; Northwind Group pays."
    fs = [F(C, "the Northwind Group", txt, score=0.6), F(C, "Northwind Group", txt, True, 0.6)]
    (g,) = group_findings(fs, txt)
    assert g.canonical == "Northwind Group" and len(g.findings) == 2


def test_canonical_prefers_ordinary_case_of_the_same_length():
    txt = "ACME SUPPLIES LTD signs. Acme Supplies Ltd pays."
    fs = [F(C, "ACME SUPPLIES LTD", txt), F(C, "Acme Supplies Ltd", txt)]
    (g,) = group_findings(fs, txt)
    assert g.canonical == "Acme Supplies Ltd"


# --- Other types, scores, order ------------------------------------------------------------------


def test_other_types_group_by_their_normalised_value():
    iban = PlaceholderType.IBAN
    txt = "IBAN NL91 ABNA 0417 1643 00, or NL91ABNA0417164300."
    fs = [F(iban, "NL91 ABNA 0417 1643 00", txt), F(iban, "NL91ABNA0417164300", txt)]
    (g,) = group_findings(fs, txt)
    assert {"NL91 ABNA 0417 1643 00", "NL91ABNA0417164300"} <= g.variants


def test_a_phone_number_with_and_without_its_country_code_is_one_value():
    phone = PlaceholderType.PHONE
    txt = (
        "Call 030 360 7352, from abroad +31 30 360 7352; in Dublin (01) 471 4299, +353 1 471 4299."
    )
    fs = [
        F(phone, "030 360 7352", txt),
        F(phone, "+31 30 360 7352", txt),
        F(phone, "(01) 471 4299", txt),
        F(phone, "+353 1 471 4299", txt),
    ]
    gs = by_canonical(group_findings(fs, txt))
    assert set(gs) == {"+31 30 360 7352", "+353 1 471 4299"}
    assert {"030 360 7352", "+31 30 360 7352"} <= gs["+31 30 360 7352"].variants
    assert len(gs["+353 1 471 4299"].findings) == 2


def test_a_national_form_two_numbers_share_joins_neither():
    phone = PlaceholderType.PHONE
    txt = "Utrecht +31 30 360 7352, Berlin +49 30 3607352, and 030 360 7352."
    fs = [
        F(phone, "+31 30 360 7352", txt),
        F(phone, "+49 30 3607352", txt),
        F(phone, "030 360 7352", txt),
    ]
    assert len(group_findings(fs, txt)) == 3


def test_a_value_seen_on_its_own_is_not_a_variant_of_another_group():
    amount = PlaceholderType.AMOUNT
    txt = "EUR 1,250,000 or USD 1,250,000; 1,250,000 in all."
    fs = [
        F(amount, "EUR 1,250,000", txt),
        F(amount, "USD 1,250,000", txt),
        F(amount, "1,250,000", txt, last=True),
    ]
    gs = by_canonical(group_findings(fs, txt))
    assert len(gs) == 3
    assert "1,250,000" not in gs["EUR 1,250,000"].variants | gs["USD 1,250,000"].variants


def test_best_score_decides_the_check():
    txt = "Riverside Partners and Riverside Partners"
    fs = [F(C, "Riverside Partners", txt, score=0.6), F(C, "Riverside Partners", txt, True)]
    (g,) = group_findings(fs, txt)
    assert not g.needs_check


def test_a_sweep_find_never_clears_the_check():
    txt = "Riverside Partners and Riverside Partners"
    swept = Finding(C, 23, 41, "Riverside Partners", 1.0, "sweep")
    (g,) = group_findings([F(C, "Riverside Partners", txt, score=0.6), swept], txt)
    assert g.needs_check


def test_groups_in_order_of_first_appearance():
    txt = "Jane Doe met Acme Supplies Ltd. Acme Supplies Ltd met Jane Doe and Bob Ray."
    fs = [
        F(C, "Acme Supplies Ltd", txt, last=True),
        F(P, "Bob Ray", txt),
        F(P, "Jane Doe", txt, last=True),
        F(C, "Acme Supplies Ltd", txt),
        F(P, "Jane Doe", txt),
    ]
    gs = group_findings(fs, txt)
    assert [g.canonical for g in gs] == ["Jane Doe", "Acme Supplies Ltd", "Bob Ray"]
    assert all(g.findings == sorted(g.findings, key=lambda f: f.start) for g in gs)
    assert all(g.placeholder == "" and g.enabled and not g.disabled for g in gs)
    assert len({g.id for g in gs}) == 3 and all(int(g.id, 16) >= 0 for g in gs)


def test_kept_variants_only():
    txt = "Total Logistics Ltd signs."
    (g,) = group_findings([F(C, "Total Logistics Ltd", txt)], txt, keep=lambda v: v != "Total")
    assert "Total" not in g.variants and "Total Logistics" in g.variants


def test_seed_groups_take_the_findings_of_their_variants():
    txt = "Acme shall deliver to Baltic Fasteners GmbH."
    variants = {"Acme Supplies Ltd", "Acme"}
    seed = Group(uuid.uuid4().hex, C, "Acme Supplies Ltd", variants, [], "[COMPANY_1]")
    fs = [F(C, "Acme", txt, score=0.6), F(C, "Baltic Fasteners GmbH", txt, score=0.95)]
    gs = by_canonical(group_findings(fs, txt, seeds=[seed]))
    assert gs["Acme Supplies Ltd"] is seed and seed.placeholder == "[COMPANY_1]"
    assert [f.text for f in seed.findings] == ["Acme"] and not seed.needs_check
    assert gs["Baltic Fasteners GmbH"].placeholder == ""
