"""Owner-chosen names for placeholders (ruling R127): ``[Provider]`` in place of ``[COMPANY_1]``.

A group may carry a label, free text the owner types. The masked file writes it in square
brackets; the canonical ``[TYPE_N]`` stays the group's identity in the key, and the label is an
alias stored beside it. Restore finds a label only as a *bracketed* token: the word "Provider"
on its own, as in "the Provider shall pay", is ordinary text and is never replaced. Changed forms
of the token (spaces inside the brackets, another case, escaped or full-width brackets, markdown
bold) are found as changed, and the restore asks the owner before it puts a value back for one.

``clean_label`` and ``label_key`` define what a valid label is and when two labels are the same.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from themask.placeholders import find_placeholders

MAX_LABEL_LENGTH = 32


class LabelError(ValueError):
    """A label that cannot be used; the message says why, in plain words."""


# A space, or one of the spaces a Word file or an AI tool may put in its place.
_SPACES = " \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}\N{THIN SPACE}"
_RUNS = re.compile(rf"[{_SPACES}\-_]+")
_BRACKETS = "[]\N{FULLWIDTH LEFT SQUARE BRACKET}\N{FULLWIDTH RIGHT SQUARE BRACKET}"


def _is_letter_or_digit(char: str) -> bool:
    return unicodedata.category(char)[0] in "LM" or unicodedata.category(char) == "Nd"


def label_key(label: str) -> str:
    """What two labels are compared by: case folded, full-width forms folded, and a run of
    spaces, hyphens and underscores one space, so "Data-Provider" and "data provider" are one.
    """
    folded = unicodedata.normalize("NFKC", label).casefold()
    return _RUNS.sub(" ", folded).strip()


def clean_label(label: str) -> str:
    """``label`` trimmed, with a run of spaces made one; raises LabelError if it is not valid.

    Valid is 1 to 32 characters of Unicode letters, digits, spaces, hyphens and underscores, with
    at least one letter; no brackets, no line break or other control character.
    """
    if any(unicodedata.category(c).startswith("C") for c in label):
        raise LabelError("A name cannot contain a line break or other control characters.")
    if any(c in _BRACKETS for c in label):
        raise LabelError("A name cannot contain square brackets; they are added for you.")
    text = re.sub(r" +", " ", unicodedata.normalize("NFC", label).strip(" "))
    if not text:
        raise LabelError("Type a name, or leave it empty to keep the default.")
    if len(text) > MAX_LABEL_LENGTH:
        raise LabelError(f"A name can have at most {MAX_LABEL_LENGTH} characters.")
    for char in text:
        if not (_is_letter_or_digit(char) or char in " -_"):
            raise LabelError("A name can have letters, digits, spaces, hyphens and underscores.")
    if not any(unicodedata.category(c)[0] == "L" for c in text):
        raise LabelError("A name needs at least one letter; digits alone are not allowed.")
    return text


def canonical_form(label: str) -> str | None:
    """The canonical placeholder (``[COMPANY_1]``) that ``label`` spells, in any case and with
    spaces, hyphens or underscores, or None if it spells none.
    """
    found = find_placeholders(f"[{label}]")
    return found[0].placeholder if found else None


def check_label(
    label: str,
    *,
    own: str,
    other_placeholders: Iterable[str],
    other_labels: Mapping[str, str],
) -> str | None:
    """The cleaned label for the group whose canonical placeholder is ``own``; raises LabelError.

    Returns None when the label spells ``own`` itself: typing COMPANY_1 for the group that is
    COMPANY_1 means no label. ``other_placeholders`` are the other groups' canonical
    placeholders (refused: restore could not tell them apart) and ``other_labels`` maps the
    ``label_key`` of every other group's label to that group's placeholder.
    """
    text = clean_label(label)
    spelt = canonical_form(text)
    if spelt == own:
        return None
    if spelt is not None:
        if spelt in set(other_placeholders):
            raise LabelError(
                f"{text} looks like the placeholder {spelt} of another value, so a restore "
                "could not tell them apart. Choose another name."
            )
        raise LabelError(
            f"{text} looks like a placeholder such as [COMPANY_1]. Choose a different name."
        )
    if label_key(text) in other_labels:
        raise LabelError(f"The name {text} is already used for another value. Choose another.")
    return text


def validate_key_labels(labels: Iterable[str | None]) -> None:
    """Raises LabelError unless the labels (None for an entry without one) are valid and distinct."""
    seen: set[str] = set()
    for label in labels:
        if label is None:
            continue
        text = clean_label(label)
        if text != label or canonical_form(text) is not None:
            raise LabelError("A stored name is not valid.")
        key = label_key(text)
        if key in seen:
            raise LabelError("Two values have the same name.")
        seen.add(key)


# --- Finding labels in a text -------------------------------------------------------------------

_OPEN = r"(?:\\?\[|\N{FULLWIDTH LEFT SQUARE BRACKET})"
_CLOSE = r"(?:\\?\]|\N{FULLWIDTH RIGHT SQUARE BRACKET})"
_INNER = r"(?:\\_|[^\[\]\\\r\n\N{FULLWIDTH LEFT SQUARE BRACKET}\N{FULLWIDTH RIGHT SQUARE BRACKET}]){1,%d}"

# Both brackets are required: a bare word is never a label. Markdown round it is tolerated.
_LABEL_TOKEN_RE = re.compile(
    rf"(?P<mark>\*\*|__|`)?{_OPEN}(?P<inner>{_INNER % (MAX_LABEL_LENGTH * 2 + 8)}){_CLOSE}"
    r"(?(mark)(?P=mark))"
)


@dataclass(frozen=True)
class LabelMatch:
    """A bracketed token whose inner text is one of the given labels."""

    start: int
    end: int
    raw: str
    key: str
    exact: bool


def find_labels(text: str, labels: Mapping[str, str]) -> list[LabelMatch]:
    """Every bracketed token of ``text`` that spells one of ``labels``, in text order.

    ``labels`` maps a label's ``label_key`` to the label as stored. ``exact`` is set when the
    token is written ``[Label]`` exactly as stored; any other form is a changed one.
    """
    found = []
    for match in _LABEL_TOKEN_RE.finditer(text):
        inner = match["inner"].replace("\\_", "_").strip(_SPACES)
        key = label_key(inner)
        stored = labels.get(key)
        if stored is None:
            continue
        raw = match.group()
        found.append(LabelMatch(match.start(), match.end(), raw, key, raw == f"[{stored}]"))
    return found
