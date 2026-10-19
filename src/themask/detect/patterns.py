"""Pattern recognizers for what a contract writes in figures and codes.

Amounts, percentages and quantities; VAT, company registration, bank and identity numbers; and the
e-mail and web address recognizers that stand in for Presidio's own. Every one is a Presidio
``PatternRecognizer``. Ours report one of our placeholder types as their entity, so the engine needs
no second mapping for them; the two stand-ins report Presidio's entity names, which the engine maps
like those of every other Presidio recognizer.

A regular expression finds the candidates, then a check looks at each one in its place in the text
and either confirms it with a score or drops it. A candidate that may be a confidential value is
kept: a missed value is a leak, while a value hidden by mistake costs the owner one click in review.
"""

from __future__ import annotations

import re

from presidio_analyzer import (
    AnalysisExplanation,
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpArtifacts
from presidio_analyzer.predefined_recognizers import EmailRecognizer, UrlRecognizer
from schwifty import BIC
from schwifty.exceptions import SchwiftyException
from stdnum.ch import uid as ch_uid
from stdnum.eu import vat as eu_vat
from stdnum.gb import vat as gb_vat
from stdnum.nl import bsn
from stdnum.no import mva as no_mva
from stdnum.tr import tckimlik

from themask.model import PlaceholderType

# --- Building blocks ------------------------------------------------------------------------------


def _any_of(*alternatives: str) -> str:
    """A group that matches any one of ``alternatives``, tried in the order given."""
    return "(?:" + "|".join(alternatives) + ")"


def _any_case(*alternatives: str) -> str:
    """``_any_of``, in upper, lower or mixed case."""
    return "(?i:" + "|".join(alternatives) + ")"


# A space, or one of the spaces Word puts between groups of digits: no-break, narrow no-break,
# thin and figure space.
_SPACE_CHARS = r" \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}\N{THIN SPACE}\N{FIGURE SPACE}"
_SPACE = "[" + _SPACE_CHARS + "]"
_APOSTROPHES = r"'\N{RIGHT SINGLE QUOTATION MARK}"
_DASH = r"[\-\N{EN DASH}]"
_LETTER = r"[^\W\d_]"


def _in_brackets(inner: str) -> str:
    """``inner`` in round brackets, as a contract repeats a number in words: "ten (10)"."""
    return "(?:" + _SPACE + r"*\(" + _SPACE + "*" + inner + _SPACE + r"*\))"


# A figure as an amount or a quantity is written. A full stop or a comma may split the digits into
# groups of any length, so that 0.125 and 1,250,000.00 are both read whole; a space or an apostrophe
# may stand before a group of exactly three (1 250 000, and the Swiss 1'250'000).
_FIGURE = r"\d+(?:[.,]\d+|[" + _SPACE_CHARS + _APOSTROPHES + r"]\d{3}(?!\d))*"
_FIGURE_IN_BRACKETS = _in_brackets(_FIGURE)

# A second figure that makes a range of the first: 10-20, 10 – 20, 10 to 20.
_TO = _SPACE + "?" + _any_of(_DASH, "to") + _SPACE + "?"
_RANGE = "(?:" + _TO + _FIGURE + ")?"

# A multiplier after a figure: 1.25m, 500k, 2.3bn, 3 million.
_MAGNITUDE = "(?:" + _SPACE + r"?(?i:thousand|million|billion|trillion|mln|mio|mn|bn|k|m)(?!\w))"

# A number in words, from "one" up: "twenty-five thousand", "two hundred and fifty thousand".
# Tens and teens are tried before ones, so that "seventy" and "seventeen" are not read as "seven".
# A hyphen is only ever the gap between two words, so "twenty-one" can be read in one way only: with
# two readings, a long run of such words took exponential time to match.
_ONES = "one|two|three|four|five|six|seven|eight|nine"
_TEENS = "ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
_TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_BELOW_HUNDRED = _any_of(_TENS, _TEENS, _ONES)
_WORD_GAP = _any_of(_SPACE + "+(?:and" + _SPACE + "+)?", "-")
_NUMBER_PART = _any_of("hundred|thousand|million|billion", _BELOW_HUNDRED)
_NUMBER_WORDS = r"(?i:\b" + _BELOW_HUNDRED + "(?:" + _WORD_GAP + _NUMBER_PART + r")*\b)"

# A number in words, maybe followed by the same number in figures in brackets: "fifty thousand",
# "ten (10)". The words are captured, for the checks that need to know what they say.
_SPELLED = "(?P<words>" + _NUMBER_WORDS + ")" + _FIGURE_IN_BRACKETS + "?"

# Currency signs, written before or after a figure.
_CURRENCY_SIGN = (
    r"(?:\N{EURO SIGN}|\N{POUND SIGN}|\N{YEN SIGN}|\N{TURKISH LIRA SIGN}|\N{INDIAN RUPEE SIGN}"
    r"|\N{RUBLE SIGN}|(?:US|A|C|NZ|HK|S)?\$)"
)
# The ISO codes of the currencies a European contract is likely to use, and the abbreviations kr,
# zł and TL. Upper case only, as they are written: "TRY" is the Turkish lira, "try" is a verb.
_CURRENCY_CODES = (
    "EUR|GBP|USD|CHF|TRY|SEK|NOK|DKK|ISK|PLN|CZK|HUF|RON|BGN|RSD|UAH|RUB|JPY|CNY|RMB|HKD|SGD|AUD"
    "|CAD|NZD|INR|ZAR|BRL|MXN|AED|SAR|QAR|KWD|ILS|EGP|MAD|KRW|TWD|THB|MYR|IDR|NGN|KES|TL|kr"
    r"|z\N{LATIN SMALL LETTER L WITH STROKE}"
)
# A code counts only when it is not part of a longer word.
_CURRENCY_CODE = "(?<!" + _LETTER + ")(?:" + _CURRENCY_CODES + ")(?!" + _LETTER + ")"
_CURRENCY_MARK = _any_of(_CURRENCY_SIGN, _CURRENCY_CODE)

# Currency names, written after a figure or a number in words.
_DOLLAR_COUNTRIES = _any_of(
    "us",
    r"u\.s\.",
    "american",
    "canadian",
    "australian",
    "singapore",
    "hong" + _SPACE + "+kong",
    "new" + _SPACE + "+zealand",
)
_CURRENCY_WORD = (
    _any_case(
        "euros?",
        "pounds?(?:" + _SPACE + "+sterling)?",
        "sterling",
        "(?:" + _DOLLAR_COUNTRIES + _SPACE + "+)?dollars?",
        "(?:swiss" + _SPACE + "+)?francs?",
        "(?:turkish" + _SPACE + "+)?liras?",
        "yen|yuan|renminbi|rupees?|roubles?|rubles?|kron(?:a|e|er|or|ur)|forints?",
        r"z(?:l|\N{LATIN SMALL LETTER L WITH STROKE})otys?",
    )
    + r"(?!\w)"
)
_CURRENCY_AFTER = _any_of(_CURRENCY_MARK, _CURRENCY_WORD)

# The units a quantity is counted or measured in; never a unit of time, so that "30 days" stays
# visible. Single letters are case-sensitive (t, l, L, m) so that they do not match a stray capital.
# "records" is how a data processing agreement counts the personal data it covers ("up to 350,000
# records"); one record is no volume.
_UNIT_WORDS = (
    "units?|pieces?|pcs|pc|items?|cartons?|cases?|boxes|box|pallets?|packs?|rolls?|bags?"
    "|containers?|kilograms?|kilos?|kgs?|tonnes?|tons?|litres?|liters?|ml|sqm|cbm|metres?|meters?"
    r"|km|m\N{SUPERSCRIPT TWO}|m2|m\N{SUPERSCRIPT THREE}|m3|records"
)
_UNIT = "(?:(?i:" + _UNIT_WORDS + r")|t|l|L|m)(?!\w)"

# What makes a figure a duration, which stays visible: "1,000 days", "2,500 working days",
# "a 1,000-day period", "ten thousand (10,000) days".
_DAY_KIND = "(?i:(?:business|working|calendar|banking)" + _SPACE + "+)?"
_TIME_UNIT = r"(?i:day|week|month|year|hour)s?\b"
_DURATION_AFTER = re.compile("(?:" + _SPACE + r"|-|\))*" + _DAY_KIND + _TIME_UNIT)

# What may stand between a label such as "number" and the value after it: spaces, and the tab a
# form in Word puts there ("BIC:\tDEUTDEBB").
_LABEL_GAP = "[" + _SPACE_CHARS + "\t]"
_LABEL_TO_VALUE = _LABEL_GAP + "*[:#]?" + _LABEL_GAP + "*"

# The words that make the number after them a reference into the contract or a law, which stays
# visible: "section 1159", "Article 1101", "§ 1004".
_REFERENCE_WORDS = (
    "clauses?|sections?|sec|articles?|art|schedules?|annex(?:es)?|appendix|appendices|exhibits?"
    "|paragraphs?|para|parts?"
)
_REFERENCE = r"(?:\b(?i:" + _REFERENCE_WORDS + r")\.?|\N{SECTION SIGN})"
_REFERENCE_BEFORE = re.compile(_REFERENCE + _SPACE + r"*\Z")

# A figure that is not part of a longer number or word.
_ALONE_BEFORE = r"(?<![\w.,])"
_ALONE_AFTER = r"(?!\w|[.,]\d)"


class CheckedPatternRecognizer(PatternRecognizer):
    """A Presidio pattern recognizer that checks every match in its place in the text.

    Presidio's own check (``validate_result``) sees only the matched text, and can only keep a match
    at full score or drop it. ``score_match`` also sees the text around the match and returns its
    score: the pattern's own, another one, or 0 to drop it. A pattern may capture the value in a
    group named ``value``; the finding is then that group alone, and the words around it (such as
    "account number") are only context.

    Each pattern carries its own flags inline, such as ``(?i:...)`` around words that may be written
    in any case.
    """

    # Set by Presidio's EntityRecognizer (to the class name); declared here for the type checker.
    name: str

    def __init__(
        self, entity: PlaceholderType, patterns: list[Pattern], context: list[str] | None = None
    ) -> None:
        super().__init__(
            supported_entity=entity.value,
            patterns=patterns,
            context=context or [],
            global_regex_flags=0,
        )
        self._expressions = [(pattern, re.compile(pattern.regex)) for pattern in patterns]

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: NlpArtifacts | None = None,
        regex_flags: int | None = None,
    ) -> list[RecognizerResult]:
        """Every checked match in ``text``; ``regex_flags`` is ignored, the patterns set theirs."""
        results = []
        for pattern, expression in self._expressions:
            for match in expression.finditer(text):
                score = self.score_match(text, match, pattern)
                if score <= 0:
                    continue
                if "value" in expression.groupindex:
                    start, end = match.span("value")
                else:
                    start, end = match.span()
                explanation = AnalysisExplanation(
                    recognizer=self.name,
                    original_score=pattern.score,
                    pattern_name=pattern.name,
                    pattern=pattern.regex,
                    textual_explanation=f"Detected by `{self.name}` using pattern `{pattern.name}`",
                )
                results.append(
                    RecognizerResult(
                        entity_type=self.supported_entities[0],
                        start=start,
                        end=end,
                        score=score,
                        analysis_explanation=explanation,
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                        },
                    )
                )
        return EntityRecognizer.remove_duplicates(results)

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        """The score of ``match``, found by ``pattern`` in ``text``; 0 drops it."""
        return pattern.score


# --- Money, percentages and quantities -----------------------------------------------------------

# 1.000,- and 1.000,–: how a Dutch, German or Swiss amount may end.
_DECIMAL_DASHES = r"(?:[.,]" + _DASH + "{1,2})?"
_AMOUNT_FIGURE = _FIGURE + _RANGE + _DECIMAL_DASHES + _MAGNITUDE + "?"


class AmountRecognizer(CheckedPatternRecognizer):
    """Amounts of money: a figure with a currency before or after it, or a number in words.

    EUR 1,250,000.00 · €1.25m · 1.250.000,00 EUR · EUR 1 250 000,00 · CHF 1'250'000.– ·
    "one million euros" · "fifty thousand (50,000) euros".
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.AMOUNT,
            [
                Pattern(
                    "Currency before the figure",
                    _CURRENCY_MARK + _SPACE + "?" + _AMOUNT_FIGURE,
                    0.85,
                ),
                Pattern(
                    "Currency after the figure",
                    _ALONE_BEFORE + _AMOUNT_FIGURE + _SPACE + "?" + _CURRENCY_AFTER,
                    0.85,
                ),
                Pattern("Amount in words", _SPELLED + _SPACE + "+" + _CURRENCY_AFTER, 0.85),
            ],
        )


_PERCENT_FIGURE = r"\d+(?:[.,]\d+)?"
_PERCENT_FIGURES = _PERCENT_FIGURE + "(?:" + _TO + _PERCENT_FIGURE + ")?"
_PER_CENT = "(?i:per" + _SPACE + r"?-?cent|percent|pct)(?!\w)"
_PERCENT_MARK = _any_of(_SPACE + "?%", _SPACE + "*" + _PER_CENT)
# What makes a number in words a percentage.
_PERCENT_AFTER_WORDS = _any_of(
    _in_brackets(_PERCENT_FIGURE + _SPACE + "?%"),  # five (5%)
    _FIGURE_IN_BRACKETS + "?" + _PERCENT_MARK,  # five per cent, five (5) per cent
)


class PercentRecognizer(CheckedPatternRecognizer):
    """Percentages: 12.5% · 12,5 % · 5-10% · 8 per cent · 8 percent · "five (5) per cent"."""

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.PERCENT,
            [
                Pattern(
                    "Percentage in figures",
                    _ALONE_BEFORE + _PERCENT_FIGURES + _PERCENT_MARK,
                    0.85,
                ),
                Pattern("Percentage in words", _NUMBER_WORDS + _PERCENT_AFTER_WORDS, 0.85),
            ],
        )


# "records" as a quantity's unit, and a plain year before it.
_RECORDS = re.compile(r"(?i:records)\Z")
_PLAIN_YEAR = re.compile(r"(?:19|20)\d{2}(?!\d)" + _SPACE + r"?(?i:records)\Z")
# A currency just before a figure: the figure is an amount (€2.5m), not a length in metres.
_CURRENCY_BEFORE = re.compile(_CURRENCY_MARK + _SPACE + r"?\Z")
_SCALE_WORD = re.compile(r"(?i:hundred|thousand|million|billion)")


class QuantityRecognizer(CheckedPatternRecognizer):
    """Quantities: a figure or a number in words with a unit that is not a unit of time.

    10,000 units · 48 pallets · 2.5 tonnes · 500kg · 1 250 m² · 2.5 million units · "ten (10)
    pallets" · 350,000 records. A number in words counts only with a scale word or figures after
    it, so that "in two cases" and "one item" stay prose. Records named by a reference or a year
    ("the Article 30 records", "the 2025 records") are no quantity.
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.QUANTITY,
            [
                Pattern(
                    "Quantity in figures",
                    _ALONE_BEFORE + _FIGURE + _RANGE + _MAGNITUDE + "?" + _SPACE + "?" + _UNIT,
                    0.8,
                ),
                Pattern("Quantity in words", _SPELLED + _SPACE + "+" + _UNIT, 0.8),
            ],
        )

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        words = match.groupdict().get("words")
        if words is not None:
            spelled_out = _SCALE_WORD.search(words) or "(" in match.group()
            return pattern.score if spelled_out else 0.0
        if _CURRENCY_BEFORE.search(text, max(0, match.start() - 8), match.start()):
            return 0.0
        if _RECORDS.search(match.group()) and _are_records_named(text, match):
            return 0.0
        return pattern.score


def _are_records_named(text: str, match: re.Match[str]) -> bool:
    """Whether the figure before "records" names them rather than counts them: a reference ("the
    Article 30 records") or a year ("the 2025 records", ruling R95).
    """
    if _PLAIN_YEAR.match(match.group()):
        return True
    return _REFERENCE_BEFORE.search(text, max(0, match.start() - 24), match.start()) is not None


# --- VAT, registration and identity numbers ------------------------------------------------------

# One optional space, full stop or hyphen between two characters of a VAT number.
_SEP = r"[ .\-]?"


def _digits(count: int, most: int | None = None) -> str:
    """``count`` digits (``count`` to ``most`` when given), each two maybe split by one ``_SEP``."""
    repeat = f"{{{count - 1}}}" if most is None else f"{{{count - 1},{most - 1}}}"
    return r"\d(?:" + _SEP + r"\d)" + repeat


_UK_VAT = _digits(12) + "|" + _digits(9) + "|(?:GD|HA)" + _SEP + r"\d{3}"

# What follows each country prefix in a VAT number, as the countries write them.
_VAT_FORMATS = {
    "AT": "U" + _SEP + _digits(8),
    "BE": _digits(9, 10),
    "BG": _digits(9, 10),
    "CY": _digits(8) + _SEP + "[A-Z]",
    "CZ": _digits(8, 10),
    "DE": _digits(9),
    "DK": _digits(8),
    "EE": _digits(9),
    "EL": _digits(9),
    "GR": _digits(9),
    "ES": "[0-9A-Z]" + _SEP + _digits(7) + _SEP + "[0-9A-Z]",
    "FI": _digits(8),
    "FR": "[0-9A-HJ-NP-Z]{2}" + _SEP + _digits(9),
    "HR": _digits(11),
    "HU": _digits(8),
    "IE": r"\d" + _SEP + "[0-9A-Z+*]" + _SEP + _digits(5) + _SEP + "[A-Z]{1,2}",
    "IT": _digits(11),
    "LT": _digits(12) + "|" + _digits(9),
    "LU": _digits(8),
    "LV": _digits(11),
    "MT": _digits(8),
    "NL": _digits(9) + _SEP + "B" + _SEP + r"\d{2}",
    "PL": _digits(10),
    "PT": _digits(9),
    "RO": _digits(2, 10),
    "SE": _digits(12),
    "SI": _digits(8),
    "SK": _digits(10),
    "XI": _UK_VAT,
    "GB": _UK_VAT,
    "CH": "E" + _SEP + _digits(9) + "(?:" + _SPACE + "?(?:MWST|TVA|IVA|TPV))?",
    "NO": _digits(9) + "(?:" + _SPACE + "?MVA)?",
}
_VAT = (
    r"(?<![A-Za-z0-9])"
    + _any_of(*(country + _SEP + _any_of(body) for country, body in _VAT_FORMATS.items()))
    + r"(?![A-Za-z0-9])"
)
_SWISS_VAT_SUFFIX = re.compile(r"\W*(?:MWST|TVA|IVA|TPV)\Z")


def _vat_is_valid(number: str) -> bool:
    """Whether the check digits of a VAT number (with its country prefix) are right."""
    country = number[:2]
    if country == "GB":
        return bool(gb_vat.is_valid(number))
    if country == "CH":
        return bool(ch_uid.is_valid(_SWISS_VAT_SUFFIX.sub("", number)))
    if country == "NO":
        return bool(no_mva.is_valid(number))
    return bool(eu_vat.is_valid(number))


class VatRecognizer(CheckedPatternRecognizer):
    """VAT numbers with their country prefix, in the format of an EU country, the UK, CH or NO.

    0.9 when the check digits are right, 0.6 when only the format is: a number with a typing error
    in it is still the party's number.
    """

    def __init__(self) -> None:
        super().__init__(PlaceholderType.ID, [Pattern("VAT number", _VAT, 0.6)])

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        return 0.9 if _vat_is_valid(match.group()) else pattern.score


# The words before a company registration number, then "number" (or "no", "nr") and the number:
# maybe a letter prefix (SC123456, B 123456), then digits, maybe in groups (0123.456.789).
_REGISTRATION_CONTEXT = r"\b" + _any_case(
    "registered",
    "registration",
    "company",
    "companies" + _SPACE + "+house",
    "chamber" + _SPACE + "+of" + _SPACE + "+commerce",
    "kvk",
    "hrb",
)
_NUMBER_LABEL = r"(?i:\b(?:number|nummer|no|nr)\b\.?)"
_REGISTRATION_LABEL = _REGISTRATION_CONTEXT + r"\b[^\n]{0,40}?" + _NUMBER_LABEL + _LABEL_TO_VALUE
_REGISTER_LABEL = r"(?i:\b(?:kvk|hrb)\b)[:.\-" + _SPACE_CHARS + "]*"  # KvK 12345678, HRB 123456
_REGISTRATION_VALUE = (
    r"(?P<value>(?:[A-Z]{1,3}[ \-]?)?\d+(?:[.\-/" + _SPACE_CHARS + r"]\d+)*)(?!\w)"
)


class RegistrationNumberRecognizer(CheckedPatternRecognizer):
    """Company registration numbers, found by the words before them.

    "registered in England and Wales under number 01234567" · "Company No. 01234567" ·
    "KvK 12345678" · "HRB 123456". The number has 5 to 15 letters and digits.
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.ID,
            [
                Pattern(
                    "Registration number after its label",
                    _REGISTRATION_LABEL + _REGISTRATION_VALUE,
                    0.7,
                ),
                Pattern("KvK or HRB number", _REGISTER_LABEL + _REGISTRATION_VALUE, 0.7),
            ],
        )

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        characters = re.sub(r"[^0-9A-Za-z]", "", match["value"])
        return pattern.score if 5 <= len(characters) <= 15 else 0.0


# A BIC: bank (4 letters), country (2 letters), location (2 letters or digits), maybe a branch (3).
_BIC = r"(?<![A-Za-z0-9])[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?(?![A-Za-z0-9])"
# Its label, on the same line and directly before it: "BIC:", "SWIFT code", "BIC/SWIFT (code):".
_BIC_NAME = _any_case("bic", "swift", "bank" + _SPACE + "+identifier")
_BIC_WORDS = r"\b" + _BIC_NAME + r"(?:[ /()]*" + _any_case("bic", "swift", "code") + r"\)?)*"
_BIC_LABEL = re.compile(_BIC_WORDS + _LABEL_TO_VALUE + r"\Z")


class BicRecognizer(CheckedPatternRecognizer):
    """BIC (SWIFT) codes, validated with schwifty.

    In form, many upper-case contract words are BICs: SUPPLIER is bank SUPP in Liechtenstein, and
    TERMINATION a branch in India. So a valid code also needs one of these: schwifty's bank
    registry knows it, it has a digit (no word has one), or its label ("BIC:", "SWIFT") comes
    directly before it on the same line.
    """

    def __init__(self) -> None:
        super().__init__(PlaceholderType.ID, [Pattern("BIC", _BIC, 0.9)])

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        code = match.group()
        try:
            bic = BIC(code)
        except SchwiftyException:
            return 0.0
        labelled = _BIC_LABEL.search(text, max(0, match.start() - 40), match.start())
        if bic.exists or any(character.isdigit() for character in code) or labelled:
            return pattern.score
        return 0.0


# Account numbers and sort codes come directly after their label, on the same line, maybe after
# "is" ("the account number is 12345678").
_ACCOUNT_SEP = "[" + _SPACE_CHARS + r"\-]?"
_ACCOUNT_NUMBER_WORD = "(?:" + _SPACE + r"+(?i:number|no|nr)\b\.?)?"
_IS = "(?:" + _SPACE + r"+(?i:is)\b)?"
_ACCOUNT_LABEL = r"(?i:\b(?:account|acct|a/c)\b)" + _ACCOUNT_NUMBER_WORD + _IS + _LABEL_TO_VALUE
_ACCOUNT_DIGITS = r"(?P<value>\d(?:" + _ACCOUNT_SEP + r"\d){5,17})(?!\d)"
_SORT_CODE_LABEL = r"(?i:\bsort[ \-]?code\b)" + _IS + _LABEL_TO_VALUE
_SORT_CODE_DIGITS = r"(?P<value>\d{2}" + _ACCOUNT_SEP + r"\d{2}" + _ACCOUNT_SEP + r"\d{2})(?!\d)"
# A date written with hyphens (01-03-2026, 03-31-2026, 2026-03-01) is not an account number; one
# whose day or month cannot be (1234-56-78) may be.
_HYPHENATED = re.compile(
    r"(?P<a>\d{1,2})-(?P<b>\d{1,2})-\d{4}|\d{4}-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
)
# An IBAN after its label, its check digits right or wrong: a country, two digits, then up to 30
# letters and digits, in groups of four or in one piece.
_IBAN_LABEL = r"(?i:\biban\b)" + _ACCOUNT_NUMBER_WORD + _LABEL_TO_VALUE
_IBAN_GROUP = "(?:" + _SPACE + r"?[A-Z0-9]{4})"
_IBAN_REST = "(?:" + _SPACE + r"?[A-Z0-9]{1,3})"
_IBAN_SHAPE = r"(?P<value>[A-Z]{2}\d{2}" + _IBAN_GROUP + "{2,7}" + _IBAN_REST + r"?)(?![A-Za-z0-9])"
_IBAN = "IBAN after its label"


def _is_a_hyphenated_date(value: str) -> bool:
    """Whether ``value`` is a date written with hyphens: day and month first in either order, or
    the year first, each of them a day and a month that can be.
    """
    parts = _HYPHENATED.fullmatch(value)
    if parts is None:
        return False
    if parts["a"] is not None:
        a, b = int(parts["a"]), int(parts["b"])
        return (1 <= a <= 31 and 1 <= b <= 12) or (1 <= a <= 12 and 1 <= b <= 31)
    return 1 <= int(parts["month"]) <= 12 and 1 <= int(parts["day"]) <= 31


def _iban_is_valid(value: str) -> bool:
    """Whether the check digits of the IBAN ``value`` are right (ISO 7064, mod 97)."""
    compact = "".join(value.split())
    moved = compact[4:] + compact[:4]
    return int("".join(str(int(character, 36)) for character in moved)) % 97 == 1


class AccountNumberRecognizer(CheckedPatternRecognizer):
    """Bank account numbers and sort codes, found by the label directly before them.

    "Account number: 12345678" · "A/C 87654321" · "Sort code: 12-34-56". An IBAN on an account
    line is left to Presidio's IBAN recognizer, which checks it. After its own label, an IBAN
    whose check digits are wrong is still the party's number, with a typing error in it: it is
    found at 0.6, for the owner to check, as a VAT number with wrong check digits is.
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.ID,
            [
                Pattern("Account number", _ACCOUNT_LABEL + _ACCOUNT_DIGITS, 0.7),
                Pattern("Sort code", _SORT_CODE_LABEL + _SORT_CODE_DIGITS, 0.7),
                Pattern(_IBAN, _IBAN_LABEL + _IBAN_SHAPE, 0.6),
            ],
        )

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        if pattern.name == _IBAN:
            return 0.0 if _iban_is_valid(match["value"]) else pattern.score
        return 0.0 if _is_a_hyphenated_date(match["value"]) else pattern.score


_BSN = "Dutch BSN"
_TCKN = "Turkish TCKN"
_BSN_DIGITS = r"\d{4}\.\d{2}\.\d{3}|\d{3}" + _SPACE + r"\d{3}" + _SPACE + r"\d{3}|\d{9}"
_PASSPORT_LABEL = r"(?i:\bpassport" + _SPACE + r"+(?:number|no|nr)\b\.?)" + _LABEL_TO_VALUE
_PASSPORT_NUMBER = r"(?P<value>(?=[A-Z0-9]*\d)[A-Z0-9]{6,12})(?![A-Za-z0-9])"


class NationalIdRecognizer(CheckedPatternRecognizer):
    """Personal identity numbers.

    The Dutch BSN and the Turkish TCKN are found by their check digits, passport numbers by the
    words "passport number" (or "no", "nr") before them.
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.ID,
            [
                Pattern(
                    _BSN, _ALONE_BEFORE + "(?P<value>" + _BSN_DIGITS + ")" + _ALONE_AFTER, 0.85
                ),
                Pattern(_TCKN, _ALONE_BEFORE + r"(?P<value>[1-9]\d{10})" + _ALONE_AFTER, 0.85),
                Pattern("Passport number", _PASSPORT_LABEL + _PASSPORT_NUMBER, 0.85),
            ],
        )

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        if pattern.name == _BSN:
            valid = bool(bsn.is_valid(match["value"]))
        elif pattern.name == _TCKN:
            valid = bool(tckimlik.is_valid(match["value"]))
        else:
            valid = True
        return pattern.score if valid else 0.0


# --- Bare numbers ---------------------------------------------------------------------------------

# Groups of three digits after the first, all split by the same separator: 48,000 · 1.250.000 ·
# 1 250 000 · 1'250'000. Or four digits and more in one piece: 48000.
_GROUPED_INTEGER = (
    r"\d{1,3}(?P<sep>[,." + _SPACE_CHARS + _APOSTROPHES + r"])\d{3}(?:(?P=sep)\d{3})*"
)
_BARE_INTEGER = "(?P<integer>" + _GROUPED_INTEGER + r"|\d{4,})"
# Not part of a longer number or word, nor of a reference such as Regulation (EU) 2016/679.
_BARE_BEFORE = r"(?<![\w.,/" + _APOSTROPHES + "])"
_BARE_AFTER = r"(?![\w%]|[.," + _APOSTROPHES + r"]\d)"
_BARE_FIGURE = _BARE_BEFORE + _BARE_INTEGER + r"(?P<decimals>[.,]\d+)?" + _BARE_AFTER

_THOUSANDS_WORD = re.compile(r"(?i:thousand|million|billion)")
# A standard a number is the reference of: "ISO 9001", "EN 1090", "ISO/IEC 27001", "BS EN 1176".
_STANDARD_BEFORE = re.compile(
    r"\b(?:ISO|EN|IEC|DIN|BS|NEN|ASTM|ANSI|IEEE)(?:[/ ](?:IEC|EN|ISO|TS|TR|PAS))*" + _SPACE + r"*\Z"
)
# A number with a slash and a number after it is the reference of a law or a case: "Regulation
# (EU) No 1169/2011".
_SLASH_AND_NUMBER = re.compile(r"/\d")
# The month before a year makes the year a date's: "21 July 2026", "July 21, 2026"; a PDF's text
# may glue a footnote mark to it ("21 July 2026.3").
_MONTH_NAMES = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    "|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DAY_AND_COMMA = r"\d{1,2}(?i:st|nd|rd|th)?,"
_MONTH_BEFORE = re.compile(
    r"\b(?i:" + _MONTH_NAMES + r")\.?" + _SPACE + "+(?:" + _DAY_AND_COMMA + _SPACE + r"*)?\Z"
)
# A time of day in four figures, before its time zone: "by 1700 CET".
_TIME_ZONE_AFTER = re.compile(_SPACE + r"*(?:CET|CEST|GMT|BST|UTC|EET|EEST|WET|WEST)\b")
# A clause number with three digits after its point starts its line, and its heading or its first
# sentence follows it: "1.100 The Supplier shall ...". Only that shape: an amount at the start of a
# line, before the words that say what it pays for, stays one ("48,000<tab>Annual licence fee",
# "1.250.000 Gesamtpreis", ruling R95).
_CLAUSE_SHAPE = re.compile(r"\d{1,3}\.\d{3}")
_LINE_START_BEFORE = re.compile(r"(?:\A|\n)[ \t]*\Z")
_HEADING_AFTER = re.compile(r"[ \t]+[A-Z]")
# Words that make a bare number a likely amount when they come shortly before it.
# Presidio matches them as whole words, so "subtotal" is one of its own.
_PRICE_WORDS = (
    "price",
    "fee",
    "amount",
    "total",
    "subtotal",
    "value",
    "charge",
    "consideration",
    "sum",
)


class BareNumberRecognizer(CheckedPatternRecognizer):
    """Numbers of 1,000 and more without a currency or unit: a price in a table, a sum in prose.

    48,000 · 1.250.000,00 · 1 250 000 · 48000 · "ten thousand (10,000)". They are amounts for the
    owner to check: 0.4, which Presidio raises to 0.75 when a word such as "price" or "fee" comes
    shortly before. Years (1900 to 2099, and the year of a date with something glued to it,
    "21 July 2026.3"), durations ("1,000 days"), times of day ("1700 CET") and references
    ("section 1159", "ISO 9001", "Regulation (EU) No 1169/2011") stay visible. A clause number such
    as 10.2, at the start of a line or after "clause", is never one of these numbers: it is below
    1,000, and its digits are not in groups of three; one with three digits after its point ("1.100
    The Supplier shall") starts its line before a capital.
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.AMOUNT,
            [
                Pattern("Number in figures", _BARE_FIGURE, 0.4),
                Pattern("Number in words", _SPELLED, 0.4),
            ],
            context=list(_PRICE_WORDS),
        )

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        start, end = match.span()
        if _DURATION_AFTER.match(text, end):
            return 0.0
        words = match.groupdict().get("words")
        if words is not None:
            return pattern.score if _THOUSANDS_WORD.search(words) else 0.0
        integer = match["integer"]
        digits = re.sub(r"\D", "", integer).lstrip("0")
        # Only four digits or fewer can be below 1,000 or a year. A longer run is never turned into
        # a number: Python refuses to for more than 4,300 digits.
        value = int(digits or "0") if len(digits) <= 4 else 10_000
        if value < 1000:
            return 0.0
        before = max(0, start - 24)
        is_a_year = integer.isdigit() and 1900 <= value <= 2099
        if is_a_year and (match["decimals"] is None or _MONTH_BEFORE.search(text, before, start)):
            return 0.0  # a year
        if integer.isdigit() and _is_a_time_of_day(value) and _TIME_ZONE_AFTER.match(text, end):
            return 0.0
        if _SLASH_AND_NUMBER.match(text, end):
            return 0.0
        if _REFERENCE_BEFORE.search(text, before, start):
            return 0.0
        if _STANDARD_BEFORE.search(text, before, start):
            return 0.0
        if _is_a_clause_number(text, match):
            return 0.0
        return pattern.score


def _is_a_clause_number(text: str, match: re.Match[str]) -> bool:
    """Whether the bare figure ``match`` is a clause number: in its shape (``_CLAUSE_SHAPE``, no
    decimals), at the start of its line and before a capital.
    """
    start, end = match.span()
    return (
        match["decimals"] is None
        and _CLAUSE_SHAPE.fullmatch(match["integer"]) is not None
        and _LINE_START_BEFORE.search(text, max(0, start - 24), start) is not None
        and _HEADING_AFTER.match(text, end) is not None
    )


def _is_a_time_of_day(value: int) -> bool:
    """Whether four figures ``value`` read as hours and minutes: 1700 is five in the afternoon."""
    return value // 100 < 24 and value % 100 < 60


# --- E-mail and web addresses ---------------------------------------------------------------------


class EmailAddressRecognizer(EmailRecognizer):
    """Presidio's e-mail recognizer without its look-up of the domain in the public-suffix list.

    That look-up needs the list tldextract downloads, and it turns down every address whose
    top-level domain the list does not know, such as j.smith@northwind.example. Here an address
    counts when its top-level domain has a letter in it, which rules out a version number like 1.2.
    """

    def validate_result(self, pattern_text: str) -> bool:
        top_level_domain = pattern_text.rsplit(".", 1)[-1]
        return any(character.isalpha() for character in top_level_domain)


# Top-level domains for a domain name written without "https://" or "www.". Only known ones count,
# in lower case, so that a full stop with no space after it ("the warehouse.of the Buyer", "the
# Goods.It shall") is not read as a web address: generic domains, and those of the countries a
# party is likely to be in.
_TOP_LEVEL_DOMAINS = (
    "com|net|org|info|biz|eu|int|edu|gov|io|co|ai|example"
    "|uk|de|nl|fr|ch|ie|tr|es|dk|se|pl|fi|pt|gr|cz|sk|hu|ro|bg|hr|si|lt|lv|ee|lu|mt|cy|li|rs|ru|ua"
    "|ca|au|nz|jp|cn|hk|sg|kr|tw|br|mx|za|ae|il"
)
# Top-level domains that are also English words count only in a name written all in lower case:
# "acme.it" is a web address, but "the Supplier.it shall" is a sentence with a space missing.
_WORD_TOP_LEVEL_DOMAINS = (
    "at|be|it|no|us|in|app|dev|tech|online|site|shop|store|cloud|digital|email|legal|law|company"
    "|group|global|world|services|solutions|consulting|partners|finance|bank|insurance|capital"
)
_DOMAIN_LABEL = r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?"
_DOMAIN_LABELS = _DOMAIN_LABEL + r"(?:\." + _DOMAIN_LABEL + r")*\."
_HOST = (
    _any_of(
        "(?i:" + _DOMAIN_LABELS + ")(?-i:" + _TOP_LEVEL_DOMAINS + ")",
        "(?-i:" + _DOMAIN_LABELS + "(?:" + _WORD_TOP_LEVEL_DOMAINS + "))",
    )
    + r"(?![\w\-])"
)
# Not part of a longer name, an e-mail address or a path.
_DOMAIN_START = r"(?<![\w.@/\-])"
_ADDRESS_REST = r"(?:[/?#][^\s<>\"'`]*)?"
_SCHEME_ADDRESS = r"(?i:\b(?:https?|ftp)://[^\s<>\"'`]+)"
_WWW_ADDRESS = (
    "(?i:" + _DOMAIN_START + r"www\d{0,3}\.[a-z0-9\-]+(?:\.[a-z0-9\-]+)+" + _ADDRESS_REST + ")"
)
_DOMAIN_NAME = "(?i:" + _DOMAIN_START + _HOST + _ADDRESS_REST + ")"


class WebAddressRecognizer(UrlRecognizer):
    """Presidio's URL recognizer with whole domain names.

    Presidio's own patterns end a domain wherever a top-level domain from its list ends, so that
    "https://www.northwind.example/legal" comes out as "https://www.no" and "j.smith@..." as "j.sm".
    Here, after "https://" or "www." anything up to the next space counts; without them, the domain
    must end in a known top-level domain followed by the end of the name.
    """

    def __init__(self) -> None:
        super().__init__(
            patterns=[
                Pattern("Address with scheme", _SCHEME_ADDRESS, 0.6),
                Pattern("Address starting with www", _WWW_ADDRESS, 0.5),
                Pattern("Domain name", _DOMAIN_NAME, 0.5),
            ]
        )


# A web address after its label ("Website:", "Web:", "URL:"), with any top-level domain of two
# letters or more: the label says what it is ("Website: acme.me"). The label ends in a colon or a
# tab, so that "on the web e.g. on its portal" and "a web site.Customers" stay prose (ruling R95).
_WEB_LABEL = (
    r"(?i:\b(?:website|web|url|internet|homepage)\b)" + _LABEL_GAP + r"*[:\t]" + _LABEL_GAP + "*"
)
_TOP_LEVEL_DOMAIN_LETTERS = re.compile(r"[^\W\d_]{2,}")
_LABELLED_DOMAIN = (
    r"(?P<value>(?i:" + _DOMAIN_LABEL + r"(?:\." + _DOMAIN_LABEL + r")+)" + _ADDRESS_REST + r")"
    r"(?<![.,;:!?)])"
)


class LabelledWebAddressRecognizer(CheckedPatternRecognizer):
    """A web address written after its label, whatever its top-level domain: "Website: acme.me".

    Without a label, a domain needs a known top-level domain (``WebAddressRecognizer``), so that a
    full stop with no space after it ("the Supplier.to") is no web address.
    """

    def __init__(self) -> None:
        super().__init__(
            PlaceholderType.URL,
            [Pattern("Web address after its label", _WEB_LABEL + _LABELLED_DOMAIN, 0.85)],
        )

    def score_match(self, text: str, match: re.Match[str], pattern: Pattern) -> float:
        top_level_domain = match["value"].split("/")[0].rsplit(".", 1)[-1]
        letters = _TOP_LEVEL_DOMAIN_LETTERS.fullmatch(top_level_domain) is not None
        return pattern.score if letters else 0.0


def contract_recognizers() -> list[EntityRecognizer]:
    """One of each of the recognizers above, to add to a Presidio registry."""
    return [
        AmountRecognizer(),
        PercentRecognizer(),
        QuantityRecognizer(),
        VatRecognizer(),
        RegistrationNumberRecognizer(),
        BicRecognizer(),
        AccountNumberRecognizer(),
        NationalIdRecognizer(),
        BareNumberRecognizer(),
        EmailAddressRecognizer(),
        WebAddressRecognizer(),
        LabelledWebAddressRecognizer(),
    ]
