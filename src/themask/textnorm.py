"""Text normalisation and value variants.

``normalize`` is what the leak check uses to prove a value is really gone from a file, whatever its
spacing or punctuation. ``variants_of`` is how one company, person or number is recognised in all
its spellings. ``flexible_pattern`` finds those spellings in running text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

import phonenumbers

from themask.model import PlaceholderType

# Company legal forms, spelled the way they are usually written. Match them as whole words (never
# the end of an ordinary word such as "Nabisco"), with or without their dots ("B.V." and "BV"), and
# ignoring case ("GMBH", "ltd", "plc"). The one exception: "se", "ab" and "co" (and "as", which is
# what "A/S" becomes without its slash) are ordinary words in lower case, so they only count when
# they are capitalised ("SE", "AB", "Co.").
LEGAL_FORMS: tuple[str, ...] = (
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

# Words that begin many company names without telling one company from another. The first word of a
# company name is only used on its own when it is not one of these. Compare ignoring case.
COMMON_WORDS: frozenset[str] = frozenset(
    {
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
)

# Titles that come before a person's name. Compare ignoring case and a trailing dot ("Dr.").
HONORIFICS: tuple[str, ...] = (
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
# normalize
# --------------------------------------------------------------------------------------------

_NOT_A_LETTER_OR_DIGIT = re.compile(r"[\W_]+")


def normalize(s: str) -> str:
    """Reduce ``s`` to lower-case letters and digits, so two spellings of a value compare equal.

    The text is put in NFKC form (a "fi" ligature or a full-width digit becomes plain text), case
    folded, and then everything that is not a letter or a digit is dropped: every Unicode space
    (including the non-breaking and thin spaces Word puts inside numbers), quotes, brackets,
    slashes, hyphens and dashes, full stops, commas, and any other symbol or invisible character.
    So ``1,250,000``, ``1.250.000`` and ``1 250 000`` all become ``1250000``.
    """
    folded = unicodedata.normalize("NFKC", s).casefold()
    return _NOT_A_LETTER_OR_DIGIT.sub("", folded)


# --------------------------------------------------------------------------------------------
# variants_of
# --------------------------------------------------------------------------------------------

_HONORIFIC_KEYS = frozenset(normalize(honorific) for honorific in HONORIFICS)

# Legal forms grouped by how many words they are written in ("Ltd. Şti." is two, the rest one),
# each as its normalised spelling, which is how "B.V.", "BV" and "b.v." come out the same. The
# longest group comes first, so a name is always tested for its longest possible legal form.
_LEGAL_FORM_KEYS: dict[int, frozenset[str]] = {
    words: frozenset(normalize(form) for form in LEGAL_FORMS if len(form.split()) == words)
    for words in sorted({len(form.split()) for form in LEGAL_FORMS}, reverse=True)
}
# Legal forms that are also ordinary words in lower case; see the note on LEGAL_FORMS.
_ORDINARY_WORDS = frozenset({"se", "ab", "co", "as"})
_COMMON_WORDS_FOLDED = frozenset(word.casefold() for word in COMMON_WORDS)
# What is left dangling in front of a legal form: "Smith & Co." leaves "Smith &".
_CONNECTORS = frozenset({"", "and"})
_EDGE_PUNCTUATION = re.compile(r"^[\W_]+|[\W_]+$")
_MIN_LETTERS_IN_FIRST_TOKEN = 4

_AMOUNT = re.compile(
    r"""
    ^(?P<before>\D*?)                 # a currency code or symbol written before the number
    (?P<number>\d(?:[\d.,\s]*\d)?)    # 1,250,000.00  1.250.000,00  1 250 000,00
    (?P<magnitude>\s*(?:k|m|bn|million|billion|thousand)\b)?    # 1.25m  2 million
    (?P<after>\D*)$                   # a currency code or symbol written after the number
    """,
    re.IGNORECASE | re.VERBOSE,
)
# ",00" or ".00" at the end. Three zeros ("1.000") are a thousands group, not decimals.
_ZERO_DECIMALS = re.compile(r"[.,]00$")
# A bare "5" or "25" would match clause numbers all over a contract, so a number on its own is only
# a variant when it still has this many digits (or letters, in "1.25m") once separators are gone.
_MIN_BARE_AMOUNT_LENGTH = 4

# Tried in this order; None is for numbers written with a "+" and country code. The first region
# that accepts the digits as a valid number decides how the national format is written.
_PHONE_REGIONS: tuple[str | None, ...] = (None, "GB", "NL", "DE", "TR")

_URL_SCHEME = re.compile(r"[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def _person_variants(value: str) -> set[str]:
    tokens = value.split()
    variants: set[str] = set()
    while tokens and normalize(tokens[0]) in _HONORIFIC_KEYS:
        tokens = tokens[1:]
        if len(tokens) >= 2:  # "Mr Smith" must not become "Smith"
            variants.add(" ".join(tokens))
    if len(tokens) >= 2 and tokens[0][0].isalpha():
        variants.add(f"{tokens[0][0]}. {tokens[-1]}")
    return variants


def _is_legal_form(text: str, words: int) -> bool:
    key = normalize(text)
    if key not in _LEGAL_FORM_KEYS[words]:
        return False
    return not (key in _ORDINARY_WORDS and text.islower())


def _without_legal_form(tokens: list[str]) -> list[str] | None:
    """``tokens`` minus one trailing legal form, or ``None`` when the name does not end in one."""
    for words in _LEGAL_FORM_KEYS:
        if len(tokens) > words and _is_legal_form(" ".join(tokens[-words:]), words):
            name = tokens[:-words]
            while name and normalize(name[-1]) in _CONNECTORS:
                name = name[:-1]
            return name
    return None


def _company_variants(value: str) -> set[str]:
    tokens = value.split()
    without_form = _without_legal_form(tokens)
    name = tokens if without_form is None else without_form
    variants: set[str] = set()
    if without_form is not None and len(name) >= 2:
        variants.add(" ".join(name).rstrip(" ,;"))
    if name:
        first = _EDGE_PUNCTUATION.sub("", name[0])
        letters = sum(character.isalpha() for character in first)
        if letters >= _MIN_LETTERS_IN_FIRST_TOKEN and first.casefold() not in _COMMON_WORDS_FOLDED:
            variants.add(first)
    return variants


def _amount_variants(value: str) -> set[str]:
    parsed = _AMOUNT.match(value)
    if parsed is None:  # no digits, or more than one number
        return set()
    before, magnitude, after = parsed["before"], parsed["magnitude"] or "", parsed["after"]
    numbers = {parsed["number"]}
    if not magnitude:
        numbers.add(_ZERO_DECIMALS.sub("", parsed["number"]))
    has_currency = bool((before + after).strip())
    variants: set[str] = set()
    for number in numbers:
        bare = number + magnitude
        if len(normalize(bare)) >= _MIN_BARE_AMOUNT_LENGTH:
            variants.add(bare)
        if has_currency:
            variants.add(f"{before}{bare}{after}".strip())
    return variants


def _parse_phone(value: str, region: str | None) -> phonenumbers.PhoneNumber | None:
    try:
        return phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException:
        return None


def _phone_variants(value: str) -> set[str]:
    for region in _PHONE_REGIONS:
        number = _parse_phone(value, region)
        if number is not None and phonenumbers.is_valid_number(number):
            return {phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)}
    return set()


def _url_variants(value: str) -> set[str]:
    scheme = _URL_SCHEME.match(value)
    head = scheme.group() if scheme else ""
    without_scheme = value[len(head) :]
    without_www = without_scheme[4:] if without_scheme[:4].casefold() == "www." else without_scheme
    variants = {without_scheme}
    if without_www:
        variants |= {head + without_www, without_www}
    variants.discard("")
    return variants


_VARIANT_RULES: dict[PlaceholderType, Callable[[str], set[str]]] = {
    PlaceholderType.PERSON: _person_variants,
    PlaceholderType.COMPANY: _company_variants,
    PlaceholderType.AMOUNT: _amount_variants,
    PlaceholderType.PHONE: _phone_variants,
    PlaceholderType.URL: _url_variants,
}


def variants_of(value: str, t: PlaceholderType) -> set[str]:
    """Every other way ``value`` is likely to be written, plus ``value`` itself.

    * PERSON: without the honorific ("Mr John Smith" gives "John Smith"), and as first initial plus
      surname ("J. Smith"). The surname alone is never a variant: it would hide every other person
      who shares it.
    * COMPANY: without one trailing legal form ("Northwind Trading B.V." gives "Northwind
      Trading"), and the first word alone ("Northwind") when it has at least four letters and is not
      one of ``COMMON_WORDS``.
    * AMOUNT: with and without the currency code or symbol, and with and without zero decimals
      ("EUR 1,250,000.00" gives "1,250,000"). A number on its own with fewer than four digits is
      skipped ("5", "25"), because it would match clause numbers all over the contract.
    * PHONE: the national format when the number is valid in the UK, the Netherlands, Germany or
      Turkey, or carries its own country code ("+31 20 123 4567" gives "020 123 4567").
    * URL: without the scheme, without ``www.``, and without both.
    * Every other type: just the value. Spacing and case differences are handled by ``normalize``
      and ``flexible_pattern``.
    """
    derive = _VARIANT_RULES.get(t)
    return {value} | (derive(value) if derive else set())


# --------------------------------------------------------------------------------------------
# flexible_pattern
# --------------------------------------------------------------------------------------------

_NOT_PRECEDED_BY_LETTER_OR_DIGIT = r"(?<![A-Za-z0-9])"
_NOT_FOLLOWED_BY_LETTER_OR_DIGIT = r"(?![A-Za-z0-9])"


def flexible_pattern(value: str) -> re.Pattern[str]:
    """A case-insensitive pattern that finds ``value`` however the text spaces it.

    Every run of whitespace in ``value`` matches any run of whitespace in the text (a space, a
    tab, a line break or a non-breaking space), and everything else is matched literally. When
    ``value`` starts or ends with a letter or digit, it must not touch another letter or digit
    there, so "Smith" is not found inside "Smithson". A blank ``value`` is rejected, because its
    pattern would match everywhere.
    """
    if not value.strip():
        raise ValueError("A blank value cannot be searched for.")
    body = "".join(
        r"\s+" if part.isspace() else re.escape(part) for part in re.split(r"(\s+)", value)
    )
    start = _NOT_PRECEDED_BY_LETTER_OR_DIGIT if value[0].isalnum() else ""
    end = _NOT_FOLLOWED_BY_LETTER_OR_DIGIT if value[-1].isalnum() else ""
    return re.compile(start + body + end, re.IGNORECASE)
