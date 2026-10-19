"""One identity for each value: what makes two spellings one value, by type (ruling R100).

``value_key`` is the key by which the grouping, the matching of a case's key when a file is added
and the review's "which group has this value" decide that two texts are one value. What is
compared depends on the type:

* AMOUNT, PERCENT, QUANTITY: the number as the leak check folds it (``leakcheck.number_fold``:
  letters and digits only, each decimal point a mark, the zeros that end a decimal part dropped),
  with the words beside it, a currency or a unit, in any order. So "EUR 1,250", "EUR 1.250,00"
  and "1,250.00 EUR" are one value; "EUR 1.25" and "EUR 125" are two, and so are "$100" and
  "€100". A currency sign counts as its code and a currency written as a word too ("€100",
  "EUR 100" and "100 euros" are one value); "per cent", "percent" and "pct" are the "%" sign;
  a range is marked, so that "10-20" is not "1020".
* EMAIL, URL: the text in NFKC form, case folded, with every space removed and its dots and
  punctuation kept: "a.b@example.com" and "ab@example.com" are two addresses.
* PHONE, IBAN, ID: letters and digits only (``normalize``): "NL91 ABNA 0417 1643 00" and
  "NL91ABNA0417164300" are one number. A phone number with and without its country code is
  joined by the grouping on top of this (``grouping._phone_keys``).
* PERSON, COMPANY, ADDRESS, CUSTOM: ``normalize``, as the grouping of names has always done.

The sweep still finds every spelling of a group's variants (``flexible_pattern``); the key only
decides what is ONE value, so that a restore never writes one value in place of another.
"""

from __future__ import annotations

import re
import unicodedata

from themask.model import PlaceholderType
from themask.textnorm import normalize

_NUMBERS = frozenset({PlaceholderType.AMOUNT, PlaceholderType.PERCENT, PlaceholderType.QUANTITY})
_ADDRESSES = frozenset({PlaceholderType.EMAIL, PlaceholderType.URL})

# A currency sign (the dollar sign with the country letters it may carry) and its ISO code; the
# text is case folded by then.
_SIGN = re.compile(
    r"(?<![^\W\d_])(?P<dollar>us|a|c|nz|hk|s)?\$|(?P<sign>[\N{EURO SIGN}\N{POUND SIGN}"
    r"\N{YEN SIGN}\N{TURKISH LIRA SIGN}\N{INDIAN RUPEE SIGN}\N{RUBLE SIGN}])"
)
_DOLLARS = {None: "usd", "us": "usd", "a": "aud", "c": "cad", "nz": "nzd", "hk": "hkd", "s": "sgd"}
_SIGNS = {
    "\N{EURO SIGN}": "eur",
    "\N{POUND SIGN}": "gbp",
    "\N{YEN SIGN}": "jpy",
    "\N{TURKISH LIRA SIGN}": "try",
    "\N{INDIAN RUPEE SIGN}": "inr",
    "\N{RUBLE SIGN}": "rub",
}
_STROKE_L = "\N{LATIN SMALL LETTER L WITH STROKE}"
# A currency written as a word, as the AmountRecognizer knows them, and its code; the longer
# phrases come first, so that "us dollars" is not read as "us" and "dollars".
_WORDS = [
    (re.compile(r"\b(?:us|u\.s\.|american)\s+dollars?\b"), "usd"),
    (re.compile(r"\bcanadian\s+dollars?\b"), "cad"),
    (re.compile(r"\baustralian\s+dollars?\b"), "aud"),
    (re.compile(r"\bsingapore\s+dollars?\b"), "sgd"),
    (re.compile(r"\bhong\s+kong\s+dollars?\b"), "hkd"),
    (re.compile(r"\bnew\s+zealand\s+dollars?\b"), "nzd"),
    (re.compile(r"\bdollars?\b"), "usd"),
    (re.compile(r"\beuros?\b"), "eur"),
    (re.compile(r"\bpounds?(?:\s+sterling)?\b|\bsterling\b"), "gbp"),
    (re.compile(r"\b(?:swiss\s+)?francs?\b"), "chf"),
    (re.compile(r"\b(?:turkish\s+)?liras?\b|\btl\b"), "try"),
    (re.compile(r"\byen\b"), "jpy"),
    (re.compile(r"\byuan\b|\brenminbi\b|\brmb\b"), "cny"),
    (re.compile(r"\brupees?\b"), "inr"),
    (re.compile(r"\broubles?\b|\brubles?\b"), "rub"),
    (re.compile(r"\bkron(?:a|e|er|or|ur)\b"), "kr"),
    (re.compile(r"\bforints?\b"), "huf"),
    (re.compile(rf"\bz[l{_STROKE_L}]otys?\b|\bz{_STROKE_L}\b"), "pln"),
]
# "per cent", "percent" and "pct" are the "%" sign, which adds nothing to the key.
_PERCENT = re.compile(r"\bper\s?-?cent\b|\bpercent\b|\bpct\b")
# A range: "10-20", "10 – 20" and "10 to 20" are one shape, and none is 1020.
_RANGE = re.compile(r"(?<=\d)\s*[\-\N{EN DASH}]\s*(?=\d)")
_LETTERS = re.compile(r"[^\W\d_]+")
_SPACES = re.compile(r"\s+")


def value_key(kind: PlaceholderType, text: str) -> str:
    """The identity of ``text`` as a value of type ``kind`` (see the module): two texts are one
    value when their keys are equal."""
    if kind in _NUMBERS:
        return _number_key(text)
    if kind in _ADDRESSES:
        return _SPACES.sub("", unicodedata.normalize("NFKC", text).casefold())
    return normalize(text)


def _number_key(text: str) -> str:
    """The currency or unit words of ``text``, sorted, then "|", then its number folded."""
    # Imported here: the leak check imports the grouping (for a person's name) and the
    # pipeline (for the rescan), and the grouping imports this module.
    from themask.leakcheck import number_fold

    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _SIGN.sub(_code_of_sign, folded)
    for word, code in _WORDS:
        folded = word.sub(f" {code} ", folded)
    folded = _RANGE.sub(" to ", _PERCENT.sub(" ", folded))
    words = sorted(set(_LETTERS.findall(folded)))
    return " ".join(words) + "|" + number_fold(_LETTERS.sub(" ", folded))


def _code_of_sign(match: re.Match[str]) -> str:
    sign = match.group("sign")
    code = _SIGNS[sign] if sign is not None else _DOLLARS[match.group("dollar")]
    return f" {code} "
