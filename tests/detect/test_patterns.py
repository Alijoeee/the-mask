"""The detection engine and its pattern recognizers.

Most tests go through the session-scoped ``engine`` fixture, the way the analysis pipeline uses it.
A test that a recognizer does not fire runs that recognizer on its own, so that a find by another
recognizer in the same text cannot hide its mistake.
"""

import time

import pytest

from themask.detect.engine import MIN_SCORE, PHONE_REGIONS, Engine
from themask.detect.patterns import (
    AccountNumberRecognizer,
    AmountRecognizer,
    BareNumberRecognizer,
    BicRecognizer,
    EmailAddressRecognizer,
    NationalIdRecognizer,
    PercentRecognizer,
    QuantityRecognizer,
    RegistrationNumberRecognizer,
    VatRecognizer,
    WebAddressRecognizer,
)
from themask.model import PlaceholderType

AMOUNT = PlaceholderType.AMOUNT
PERCENT = PlaceholderType.PERCENT
QUANTITY = PlaceholderType.QUANTITY
ID = PlaceholderType.ID

# The spaces Word may put between groups of digits, named so that nobody has to tell them apart
# by eye.
NBSP = "\N{NO-BREAK SPACE}"
NARROW_NBSP = "\N{NARROW NO-BREAK SPACE}"
THIN_SPACE = "\N{THIN SPACE}"


def types_at(engine, text, needle):
    return {f.type for f in engine.analyze(text) if text[f.start : f.end].strip() == needle}


def texts_of(engine, text, placeholder_type):
    """The exact text of every finding of one type."""
    return {f.text for f in engine.analyze(text) if f.type == placeholder_type}


def found_by(recognizer, text):
    """What one recognizer finds in ``text`` on its own: matched text -> score."""
    results = recognizer.analyze(text, recognizer.supported_entities)
    return {text[r.start : r.end]: r.score for r in results}


# --- Amounts -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,needle",
    [
        ("The Price is EUR 1,250,000.00 per year.", "EUR 1,250,000.00"),
        ("a fee of €1.25m", "€1.25m"),
        ("pay 1.250.000,00 EUR", "1.250.000,00 EUR"),
        ("the sum of one million euros", "one million euros"),
        ("EUR 1 250 000,00", "EUR 1 250 000,00"),
        ("GBP 48,000", "GBP 48,000"),
    ],
)
def test_amounts(engine, text, needle):
    assert PlaceholderType.AMOUNT in types_at(engine, text, needle)


@pytest.mark.parametrize(
    "text,needle",
    [
        (f"EUR 1{NBSP}250{NBSP}000,00", f"EUR 1{NBSP}250{NBSP}000,00"),
        (
            f"EUR{NBSP}1{NARROW_NBSP}250{NARROW_NBSP}000,00",
            f"EUR{NBSP}1{NARROW_NBSP}250{NARROW_NBSP}000,00",
        ),
        (f"a price of 1{THIN_SPACE}250{THIN_SPACE}000 € net", f"1{THIN_SPACE}250{THIN_SPACE}000 €"),
        ("a cap of £500k", "£500k"),
        ("USD 2.3bn in total", "USD 2.3bn"),
        ("EUR 3 million", "EUR 3 million"),
        ("1.5 million euros", "1.5 million euros"),
        ("a deposit of 1.000 € is due", "1.000 €"),
        ("€ 1.000,- per month", "€ 1.000,-"),
        ("CHF 1'250'000.00", "CHF 1'250'000.00"),
        ("US$ 5,000", "US$ 5,000"),
        ("EUR 0.125 per piece", "EUR 0.125"),
        ("between EUR 10-20 per unit", "EUR 10-20"),
        ("TRY 75,000", "TRY 75,000"),
        ("250.000 TL", "250.000 TL"),
        ("fifty thousand pounds sterling", "fifty thousand pounds sterling"),
        ("two hundred and fifty thousand euros", "two hundred and fifty thousand euros"),
        ("Twenty-Five Thousand Euros", "Twenty-Five Thousand Euros"),
        ("fifty thousand (50,000) euros", "fifty thousand (50,000) euros"),
    ],
)
def test_amounts_in_more_forms(engine, text, needle):
    assert AMOUNT in types_at(engine, text, needle)


@pytest.mark.parametrize(
    "text,value",
    [
        ("The fee is EUR 1,000.", "EUR 1,000"),
        ("EUR 1,000, payable monthly", "EUR 1,000"),
        ("a deposit (EUR 1,000) is due", "EUR 1,000"),
        ("the fee is €1.25m; the deposit", "€1.25m"),
    ],
)
def test_amount_never_includes_trailing_punctuation(engine, text, value):
    assert texts_of(engine, text, AMOUNT) == {value}


@pytest.mark.parametrize(
    "text",
    [
        "within 30 days",
        "in 2026",
        "clause 10.2 applies",
        "a term of 5 years",
        "Schedule 3",
    ],
)
def test_not_amount_or_quantity(engine, text):
    assert not {PlaceholderType.AMOUNT, PlaceholderType.QUANTITY} & {
        f.type for f in engine.analyze(text)
    }


@pytest.mark.parametrize(
    "text",
    [
        "10.2 The Supplier shall deliver the Goods.",
        "12.3.4 Delivery",
        "as set out in Section 4.1(b)",
        "for 1,000 days",
        "within 2,500 working days",
        "Vehicles shall meet the Euro 6 emission standard.",
        "under Regulation (EU) 2016/679",
        "section 1159 of the Companies Act 2006",
        "on 01.03.2026",
        "between 09:00 and 17:00 hours",
    ],
)
def test_clause_numbers_dates_and_durations_are_not_amounts(engine, text):
    assert not {AMOUNT, QUANTITY} & {f.type for f in engine.analyze(text)}


@pytest.mark.parametrize(
    "text",
    [
        "Total price: 48,000",
        "minimum order of 10,000 units",
        "a discount of 12.5%",
        "a period of 30 days",
        "the year 2026",
        "Euro 6",
        "try 1,000 times",
    ],
)
def test_amount_needs_a_currency(text):
    assert found_by(AmountRecognizer(), text) == {}


# --- Percentages ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,needle",
    [("a discount of 12.5%", "12.5%"), ("interest at 8 per cent", "8 per cent")],
)
def test_percent(engine, text, needle):
    assert PlaceholderType.PERCENT in types_at(engine, text, needle)


@pytest.mark.parametrize(
    "text,needle",
    [
        ("a rebate of 12,5 %", "12,5 %"),
        (f"a rebate of 12.5{NBSP}%", f"12.5{NBSP}%"),
        ("8 percent a year", "8 percent"),
        ("a margin of five per cent", "five per cent"),
        ("a margin of five (5) per cent", "five (5) per cent"),
        ("a margin of five (5%)", "five (5%)"),
        ("a discount of 5-10%", "5-10%"),
        ("Seven Percent", "Seven Percent"),
    ],
)
def test_percent_in_more_forms(engine, text, needle):
    assert PERCENT in types_at(engine, text, needle)


@pytest.mark.parametrize(
    "text",
    ["a percentage of the Price", "the 95 percentile", "a few per cent", "per cent", "EUR 12.50"],
)
def test_percent_needs_a_number_and_a_percent_sign_or_word(text):
    assert found_by(PercentRecognizer(), text) == {}


# --- Quantities ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,needle",
    [
        ("minimum order of 10,000 units", "10,000 units"),
        ("deliver 48 pallets", "48 pallets"),
        ("capacity of 2.5 tonnes", "2.5 tonnes"),
    ],
)
def test_quantity(engine, text, needle):
    assert PlaceholderType.QUANTITY in types_at(engine, text, needle)


@pytest.mark.parametrize(
    "text,needle",
    [
        ("500kg of resin", "500kg"),
        ("1,000 Cartons", "1,000 Cartons"),
        (f"10{NBSP}000 units", f"10{NBSP}000 units"),
        ("a floor area of 1 250 m²", "1 250 m²"),
        ("a load of 2.5t", "2.5t"),
        ("20 litres", "20 litres"),
        ("10-20 pallets", "10-20 pallets"),
        ("2.5 million units", "2.5 million units"),
        ("ten (10) pallets", "ten (10) pallets"),
        ("ten thousand units", "ten thousand units"),
    ],
)
def test_quantity_in_more_forms(engine, text, needle):
    assert QUANTITY in types_at(engine, text, needle)


# The volume of personal data a data processing agreement covers is a quantity too.
@pytest.mark.parametrize(
    "text,needle",
    [
        ("The processing concerns up to 350,000 records about", "350,000 records"),
        ("up to 400.000 records", "400.000 records"),
        (f"up to 90{NBSP}000 records", f"90{NBSP}000 records"),
    ],
)
def test_records_are_a_quantity(text, needle):
    assert found_by(QuantityRecognizer(), text) == {needle: 0.8}


@pytest.mark.parametrize(
    "text",
    [
        "the Article 30 records of processing activities",
        "under clause 12 records shall be kept",
        "Section 5 pallets",
        "keep 1 record of each order",
        "the records of the Supplier",
    ],
)
def test_a_reference_or_a_single_record_is_no_quantity(text):
    assert found_by(QuantityRecognizer(), text) == {}


@pytest.mark.parametrize(
    "text",
    [
        "within 30 days",
        "a term of 5 years",
        "12 hours",
        "3 months",
        "2 weeks",
        "45 minutes",
        "Schedule 3",
        "a fee of €2.5m",
        "EUR 2.5 m",
        "in two cases",
        "one item of the Goods",
        "clause 10.2 applies",
    ],
)
def test_quantity_needs_a_unit_that_is_not_time(text):
    assert found_by(QuantityRecognizer(), text) == {}


# --- Bank details --------------------------------------------------------------------------------


def test_iban_valid_only(engine):
    assert PlaceholderType.IBAN in types_at(
        engine, "IBAN NL91 ABNA 0417 1643 00", "NL91 ABNA 0417 1643 00"
    )
    assert PlaceholderType.IBAN not in {
        f.type for f in engine.analyze("IBAN NL91 ABNA 0417 1643 01")
    }


def test_bic(engine):
    assert PlaceholderType.ID in types_at(engine, "BIC: ABNANL2A", "ABNANL2A")


@pytest.mark.parametrize(
    "text,needle",
    [
        ("BIC: ABNANL2A", "ABNANL2A"),
        ("BIC RABONL2U", "RABONL2U"),
        ("SWIFT: DEUTDEFF", "DEUTDEFF"),
        ("SWIFT code DEUTDEFF500", "DEUTDEFF500"),
        ("BIC/SWIFT code: DEUTDEFF", "DEUTDEFF"),
        ("BIC (SWIFT): DEUTDEFF", "DEUTDEFF"),
        ("IBAN DE89 3704 0044 0532 0130 00, BIC DEUTDEFF", "DEUTDEFF"),
        ("Bank: HSBC UK, HSBCGB2L", "HSBCGB2L"),
    ],
)
def test_bic_in_more_forms(text, needle):
    assert found_by(BicRecognizer(), text) == {needle: 0.9}


# A BIC's label counts only on its own line, directly before the code.
HEADINGS_AFTER_A_BIC = (
    "IBAN: NL91 ABNA 0417 1643 00\nBIC: ABNANL2A\nSUPPLIER: Northwind Trading B.V.\n"
    "CUSTOMER: Acme Supplies Ltd"
)


def test_headings_after_a_bic_are_never_findings(engine):
    assert not {"SUPPLIER", "CUSTOMER"} & {f.text for f in engine.analyze(HEADINGS_AFTER_A_BIC)}
    assert found_by(BicRecognizer(), HEADINGS_AFTER_A_BIC) == {"ABNANL2A": 0.9}


@pytest.mark.parametrize(
    "text",
    [
        # Upper-case contract words that are BICs in form (SUPPLIER: bank SUPP, country LI).
        "THE SUPPLIER SHALL INDEMNIFY THE CUSTOMER",
        "TERMINATION",
        "DEFINITIONS AND INTERPRETATION",
        "ARBITRATION",
        "abnanl2a",
        "ABNAXX2A",
        "SWIFT\nDEUTDEFF",
        "the BIC of the SUPPLIER",
    ],
)
def test_bic_needs_a_real_one(text):
    assert found_by(BicRecognizer(), text) == {}


def test_a_bic_after_its_label_and_a_tab(engine):
    # Forms in Word put a tab between a label and its value.
    assert found_by(BicRecognizer(), "BIC:\tDEUTDEBB") == {"DEUTDEBB": 0.9}


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Account number: 12345678", "12345678"),
        ("account no. 1234 5678 90", "1234 5678 90"),
        ("A/C 87654321", "87654321"),
        ("Sort code: 12-34-56", "12-34-56"),
        ("sort code 12 34 56, account 12345678", "12 34 56"),
    ],
)
def test_account_numbers(engine, text, needle):
    assert ID in types_at(engine, text, needle)


@pytest.mark.parametrize(
    "text",
    [
        "on account of 2,000,000 units",
        "taking into account the 12 months",
        "Account: NL91 ABNA 0417 1643 00",
        "12345678",
        "the account holder is Acme Supplies Ltd",
        "the account holder, 12345678",
        "taking into account the 01-03-2026 forecast",
        "Account: 01-03-2026",
        "account 2026-03-01",
        "account\n12345678",
    ],
)
def test_account_number_needs_its_label(text):
    assert found_by(AccountNumberRecognizer(), text) == {}


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Account number:\t12345678", "12345678"),
        ("The account number is 12345678.", "12345678"),
        ("Sort code is 12-34-56", "12-34-56"),
        ("Account number: 1234-56-78", "1234-56-78"),  # no date: there is no 56th month
    ],
)
def test_account_numbers_in_more_forms(text, needle):
    assert found_by(AccountNumberRecognizer(), text) == {needle: 0.7}


def test_a_mistyped_iban_after_its_label_is_an_id_to_check(engine):
    # A wrong check digit: Presidio's IBAN recognizer turns it down, but it is the party's number.
    text = "IBAN: NL91 ABNA 0417 1643 01"
    assert found_by(AccountNumberRecognizer(), text) == {"NL91 ABNA 0417 1643 01": 0.6}
    assert ID in types_at(engine, text, "NL91 ABNA 0417 1643 01")
    # A valid one is Presidio's, found as an IBAN.
    assert found_by(AccountNumberRecognizer(), "IBAN: NL91 ABNA 0417 1643 00") == {}


def test_a_labelled_number_shaped_like_a_date_is_still_an_id(engine):
    assert ID in types_at(engine, "Company No. 12/2024", "12/2024")


# --- VAT, registration and identity numbers ------------------------------------------------------


def test_vat(engine):
    assert PlaceholderType.ID in types_at(engine, "VAT number NL123456782B01", "NL123456782B01")


@pytest.mark.parametrize(
    "text,needle,score",
    [
        ("VAT number NL123456782B01", "NL123456782B01", 0.9),
        ("BTW NL 1234.56.782.B01", "NL 1234.56.782.B01", 0.9),
        ("USt-IdNr. DE 136 695 976", "DE 136 695 976", 0.9),
        ("VAT: BE0123456749", "BE0123456749", 0.9),
        ("VAT: ATU13585627", "ATU13585627", 0.9),
        ("VAT: FR40303265045", "FR40303265045", 0.9),
        ("VAT registration GB980780684", "GB980780684", 0.9),
        ("MWST CHE-107.787.577 IVA", "CHE-107.787.577 IVA", 0.9),
        ("Org.nr. NO 995 525 828 MVA", "NO 995 525 828 MVA", 0.9),
        # The right form, a wrong check digit: still hidden, as a value to check.
        ("VAT number NL123456789B01", "NL123456789B01", 0.6),
        ("VAT: DE123456789", "DE123456789", 0.6),
    ],
)
def test_vat_scores(text, needle, score):
    assert found_by(VatRecognizer(), text) == {needle: score}


@pytest.mark.parametrize(
    "text",
    [
        "NL1234",
        "IBAN DE89 3704 0044 0532 0130 00",
        "IBAN NL91 ABNA 0417 1643 00",
        "the DE team",
        "postcode DE-80331",
        "nl123456782b01",
    ],
)
def test_vat_needs_a_country_and_its_format(text):
    assert found_by(VatRecognizer(), text) == {}


def test_registration(engine):
    assert PlaceholderType.ID in types_at(
        engine, "registered in England and Wales under number 01234567", "01234567"
    )


# What the label before a number calls it beats what else its digits could be: Presidio's phone
# recognizer takes "number" for its own context word, and its NHS recognizer reads the 3-3-4 shape
# of many national phone numbers.
@pytest.mark.parametrize(
    "text,needle",
    [
        ("registered in England and Wales under number 08846969, whose office", "08846969"),
        ("Account number: 08846969", "08846969"),
    ],
)
def test_a_number_its_label_calls_an_id_is_no_phone_number(engine, text, needle):
    types = types_at(engine, text, needle)
    assert ID in types and PlaceholderType.PHONE not in types


@pytest.mark.parametrize(
    "text",
    [
        "the account manager is Ms Smith (telephone 013 625 5086), who shall",
        "Tel: 013 625 5086",
        "Phone: 013 625 5086",
    ],
)
def test_a_number_its_label_calls_a_telephone_number_is_no_nhs_number(engine, text):
    types = types_at(engine, text, "013 625 5086")
    assert PlaceholderType.PHONE in types and ID not in types


def test_an_nhs_number_without_a_telephone_label_is_still_an_id(engine):
    assert ID in types_at(engine, "NHS number 943 476 5919", "943 476 5919")


@pytest.mark.parametrize(
    "text,needle",
    [
        ("registered in England and Wales under number 01234567", "01234567"),
        ("Company No. 01234567", "01234567"),
        ("company registration number SC123456", "SC123456"),
        ("registered with the Chamber of Commerce under number 12345678", "12345678"),
        ("KvK 12345678", "12345678"),
        ("KvK-nummer: 12345678", "12345678"),
        ("Amtsgericht München HRB 123456", "123456"),
        ("Companies House number 01234567", "01234567"),
        ("registered under number 0123.456.789", "0123.456.789"),
    ],
)
def test_registration_in_more_forms(text, needle):
    assert found_by(RegistrationNumberRecognizer(), text) == {needle: 0.7}


@pytest.mark.parametrize(
    "text",
    [
        "registered in England and Wales",
        "the company number is to be confirmed",
        "registered under number 1234",
        "the company has no 2 offices",
        "a registered letter",
        "number 01234567",
    ],
)
def test_registration_needs_its_context_and_a_number(text):
    assert found_by(RegistrationNumberRecognizer(), text) == {}


@pytest.mark.parametrize(
    "text,needle",
    [
        ("BSN 111222333", "111222333"),
        ("BSN 1112.22.333", "1112.22.333"),
        ("T.C. Kimlik No 10000000146", "10000000146"),
        ("passport number X1234567", "X1234567"),
        ("Passport No: 123456789", "123456789"),
    ],
)
def test_national_ids(engine, text, needle):
    assert ID in types_at(engine, text, needle)
    assert found_by(NationalIdRecognizer(), text) == {needle: 0.85}


@pytest.mark.parametrize(
    "text",
    ["123456789", "12345678901", "a valid passport", "passport photo 12345678", "1112.22.334"],
)
def test_national_id_needs_a_checksum_or_passport_context(text):
    assert found_by(NationalIdRecognizer(), text) == {}


# --- Bare numbers --------------------------------------------------------------------------------


def test_bare_number_in_price_context_is_low_confidence_amount(engine):
    (f,) = [f for f in engine.analyze("Total price: 48,000") if f.type == PlaceholderType.AMOUNT]
    assert 0.3 <= f.score < 0.85


@pytest.mark.parametrize(
    "text,needle,score",
    [
        ("Total price: 48,000", "48,000", 0.75),
        ("the value is 1,250,000.00", "1,250,000.00", 0.75),
        ("a fee of 2.500,00", "2.500,00", 0.75),
        ("48,000", "48,000", 0.4),
        (f"1{NBSP}250{NBSP}000", f"1{NBSP}250{NBSP}000", 0.4),
        ("1 250 000", "1 250 000", 0.4),
        ("a cap of 48000", "48000", 0.4),
        ("ten thousand (10,000)", "ten thousand (10,000)", 0.4),
    ],
)
def test_bare_numbers(engine, text, needle, score):
    (f,) = [f for f in engine.analyze(text) if f.type == AMOUNT and f.text == needle]
    assert f.score == pytest.approx(score)


@pytest.mark.parametrize(
    "text",
    [
        "in 2026",
        "from 1999 to 2099",
        "999.99",
        "12.50",
        "for 1,000 days",
        "2,500 working days",
        "1,500 hours",
        "a 1,000-day period",
        "10.2 The Supplier shall pay",
        "section 1159 of the Act",
        "Article 1101",
        "on 01.03.2026",
        "Regulation (EU) 2016/679",
        "Schedule 3",
        "twenty",
        "five hundred",
        "one thousand days",
        # A year with a footnote mark glued to it, as a PDF's text gives it.
        "agreed on 21 July 2026.3 This Agreement",
        "agreed on July 21, 2026.3",
        # References to a law and to a standard.
        "Regulation (EU) No 1169/2011",
        "certified to ISO 9001",
        "to EN 1090 and ISO/IEC 27001",
        # A duration with its figure in brackets, and a time of day.
        "for ten thousand (10,000) days",
        "by 1700 CET each day",
        "after 1730 hours",
    ],
)
def test_bare_number_exclusions(text):
    assert found_by(BareNumberRecognizer(), text) == {}


def test_a_very_long_run_of_digits_is_read_without_error():
    # Python refuses to turn more than 4,300 digits into a number; the check never needs to.
    digits = "1" * 5000
    assert found_by(BareNumberRecognizer(), f"Total: {digits}") == {digits: 0.4}
    zeros = "0" * 5000 + "12"
    assert found_by(BareNumberRecognizer(), f"Total: {zeros}") == {}


# --- E-mail, phone, web addresses ----------------------------------------------------------------


def test_email_phone_url(engine):
    t = "Contact j.smith@northwind.example, +31 20 123 4567 or https://www.northwind.example/legal"
    found = {f.type for f in engine.analyze(t)}
    assert {PlaceholderType.EMAIL, PlaceholderType.PHONE, PlaceholderType.URL} <= found


def test_email_phone_url_spans_are_whole(engine):
    t = "Contact j.smith@northwind.example, +31 20 123 4567 or https://www.northwind.example/legal."
    assert texts_of(engine, t, PlaceholderType.EMAIL) == {"j.smith@northwind.example"}
    assert texts_of(engine, t, PlaceholderType.PHONE) == {"+31 20 123 4567"}
    assert texts_of(engine, t, PlaceholderType.URL) == {"https://www.northwind.example/legal"}


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Write to legal@acme.co.uk today", "legal@acme.co.uk"),
        ("Write to notices@northwind.example.", "notices@northwind.example"),
    ],
)
def test_email_addresses(text, needle):
    assert set(found_by(EmailAddressRecognizer(), text)) == {needle}


@pytest.mark.parametrize(
    "text,needle",
    [
        ("See https://www.northwind.example/legal.", "https://www.northwind.example/legal"),
        ("(see https://acme.example/terms)", "https://acme.example/terms"),
        ("Visit www.acme.example, or call", "www.acme.example"),
        ("Visit acme.com for the terms", "acme.com"),
        ("Visit Acme.com for the terms", "Acme.com"),
        ("http://shop.acme.co.uk/terms?lang=en", "http://shop.acme.co.uk/terms?lang=en"),
        ("see northwind.example", "northwind.example"),
        ("see acme.co.uk", "acme.co.uk"),
        ("see acme.it/terms", "acme.it/terms"),
        ("see https://www.acme.to/terms", "https://www.acme.to/terms"),
    ],
)
def test_web_addresses(engine, text, needle):
    assert texts_of(engine, text, PlaceholderType.URL) == {needle}


@pytest.mark.parametrize(
    "text",
    [
        "Contact j.smith@northwind.example",
        "The Goods.It shall be delivered",
        "e.g. the Goods, i.e. all of them",
        "Acme Ltd. and Northwind B.V.",
        # A missing space after a full stop: no top-level domain, or not one in this list, or a
        # word that counts as one only in a name written all in lower case.
        "the warehouse.of the Buyer",
        "the Supplier.to the Buyer",
        "the Goods.it shall be delivered",
        "the Supplier.in good time",
    ],
)
def test_web_address_needs_a_whole_domain(engine, text):
    assert found_by(WebAddressRecognizer(), text) == {}
    assert PlaceholderType.URL not in {f.type for f in engine.analyze(text)}


# Numbers in their national form. Apart from the first two, Presidio's default regions (US, GB, DE,
# FR, IL, IN, CA, BR) do not find them: they are found because their country is in PHONE_REGIONS.
@pytest.mark.parametrize(
    "text,needle",
    [
        ("Tel. 020 123 4567", "020 123 4567"),
        ("Tel. +44 20 7946 0958", "+44 20 7946 0958"),
        ("Tel. 012 34 56 78", "012 34 56 78"),  # Belgium
        ("Tel. 0501 234 56 78", "0501 234 56 78"),  # Turkey
        ("Tel. 612 34 56 78", "612 34 56 78"),  # Spain
        ("Tel. 32 12 34 56", "32 12 34 56"),  # Denmark
        ("Tel. 070-123 45 67", "070-123 45 67"),  # Sweden
        ("Tel. 21 23 45 67", "21 23 45 67"),  # Norway
        ("Tel. 512 345 678", "512 345 678"),  # Poland
    ],
)
def test_phone_numbers_from_the_owners_regions(engine, text, needle):
    assert PlaceholderType.PHONE in types_at(engine, text, needle)


def test_phone_regions():
    assert " ".join(PHONE_REGIONS) == "GB NL DE FR BE IE TR US ES IT CH AT DK SE NO PL"


# --- The engine ----------------------------------------------------------------------------------

CONTRACT = (
    "Northwind Trading B.V. (KvK 12345678, VAT number NL123456782B01) shall be paid\n"
    "EUR 1,250,000.00 for 10,000 units, less a discount of 12.5%, within 30 days.\n"
    "The notice was sent by Jane Smith to the Buyer on Monday.\n"
    "Contact j.smith@northwind.example or +31 20 123 4567."
)


def test_findings_are_in_text_order_and_carry_their_text(engine):
    findings = engine.analyze(CONTRACT)
    assert findings
    assert [f.start for f in findings] == sorted(f.start for f in findings)
    assert all(f.text == CONTRACT[f.start : f.end] for f in findings)
    assert all(f.score >= MIN_SCORE for f in findings)


def test_empty_text(engine):
    assert engine.analyze("") == []


def test_a_missing_model_is_an_error_not_a_download():
    with pytest.raises(OSError, match="not installed"):
        Engine("xx_no_such_model")


def test_overlapping_findings_are_all_kept(engine):
    found = {(f.type, f.text) for f in engine.analyze("minimum order of 10,000 units")}
    assert {(QUANTITY, "10,000 units"), (AMOUNT, "10,000")} <= found


def test_sources(engine):
    findings = engine.analyze(CONTRACT)
    by_text = {(f.type, f.text): f.source for f in findings}
    assert by_text[(PlaceholderType.PERSON, "Jane Smith")] == "model"
    assert by_text[(AMOUNT, "EUR 1,250,000.00")] == "pattern"
    assert by_text[(PlaceholderType.PHONE, "+31 20 123 4567")] == "pattern"
    assert by_text[(PlaceholderType.EMAIL, "j.smith@northwind.example")] == "pattern"
    assert by_text[(PlaceholderType.COMPANY, "Northwind Trading B.V.")] == "rule"  # Task 7
    assert {f.source for f in findings} <= {"pattern", "model", "rule"}


def test_model_companies_keep_their_score(engine):
    # Presidio would lower the score of companies; nlp_config.yaml stops it. A company with a legal
    # form that the contract rules leave alone (a legal form in lower case) keeps the model's score.
    t = "Supplies are sourced from Baltic Fasteners gmbh and its affiliates."
    (f,) = [f for f in engine.analyze(t) if f.type == PlaceholderType.COMPANY]
    assert f.text == "Baltic Fasteners gmbh" and f.source == "model" and f.score == 0.85


def test_money_percent_and_quantity_come_only_from_patterns(engine):
    findings = engine.analyze(CONTRACT + " The fee is fifty thousand euros.")
    assert {f.source for f in findings if f.type in {AMOUNT, PERCENT, QUANTITY}} == {"pattern"}


def test_dates_stay_visible(engine):
    t = "This Agreement is dated 1 March 2026 and amended on 01/03/2027."
    assert not [f for f in engine.analyze(t) if "2026" in f.text or "2027" in f.text]


# Numeric dates pass for phone numbers (01.03.2026 in Italy, 2026-03-01 in Denmark) and for
# account numbers; they must still stay visible.
@pytest.mark.parametrize(
    "text",
    [
        "on 01.03.2026",  # dd.mm.yyyy
        "on 01-03-2026",  # dd-mm-yyyy
        "on 31-12-2026",
        "on 2026-03-01",  # yyyy-mm-dd
        "on 2026-12-31",
        "on 01/03/2026",  # dd/mm/yyyy
        "on 1 March 2026",
        "on March 1, 2026",
        "This Agreement commences on 2026-03-01 and ends on 01.09.2027.",
        "taking into account the 01-03-2026 forecast",
        # A bracket before the date, and the forms Presidio's date recognizer does not know.
        "signed (01.03.2026) by both",
        "on 2026.03.01",  # yyyy.mm.dd
        "on 01-03-26",  # dd-mm-yy
        "on 01 03 2026",  # dd mm yyyy
        "on 2026/03/01",
    ],
)
def test_dates_are_not_findings(engine, text):
    assert engine.analyze(text) == []


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Tel: (030) 360 7352", "(030) 360 7352"),
        ("Telephone: 01 03 2026 99", "01 03 2026 99"),
    ],
)
def test_a_phone_number_that_starts_like_a_date_is_still_found(engine, text, needle):
    assert texts_of(engine, text, PlaceholderType.PHONE) == {needle}


def test_a_phone_number_next_to_a_date_is_still_found(engine):
    t = "call +31 20 123 4567 on 01.03.2026"
    assert texts_of(engine, t, PlaceholderType.PHONE) == {"+31 20 123 4567"}


def test_long_runs_of_number_words_are_quick(engine):
    text = "-".join(["twenty", "one"] * 20)  # 40 hyphenated number words
    start = time.perf_counter()
    engine.analyze(text)
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    "text,needle,placeholder_type",
    [
        ("Card 4111 1111 1111 1111", "4111 1111 1111 1111", ID),
        ("NI number AB 12 34 56 C", "AB 12 34 56 C", ID),
        ("MAC 00:1A:2B:3C:4D:5E", "00:1A:2B:3C:4D:5E", ID),
        (
            "whose registered office is at Keizersgracht 123, 1015 CJ Amsterdam",
            "Keizersgracht 123",
            PlaceholderType.ADDRESS,
        ),
    ],
)
def test_presidio_entities_are_mapped_to_placeholder_types(engine, text, needle, placeholder_type):
    assert placeholder_type in types_at(engine, text, needle)


# Presidio recognizers the engine does without (ruling R12), so that these stay visible.


@pytest.mark.parametrize("text", ["12.3.4.1 applies", "clause 12.3.4.1"])
def test_four_level_clause_numbers_stay_visible(engine, text):
    assert engine.analyze(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "product code A1234",  # was a US driver's licence
        "code AB1234563",  # was a US DEA (medical licence) number
    ],
)
def test_codes_are_not_findings(engine, text):
    assert engine.analyze(text) == []


def test_a_bank_reference_is_not_an_id(engine):
    # Was a US bank account number. As a bare number of 1,000 and more it is still an amount.
    assert ID not in {f.type for f in engine.analyze("bank reference 123456789012")}


def test_ip_addresses_are_not_found(engine):
    """A known limit: Presidio's IP recognizer read four-level clause numbers as IP addresses."""
    assert engine.analyze("192.168.0.1") == []
