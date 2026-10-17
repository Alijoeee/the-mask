import re

import pytest

from themask.model import PlaceholderType
from themask.textnorm import (
    COMMON_WORDS,
    HONORIFICS,
    LEGAL_FORMS,
    flexible_pattern,
    normalize,
    variants_of,
)

# Spaces and marks that look like nothing (or like an ordinary character) in an editor.
NBSP = "\N{NO-BREAK SPACE}"
NARROW_NBSP = "\N{NARROW NO-BREAK SPACE}"
THIN_SPACE = "\N{THIN SPACE}"

# --------------------------------------------------------------------------------------------
# normalize
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("1,250,000", "1.250.000"),
        ("EUR 1 250 000,00", "eur 1.250.000,00"),
        ("NL91 ABNA 0417 1643 00", "NL91ABNA0417164300"),
        ("John  Smith", "john\N{NO-BREAK SPACE}smith"),
        ("Acme Supplies Ltd.", "ACME SUPPLIES LTD"),
    ],
)
def test_normalize_equal(a: str, b: str) -> None:
    assert normalize(a) == normalize(b)


def test_normalize_keeps_digits_and_letters() -> None:
    assert normalize("K4-F7 x") == "k4f7x"


@pytest.mark.parametrize(
    "separator",
    [
        NBSP,
        NARROW_NBSP,
        THIN_SPACE,
        "\N{FIGURE SPACE}",
        "\N{IDEOGRAPHIC SPACE}",
        "\t",
        "\n",
    ],
    ids=[
        "nbsp",
        "narrow-nbsp",
        "thin-space",
        "figure-space",
        "ideographic-space",
        "tab",
        "newline",
    ],
)
def test_normalize_treats_every_kind_of_space_as_nothing(separator: str) -> None:
    # Word types numbers like "1 250 000" with non-breaking and thin spaces as separators.
    spaced = f"EUR 1{separator}250{separator}000,00"
    assert normalize(spaced) == normalize("EUR 1,250,000.00") == "eur125000000"


def test_normalize_drops_invisible_characters() -> None:
    # Soft hyphens, zero-width spaces and byte-order marks sneak in from Word and from PDFs.
    assert normalize("Smi\N{SOFT HYPHEN}th") == "smith"
    assert normalize("Smi\N{ZERO WIDTH SPACE}th") == "smith"
    assert normalize("\N{ZERO WIDTH NO-BREAK SPACE}Smith") == "smith"


def test_normalize_drops_every_listed_punctuation_mark() -> None:
    punctuation = (
        ".,;:'\""
        "\N{RIGHT SINGLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}"
        "\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
        "()[]{}/\\-_\N{EN DASH}\N{EM DASH}"
    )
    assert normalize(f"a{punctuation}b") == "ab"
    assert normalize("O\N{RIGHT SINGLE QUOTATION MARK}Brien") == normalize("O'Brien") == "obrien"
    assert normalize("Smith\N{EN DASH}Jones") == normalize("Smith-Jones") == "smithjones"


def test_normalize_keeps_letters_beyond_ascii() -> None:
    assert normalize("Müller Şahin") == "müllerşahin"


def test_normalize_folds_case_beyond_ascii() -> None:
    assert normalize("STRASSE") == normalize("Straße") == "strasse"
    # Turkish capital dotted I casefolds to "i" plus a combining dot, which must not survive.
    assert normalize("İSTANBUL") == normalize("istanbul") == "istanbul"


def test_normalize_applies_compatibility_forms() -> None:
    assert normalize("\N{LATIN SMALL LIGATURE FI}nance") == "finance"  # common in PDF text
    assert normalize("\N{FULLWIDTH DIGIT ONE}\N{FULLWIDTH DIGIT TWO}3") == "123"


def test_normalize_of_only_separators_is_empty() -> None:
    assert normalize("") == ""
    assert normalize(f" {NBSP}.,;:-\N{EN DASH}_/ ") == ""


def test_normalize_does_not_merge_different_values() -> None:
    assert normalize("1.250.000") != normalize("1.250.001")
    assert normalize("John Smith") != normalize("John Smyth")


@pytest.mark.parametrize(
    "text",
    [f"EUR 1{NBSP}250 000,00", "Müller & Söhne", "İSTANBUL", "\N{LATIN SMALL LIGATURE FI}nance"],
)
def test_normalize_is_idempotent(text: str) -> None:
    assert normalize(normalize(text)) == normalize(text)


# --------------------------------------------------------------------------------------------
# The shared lists (Task 7 reuses LEGAL_FORMS and COMMON_WORDS, Task 8 reuses HONORIFICS)
# --------------------------------------------------------------------------------------------


def test_legal_forms_are_the_agreed_list() -> None:
    assert LEGAL_FORMS == (
        "B.V.",
        "N.V.",
        "GmbH",
        "AG",
        "S.A.",
        "S.A.S.",
        "S.r.l.",
        "S.p.A.",
        "Ltd",
        "Limited",
        "LLP",
        "LLC",
        "Inc.",
        "Incorporated",
        "plc",
        "Corp.",
        "Corporation",
        "Co.",
        "KG",
        "OHG",
        "A.Ş.",
        "Ltd. Şti.",
        "Oy",
        "AB",
        "ApS",
        "A/S",
        "SE",
    )


def test_common_words_are_the_agreed_list() -> None:
    assert isinstance(COMMON_WORDS, frozenset)
    assert COMMON_WORDS == {
        "General",
        "International",
        "Global",
        "European",
        "National",
        "United",
        "Services",
        "Service",
        "Group",
        "Holdings",
        "Holding",
        "Trading",
        "Supplies",
        "Supply",
        "Industries",
        "Industrial",
        "Systems",
        "Solutions",
        "Partners",
        "Capital",
        "Technologies",
        "Technology",
        "Logistics",
        "Consulting",
        "Management",
        "Development",
        "Investments",
        "Enterprises",
        "Company",
        "Limited",
        "The",
        "New",
        "First",
        "Royal",
        "Standard",
        "Universal",
        "Western",
        "Eastern",
        "Northern",
        "Southern",
        "Central",
    }


def test_honorifics_are_the_agreed_list() -> None:
    assert HONORIFICS == (
        "Mr",
        "Mrs",
        "Ms",
        "Mx",
        "Dr",
        "Prof",
        "Sir",
        "Dame",
        "Mevr",
        "Dhr",
        "Herr",
        "Frau",
    )


# --------------------------------------------------------------------------------------------
# variants_of: rules that hold for every type
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("placeholder_type", list(PlaceholderType))
def test_variants_always_include_the_value(placeholder_type: PlaceholderType) -> None:
    value = "  Mr John Smith Ltd  https://www.x.example EUR 1,000.00 "
    assert value in variants_of(value, placeholder_type)


@pytest.mark.parametrize(
    "placeholder_type",
    [
        PlaceholderType.PERCENT,
        PlaceholderType.QUANTITY,
        PlaceholderType.EMAIL,
        PlaceholderType.ADDRESS,
        PlaceholderType.CUSTOM,
    ],
)
def test_other_types_return_only_the_value(placeholder_type: PlaceholderType) -> None:
    # IBAN and ID have their own rules, further down. Case is handled by the matching, not here.
    value = "Mr John Smith Ltd EUR 1,250,000.00 https://www.northwind.example +31 20 123 4567"
    assert variants_of(value, placeholder_type) == {value}


@pytest.mark.parametrize("placeholder_type", list(PlaceholderType))
@pytest.mark.parametrize(
    "value", ["Mr", "Ltd", "Mr Ltd", "https://", "www.", "EUR", "...", "+", "0", "   ", "- . -"]
)
def test_degenerate_values_never_produce_empty_variants(
    placeholder_type: PlaceholderType, value: str
) -> None:
    variants = variants_of(value, placeholder_type)
    assert value in variants
    assert "" not in variants


# --------------------------------------------------------------------------------------------
# variants_of: PERSON
# --------------------------------------------------------------------------------------------


def test_person_variants() -> None:
    v = variants_of("Mr John Smith", PlaceholderType.PERSON)
    assert {"Mr John Smith", "John Smith", "J. Smith"} <= v and "Smith" not in v


def test_person_without_honorific_gets_the_initial_form() -> None:
    assert variants_of("John Smith", PlaceholderType.PERSON) == {"John Smith", "J. Smith"}


@pytest.mark.parametrize("honorific", HONORIFICS)
def test_person_every_honorific_is_stripped(honorific: str) -> None:
    for spelling in (honorific, honorific + ".", honorific.upper(), honorific.lower()):
        v = variants_of(f"{spelling} Jane Smith", PlaceholderType.PERSON)
        assert {"Jane Smith", "J. Smith"} <= v, spelling


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Dr. Jane Smith", {"Dr. Jane Smith", "Jane Smith", "J. Smith"}),
        ("MRS JANE SMITH", {"MRS JANE SMITH", "JANE SMITH", "J. SMITH"}),
        ("Herr Hans Müller", {"Herr Hans Müller", "Hans Müller", "H. Müller"}),
        ("Dhr. Jan Jansen", {"Dhr. Jan Jansen", "Jan Jansen", "J. Jansen"}),
    ],
)
def test_person_variants_per_honorific(value: str, expected: set[str]) -> None:
    assert variants_of(value, PlaceholderType.PERSON) == expected


def test_person_stacked_honorifics() -> None:
    v = variants_of("Prof. Dr. Jane Smith", PlaceholderType.PERSON)
    assert v == {"Prof. Dr. Jane Smith", "Dr. Jane Smith", "Jane Smith", "J. Smith"}


@pytest.mark.parametrize("value", ["Mr Smith", "Dr. Smith", "Smith", "Frau Müller"])
def test_person_surname_alone_is_never_added(value: str) -> None:
    assert variants_of(value, PlaceholderType.PERSON) == {value}


def test_person_initial_is_built_from_the_first_and_last_token() -> None:
    v = variants_of("John Paul Smith", PlaceholderType.PERSON)
    assert v == {"John Paul Smith", "J. Smith"}


def test_person_variants_collapse_odd_whitespace() -> None:
    value = "mr  john\nsmith"
    assert variants_of(value, PlaceholderType.PERSON) == {value, "john smith", "j. smith"}


# --------------------------------------------------------------------------------------------
# variants_of: COMPANY
# --------------------------------------------------------------------------------------------


def test_company_variants() -> None:
    v = variants_of("Northwind Trading B.V.", PlaceholderType.COMPANY)
    assert {"Northwind Trading", "Northwind"} <= v


def test_company_first_word_not_common() -> None:
    assert "General" not in variants_of("General Supplies Ltd", PlaceholderType.COMPANY)


@pytest.mark.parametrize("form", LEGAL_FORMS)
def test_company_every_legal_form_is_stripped_with_or_without_dots(form: str) -> None:
    for spelling in {form, form.replace(".", "")}:
        v = variants_of(f"Zephyr Ventures {spelling}", PlaceholderType.COMPANY)
        assert "Zephyr Ventures" in v, spelling


@pytest.mark.parametrize(
    "form",
    ["gmbh", "GMBH", "ltd", "LTD", "plc", "PLC", "llc", "limited", "LIMITED", "ag", "kg", "aps"],
)
def test_company_legal_forms_match_whatever_the_case(form: str) -> None:
    v = variants_of(f"Zephyr Ventures {form}", PlaceholderType.COMPANY)
    assert "Zephyr Ventures" in v


@pytest.mark.parametrize("form", ["SE", "Se", "AB", "Ab", "Co", "Co.", "CO", "AS", "A/S"])
def test_company_capitalised_se_ab_co_as_are_legal_forms(form: str) -> None:
    v = variants_of(f"Zephyr Ventures {form}", PlaceholderType.COMPANY)
    assert "Zephyr Ventures" in v


@pytest.mark.parametrize("word", ["se", "ab", "co", "co.", "as"])
def test_company_lower_case_se_ab_co_as_are_ordinary_words(word: str) -> None:
    value = f"Zephyr Ventures {word}"
    assert variants_of(value, PlaceholderType.COMPANY) == {value, "Zephyr"}


@pytest.mark.parametrize(
    "name",
    ["Zephyr Nabisco", "Zephyr Pharmaco", "Zephyr Case", "Zephyr Lab", "Zephyr Hubs", "Zephyr Bvs"],
)
def test_company_legal_form_must_be_a_whole_word(name: str) -> None:
    assert variants_of(name, PlaceholderType.COMPANY) == {name, "Zephyr"}


def test_company_strips_only_one_legal_form() -> None:
    v = variants_of("Smith & Co. Ltd", PlaceholderType.COMPANY)
    assert v == {"Smith & Co. Ltd", "Smith & Co.", "Smith"}


def test_company_comma_before_the_legal_form_is_dropped() -> None:
    v = variants_of("Acme, Inc.", PlaceholderType.COMPANY)
    assert v == {"Acme, Inc.", "Acme"}


def test_company_dangling_ampersand_is_dropped() -> None:
    v = variants_of("Smith & Co.", PlaceholderType.COMPANY)
    assert v == {"Smith & Co.", "Smith"}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Northwind Trading", {"Northwind Trading", "Northwind"}),
        ("Northwind", {"Northwind"}),
        ("Acme Ltd", {"Acme Ltd", "Acme"}),
        ("ACME Supplies Ltd", {"ACME Supplies Ltd", "ACME Supplies", "ACME"}),
        (
            "Rolls-Royce Holdings plc",
            {"Rolls-Royce Holdings plc", "Rolls-Royce Holdings", "Rolls-Royce"},
        ),
        ("Marmara Tekstil Ltd. Şti.", {"Marmara Tekstil Ltd. Şti.", "Marmara Tekstil", "Marmara"}),
        ("Anadolu Gıda A.Ş.", {"Anadolu Gıda A.Ş.", "Anadolu Gıda", "Anadolu"}),
        ("ANADOLU GIDA LTD. ŞTİ.", {"ANADOLU GIDA LTD. ŞTİ.", "ANADOLU GIDA", "ANADOLU"}),
        ("Nordic Parts A/S", {"Nordic Parts A/S", "Nordic Parts", "Nordic"}),
    ],
)
def test_company_variants_in_full(value: str, expected: set[str]) -> None:
    assert variants_of(value, PlaceholderType.COMPANY) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        # A first token needs at least four letters ...
        ("BP Chemicals Ltd", {"BP Chemicals Ltd", "BP Chemicals"}),
        ("IBM Nederland B.V.", {"IBM Nederland B.V.", "IBM Nederland"}),
        ("Abc Parts Ltd", {"Abc Parts Ltd", "Abc Parts"}),
        ("Abcd Parts Ltd", {"Abcd Parts Ltd", "Abcd Parts", "Abcd"}),
        # ... and when a legal form leaves a single word, that word is a first token too.
        ("General Ltd", {"General Ltd"}),
        ("BP Ltd", {"BP Ltd"}),
    ],
)
def test_company_first_token_needs_four_letters_and_a_distinctive_word(
    value: str, expected: set[str]
) -> None:
    assert variants_of(value, PlaceholderType.COMPANY) == expected


@pytest.mark.parametrize("word", sorted(COMMON_WORDS))
def test_company_common_first_word_is_never_a_variant(word: str) -> None:
    for spelling in (word, word.upper(), word.lower()):
        v = variants_of(f"{spelling} Zephyr Ltd", PlaceholderType.COMPANY)
        assert spelling not in v, spelling
        assert f"{spelling} Zephyr" in v, spelling


# --------------------------------------------------------------------------------------------
# variants_of: AMOUNT
# --------------------------------------------------------------------------------------------


def test_amount_variants() -> None:
    assert "1,250,000" in variants_of("EUR 1,250,000.00", PlaceholderType.AMOUNT)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("EUR 1,250,000.00", {"EUR 1,250,000.00", "1,250,000.00", "EUR 1,250,000", "1,250,000"}),
        ("€ 1.250.000,00", {"€ 1.250.000,00", "1.250.000,00", "€ 1.250.000", "1.250.000"}),
        ("1.250.000,00 EUR", {"1.250.000,00 EUR", "1.250.000,00", "1.250.000 EUR", "1.250.000"}),
        (
            f"EUR 1{NBSP}250{NBSP}000,00",
            {
                f"EUR 1{NBSP}250{NBSP}000,00",
                f"1{NBSP}250{NBSP}000,00",
                f"EUR 1{NBSP}250{NBSP}000",
                f"1{NBSP}250{NBSP}000",
            },
        ),
        ("$1,250,000", {"$1,250,000", "1,250,000"}),
        ("1,250,000.00", {"1,250,000.00", "1,250,000"}),
        ("1,250,000", {"1,250,000"}),
        ("€1.25m", {"€1.25m", "1.25m"}),
        ("EUR 1.25 million", {"EUR 1.25 million", "1.25 million"}),
    ],
)
def test_amount_variants_with_and_without_currency_and_decimals(
    value: str, expected: set[str]
) -> None:
    assert variants_of(value, PlaceholderType.AMOUNT) == expected


def test_amount_keeps_decimals_that_are_not_zero() -> None:
    v = variants_of("EUR 1,250.50", PlaceholderType.AMOUNT)
    assert v == {"EUR 1,250.50", "1,250.50"}


def test_amount_dot_thousands_are_not_mistaken_for_decimals() -> None:
    assert variants_of("EUR 1.000", PlaceholderType.AMOUNT) == {"EUR 1.000", "1.000"}
    assert variants_of("EUR 1.000,00", PlaceholderType.AMOUNT) == {
        "EUR 1.000,00",
        "1.000,00",
        "EUR 1.000",
        "1.000",
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        # A bare "5" or "25" would match clause numbers all over a contract, so only the
        # currency form stays; "500,00" still has enough digits to stand on its own.
        ("EUR 5.00", {"EUR 5.00", "EUR 5"}),
        ("EUR 25", {"EUR 25"}),
        ("€ 500,00", {"€ 500,00", "500,00", "€ 500"}),
    ],
)
def test_amount_short_bare_numbers_are_not_variants(value: str, expected: set[str]) -> None:
    assert variants_of(value, PlaceholderType.AMOUNT) == expected


@pytest.mark.parametrize("value", ["one million euros", "EUR", "TBC", "EUR 1,250 - 2,500"])
def test_amount_that_is_not_one_number_has_only_the_value(value: str) -> None:
    assert variants_of(value, PlaceholderType.AMOUNT) == {value}


# --------------------------------------------------------------------------------------------
# variants_of: PHONE
# --------------------------------------------------------------------------------------------


def test_phone_variants() -> None:
    assert "020 123 4567" in variants_of("+31 20 123 4567", PlaceholderType.PHONE)


@pytest.mark.parametrize(
    "value,national",
    [
        ("+31 20 123 4567", "020 123 4567"),
        ("+31201234567", "020 123 4567"),
        ("+31 (0)20 123 4567", "020 123 4567"),
        ("+44 20 7946 0958", "020 7946 0958"),
        ("0031 20 123 4567", "020 123 4567"),
        ("0201234567", "020 123 4567"),
        ("02079460958", "020 7946 0958"),
        ("0312 123 45 67", "(0312) 123 45 67"),
    ],
)
def test_phone_national_format(value: str, national: str) -> None:
    assert variants_of(value, PlaceholderType.PHONE) == {value, national}


def test_phone_regions_are_tried_in_the_agreed_order() -> None:
    # 0232 123 45 67 is a valid Turkish number but also a valid German one; DE comes before TR.
    v = variants_of("0232 123 45 67", PlaceholderType.PHONE)
    assert v == {"0232 123 45 67", "02321 234567"}


@pytest.mark.parametrize("value", ["call me", "12345", "+31 1", "+999 123456"])
def test_phone_that_does_not_parse_has_only_the_value(value: str) -> None:
    assert variants_of(value, PlaceholderType.PHONE) == {value}


# --------------------------------------------------------------------------------------------
# variants_of: URL
# --------------------------------------------------------------------------------------------


def test_url_variants() -> None:
    assert {"northwind.example", "www.northwind.example"} <= variants_of(
        "https://www.northwind.example", PlaceholderType.URL
    )


def test_url_all_four_forms() -> None:
    assert variants_of("https://www.northwind.example/legal", PlaceholderType.URL) == {
        "https://www.northwind.example/legal",
        "www.northwind.example/legal",
        "https://northwind.example/legal",
        "northwind.example/legal",
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        ("http://northwind.example", {"http://northwind.example", "northwind.example"}),
        ("www.northwind.example", {"www.northwind.example", "northwind.example"}),
        ("northwind.example", {"northwind.example"}),
        (
            "HTTPS://WWW.Northwind.Example",
            {
                "HTTPS://WWW.Northwind.Example",
                "WWW.Northwind.Example",
                "HTTPS://Northwind.Example",
                "Northwind.Example",
            },
        ),
        # Only the "www." label is dropped, never part of another host name.
        (
            "https://www2.northwind.example",
            {"https://www2.northwind.example", "www2.northwind.example"},
        ),
        ("https://wwwx.example", {"https://wwwx.example", "wwwx.example"}),
    ],
)
def test_url_without_scheme_and_without_www(value: str, expected: set[str]) -> None:
    assert variants_of(value, PlaceholderType.URL) == expected


# --------------------------------------------------------------------------------------------
# variants_of: IBAN and ID (the sweep cannot match an unspaced value against a spaced one)
# --------------------------------------------------------------------------------------------


def test_iban_variants() -> None:
    v = variants_of("NL91 ABNA 0417 1643 00", PlaceholderType.IBAN)
    assert {"NL91ABNA0417164300", "NL91 ABNA 0417 1643 00"} <= v


def test_iban_written_without_spaces_gets_the_grouped_form() -> None:
    v = variants_of("NL91ABNA0417164300", PlaceholderType.IBAN)
    assert {"NL91 ABNA 0417 1643 00"} <= v


@pytest.mark.parametrize(
    "value",
    [
        "NL91 ABNA 0417 1643 00",
        "NL91ABNA0417164300",
        "NL91 ABNA 04171643 00",  # grouped some other way
        f"NL91{NBSP}ABNA{NBSP}0417{NBSP}1643{NBSP}00",
        "NL91\nABNA 0417\t1643  00",  # broken over a line
        " NL91 ABNA 0417 1643 00 ",
    ],
)
def test_iban_comes_spaced_and_unspaced_whichever_way_it_was_written(value: str) -> None:
    v = variants_of(value, PlaceholderType.IBAN)
    assert v == {value, "NL91ABNA0417164300", "NL91 ABNA 0417 1643 00"}


@pytest.mark.parametrize(
    "iban,grouped",
    [
        ("DE89370400440532013000", "DE89 3704 0044 0532 0130 00"),  # last group of two
        ("NO9386011117947", "NO93 8601 1117 947"),  # last group of three
        ("BE68539007547034", "BE68 5390 0754 7034"),  # all groups of four
    ],
)
def test_iban_is_grouped_in_fours_with_a_short_last_group(iban: str, grouped: str) -> None:
    assert variants_of(iban, PlaceholderType.IBAN) == {iban, grouped}


def test_iban_keeps_the_case_it_was_written_in() -> None:
    v = variants_of("nl91abna0417164300", PlaceholderType.IBAN)
    assert v == {"nl91abna0417164300", "nl91 abna 0417 1643 00"}


def test_iban_with_other_separators_is_not_regrouped() -> None:
    # Hyphens are not part of the IBAN formats, so no grouping is invented for them.
    value = "NL91-ABNA-0417-1643-00"
    assert variants_of(value, PlaceholderType.IBAN) == {value}


def test_id_variants() -> None:
    assert {"12345678"} <= variants_of("12.345.678", PlaceholderType.ID)


def test_id_that_is_already_compact_has_only_the_value() -> None:
    assert variants_of("NL123456782B01", PlaceholderType.ID) == {"NL123456782B01"}


@pytest.mark.parametrize(
    "value,compact",
    [
        ("12.345.678", "12345678"),
        ("NL 1234.56.782.B01", "NL123456782B01"),
        ("123-45-6789", "123456789"),
        ("12.34-56 78", "12345678"),
        (f"NL{NBSP}1234 56 782{NBSP}B01", "NL123456782B01"),
        ("AB\N{HYPHEN}123456", "AB123456"),
        ("AB\N{NON-BREAKING HYPHEN}123456", "AB123456"),
        ("nl 1234-56-782-b01", "nl123456782b01"),  # case is left as written
    ],
)
def test_id_loses_its_spaces_dots_and_hyphens(value: str, compact: str) -> None:
    assert variants_of(value, PlaceholderType.ID) == {value, compact}


def test_id_keeps_every_other_character() -> None:
    assert variants_of("AB/12_34", PlaceholderType.ID) == {"AB/12_34"}


# --------------------------------------------------------------------------------------------
# flexible_pattern
# --------------------------------------------------------------------------------------------


def test_flexible_pattern() -> None:
    assert flexible_pattern("John Smith").search("JOHN\n  smith") and not flexible_pattern(
        "Smith"
    ).search("Smithson")


def test_flexible_pattern_is_compiled_and_case_insensitive() -> None:
    pattern = flexible_pattern("Acme Ltd")
    assert isinstance(pattern, re.Pattern)
    assert pattern.flags & re.IGNORECASE
    assert pattern.search("ACME LTD") and pattern.search("acme ltd")


@pytest.mark.parametrize(
    "separator",
    [" ", "  ", "\t", "\n", "\r\n \r\n", NBSP, NARROW_NBSP, THIN_SPACE],
    ids=[
        "space",
        "two-spaces",
        "tab",
        "newline",
        "blank-line",
        "nbsp",
        "narrow-nbsp",
        "thin-space",
    ],
)
def test_flexible_pattern_any_whitespace_matches_any_whitespace(separator: str) -> None:
    assert flexible_pattern("EUR 1 250 000").search(f"pay EUR{separator}1{separator}250 000 now")


def test_flexible_pattern_needs_whitespace_where_the_value_has_it() -> None:
    assert not flexible_pattern("John Smith").search("JohnSmith")
    assert not flexible_pattern("EUR 1 250").search("EUR 1250")


def test_flexible_pattern_matches_everything_else_literally() -> None:
    assert flexible_pattern("EUR 1.250.000,00").search("EUR 1.250.000,00")
    assert not flexible_pattern("EUR 1.250.000,00").search("EUR 1x250x000,00")
    assert flexible_pattern("a+b (c) [d] {e} $f ^g |h").search("A+B (C) [D] {E} $F ^G |H")
    assert not flexible_pattern("a+b").search("aab")
    assert flexible_pattern("J. Smith").search(f"signed J.{NBSP}Smith")
    assert not flexible_pattern("J. Smith").search("signed JX Smith")


@pytest.mark.parametrize("text", ["Smithson", "Blacksmith", "Smith2", "2Smith", "xSmith"])
def test_flexible_pattern_is_not_found_inside_a_longer_word(text: str) -> None:
    assert not flexible_pattern("Smith").search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Mr. Smith, Esq.",
        "(Smith)",
        "Smith's",
        "SMITH",
        "by Smith.",
        "Smith\N{RIGHT SINGLE QUOTATION MARK}s",
        "Smith-Jones",
        "Smith\N{SUPERSCRIPT ONE}",  # a footnote mark must not hide the name from the sweep
    ],
)
def test_flexible_pattern_is_found_next_to_punctuation(text: str) -> None:
    assert flexible_pattern("Smith").search(text)


def test_flexible_pattern_has_no_boundary_where_the_value_ends_in_punctuation() -> None:
    # Boundaries are only added at a letter or digit; "B.V." and "(Smith)" can sit against letters.
    assert flexible_pattern("Northwind B.V.").search("the Northwind B.V., a company")
    assert flexible_pattern("(Smith)").search("x(Smith)y")
    assert flexible_pattern("€1,250").search("pay€1,250")
    assert not flexible_pattern("€1,250").search("pay €1,2500")


def test_flexible_pattern_boundary_also_applies_to_non_ascii_letter_ends() -> None:
    # A value that starts or ends in a non-ASCII letter still counts as starting or ending in a
    # letter, so it must not match inside a longer word.
    assert not flexible_pattern("Café").search("Cafés")
    assert flexible_pattern("Café").search("Le Café, Paris")
    assert not flexible_pattern("Ömer").search("XÖmer")
    assert flexible_pattern("Ömer").search("Herr Ömer")


def test_flexible_pattern_finds_every_occurrence() -> None:
    pattern = flexible_pattern("John Smith")
    spans = [m.span() for m in pattern.finditer("John Smith and john   smith")]
    assert spans == [(0, 10), (15, 27)]


@pytest.mark.parametrize("value", ["", " ", "   ", "\n", NBSP])
def test_flexible_pattern_rejects_a_blank_value(value: str) -> None:
    # A blank pattern would match everywhere, so it must never be built.
    with pytest.raises(ValueError):
        flexible_pattern(value)


# --------------------------------------------------------------------------------------------
# The three functions together: other spellings of a value are found
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,placeholder_type,text,found",
    [
        ("Mr John Smith", PlaceholderType.PERSON, "Signed: J. Smith (Buyer)", "J. Smith"),
        (
            "Northwind Trading B.V.",
            PlaceholderType.COMPANY,
            "NORTHWIND  TRADING shall pay",
            "NORTHWIND  TRADING",
        ),
        ("EUR 1,250,000.00", PlaceholderType.AMOUNT, "a fee of 1,250,000 a year", "1,250,000"),
        ("+31 20 123 4567", PlaceholderType.PHONE, "call 020 123 4567 today", "020 123 4567"),
        (
            "https://www.northwind.example",
            PlaceholderType.URL,
            "visit northwind.example for details",
            "northwind.example",
        ),
        (
            "NL91ABNA0417164300",
            PlaceholderType.IBAN,
            "account NL91 ABNA 0417 1643 00 at",
            "NL91 ABNA 0417 1643 00",
        ),
        (
            "NL91 ABNA 0417 1643 00",
            PlaceholderType.IBAN,
            "account NL91ABNA0417164300 at",
            "NL91ABNA0417164300",
        ),
        ("12.345.678", PlaceholderType.ID, "number 12345678 applies", "12345678"),
    ],
)
def test_another_spelling_is_found_by_the_pattern_and_by_normalize(
    value: str, placeholder_type: PlaceholderType, text: str, found: str
) -> None:
    variants = variants_of(value, placeholder_type)
    matches = [m.group() for v in variants for m in flexible_pattern(v).finditer(text)]
    assert found in matches
    assert any(normalize(v) in normalize(text) for v in variants - {value})
