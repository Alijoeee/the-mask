"""Contract-aware rules for parties, signatures, addresses and defined terms, and how the engine
uses them alongside the language model.

The tests that take the ``engine`` fixture go through ``Engine.analyze``; the others call the rules
directly, which need no language model.
"""

import time

import pytest

from themask.detect.contract_rules import (
    apply_rules,
    find_addresses,
    find_defined_terms,
    find_legal_form_companies,
    find_parties,
    find_signature_blocks,
    is_job_title,
)
from themask.model import Finding, PlaceholderType

PERSON = PlaceholderType.PERSON
COMPANY = PlaceholderType.COMPANY
ADDRESS = PlaceholderType.ADDRESS

# Typographic quotes, as Word puts them around a defined term.
OPEN, CLOSE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"
OPEN_SINGLE, CLOSE_SINGLE = "\N{LEFT SINGLE QUOTATION MARK}", "\N{RIGHT SINGLE QUOTATION MARK}"

PARTIES = (
    "THIS AGREEMENT is made on 1 March 2026\nBETWEEN:\n(1) Northwind Trading B.V., a company"
    " registered in the Netherlands under number 12345678, whose registered office is at"
    ' Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands (the "Supplier"); and\n(2) Acme'
    " Supplies Ltd, registered in England and Wales under number 01234567, whose registered"
    ' office is at 10 Downing Street, London SW1A 2AA (the "Buyer").'
)


def texts(fs, t):
    return {t[f.start : f.end] for f in fs}


def of_type(fs, placeholder_type):
    return [f for f in fs if f.type == placeholder_type]


# --- The brief's tests ---------------------------------------------------------------------------


def test_parties_found():
    fs, terms = apply_rules(PARTIES)
    assert {"Northwind Trading B.V.", "Acme Supplies Ltd"} <= texts(of_type(fs, COMPANY), PARTIES)
    assert terms == {"Supplier", "Buyer"}


def test_addresses_found():
    fs, _ = apply_rules(PARTIES)
    addr = texts(of_type(fs, ADDRESS), PARTIES)
    assert any(a.startswith("Keizersgracht 123") and a.endswith("Netherlands") for a in addr)
    assert any("SW1A 2AA" in a for a in addr)


def test_signature_block():
    t = (
        "SIGNED for and on behalf of the Supplier\nBy: ____\nName: Dr Jane Smith\n"
        "Title: Managing Director\nAttention: Mr Tom Brown"
    )
    fs, _ = apply_rules(t)
    assert {"Dr Jane Smith", "Mr Tom Brown"} <= texts(of_type(fs, PERSON), t)
    assert "Managing Director" not in texts(fs, t)


def test_jurisdiction_stays_visible(engine):
    fs = engine.analyze(
        "This Agreement is governed by the laws of the Netherlands and the courts of Amsterdam."
    )
    assert not of_type(fs, ADDRESS)


def test_model_person_in_prose(engine):
    t = "The notice was sent by Jane Smith to the Buyer on Monday."
    assert "Jane Smith" in texts(of_type(engine.analyze(t), PERSON), t)


def test_legal_form_company_in_prose(engine):
    t = "Supplies are sourced from Baltic Fasteners GmbH and its affiliates."
    assert "Baltic Fasteners GmbH" in texts(of_type(engine.analyze(t), COMPANY), t)


# --- apply_rules ---------------------------------------------------------------------------------


def test_rule_findings_are_in_text_order_and_carry_their_text():
    fs, _ = apply_rules(PARTIES)
    assert fs == sorted(fs, key=lambda f: (f.start, f.end))
    assert all(isinstance(f, Finding) and f.source == "rule" for f in fs)
    assert all(f.text == PARTIES[f.start : f.end] for f in fs)
    assert len({(f.type, f.start, f.end) for f in fs}) == len(fs)  # each one once


def test_rule_scores():
    fs, _ = apply_rules(PARTIES)
    by_text = {f.text: f.score for f in fs}
    assert by_text["Northwind Trading B.V."] == 0.95
    assert by_text["Acme Supplies Ltd"] == 0.95
    assert all(0.8 <= f.score <= 0.95 for f in fs)


def test_empty_text():
    assert apply_rules("") == ([], set())


# --- find_parties --------------------------------------------------------------------------------


def test_parties_with_and_without_a_legal_form():
    t = (
        "BETWEEN:\n(1) Northwind Trading, a company registered in the Netherlands (the"
        ' "Supplier"); and\n(2) Acme Supplies Ltd, a company registered in England (the "Buyer").'
    )
    fs = find_parties(t)
    assert {(f.type, f.text, f.score) for f in fs} == {
        (COMPANY, "Northwind Trading", 0.9),
        (COMPANY, "Acme Supplies Ltd", 0.95),
    }


def test_parties_in_prose():
    t = (
        "This Agreement is made between Acme Supplies Ltd, a company incorporated in England"
        " (company number 01234567), and Northwind Trading B.V., a company incorporated in the"
        " Netherlands."
    )
    assert texts(find_parties(t), t) == {"Acme Supplies Ltd", "Northwind Trading B.V."}


def test_parties_named_one_after_the_other():
    t = "This Agreement is made by and between Northwind Trading B.V. and Acme Supplies Ltd."
    assert texts(find_parties(t), t) == {"Northwind Trading B.V.", "Acme Supplies Ltd"}


def test_a_party_who_is_a_person():
    t = (
        'BETWEEN:\n(1) Mr John Carter of 12 Mill Lane, Leeds LS1 4AB (the "Consultant"); and\n'
        '(2) Acme Supplies Ltd (the "Client").'
    )
    fs = find_parties(t)
    assert {(f.type, f.text) for f in fs} == {
        (PERSON, "Mr John Carter"),
        (COMPANY, "Acme Supplies Ltd"),
    }


def test_parties_in_capitals_and_under_a_parties_heading():
    t = "PARTIES\n(1) NORTHWIND TRADING B.V.; and\n(2) THE MARLOWE PRINT AND PACKAGING LIMITED."
    assert texts(find_parties(t), t) == {
        "NORTHWIND TRADING B.V.",
        "MARLOWE PRINT AND PACKAGING LIMITED",
    }


def test_parties_clause_must_start_within_the_first_4000_characters():
    late = "x " * 2000 + 'BETWEEN:\n(1) Northwind Trading, a company (the "Supplier").'
    assert find_parties(late) == []


@pytest.mark.parametrize(
    "text",
    [
        "This Agreement governs the relationship between the Supplier and the Buyer.",
        "Any dispute between the parties shall be referred to the courts of England and Wales.",
        "between Supplier and Buyer",
        "BETWEEN:\n(1) the Supplier (as defined below); and\n(2) the Buyer.",
    ],
)
def test_parties_clause_without_names_finds_nothing(text):
    assert find_parties(text) == []


def test_jurisdiction_in_a_parties_clause_is_not_a_party():
    fs = find_parties(PARTIES)
    assert texts(fs, PARTIES) == {"Northwind Trading B.V.", "Acme Supplies Ltd"}


def test_parties_clause_ends_with_its_last_party():
    # From the corpus (supply-07-annex): numbered headings follow the parties straight away.
    t = (
        f"BETWEEN:\n(1) Isarthal Hygiene Systems GmbH, whose registered office is at"
        f" Friedrichstraße 73, 60466 Frankfurt am Main, Germany (the {OPEN}Supplier{CLOSE}); and\n"
        f"(2) Veldkamp Distribution B.V., whose registered office is at Weena 24, 3042 HW"
        f" Rotterdam, the Netherlands (the {OPEN}Buyer{CLOSE}).\n"
        "Words defined in the Agreement have the same meaning here.\n1. PRODUCTS\nProduct\n"
        "Lead time\n2. QUALITY CONTACTS\n2.1 Questions go to the Supplier.\n3. VALIDITY\n"
    )
    assert texts(find_parties(t), t) == {
        "Isarthal Hygiene Systems GmbH",
        "Veldkamp Distribution B.V.",
    }
    fs, _ = apply_rules(t)
    assert not {"PRODUCTS", "QUALITY CONTACTS", "VALIDITY", "Product", "Lead"} & texts(fs, t)


def test_parties_clause_ends_with_the_first_line_that_names_no_party():
    t = (
        'BETWEEN:\n(1) Northwind Trading B.V. (the "Supplier")\n\n(2) Acme Supplies Ltd (the'
        ' "Buyer")\nWords defined in the Agreement have the same meaning here.\n'
        "2. Delivery shall take place at the Site.\n"
    )
    assert texts(find_parties(t), t) == {"Northwind Trading B.V.", "Acme Supplies Ltd"}


def test_parties_clause_ends_at_a_heading():
    t = (
        'BETWEEN:\n(1) Northwind Trading (the "Supplier"); and\n(2) Acme Supplies\n'
        "BACKGROUND\nA. Smith"
    )
    assert texts(find_parties(t), t) == {"Northwind Trading", "Acme Supplies"}


# --- find_legal_form_companies -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Northwind Trading B.V.",
        "Northwind Trading BV",
        "Ambergate Foodservice N.V.",
        "Kronberg Medical AG",
        "Baltic Fasteners GmbH",
        "Thamesgate Catering plc",
        "Riverside Partners LLP",
        "Kestrel Analytics Limited",
        "Acme Supplies Ltd",
        "Acme, Inc.",
        "Smith & Co.",
        "Müller & Söhne GmbH & Co. KG",
        "Marmara Tekstil Ltd. Şti.",
        "Marmara Tekstil Ltd. Sti.",
        "Anadolu Gıda A.Ş.",
        "Nordic Parts A/S",
        "Nordic Parts AS",
        "Siemens SE",
        "Volvo AB",
        "Marlowe Print and Packaging Ltd",
        "Van der Valk Hotels B.V.",
        "Rolls-Royce Holdings plc",
        "O'Neill Foods Ltd",
        "NORTHWIND TRADING B.V.",
        "ACME SUPPLIES LTD",
    ],
)
def test_legal_form_companies(name):
    t = f"Each year we buy from {name} under the framework."
    (f,) = find_legal_form_companies(t)
    assert (f.type, f.text, f.score, f.source) == (COMPANY, name, 0.95, "rule")


@pytest.mark.parametrize(
    "text,names",
    [
        (
            "between Northwind Trading B.V. and Acme Supplies Ltd",
            {"Northwind Trading B.V.", "Acme Supplies Ltd"},
        ),
        ("Acme Ltd and Northwind B.V. agree", {"Acme Ltd", "Northwind B.V."}),
        ("the Supplier and Acme Ltd agree", {"Acme Ltd"}),
        ("Accordingly Acme Ltd shall pay.", {"Acme Ltd"}),
        ("In March Acme Ltd shall pay.", {"Acme Ltd"}),
        ("SIGNED for and on behalf of NORTHWIND TRADING B.V.", {"NORTHWIND TRADING B.V."}),
        ("SUPPLIER: Northwind Trading B.V.", {"Northwind Trading B.V."}),
        ("Acme Ltd's obligations survive.", {"Acme Ltd"}),
        ("(Acme Ltd)", {"Acme Ltd"}),
        ("We buy from Acme Ltd.", {"Acme Ltd"}),  # the full stop ends the sentence
        ("Acme Ltd. shall pay.", {"Acme Ltd."}),  # here it belongs to the abbreviation
        ("We buy from Northwind Trading B.V.", {"Northwind Trading B.V."}),
        ("Supplies come from Baltic Fasteners and Kronberg Medical AG.", {"Kronberg Medical AG"}),
        ("Alpha Beta Gamma Delta Epsilon Zeta Eta Ltd", {"Beta Gamma Delta Epsilon Zeta Eta Ltd"}),
    ],
)
def test_legal_form_company_boundaries(text, names):
    assert texts(find_legal_form_companies(text), text) == names


@pytest.mark.parametrize(
    "text",
    [
        "Acme is a limited company.",
        "the Company incorporated in England",
        "Each pallet weighs 500 kg.",
        "Net Weight kg",
        "THE GOODS AS DESCRIBED IN SCHEDULE 1",
        "PRODUCT LIMITED WARRANTY",
        "Goods such as these",
        "Co-operation between the parties",
        "The Supplier's liability is limited.",
        "Limited Warranty",
        "LIMITATION OF LIABILITY",
        "Nabisco Biscuits are sold.",
    ],
)
def test_no_legal_form_company(text):
    assert find_legal_form_companies(text) == []


# --- find_signature_blocks -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Name: John Carter\nTitle: Managing Director", {(PERSON, "John Carter")}),
        ("Name: JOHN CARTER", {(PERSON, "JOHN CARTER")}),
        ("Name: J. Carter", {(PERSON, "J. Carter")}),
        ("Name: Jane van der Berg", {(PERSON, "Jane van der Berg")}),
        ("Printed name: Laura Price", {(PERSON, "Laura Price")}),
        ("By: Laura Price", {(PERSON, "Laura Price")}),
        ("By: Northwind Trading B.V.", {(COMPANY, "Northwind Trading B.V.")}),
        ("Signed by: Laura Price", {(PERSON, "Laura Price")}),
        ("SIGNED by LAURA PRICE as a deed", {(PERSON, "LAURA PRICE")}),
        ("Attn: Ms Laura Price", {(PERSON, "Ms Laura Price")}),
        ("Attn. Ms Laura Price", {(PERSON, "Ms Laura Price")}),
        ("For the attention of: Mr Tom Brown", {(PERSON, "Mr Tom Brown")}),
        ("For the attention of Mr Tom Brown", {(PERSON, "Mr Tom Brown")}),
        ("FAO: Mr Tom Brown", {(PERSON, "Mr Tom Brown")}),
        ("Attention: Mr John Carter, Head of Sales", {(PERSON, "Mr John Carter")}),
        (
            "Attention: Mr John Carter and Ms Jane Doe",
            {(PERSON, "Mr John Carter"), (PERSON, "Ms Jane Doe")},
        ),
        ("Attention: Legal Department, Acme Supplies Ltd", {(COMPANY, "Acme Supplies Ltd")}),
        ("Name: Jane Smith Date: 1 March 2026", {(PERSON, "Jane Smith")}),
        ("Name:\tJane Smith\tName:\tTom Brown", {(PERSON, "Jane Smith"), (PERSON, "Tom Brown")}),
        ("Name:\nJohn Carter\nTitle:\nManaging Director", {(PERSON, "John Carter")}),
    ],
)
def test_signature_and_notice_names(text, expected):
    fs = find_signature_blocks(text)
    assert {(f.type, f.text) for f in fs} == expected
    assert all(f.score >= 0.9 for f in fs)


@pytest.mark.parametrize(
    "text",
    [
        "By: ______________________________\nName: ____________\nDate: ____________",
        "Name: [Name]",
        "Witness name: [Name]",
        "Title: Managing Director",
        "Attention: Legal Counsel",
        "Attention: the Managing Director",
        "Attention: Head of Legal",
        "Attention: Legal Department",
        "Name: Chief Executive Officer",
        "Name: Supplier",
        "Signed by the parties on the date above.",
        "SIGNED BY AND ON BEHALF OF THE SUPPLIER",
    ],
)
def test_signature_lines_without_a_name_find_nothing(text):
    assert find_signature_blocks(text) == []


@pytest.mark.parametrize(
    "text,name",
    [
        # From the corpus: the language model misses these.
        ("The account manager for the Buyer is Mr Bennett (telephone 030 360 7352).", "Mr Bennett"),
        (
            "The Buyer's quality team is led by Mr Dean Andrews, who may be reached",
            "Mr Dean Andrews",
        ),
        ("Copies go to Dr. Jane Smith.", "Dr. Jane Smith"),
        ("Copies go to Mevr. van der Berg.", "Mevr. van der Berg"),
        ("COPIES GO TO MR JOHN SMITH", "MR JOHN SMITH"),
        ("Copies go to Prof. Dr. Hans Müller", "Prof. Dr. Hans Müller"),
    ],
)
def test_a_name_after_an_honorific_is_a_person(text, name):
    fs, _ = apply_rules(text)
    assert {(f.type, f.text, f.score) for f in fs} == {(PERSON, name, 0.9)}


@pytest.mark.parametrize(
    "text",
    ["Dear Sir or Madam,", "Join the call on MS Teams.", "Mr Chairman, the meeting is open.", "Mr"],
)
def test_an_honorific_without_a_name_finds_nothing(text):
    assert apply_rules(text) == ([], set())


@pytest.mark.parametrize(
    "title",
    [
        "Director",
        "Managing Director",
        "CEO",
        "Chief Executive Officer",
        "Legal Counsel",
        "General Counsel",
        "Head of Sales",
        "Company Secretary",
        "Data Protection Officer",
        "Procurement Manager",
        "Legal Department",
        "VP Sales",
    ],
)
def test_job_titles(title):
    assert is_job_title(title)


@pytest.mark.parametrize(
    "name", ["Jane Smith", "Laura Price", "Mr Tom Brown", "Laura Head", "Northwind", ""]
)
def test_names_are_not_job_titles(name):
    assert not is_job_title(name)


# --- find_addresses ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,address",
    [
        (
            "Address: Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands\nE-mail: x@y.example",
            "Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands",
        ),
        (
            "Registered office: 10 Downing Street, London SW1A 2AA",
            "10 Downing Street, London SW1A 2AA",
        ),
        (
            (
                "having its registered office at Friedrichstraße 123, 10117 Berlin, Germany, and"
                " its VAT number DE123456789"
            ),
            "Friedrichstraße 123, 10117 Berlin, Germany",
        ),
        (
            'with its principal place of business at 12 Mill Lane, Leeds LS1 4AB (the "Site")',
            "12 Mill Lane, Leeds LS1 4AB",
        ),
        (
            "whose registered office is at Weena 12, 3011 AB Rotterdam; and",
            "Weena 12, 3011 AB Rotterdam",
        ),
        (
            'whose registered office is at 10 Downing Street, London SW1A 2AA, "the Buyer"',
            "10 Downing Street, London SW1A 2AA",
        ),
        ("Deliveries go to 12 Mill Lane, Leeds LS1 4AB.", "12 Mill Lane, Leeds LS1 4AB"),
        (
            "The warehouse at Industrieweg 12, 3044 AS Rotterdam is open.",
            "Industrieweg 12, 3044 AS Rotterdam",
        ),
        (
            "Collect from Berliner Straße 12, 60311 Frankfurt am Main by noon.",
            "Berliner Straße 12, 60311 Frankfurt am Main",
        ),
        (
            "Ship to Büyükdere Caddesi No: 185, 34394 Istanbul, Turkey (attention: stores)",
            "Büyükdere Caddesi No: 185, 34394 Istanbul, Turkey",
        ),
        ("Ship to Gül Sok. No. 3, 06100 Ankara.", "Gül Sok. No. 3, 06100 Ankara"),
        (
            "Ship to 12 rue de la Paix, 75002 Paris, France.",
            "12 rue de la Paix, 75002 Paris, France",
        ),
        (
            "Ship to 12 Harcourt Street, Dublin 2, D02 X285, Ireland.",
            "12 Harcourt Street, Dublin 2, D02 X285, Ireland",
        ),
        (
            "Ship to Unit 5, 12 St John's Road, Bristol BS1 2AB today.",
            "Unit 5, 12 St John's Road, Bristol BS1 2AB",
        ),
        (
            "Address: Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands, VAT number NL1",
            "Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands",
        ),
        (
            "Address: Northwind Trading B.V., Keizersgracht 123, 1015 CJ Amsterdam",
            "Keizersgracht 123, 1015 CJ Amsterdam",
        ),
        ("Address:\nKeizersgracht 123, 1015 CJ Amsterdam", "Keizersgracht 123, 1015 CJ Amsterdam"),
    ],
)
def test_addresses(text, address):
    assert texts(find_addresses(text), text) == {address}


def test_address_lines_each_give_an_address():
    t = "Northwind Trading B.V.\nKeizersgracht 123\n1015 CJ Amsterdam\nthe Netherlands"
    assert texts(find_addresses(t), t) == {"Keizersgracht 123", "1015 CJ Amsterdam"}


def test_address_scores():
    # An address after its label or a registered-office phrase, a street, a postcode alone.
    t = "Address: Weena 12, 3011 AB Rotterdam\nDeliver to 12 Mill Lane, Leeds.\n3011 AB Rotterdam"
    scores = {f.text: f.score for f in find_addresses(t)}
    assert scores == {
        "Weena 12, 3011 AB Rotterdam": 0.9,
        "12 Mill Lane, Leeds": 0.85,
        "3011 AB Rotterdam": 0.8,
    }


@pytest.mark.parametrize(
    "text",
    [
        "This Agreement is governed by the laws of the Netherlands and the courts of Amsterdam.",
        "a company registered in England and Wales under number 01234567",
        "a company registered in the Netherlands under number 12345678",
        "the competent court in Amsterdam shall have exclusive jurisdiction",
        "Each party submits to the courts of Hamburg.",
        "Schedule 3 sets out the prices.",
        "SCHEDULE 3\nPRICES AND REBATES",
        "under clause 12 High Court proceedings",
        "within 30 days of 1 March 2026",
        "a minimum of 10,000 units at EUR 12,345.00",
        "Address: as set out in Schedule 1",
        "Address: the Supplier's registered office",
        "notices go to the registered office of the Supplier",
        "whose registered office is in Amsterdam",
        "IBAN NL91 ABNA 0417 1643 00, VAT number NL123456782B01",
        "3000 MT of steel and 1500 KG of copper",
        "2026 EU Member States",
        "50000 Euros are due.",
        "E-mail address: j.smith@northwind.example",
        "Address:\nName: John Carter",  # a label on the next line is no value
        "Registered office:\nTelephone: +31 20 123 4567",
    ],
)
def test_no_address(text):
    assert find_addresses(text) == []


def test_a_label_on_the_next_line_is_no_name():
    t = "By:\nName: Jane Smith\nAttention:\nAddress: 12 Mill Lane, Leeds"
    assert {(f.type, f.text) for f in find_signature_blocks(t)} == {(PERSON, "Jane Smith")}


def test_an_address_has_at_most_eight_parts():
    t = "Deliver to 12 Mill Lane, " + ", ".join(["Leeds"] * 20) + "."
    (f,) = find_addresses(t)
    assert f.text == "12 Mill Lane, " + ", ".join(["Leeds"] * 7)


# --- find_defined_terms --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,terms",
    [
        ('Northwind Trading B.V. (the "Supplier")', {"Supplier"}),
        ('Acme Supplies Ltd ("Buyer")', {"Buyer"}),
        (f"Acme Supplies Ltd (the {OPEN}Buyer{CLOSE})", {"Buyer"}),
        (f"Acme Supplies Ltd (the {OPEN_SINGLE}Buyer{CLOSE_SINGLE})", {"Buyer"}),
        ("Acme Supplies Ltd (the 'Buyer')", {"Buyer"}),
        ('Acme Supplies Ltd (hereinafter "Buyer")', {"Buyer"}),
        ('Acme Supplies Ltd (hereinafter referred to as the "Buyer")', {"Buyer"}),
        ('Acme Supplies Ltd, hereinafter "the Buyer", shall', {"Buyer"}),
        ('(each a "Party" and together the "Parties")', {"Party", "Parties"}),
        ('"Business Day" means a day other than a Saturday.', {"Business Day"}),
        (
            f"1.1 {OPEN}Confidential Information{CLOSE} means all information.",
            {"Confidential Information"},
        ),
    ],
)
def test_defined_terms(text, terms):
    assert find_defined_terms(text) == terms


@pytest.mark.parametrize(
    "text",
    [
        'He said "hello" to the Buyer.',
        '(see "Annex 1")',
        "(company number 01234567)",
        'Acme Supplies Ltd (the "")',
    ],
)
def test_quotes_that_define_nothing(text):
    assert find_defined_terms(text) == set()


def test_a_short_name_of_a_party_is_hidden_not_a_term():
    t = (
        'Acme Supplies Ltd ("Acme") and Northwind Trading B.V. (hereinafter "Northwind") agree'
        ' with Kestrel Analytics Limited ("KAL") that Acme shall pay (the "Price").'
    )
    assert find_defined_terms(t) == {"Price"}
    fs, terms = apply_rules(t)
    assert terms == {"Price"}
    shorts = {(f.type, f.start) for f in fs if f.text in {"Acme", "Northwind", "KAL"}}
    assert shorts == {
        (COMPANY, t.index('"Acme"') + 1),
        (COMPANY, t.index('"Northwind"') + 1),
        (COMPANY, t.index('"KAL"') + 1),
    }


def test_a_short_name_of_a_person_is_hidden_not_a_term():
    t = 'BETWEEN:\n(1) Mr John Carter ("Carter"); and\n(2) Acme Supplies Ltd (the "Client").'
    fs, terms = apply_rules(t)
    assert terms == {"Client"}
    assert (PERSON, "Carter") in {(f.type, f.text) for f in fs}


# --- Never findings from the rules (controller decision 7) ---------------------------------------

NEVER_FINDINGS = [
    "This Agreement is governed by the laws of the Netherlands and the courts of Amsterdam.",
    "Each party submits to the exclusive jurisdiction of the courts of England and Wales.",
    "Title: Managing Director\nTitle: Chief Executive Officer\nTitle: Legal Counsel",
    "Attention: Legal Counsel\nAttention: the Company Secretary",
    'The Supplier shall deliver the Goods to the Buyer (each a "Party").',
    "The Effective Date is in January. Payment is due in February, March and April.",
    "On Monday 3 June the Buyer pays. Delivery in May 2026.",
    "Schedule 3 applies. See Annex B and Appendix 2.",
    "SUPPLIER\nTERMINATION\nDEFINITIONS AND INTERPRETATION\nSCHEDULE 3\nGOVERNING LAW",
    "1. TERMINATION\n1.1 Either party may terminate this Agreement.",
]


@pytest.mark.parametrize("text", NEVER_FINDINGS)
def test_never_findings_from_the_rules(text):
    fs, _ = apply_rules(text)
    assert not [f for f in fs if f.type in {PERSON, COMPANY, ADDRESS}]


def test_rules_are_quick_on_a_long_contract():
    clause = (
        PARTIES + "\nThe Supplier shall deliver 10,000 units to 12 Mill Lane, Leeds LS1 4AB within"
        " 30 days. Name: Jane Smith\nTitle: Director\nAttention: Mr Tom Brown, Head of Sales\n"
    )
    text = clause * (12_000 // len(clause.split()) + 1)  # about 12,000 words
    start = time.perf_counter()
    apply_rules(text)
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    "text",
    [
        "12 High Street, London SW1A 2AA, " * 3000,  # one line of addresses
        "London SW1A 2AA " * 6000,
        "Name: \nAttention: \nAddress: \n" * 5000,
        'Acme Supplies Ltd ("Acme"), ' * 3000,
        " ".join(f'Company{n} Ltd ("C{n}")' for n in range(3000)),
    ],
    ids=["addresses", "postcodes", "labels", "short-names", "distinct-short-names"],
)
def test_rules_are_quick_on_texts_made_to_be_slow(text):
    start = time.perf_counter()
    apply_rules(text)
    assert time.perf_counter() - start < 2.0


# --- The engine with the rules (controller decision 4) -------------------------------------------


def test_engine_merges_the_rule_findings(engine):
    fs = engine.analyze(PARTIES)
    by_text = {(f.type, f.text): f.source for f in fs}
    assert by_text[(COMPANY, "Northwind Trading B.V.")] == "rule"
    assert by_text[(COMPANY, "Acme Supplies Ltd")] == "rule"
    assert by_text[(ADDRESS, "10 Downing Street, London SW1A 2AA")] == "rule"


def test_a_rule_finding_beats_the_model_on_the_same_span(engine):
    t = "Supplies are sourced from Baltic Fasteners GmbH and its affiliates."
    (f,) = of_type(engine.analyze(t), COMPANY)
    assert (f.text, f.source, f.score) == ("Baltic Fasteners GmbH", "rule", 0.95)


def test_model_places_are_kept_only_at_an_address(engine):
    fs = engine.analyze(PARTIES)
    places = {f.text for f in fs if f.type == ADDRESS and f.source == "model"}
    assert places  # the model's parts of the two addresses
    registered_in = PARTIES.index("the Netherlands under")
    for f in fs:
        if f.type == ADDRESS:
            assert not f.start <= registered_in + 4 < f.end  # "registered in the Netherlands"
            assert f.text not in {"England", "Wales"}


def test_model_company_without_a_legal_form_is_marked_for_checking(engine):
    # The model scores it 0.85: without a legal form or a rule behind it, it is capped at 0.6.
    t = "The goods are carried by Glenmore Freight to the warehouse."
    (f,) = of_type(engine.analyze(t), COMPANY)
    assert (f.text, f.source, f.score) == ("Glenmore Freight", "model", 0.6)


def test_model_findings_never_cross_a_line(engine):
    t = (
        "SUPPLIER\nNorthwind Trading B.V.\nCUSTOMER\nAcme Supplies Ltd\n"
        "Attention: Ms Laura Price, Legal Counsel\n"
        "Address: 12 High Street, Leeds LS1 4AB, United Kingdom\n"
    )
    fs = engine.analyze(t)
    assert not [f for f in fs if "\n" in f.text]
    found = texts(fs, t)
    assert not found & {"SUPPLIER", "CUSTOMER", "Attention", "Address", "Legal Counsel"}
    assert {"Northwind Trading B.V.", "Acme Supplies Ltd", "Ms Laura Price"} <= found


def test_title_lines_and_job_titles_are_never_findings(engine):
    t = (
        "Name: John Carter\nTitle: Managing Director\nName: Laura Price\n"
        "Title: Chief Executive Officer\nAttention: Legal Counsel"
    )
    fs = engine.analyze(t)
    assert texts(of_type(fs, PERSON), t) == {"John Carter", "Laura Price"}
    for title in ("Managing Director", "Chief Executive Officer", "Legal Counsel"):
        start = t.index(title)
        assert not [f for f in fs if f.start < start + len(title) and start < f.end]
