from dataclasses import FrozenInstanceError

import pytest

from themask.instruction import IMAGE_NOTE, OBJECT_NOTE
from themask.model import PlaceholderType
from themask.placeholders import (
    PLACEHOLDER_RE,
    PlaceholderMatch,
    find_placeholders,
    format_placeholder,
    next_free_number,
)

ALL_TYPES = list(PlaceholderType)

# Characters that look like an ASCII one, named so that nobody has to tell them apart by eye:
# full-width square brackets (U+FF3B, U+FF3D) and the spaces that count as a space (U+00A0,
# U+202F, U+2009).
FULL_OPEN = "\N{FULLWIDTH LEFT SQUARE BRACKET}"
FULL_CLOSE = "\N{FULLWIDTH RIGHT SQUARE BRACKET}"
NBSP = "\N{NO-BREAK SPACE}"
NARROW_NBSP = "\N{NARROW NO-BREAK SPACE}"
THIN_SPACE = "\N{THIN SPACE}"

# The ways an AI tool is known to change "[PERSON_1]" (spec 8.7), each as the whole token.
ALTERED_FORMS = [
    "PERSON_1",
    "[PERSON 1]",
    "[person_1]",
    r"\[PERSON_1\]",
    "**[PERSON_1]**",
    "__[PERSON_1]__",
    "`[PERSON_1]`",
    "[PERSON-1]",
    "[PERSON_01]",
    "[ PERSON_1 ]",
    f"{FULL_OPEN}PERSON_1{FULL_CLOSE}",
]

# Further changes the grammar tolerates; each of them still reads as "[PERSON_1]".
MORE_ALTERED_FORMS = [
    "person-1",
    "[Person 1]",
    "[PerSon_1]",
    "[PERSON_0001]",
    "[  PERSON_1  ]",
    "[PERSON_1",
    "PERSON_1]",
    r"\[PERSON_1]",
    r"[PERSON_1\]",
    f"{FULL_OPEN}PERSON_1]",
    f"[PERSON_1{FULL_CLOSE}",
    "**PERSON_1**",
    "__PERSON_1__",
    "`PERSON_1`",
    # Markdown's escaped underscore, as a Word-to-markdown conversion writes it.
    r"PERSON\_1",
    r"person\_1",
    r"[PERSON\_1]",
    r"\[PERSON\_1\]",
    r"**PERSON\_1**",
    r"[PERSON\_1",
    # A space between the name and the number needs the brackets, and may be any of the spaces.
    "[ Person 1 ]",
    r"\[PERSON 1\]",
    "**[PERSON 1]**",
    f"{FULL_OPEN}PERSON 1{FULL_CLOSE}",
    f"[PERSON{NBSP}1]",
    f"[PERSON{NARROW_NBSP}1]",
    f"[PERSON{THIN_SPACE}1]",
    f"[{NBSP}PERSON_1{NARROW_NBSP}]",
    f"[{THIN_SPACE}Person{NBSP}1{THIN_SPACE}]",
]


def only_match(text: str) -> PlaceholderMatch:
    (match,) = find_placeholders(text)
    return match


def test_format() -> None:
    assert format_placeholder(PlaceholderType.PERSON, 1) == "[PERSON_1]"


@pytest.mark.parametrize(
    ("placeholder_type", "number", "expected"),
    [
        (PlaceholderType.COMPANY, 2, "[COMPANY_2]"),
        (PlaceholderType.ID, 10, "[ID_10]"),
        (PlaceholderType.AMOUNT, 1000, "[AMOUNT_1000]"),
    ],
)
def test_format_writes_a_plain_decimal_number(
    placeholder_type: PlaceholderType, number: int, expected: str
) -> None:
    assert format_placeholder(placeholder_type, number) == expected


@pytest.mark.parametrize("raw", ["[PERSON_1]"])
def test_exact(raw: str) -> None:
    (m,) = find_placeholders(f"Dear {raw},")
    assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", True, raw)


@pytest.mark.parametrize("number", [1, 9, 10, 123])
@pytest.mark.parametrize("placeholder_type", ALL_TYPES)
def test_every_type_is_found_in_its_exact_form(
    placeholder_type: PlaceholderType, number: int
) -> None:
    raw = f"[{placeholder_type.value}_{number}]"
    assert find_placeholders(f"see {raw}.") == [PlaceholderMatch(4, 4 + len(raw), raw, raw, True)]


@pytest.mark.parametrize("raw", ALTERED_FORMS)
def test_altered(raw: str) -> None:
    (m,) = find_placeholders(f"Dear {raw},")
    assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", False, raw)


@pytest.mark.parametrize("raw", ALTERED_FORMS + MORE_ALTERED_FORMS)
def test_an_altered_token_is_replaceable_in_one_piece(raw: str) -> None:
    # start and end must cover every character of the token, markers and brackets included,
    # so that a restore which replaces text[start:end] leaves nothing of the old form behind.
    text = f"Dear {raw}, bye"
    (m,) = find_placeholders(text)
    assert (m.start, m.end) == (5, 5 + len(raw))
    assert text[m.start : m.end] == m.raw == raw
    assert (m.placeholder, m.exact) == ("[PERSON_1]", False)


@pytest.mark.parametrize("placeholder_type", ALL_TYPES)
def test_every_type_name_is_found_in_lower_and_mixed_case(
    placeholder_type: PlaceholderType,
) -> None:
    expected = f"[{placeholder_type.value}_4]"
    for name in (placeholder_type.value.lower(), placeholder_type.value.capitalize()):
        m = only_match(f"[{name}_4]")
        assert (m.placeholder, m.exact) == (expected, False)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [("[PERSON_007]", "[PERSON_7]"), ("[COMPANY_010]", "[COMPANY_10]"), ("[ID_00]", "[ID_0]")],
)
def test_leading_zeros_are_dropped_from_the_canonical_form(raw: str, canonical: str) -> None:
    m = only_match(raw)
    assert (m.raw, m.placeholder, m.exact) == (raw, canonical, False)


@pytest.mark.parametrize(
    ("text", "raw"),
    [
        ("**[PERSON_1] signs**", "[PERSON_1]"),
        ("[PERSON_1]** signs", "[PERSON_1]"),
        ("**[PERSON_1]__", "[PERSON_1]"),
        ("__[PERSON_1]", "[PERSON_1]"),
        ("*[PERSON_1]*", "[PERSON_1]"),
        ("_[PERSON_1]_", "[PERSON_1]"),
        ("[PERSON_1]s", "[PERSON_1]"),
        ("x[PERSON_1]", "[PERSON_1]"),
        ("[[PERSON_1]]", "[PERSON_1]"),
        ("(see [PERSON_1])", "[PERSON_1]"),
    ],
)
def test_markers_join_the_token_only_as_a_matching_pair(text: str, raw: str) -> None:
    # Only a marker that both opens and closes the token joins it. Anything else round a
    # well-formed "[PERSON_1]" (a lone or different marker, letters, other brackets) stays
    # outside it, and the placeholder itself is still exact.
    m = only_match(text)
    assert (m.raw, m.exact) == (raw, True)
    assert text[m.start : m.end] == raw


def test_spaces_next_to_a_bare_name_are_not_part_of_the_token() -> None:
    text = "Dear  PERSON_1 , bye"
    m = only_match(text)
    assert text[m.start : m.end] == "PERSON_1"


@pytest.mark.parametrize("raw", [r"PERSON\_1", r"[PERSON\_1]", "[PERSON 1]", "[ PERSON_1 ]"])
def test_an_escaped_underscore_and_a_spaced_pair_of_brackets_are_changed_forms(raw: str) -> None:
    m = only_match(f"Dear {raw}, thanks")
    assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", False, raw)


@pytest.mark.parametrize(
    "text",
    [
        "Company 1",
        "ID 12345",
        "Phone 2",
        "person 1",
        "PERSON 1",
        "Address 5 and Email 3 and URL 4",
        "Person 1 shall pay Company 2 the Amount 500 (Quantity 1,000)",
    ],
)
def test_a_name_and_number_separated_by_a_space_without_brackets_are_prose(text: str) -> None:
    # A bracketless form needs an underscore, a hyphen or markdown's escaped underscore between
    # the name and the number; a space is ordinary text ("Company 1", "ID 12345").
    assert find_placeholders(text) == []


@pytest.mark.parametrize(
    "text",
    [
        f"PERSON{NBSP}1",
        f"Person{NARROW_NBSP}1",
        f"person{THIN_SPACE}1",
        f"Company{NBSP}2 and ID{NBSP}12345",
    ],
)
def test_unicode_spaces_are_prose_too_when_there_are_no_brackets(text: str) -> None:
    assert find_placeholders(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "[PERSON 1",
        "PERSON 1]",
        f"[PERSON{NBSP}1",
        "[Person 1 and Person 2]",
        "see [Company 1, Company 2]",
        r"\[PERSON 1",
    ],
)
def test_a_space_between_name_and_number_needs_both_brackets(text: str) -> None:
    assert find_placeholders(text) == []


@pytest.mark.parametrize("separator", ["_", "-", r"\_"])
@pytest.mark.parametrize("brackets", [("", ""), ("[", "]"), ("[", ""), ("", "]")])
def test_underscore_hyphen_and_escaped_underscore_work_with_or_without_brackets(
    brackets: tuple[str, str], separator: str
) -> None:
    opening, closing = brackets
    raw = f"{opening}PERSON{separator}1{closing}"
    m = only_match(f"Dear {raw}, thanks")
    assert (m.raw, m.placeholder) == (raw, "[PERSON_1]")
    assert m.exact == (raw == "[PERSON_1]")


def test_template_brackets_are_untouched() -> None:
    m = only_match("[Name] signs for [COMPANY_1] on [Date]")
    assert (m.raw, m.exact) == ("[COMPANY_1]", True)


def test_several_placeholders_come_back_in_text_order() -> None:
    text = "[PERSON_1] met person-2 and **[COMPANY_1]** (or [PERSON_1][PERSON_1])."
    found = find_placeholders(text)
    assert [(m.raw, m.placeholder, m.exact) for m in found] == [
        ("[PERSON_1]", "[PERSON_1]", True),
        ("person-2", "[PERSON_2]", False),
        ("**[COMPANY_1]**", "[COMPANY_1]", False),
        ("[PERSON_1]", "[PERSON_1]", True),
        ("[PERSON_1]", "[PERSON_1]", True),
    ]
    assert all(text[m.start : m.end] == m.raw for m in found)
    assert [m.start for m in found] == sorted(m.start for m in found)


def test_not_a_placeholder() -> None:
    assert find_placeholders("[Name] and [Date] and PERSONAL_1 and [TOTAL_3]") == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "nothing here",
        "[PERSON]",
        "[PERSON_]",
        "[PERSON_X]",
        "[PERSON_1a]",
        "PERSON_1a",
        "XPERSON_1",
        "PERSONAL_1",
        "PERSON__1",
        "PERSON1",
        "[PERSON1]",
        "[PERSON_ 1]",
        "[CUSTOMER_1]",
        "[IDENTITY_2]",
        "[ID]",
        "valid_1 and paid 2",
        IMAGE_NOTE,
        OBJECT_NOTE,
        "[PERSON_1234567890]",
        "PERSON_1234567890",
    ],
)
def test_near_misses_are_not_placeholders(text: str) -> None:
    assert find_placeholders(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "[PERSON_\N{ARABIC-INDIC DIGIT THREE}]",  # an Arabic-Indic digit is not a digit here
        "[PERSON_\N{FULLWIDTH DIGIT ONE}]",  # nor is a full-width one
        "[PER\N{LATIN SMALL LETTER LONG S}ON_1]",  # a long s is not an S
        "[EMA\N{LATIN CAPITAL LETTER I WITH DOT ABOVE}L_1]",  # nor is a dotted capital I an I
        "[\N{LATIN SMALL LETTER DOTLESS I}D_1]",  # nor is a dotless i an i
    ],
)
def test_only_ascii_letters_and_digits_count(text: str) -> None:
    assert find_placeholders(text) == []


def test_a_number_of_up_to_nine_digits_is_a_placeholder_number() -> None:
    m = only_match("[PERSON_123456789]")
    assert (m.placeholder, m.exact) == ("[PERSON_123456789]", True)


def test_a_very_long_number_is_not_a_placeholder_and_does_not_crash() -> None:
    # int() refuses digit strings this long; the grammar must not get that far.
    text = "[PERSON_" + "9" * 5000 + "] PERSON_" + "7" * 5000
    assert find_placeholders(text) == []
    assert next_free_number(text, PlaceholderType.PERSON) == 1


@pytest.mark.parametrize("placeholder_type", ALL_TYPES)
def test_placeholder_re_matches_the_exact_form(placeholder_type: PlaceholderType) -> None:
    m = PLACEHOLDER_RE.fullmatch(f"[{placeholder_type.value}_12]")
    assert m is not None
    assert (m["type"], m["number"]) == (placeholder_type.value, "12")


@pytest.mark.parametrize(
    "text",
    ALTERED_FORMS + MORE_ALTERED_FORMS + ["[PERSON_]", "[PERSON_x]", "[PERSON_1234567890]"],
)
def test_placeholder_re_refuses_every_other_form(text: str) -> None:
    assert PLACEHOLDER_RE.fullmatch(text) is None


def test_placeholder_re_finds_only_exact_placeholders_in_a_text() -> None:
    text = "[PERSON_1] PERSON_2 [person_3] [COMPANY_4] [Name]"
    assert [m.group() for m in PLACEHOLDER_RE.finditer(text)] == ["[PERSON_1]", "[COMPANY_4]"]


@pytest.mark.parametrize(
    "raw",
    ALTERED_FORMS
    + MORE_ALTERED_FORMS
    + [
        "[PERSON_1]",
        "[PERSON_0]",
        "[PERSON_10]",
        "[PERSON_100]",
        "[PERSON_123456789]",  # the longest number both patterns accept
        "[PERSON_007]",
        "[PERSON_00]",
    ],
)
def test_exact_means_the_same_to_find_placeholders_and_to_placeholder_re(raw: str) -> None:
    (m,) = find_placeholders(raw)
    assert m.exact == (PLACEHOLDER_RE.fullmatch(m.raw) is not None)
    assert m.exact == (m.raw == m.placeholder)


def test_placeholder_match_is_a_frozen_value() -> None:
    m = only_match("see [PERSON_1].")
    assert m == PlaceholderMatch(4, 14, "[PERSON_1]", "[PERSON_1]", True)
    with pytest.raises(FrozenInstanceError):
        m.start = 0


def test_next_free() -> None:
    assert next_free_number("[PERSON_2] [PERSON_7] [COMPANY_1]", PlaceholderType.PERSON) == 8


def test_next_free_empty() -> None:
    assert next_free_number("nothing", PlaceholderType.PERSON) == 1


def test_next_free_counts_altered_forms_too() -> None:
    # A restore would mistake any of these for a placeholder, so the numbering must clear them.
    text = r"PERSON_3 and [person-5] and **[PERSON_4]** and [PERSON_007] and PERSON\_9"
    assert next_free_number(text, PlaceholderType.PERSON) == 10


def test_next_free_ignores_what_is_not_a_placeholder() -> None:
    text = "PERSONAL_9 [PERSON_x] [CUSTOMER_8] Person 4 and ID 12345"
    assert next_free_number(text, PlaceholderType.PERSON) == 1
    assert next_free_number(text, PlaceholderType.ID) == 1


def test_next_free_after_number_zero_is_one() -> None:
    assert next_free_number("[PERSON_0]", PlaceholderType.PERSON) == 1


@pytest.mark.parametrize("placeholder_type", ALL_TYPES)
def test_next_free_looks_only_at_the_asked_type(placeholder_type: PlaceholderType) -> None:
    text = f"[{placeholder_type.value}_5]"
    assert next_free_number(text, placeholder_type) == 6
    assert all(
        next_free_number(text, other) == 1 for other in ALL_TYPES if other is not placeholder_type
    )
