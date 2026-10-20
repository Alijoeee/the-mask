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

from themask.errors import MaskError
from themask.placeholders import find_placeholders

MAX_LABEL_LENGTH = 32


class LabelError(ValueError):
    """A label that cannot be used; the message says why, in plain words."""


class LabelClashError(MaskError, ValueError):
    """An export refused because a name clashes with a value: the message says which and what to
    do. A MaskError, so the interface shows it instead of its "unexpected error" line.
    """


# A space, or one of the spaces a Word file or an AI tool may put in its place.
_SPACES = " \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}\N{THIN SPACE}"
_RUNS = re.compile(rf"[{_SPACES}\-_]+")
_BRACKETS = "[]\N{FULLWIDTH LEFT SQUARE BRACKET}\N{FULLWIDTH RIGHT SQUARE BRACKET}"


def _is_letter_or_digit(char: str) -> bool:
    return unicodedata.category(char)[0] in "LM" or unicodedata.category(char) == "Nd"


# Letters of other scripts that look like a Latin letter; a name is compared by what it looks like.
_LOOKALIKES = str.maketrans(
    {
        **dict(zip("асеіјорхуѕкмнтв", "aceijopxyskmhtb", strict=True)),
        **dict(zip("αβεηικμνορτυχζ", "abenikuvoptuxz", strict=True)),
    }
)


def fold(text: str) -> str:
    """``text`` as it looks, for comparing: compatibility forms (full-width) folded, accents and
    invisible format characters taken out, the dotted and dotless Turkish i one letter, case
    folded, and letters of other scripts that look like Latin ones written as those.
    """
    decomposed = unicodedata.normalize("NFKD", text.replace("\u0131", "i").replace("\u0130", "I"))
    kept = "".join(c for c in decomposed if unicodedata.category(c) not in {"Mn", "Me", "Cf"})
    return kept.casefold().translate(_LOOKALIKES)


_GERMAN = str.maketrans({"\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue", "\u00c4": "Ae",
                         "\u00d6": "Oe", "\u00dc": "Ue"})  # fmt: skip


def _umlautless(folded: str) -> str:
    return folded.replace("ae", "a").replace("oe", "o").replace("ue", "u")


def label_key(label: str) -> str:
    """What two names are compared by, for uniqueness and for finding them in a text: ``fold``
    with the German umlaut spellings one (Müller, Muller and Mueller), and a run of spaces,
    hyphens and underscores one space, so "Data-Provider", "data provider" and "Kiracı" /
    "KIRACI" / "Kiraci" are one name.
    """
    return _RUNS.sub(" ", _umlautless(fold(label.translate(_GERMAN)))).strip()


def words(text: str) -> list[str]:
    """The folded words (runs of letters and digits) of ``text``."""
    return re.findall(r"[^\W_]+", fold(text))


def _spellings(text: str) -> tuple[set[str], str]:
    """The folded words of ``text`` in every spelling it may be written in (Müller is also
    Mueller and Muller), and its folded text joined, in those spellings, for part-of tests.
    """
    plain = words(text)
    translit = words(text.translate(_GERMAN))
    every = set()
    for word in (*plain, *translit):
        every |= {word, word.replace("ae", "a").replace("oe", "o").replace("ue", "u")}
    return every, " | ".join({" ".join(plain), " ".join(translit)})


# Words that carry no identity: articles, joiners and legal forms. They are left out of the
# rules that compare a name with the hidden values, so "The Buyer" is a usable name when a value
# is "The Coca-Cola Company". "Group", "Holdings" and "Company" are NOT in the list: a name that
# is one of them while a value holds it is refused (the strict side; the owner picks another).
_STOP = frozenset(
    [
        "the",
        "and",
        "of",
        "for",
        "de",
        "la",
        "le",
        "van",
        "von",
        "ve",
        "ltd",
        "limited",
        "plc",
        "co",
        "inc",
        "corp",
        "corporation",
        "gmbh",
        "bv",
        "nv",
        "ag",
        "sa",
        "llc",
        "llp",
        "kg",
        "ab",
        "oy",
        "srl",
        "spa",
        "sti",
        "as",
    ]
)


def _identifying(word: str) -> bool:
    """Whether a folded word tells one value from another: not one character, not a stop word,
    not a number of fewer than three digits.
    """
    if len(word) < 2 or word in _STOP:
        return False
    return not (word.isdigit() and len(word) < 3)


def clashes_with_values(label: str, forms: Iterable[str]) -> bool:
    """Whether ``label`` could carry a hidden value, or part of one, into a masked file.

    A name is known text, so the test is strict, in three ways. A word of the name that tells
    values apart (``_identifying``) may not be a word of any of the ``forms``. Any word of a
    form with at least three letters that is not a stop word may not stand *inside* the name
    written without separators ("IBMSide", "AhmetTaraf", "Northwinds"). And the whole name,
    folded, may not be part of a form when it is three or more characters long. Case, accents
    and the German umlaut spellings are ignored throughout.
    """
    name_words, _ = _spellings(label)
    identifying = {w for w in name_words if _identifying(w)}
    plain = "".join(words(label))
    translit = "".join(words(label.translate(_GERMAN)))
    joined = {plain, translit, _umlautless(plain), _umlautless(translit)}
    name_texts = {" ".join(words(label)), " ".join(words(label.translate(_GERMAN)))}
    for form in forms:
        form_words, form_text = _spellings(form)
        if identifying & form_words:
            return True
        if any(
            sum(c.isalpha() for c in w) >= 3 and w not in _STOP and any(w in j for j in joined)
            for w in form_words
        ):
            return True
        if any(len(t.replace(" ", "")) >= 3 and t in form_text for t in name_texts):
            return True
    return False


def clash_message(label: str, placeholder: str, other: str, stored: bool) -> str:
    """Why the name ``label`` of ``placeholder`` cannot stand beside the value of ``other``."""
    if stored:
        return (
            f"The name {label} of {placeholder} is in the case already and cannot change, but it"
            f" contains or is part of a value of {other} in this file. Switch off {other} (or"
            f" leave the words out of it) to continue."
        )
    return (
        f"The name {label} given to {placeholder} contains or is part of a value of {other}, so"
        f" the masked file would still show part of it. Choose another name, or switch off"
        f" {other}."
    )


def mixed_script(label: str) -> bool:
    """Whether the letters of ``label`` come from more than one script (Latin with Cyrillic)."""
    scripts = {
        unicodedata.name(c, "?").split()[0] for c in label if unicodedata.category(c)[0] == "L"
    }
    return len(scripts & {"LATIN", "CYRILLIC", "GREEK"}) > 1


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
    if mixed_script(text):
        raise LabelError(
            "A name cannot mix letters of different alphabets (for example Latin and Cyrillic):"
            " it could not be told from another name."
        )
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
    key = label_key(text)
    if key in other_labels:
        raise LabelError(f"The name {text} is already used for another value. Choose another.")
    for other in other_labels:
        if f" {other} " in f" {key} " or f" {key} " in f" {other} ":
            raise LabelError(
                f"The name {text} contains, or is part of, the name of another value, which a"
                " restore could confuse. Choose a name that does not."
            )
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


# --- Finding names in a text ---------------------------------------------------------------------

# Any bracket an AI tool may put round a name: square, escaped, full-width, lenticular, tortoise.
_OPEN = r"(?:\\?\[|[\N{FULLWIDTH LEFT SQUARE BRACKET}\u3010\u3014])"
_CLOSE = r"(?:\\?\]|[\N{FULLWIDTH RIGHT SQUARE BRACKET}\u3011\u3015])"
_INNER = (
    r"(?:\\_|[^\[\]\\\r\n\N{FULLWIDTH LEFT SQUARE BRACKET}\N{FULLWIDTH RIGHT SQUARE BRACKET}"
    r"\u3010\u3011\u3014\u3015]){1,%d}"
)

# Both brackets are required: a bare word is never a name. Markdown round it is tolerated.
_TOKEN_RE = re.compile(
    rf"(?P<mark>\*\*|__|`)?{_OPEN}(?P<inner>{_INNER % (MAX_LABEL_LENGTH * 2 + 8)}){_CLOSE}"
    r"(?(mark)(?P=mark))"
)


@dataclass(frozen=True)
class LabelMatch:
    """A bracketed token of a text that is, or looks much like, one of the given names.

    ``key`` is the ``label_key`` of the name it spells, None for a *near miss*: a token that
    holds a name with more or less round it ("[Providers]", "[The Provider]"), which a restore
    never replaces but reports. ``exact`` is set only for ``[Name]`` exactly as stored.
    """

    start: int
    end: int
    raw: str
    key: str | None
    exact: bool


def find_brackets(text: str) -> list[tuple[int, int, str]]:
    """Every bracketed token of ``text`` (any of the brackets above), as (start, end, raw)."""
    return [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]


def find_labels(text: str, labels: Mapping[str, str], near: bool = False) -> list[LabelMatch]:
    """Every bracketed token of ``text`` that spells one of ``labels``, in text order.

    ``labels`` maps a label's ``label_key`` to the label as stored. ``exact`` is set when the
    token is written ``[Label]`` exactly as stored, and is not a markdown link's text; any other
    form is a changed one. With ``near`` the tokens that merely hold a name are listed too, with
    no key.
    """
    found = []
    for match in _TOKEN_RE.finditer(text):
        inner = match["inner"].replace("\\_", "_").strip(_SPACES)
        key = label_key(inner)
        raw = match.group()
        stored = labels.get(key)
        if stored is not None:
            link = text[match.end() : match.end() + 1] == "("
            exact = raw == f"[{stored}]" and not link
            found.append(LabelMatch(match.start(), match.end(), raw, key, exact))
        elif near and _holds_a_name(key, labels):
            found.append(LabelMatch(match.start(), match.end(), raw, None, False))
    return found


def _holds_a_name(key: str, labels: Mapping[str, str]) -> bool:
    """Whether the folded token text ``key`` holds one of the names (see ``LabelMatch``)."""
    token_words = key.split()
    squeezed = key.replace(" ", "")
    return any(
        name in key or name.replace(" ", "") in squeezed
        if len(name.replace(" ", "")) >= 4
        else name in token_words
        for name in labels
    )
