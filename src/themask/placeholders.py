"""The placeholder grammar: how ``[TYPE_N]`` is written, found again and counted.

An AI tool sometimes changes a placeholder a little: it drops the brackets, adds spaces, writes the
name in lower case, escapes the brackets or wraps the placeholder in bold. ``find_placeholders``
finds those changed forms as well as the exact one, so that a restore can put the real value back
and ask the owner first when the form was changed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from themask.model import PlaceholderType

_TYPE_NAMES = "|".join(t.value for t in PlaceholderType)

# A placeholder number has at most nine digits. A longer run of digits is never one of ours, and
# the limit keeps int() clear of Python's cap on very long digit strings. The exact pattern below
# and the tolerant one further down must agree on this limit.
_NUMBER = "[0-9]{1,9}"

# The exact form only: square brackets, upper-case type, underscore, a number without leading zeros.
PLACEHOLDER_RE = re.compile(rf"\[(?P<type>{_TYPE_NAMES})_(?P<number>0|[1-9][0-9]{{0,8}})\]")

# Besides the plain bracket, an AI tool may write it escaped (\[ or \]) or full-width.
_OPEN = r"\\?\[|\N{FULLWIDTH LEFT SQUARE BRACKET}"
_CLOSE = r"\\?\]|\N{FULLWIDTH RIGHT SQUARE BRACKET}"

# The exact form and every changed form. Letters and digits are ASCII only: with Unicode case
# folding a long s or a dotless i would pass for a letter of a type name.
#
# The brackets delimit a token. Where one is there, the token needs no word check on that side, so
# "[PERSON_1]s" still holds "[PERSON_1]". Where one is missing, the bare name or number must not be
# part of a longer word, so "PERSONAL_1" and "PERSON_1x" hold nothing.
_TOKEN_RE = re.compile(
    rf"""
    (?P<mark>\*\*|__|`)?          # markdown round the token: **bold**, __bold__ or `code`
    (?:
        (?P<open>{_OPEN})[ ]*     # an opening bracket, then any spaces
        |(?<![A-Za-z0-9])         # no bracket: the name must start a word
    )
    (?P<type>{_TYPE_NAMES})
    [_ -]
    (?P<number>{_NUMBER})
    (?:
        [ ]*(?P<close>{_CLOSE})   # any spaces, then a closing bracket
        |(?![A-Za-z0-9])          # no bracket: the number must end a word
    )
    (?(mark)(?P=mark))            # a marker that opened the token must close it
    """,
    re.VERBOSE | re.IGNORECASE | re.ASCII,
)


@dataclass(frozen=True)
class PlaceholderMatch:
    """A placeholder, exact or changed, found in a text.

    ``raw`` is ``text[start:end]``: the whole token as written, with any brackets, spaces and
    markdown markers, so that a restore can replace all of it. ``placeholder`` is the canonical
    ``[TYPE_N]`` it stands for, and ``exact`` says ``raw`` already is that canonical form.
    """

    start: int
    end: int
    raw: str
    placeholder: str
    exact: bool


def format_placeholder(t: PlaceholderType, n: int) -> str:
    """The placeholder for type ``t`` and number ``n``, for example ``[PERSON_1]``."""
    return f"[{t.value}_{n}]"


def _scan(text: str) -> Iterator[tuple[PlaceholderMatch, PlaceholderType, int]]:
    """Every placeholder in ``text``, in order, with its type and number."""
    for found in _TOKEN_RE.finditer(text):
        placeholder_type = PlaceholderType(found["type"].upper())
        number = int(found["number"])
        placeholder = format_placeholder(placeholder_type, number)
        raw = found.group()
        match = PlaceholderMatch(found.start(), found.end(), raw, placeholder, raw == placeholder)
        yield match, placeholder_type, number


def find_placeholders(text: str) -> list[PlaceholderMatch]:
    """Every placeholder in ``text``, in order: exact ``[TYPE_N]`` and changed forms alike.

    A form is exact only when it is written ``[TYPE_N]`` in upper case, with an underscore, no
    leading zero, plain square brackets and nothing round it. Type names are found in any case.
    """
    return [match for match, _, _ in _scan(text)]


def next_free_number(text: str, t: PlaceholderType) -> int:
    """The number a new placeholder of type ``t`` can take without clashing with ``text``.

    Changed forms count as well: a restore would take any of them for a placeholder of ours.
    """
    return max((n for _, found_type, n in _scan(text) if found_type is t), default=0) + 1
