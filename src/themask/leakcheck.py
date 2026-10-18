"""The leak check: proof that nothing marked is left anywhere in a masked Word file (spec 8.5).

``scan_package`` opens the finished file and searches all of it for every value of the case's
key and every variant of it, however the file cases, spaces and punctuates it. How a value is
compared depends on its type (ruling R63); a variant is compared as its entry's type:

* a name (PERSON, COMPANY, ADDRESS, CUSTOM, EMAIL, URL) by its words: case folded, punctuation
  and spacing folded to single spaces, and found only where it starts and ends on the edge of a
  word. "S. Hall" is found as "S Hall" but not in "shall", "Page" is not found in PAGEREF nor
  "B. Lee" in "reasonable endeavours";
* a number (AMOUNT, PERCENT, QUANTITY, IBAN, ID, PHONE) by its letters and digits alone
  (``textnorm.normalize``), so "1.250.000" is found for "1,250,000" and "NL91ABNA0417164300" for
  "NL91 ABNA 0417 1643 00". One of digits only counts only where no other digit touches it (ruling
  R14): "1250" is not found in "11250".

It searches:

* every part that is XML, whatever it is: a paragraph's text as Word shows it, read as one, so a
  value Word split across runs is found whole and a tab or a line break parts two words; every
  other text of its elements, its XML comments and processing instructions; and every attribute
  value on its own (ruling R19). Relationship targets and field instructions are searched
  %-decoded as well (ruling R26). A word of a field instruction that is exactly a field's name or
  the format keyword after a format switch (PAGE, \\* MERGEFORMAT) is no hit for a value spelt
  like it; anything else in an instruction is, a value of several words or a path led by a
  backslash too (ruling R31);
* every other part (pictures, embedded files, a part that is not valid XML): its bytes read as
  UTF-8 and as UTF-16, for the values of at least six letters and digits that are not all digits,
  which stray bytes do not spell by chance (ruling R14 b);
* the file's own name and the name of every part.

What is the file format's own vocabulary and never the document's content is not searched (ruling
R64): for a value of digits only, an attribute that is a bare number or hex code (a size, a
colour, an id); the namespace and schema addresses (values starting with "http://schemas.",
"http://www.w3.org" or "urn:schemas-microsoft-com") and the type of every relationship; the fonts
the file declares (``w:rFonts``, the font table's names, the typefaces of DrawingML and themes);
and the Application, AppVersion and Template of the file's extended properties.

A value of fewer than four letters and digits is not searched for: it would be found everywhere.
``unverifiable`` names the placeholders whose value and variants are all that short, which the
export reports as not checkable (ruling R14 c). A person's bare surname is never in the key
(ruling R52); it is searched for in the document's text and counts where it stands as a person's
name, the way the sweep took it: "Smith shall attend" is a hit, "the Price" is not.

A hit says where it is and shows about forty characters round it, with the hit, every other value
and variant of the key and every person's surname in them replaced by placeholders, so that no hit
ever shows what it found; a part whose name holds a value is shown with the value hidden too.
``rescan_detection`` runs the detection again on the masked file and lists what it finds that the
owner never marked. Nothing here writes to the log.
"""

from __future__ import annotations

import re
import sys
import unicodedata
import zipfile
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import accumulate
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from lxml import etree

from themask.detect.grouping import PersonName
from themask.detect.pipeline import CombinedText, analyze
from themask.detect.sweep import crosses_a_line, is_searchable, stands_as_a_name
from themask.docx.masker import FIELD_NAMES, FORMAT_SWITCHES, INSTRUCTION_WORD
from themask.docx.package import NS, RELS_NS, DocxPackage
from themask.docx.reader import extract_text
from themask.model import Group, KeyEntry, PlaceholderType
from themask.placeholders import find_placeholders
from themask.textnorm import flexible_pattern, normalize

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists

# A value is searched for when it keeps at least this many letters and digits once normalised.
MIN_LENGTH = 4
# In the bytes of a part that is not XML, a value is searched for only when it keeps at least this
# many letters and digits and is not all digits.
MIN_RAW_LENGTH = 6

# Where a hit is that is in no part: the file's own name, the name of a part.
FILE_NAME = "<file name>"
PART_NAME = "<part name>"
# What a hit in the bytes of a part shows when the bytes round it are not plain text.
BINARY_PART = "<binary part>"

# The types whose values are names, compared by their words (ruling R63); the others are numbers
# and codes, compared by their letters and digits alone.
NAME_TYPES = frozenset(
    {
        PlaceholderType.PERSON,
        PlaceholderType.COMPANY,
        PlaceholderType.ADDRESS,
        PlaceholderType.CUSTOM,
        PlaceholderType.EMAIL,
        PlaceholderType.URL,
    }
)
_PEOPLE_AND_COMPANIES = frozenset({PlaceholderType.PERSON, PlaceholderType.COMPANY})

# How much of the text a hit shows on either side of it, and how much further it reaches to
# show a word it cuts whole.
_SIDE = 20
_WORD_REACH = 10
# The ellipsis that shows where a hit's text was cut.
_CUT = "\N{HORIZONTAL ELLIPSIS}"


@dataclass(frozen=True)
class LeakHit:
    """A value of the key found in a masked file.

    ``part`` is where: the name of a part of the package, ``FILE_NAME`` for the file's own name
    or ``PART_NAME`` for the name of a part. ``placeholder`` is the value's placeholder.
    ``context`` is about forty characters round the hit as the file writes them, on one line,
    with the hit and every other value, variant and surname of the key in them replaced by
    placeholders, and an ellipsis where the text was cut; it never shows a value. A hit in an
    attribute shows the attribute's name (``descr="Logo of [COMPANY_1]"``), a hit in a name shows
    the name, and a hit in the bytes of a part that are not plain text shows ``BINARY_PART``.
    """

    part: str
    placeholder: str
    context: str


def scan_package(path: Path, entries: list[KeyEntry]) -> list[LeakHit]:
    """Every place in the Word file at ``path`` that still holds a value of ``entries``.

    The hits come in the order of the zip, after any in the file's name: for each part, one for
    its name, then those in it in the order they stand. An empty list means the file is clean of
    every value that can be checked (see ``unverifiable``). Raises what ``DocxPackage.open``
    raises for a file that is not a Word file, and lets every other error through.
    """
    pkg = DocxPackage.open(path)
    needles = _Needles.of(entries)
    people = _surnames(entries)
    if not needles and not people:
        return []
    hider = _Hider(needles, people)
    in_bytes = needles.for_bytes()
    by_surname = _surname_hits(pkg, entries, people, hider)
    hits = [
        LeakHit(FILE_NAME, match.placeholder, hider.name(path.name))
        for match in needles.matches(path.stem)
    ]
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            shown = hider.name(info.filename)
            hits += [
                LeakHit(PART_NAME, match.placeholder, shown)
                for match in needles.matches(info.filename)
            ]
            hits += _part_hits(shown, archive.read(info), needles, in_bytes, hider)
            hits += by_surname.pop(info.filename, [])
    for rest in by_surname.values():
        hits += rest
    return list(dict.fromkeys(hits))


def unverifiable(entries: list[KeyEntry]) -> list[str]:
    """The placeholders of ``entries`` that ``scan_package`` cannot check, in their order: those
    whose value and every variant keep fewer than ``MIN_LENGTH`` letters and digits once
    normalised ("5%", "AB1"). The masker replaces them all the same.
    """
    return [
        entry.placeholder
        for entry in entries
        if all(len(normalize(form)) < MIN_LENGTH for form in (entry.value, *entry.variants))
    ]


def rescan_detection(
    path: Path, engine: Engine, user_lists: UserLists, entries: list[KeyEntry]
) -> list[Group]:
    """What the detection finds in the masked Word file at ``path`` that the owner never marked.

    The file's text goes through the whole analysis (``analyze``), and the groups come back
    except those that are a placeholder and those of which any form, normalised, is a value or
    a variant of ``entries``: those are marked, and ``scan_package`` reports any of them still
    there. The banner's example placeholder is no value either.
    """
    text = extract_text(DocxPackage.open(path)).text
    groups = analyze(CombinedText.join([(path.name, text)]), engine, user_lists).groups
    marked = {normalize(form) for entry in entries for form in (entry.value, *entry.variants)}
    return [
        group
        for group in groups
        if not _is_placeholder(group.canonical)
        and not {normalize(group.canonical), *map(normalize, group.variants)} & marked
    ]


# ---- folding ------------------------------------------------------------------------------------


def _marks_and_format_characters() -> str:
    """Every mark (accents and the like) and invisible format character of Unicode, as the inside
    of a character class. A mark belongs to the letter before it and a format character (a soft
    hyphen, a zero-width space) shows nothing, so neither parts two words."""
    ranges: list[list[int]] = []
    for code in range(sys.maxunicode + 1):
        if unicodedata.category(chr(code)) in ("Mn", "Mc", "Me", "Cf"):
            if ranges and ranges[-1][1] == code - 1:
                ranges[-1][1] = code
            else:
                ranges.append([code, code])
    return "".join(
        re.escape(chr(first)) + ("" if first == last else "-" + re.escape(chr(last)))
        for first, last in ranges
    )


_MARKS = re.compile(f"[{_marks_and_format_characters()}]+")
_NOT_A_LETTER_OR_DIGIT = re.compile(r"[\W_]+")


def _casefolded(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return folded.replace("\N{LATIN SMALL LETTER DOTLESS I}", "i")


def _words_of(text: str) -> str:
    """``text`` folded the way names are compared (ruling R63): put in NFKC form and case folded
    as ``normalize`` does it, marks and format characters dropped, and every run of anything else
    that is not a letter or a digit made one space, with none at either end. Without its spaces
    it is ``normalize(text)``.
    """
    return _NOT_A_LETTER_OR_DIGIT.sub(" ", _MARKS.sub("", _casefolded(text))).strip()


@dataclass(frozen=True)
class _Trace:
    """A text folded both ways, with the start and the end in the text of what each folded
    character comes from: ``words`` is ``_words_of(text)`` and ``compact`` is ``normalize(text)``.
    """

    words: str
    word_starts: list[int]
    word_ends: list[int]
    compact: str
    compact_starts: list[int]
    compact_ends: list[int]

    def source(self, match: _Match) -> tuple[int, int]:
        """Where in the text ``match``, found in one of the folded texts, comes from."""
        starts, ends = (
            (self.word_starts, self.word_ends)
            if match.name
            else (self.compact_starts, self.compact_ends)
        )
        return starts[match.start], ends[match.end - 1]


# Folding a text piece by piece gives what folding it whole gives as long as every piece but the
# first starts with an ASCII character: NFKC leaves such a character as it is and never joins it
# to the character before, and case folding, dropping marks and folding what is not a letter or a
# digit go character by character (the spaces they leave are joined into one afterwards). Each
# folded character is traced back to its piece.
_PIECE = re.compile(r"[\x00-\x7f][^\x00-\x7f]*|[^\x00-\x7f]+")


def _traced(text: str) -> _Trace | None:
    """``text`` folded both ways and traced back; None should tracing it ever fold it otherwise
    than ``_words_of`` and ``normalize`` do."""
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    if text.isascii():
        for at, char in enumerate(text):
            chars.append(char.lower() if char.isalnum() else " ")
            starts.append(at)
            ends.append(at + 1)
    else:
        for piece in _PIECE.finditer(text):
            folded = _NOT_A_LETTER_OR_DIGIT.sub(" ", _MARKS.sub("", _casefolded(piece.group())))
            chars += folded
            starts += [piece.start()] * len(folded)
            ends += [piece.end()] * len(folded)
    words: list[str] = []
    word_starts: list[int] = []
    word_ends: list[int] = []
    for char, start, end in zip(chars, starts, ends, strict=True):
        if char == " " and (not words or words[-1] == " "):
            continue
        words.append(char)
        word_starts.append(start)
        word_ends.append(end)
    if words and words[-1] == " ":
        del words[-1], word_starts[-1], word_ends[-1]
    folded_words = "".join(words)
    letters = [at for at, char in enumerate(words) if char != " "]
    compact = folded_words.replace(" ", "")
    if folded_words != _words_of(text) or compact != normalize(text):
        return None
    return _Trace(
        folded_words,
        word_starts,
        word_ends,
        compact,
        [word_starts[at] for at in letters],
        [word_ends[at] for at in letters],
    )


# A long text is traced only round what was found in it, in chunks of about this many characters
# cut between two ASCII letters or digits: either way of folding cuts there too, so the folded
# chunks laid end to end are the folded text.
_CHUNK = 2048
_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z0-9])(?=[A-Za-z0-9])")


def _source(text: str, match: _Match) -> tuple[int, int] | None:
    """Where in ``text`` the folded characters of ``match`` come from; None should ``text`` not
    trace."""
    fold = _words_of if match.name else normalize
    low = 0
    done = 0  # how long the folded text before ``low`` is
    while low < len(text):
        high = _chunk_end(text, low)
        size = len(fold(text[low:high]))
        if done + size > match.start:
            while done + size < match.end and high < len(text):
                high = _chunk_end(text, high)
                size = len(fold(text[low:high]))
            trace = _traced(text[low:high])
            if trace is None or done + size < match.end:
                return None
            start, end = trace.source(match.shifted(-done))
            return low + start, low + end
        done += size
        low = high
    return None


def _chunk_end(text: str, low: int) -> int:
    cut = _BETWEEN_LETTERS.search(text, low + _CHUNK)
    return cut.start() if cut else len(text)


# ---- what is searched for -----------------------------------------------------------------------


@dataclass(frozen=True)
class _Match:
    """A needle ``key`` found at ``start``-``end`` of a folded text: of its words for a name
    (``name``), of its letters and digits for a number."""

    start: int
    end: int
    key: str
    placeholder: str
    name: bool

    def shifted(self, by: int) -> _Match:
        return _Match(self.start + by, self.end + by, self.key, self.placeholder, self.name)


# What may stand on either side of a name found in a folded text: nothing, a space, or the
# character that parts the texts of two blocks.
_WORD_EDGES = frozenset({"", " ", "\x00"})


@dataclass(frozen=True)
class _Needles:
    """The key as the scan looks for it: each name folded to its words and each number to its
    letters and digits (ruling R63), with its entry's placeholder. A form shorter than
    ``MIN_LENGTH`` is left out; one that two entries share keeps the first entry's placeholder.
    """

    names: dict[str, str]
    numbers: dict[str, str]

    @classmethod
    def of(cls, entries: Iterable[KeyEntry]) -> _Needles:
        names: dict[str, str] = {}
        numbers: dict[str, str] = {}
        for entry in entries:
            for form in (entry.value, *entry.variants):
                if len(normalize(form)) < MIN_LENGTH:
                    continue
                if entry.type in NAME_TYPES:
                    names.setdefault(_words_of(form), entry.placeholder)
                else:
                    numbers.setdefault(normalize(form), entry.placeholder)
        return cls(names, numbers)

    def __bool__(self) -> bool:
        return bool(self.names or self.numbers)

    @property
    def longest(self) -> int:
        return max(map(len, [*self.names, *self.numbers]), default=0)

    def for_bytes(self) -> _Needles:
        """The needles looked for in bytes: at least ``MIN_RAW_LENGTH`` letters and digits long
        and not all digits (ruling R14 b)."""

        def wanted(compact: str) -> bool:
            return len(compact) >= MIN_RAW_LENGTH and not compact.isdigit()

        return _Needles(
            {key: ph for key, ph in self.names.items() if wanted(key.replace(" ", ""))},
            {key: ph for key, ph in self.numbers.items() if wanted(key)},
        )

    def find(self, words: str, compact: str) -> Iterator[_Match]:
        """Every place where a needle stands: a name in ``words`` (text folded by
        ``_words_of``) on the edges of words, a number in ``compact`` (text folded by
        ``normalize``), one of digits only where no other digit touches it."""
        for key, placeholder in self.names.items():
            at = words.find(key)
            while at >= 0:
                end = at + len(key)
                if words[at - 1 : at] in _WORD_EDGES and words[end : end + 1] in _WORD_EDGES:
                    yield _Match(at, end, key, placeholder, True)
                at = words.find(key, at + 1)
        for key, placeholder in self.numbers.items():
            digits = key.isdigit()
            at = compact.find(key)
            while at >= 0:
                end = at + len(key)
                touched = compact[at - 1 : at].isdigit() or compact[end : end + 1].isdigit()
                if not (digits and touched):
                    yield _Match(at, end, key, placeholder, False)
                at = compact.find(key, at + 1)

    def matches(self, text: str) -> list[_Match]:
        """The places in ``text`` where a needle stands."""
        words = _words_of(text) if self.names else ""
        compact = normalize(text) if self.numbers else ""
        return list(self.find(words, compact))


def _outermost(located: Iterable[tuple[tuple[int, int], _Match]]) -> list[tuple[int, int, _Match]]:
    """The matches at their places in the text, in order; of two one of which holds the other,
    only the outer one: "Northwind Trading B.V." left in a file is one hit, not one for each of
    its variants."""
    kept: list[tuple[int, int, _Match]] = []
    reach = -1
    for (start, end), match in sorted(located, key=lambda m: (m[0][0], -m[0][1], m[1].key)):
        if end > reach:
            kept.append((start, end, match))
            reach = end
    return kept


def _surnames(entries: Iterable[KeyEntry]) -> list[tuple[KeyEntry, list[str]]]:
    """Each person of ``entries`` with the forms of their bare surname, longest first (ruling
    R52): "Price" for Tom Price, "van der Berg" and "Berg" for Jan van der Berg."""
    people = []
    for entry in entries:
        if entry.type is PlaceholderType.PERSON:
            forms = [form for form in PersonName.of(entry.value).surnames() if is_searchable(form)]
            if forms:
                people.append((entry, sorted(forms, key=lambda form: (-len(form), form))))
    return people


def _is_placeholder(text: str) -> bool:
    """Whether ``text`` is nothing but a placeholder, exact or changed ("[COMPANY_1]")."""
    stripped = text.strip()
    found = find_placeholders(stripped)
    return bool(found) and found[0].start == 0 and found[0].end == len(stripped)


# ---- what a hit shows ---------------------------------------------------------------------------


class _Hider:
    """Hides the key's values in what a hit shows (see ``LeakHit``): every value and variant,
    found as the scan finds it, and every person's bare surname as a word."""

    def __init__(self, needles: _Needles, people: list[tuple[KeyEntry, list[str]]]) -> None:
        self._needles = needles
        self._surnames = [
            (flexible_pattern(form), entry.placeholder) for entry, forms in people for form in forms
        ]
        # A value spaced or punctuated out is longer in the text than folded; the stretch
        # searched round a hit is wide enough for the longest one to be seen whole.
        self._margin = _SIDE + 40 + 4 * needles.longest

    def context(self, text: str, start: int, end: int, placeholder: str) -> str:
        """About forty characters of ``text`` round ``text[start:end]``, hidden, on one line."""
        low, high = max(0, start - self._margin), min(len(text), end + self._margin)
        region = text[low:high]
        spans = self._spans(region)
        if spans is None:
            return placeholder
        spans = _merged([(start - low, end - low, placeholder), *spans])
        first, last = _window(spans, start - low - _SIDE, end - low + _SIDE, len(region))
        first, last = _window(spans, *_whole_words(region, first, last), len(region))
        shown = " ".join(_replaced(region, spans, first, last).split())
        before = _CUT if text[: low + first].strip() else ""
        after = _CUT if text[low + last :].strip() else ""
        context = f"{before}{shown}{after}"
        return placeholder if self._shows(context) else context

    def name(self, name: str) -> str:
        """``name`` with every value in it hidden."""
        spans = self._spans(name)
        shown = name if spans is None else _replaced(name, _merged(spans), 0, len(name))
        return _CUT if self._shows(shown) else shown

    def covers(self, text: str, start: int, end: int) -> bool:
        """Whether a value or a variant of the key stands in ``text`` round ``start``-``end``."""
        trace = _traced(text)
        if trace is None:
            return False
        return any(
            source[0] <= start and end <= source[1]
            for source in map(trace.source, self._needles.find(trace.words, trace.compact))
        )

    def _spans(self, text: str) -> list[tuple[int, int, str]] | None:
        """Every stretch of ``text`` to hide, with its placeholder; None when ``text`` cannot be
        traced."""
        trace = _traced(text)
        if trace is None:
            return None
        spans = [
            (*trace.source(match), match.placeholder)
            for match in self._needles.find(trace.words, trace.compact)
        ]
        spans += [
            (m.start(), m.end(), placeholder)
            for pattern, placeholder in self._surnames
            for m in pattern.finditer(text)
        ]
        return spans

    def _shows(self, text: str) -> bool:
        """Whether ``text`` still shows a value, a variant or a surname of the key."""
        return bool(self._needles.matches(text)) or any(
            pattern.search(text) for pattern, _ in self._surnames
        )


def _merged(spans: Iterable[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """``spans`` in order, overlapping ones joined; a joined one keeps its first one's
    placeholder (the longest of those that start first)."""
    merged: list[tuple[int, int, str]] = []
    for start, end, placeholder in sorted(spans, key=lambda s: (s[0], s[0] - s[1])):
        if merged and start < merged[-1][1]:
            last_start, last_end, last_placeholder = merged[-1]
            merged[-1] = (last_start, max(last_end, end), last_placeholder)
        else:
            merged.append((start, end, placeholder))
    return merged


def _window(spans: list[tuple[int, int, str]], first: int, last: int, size: int) -> tuple[int, int]:
    """``first``-``last`` within ``0``-``size``, widened until no span sticks out of it."""
    first, last = max(0, first), min(size, last)
    while True:
        touching = [(start, end) for start, end, _ in spans if start < last and end > first]
        wider = (
            min([first, *(start for start, _ in touching)]),
            max([last, *(end for _, end in touching)]),
        )
        if wider == (first, last):
            return first, last
        first, last = wider


def _whole_words(text: str, first: int, last: int) -> tuple[int, int]:
    """``first``-``last`` widened to the edges of the words it cuts, where an edge is near."""
    back = first
    while back > 0 and not text[back - 1].isspace() and first - back < _WORD_REACH:
        back -= 1
    if back == 0 or text[back - 1].isspace():
        first = back
    ahead = last
    while ahead < len(text) and not text[ahead].isspace() and ahead - last < _WORD_REACH:
        ahead += 1
    if ahead == len(text) or text[ahead].isspace():
        last = ahead
    return first, last


def _replaced(text: str, spans: list[tuple[int, int, str]], first: int, last: int) -> str:
    """``text[first:last]`` with each of ``spans`` in it replaced by its placeholder."""
    pieces = []
    at = first
    for start, end, placeholder in spans:
        if start >= last or end <= first:
            continue
        pieces += [text[at:start], placeholder]
        at = end
    pieces.append(text[at:last])
    return "".join(pieces)


# ---- the parts ----------------------------------------------------------------------------------

_W = NS["w"]
_A = NS["a"]
_MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"
# The elements whose text is read as one: a paragraph of WordprocessingML or of DrawingML.
_PARAGRAPHS = frozenset({f"{{{_W}}}p", f"{{{_A}}}p"})
# What a paragraph shows: its texts, field instructions, and these characters for the elements
# that stand for them. Any other text in a paragraph (a drawing's position) is a text of its own.
_SHOWN_TEXTS = frozenset({f"{{{_W}}}t", f"{{{_W}}}delText", f"{{{_A}}}t", f"{{{_MATH}}}t"})
_INSTRUCTION_TEXTS = frozenset({f"{{{_W}}}instrText", f"{{{_W}}}delInstrText"})
_SHOWN_CHARACTERS = {
    f"{{{_W}}}tab": "\t",
    f"{{{_W}}}ptab": "\t",
    f"{{{_W}}}br": "\n",
    f"{{{_W}}}cr": "\n",
    f"{{{_W}}}noBreakHyphen": "\N{NON-BREAKING HYPHEN}",
    f"{{{_A}}}br": "\n",
}
_INSTRUCTION = f"{{{_W}}}instr"
_RELATIONSHIP = f"{{{RELS_NS}}}Relationship"

# The file format's own vocabulary (ruling R64). Addresses of namespaces and schemas:
_FORMAT_ADDRESSES = ("http://schemas.", "http://www.w3.org", "urn:schemas-microsoft-com")
# The fonts a file declares: every attribute of w:rFonts, and these attributes of these elements.
_RUN_FONTS = f"{{{_W}}}rFonts"
_FONT_NAMES = {
    f"{{{_W}}}font": f"{{{_W}}}name",  # the font table
    f"{{{_A}}}latin": "typeface",
    f"{{{_A}}}ea": "typeface",
    f"{{{_A}}}cs": "typeface",
    f"{{{_A}}}font": "typeface",
}
# The program and the template the extended properties name.
_PROGRAM = frozenset(f"{{{NS['ep']}}}{name}" for name in ("Application", "AppVersion", "Template"))
# A size, a colour or an id, never searched for a value of digits only.
_BARE_NUMBER = re.compile(
    r"[-+]?(?:[0-9]+(?:\.[0-9]+)?(?:%|pt|pc|pi|in|cm|mm|px|em|ex)?|[0-9a-f]+)", re.IGNORECASE
)


@dataclass
class _Block:
    """A text searched as one: the text a paragraph shows, another text, an XML comment, or an
    attribute's value.

    ``label`` is the name of the attribute that holds it, and ``bare`` says the attribute's value
    is a bare number or hex code. ``instructions`` are where field instructions stand in it, and
    ``decodes`` is the block it is the %-decoded form of.
    """

    text: str
    label: str | None = None
    instructions: list[tuple[int, int]] = field(default_factory=list)
    decodes: int | None = None
    bare: bool = False


class _Paragraph:
    """The text a paragraph shows, read piece by piece, and where its field instructions are."""

    def __init__(self) -> None:
        self.pieces: list[str] = []
        self.length = 0
        self.instructions: list[tuple[int, int]] = []

    def add(self, text: str, instruction: bool) -> None:
        if instruction:
            if self.instructions and self.instructions[-1][1] == self.length:  # it goes on
                self.instructions[-1] = (self.instructions[-1][0], self.length + len(text))
            else:
                self.instructions.append((self.length, self.length + len(text)))
        self.pieces.append(text)
        self.length += len(text)


class _Reader:
    """Reads an XML part into the blocks to search, in document order."""

    def __init__(self) -> None:
        self.blocks: list[_Block] = []
        self._paragraphs: list[tuple[int, _Paragraph]] = []

    def read(self, root: etree._Element) -> list[_Block]:
        for node in reversed(list(root.itersiblings(preceding=True))):
            self._loose(node)
        self._element(root, None)
        for node in root.itersiblings():
            self._loose(node)
        for index, paragraph in self._paragraphs:
            block = self.blocks[index]
            block.text = "".join(paragraph.pieces)
            block.instructions = paragraph.instructions
            for start, end in paragraph.instructions:
                if "%" in block.text[start:end]:
                    self._decoded(block.text[start:end], None, True, index)
        return self.blocks

    def _element(self, element: etree._Element, paragraph: _Paragraph | None) -> None:
        # The depth of the recursion is the depth of the XML, which the parser keeps to 256.
        tag = element.tag
        if tag in _PARAGRAPHS:
            paragraph = _Paragraph()
            self._paragraphs.append((len(self.blocks), paragraph))
            self.blocks.append(_Block(""))
        for name, value in element.attrib.items():
            self._attribute(tag, name, value)
        if paragraph is not None and tag in _SHOWN_CHARACTERS:
            paragraph.add(_SHOWN_CHARACTERS[tag], False)
        instruction = tag in _INSTRUCTION_TEXTS
        shown_in = paragraph if instruction or tag in _SHOWN_TEXTS else None
        if element.text and tag not in _PROGRAM:
            self._text(element.text, shown_in, instruction)
        for child in element:
            if isinstance(child.tag, str):
                self._element(child, paragraph)
            elif child.tag is not etree.Entity:  # a comment or a processing instruction
                self._loose(child)
            if child.tail:
                self._text(child.tail, shown_in, instruction)

    def _attribute(self, tag: str, name: str, value: str) -> None:
        if _is_format_vocabulary(tag, name, value):
            return
        label = name.rpartition("}")[2]
        instruction = name == _INSTRUCTION
        spans = [(0, len(value))] if instruction else []
        bare = _BARE_NUMBER.fullmatch(value) is not None
        self.blocks.append(_Block(value, label, spans, bare=bare))
        decoded = instruction or (tag == _RELATIONSHIP and name == "Target")
        if decoded and "%" in value:
            self._decoded(value, label, instruction, len(self.blocks) - 1)

    def _text(self, text: str, paragraph: _Paragraph | None, instruction: bool) -> None:
        if paragraph is not None:
            paragraph.add(text, instruction)
            return
        if text.isspace():  # the layout of the XML between elements: nothing to find
            return
        self.blocks.append(_Block(text, None, [(0, len(text))] if instruction else []))
        if instruction and "%" in text:
            self._decoded(text, None, True, len(self.blocks) - 1)

    def _decoded(self, text: str, label: str | None, instruction: bool, of: int) -> None:
        decoded = unquote(text)
        spans = [(0, len(decoded))] if instruction else []
        self.blocks.append(_Block(decoded, label, spans, decodes=of))

    def _loose(self, node: etree._Element) -> None:
        """A comment or a processing instruction: a text of its own."""
        if node.tag is etree.ProcessingInstruction:
            text = f"{node.target} {node.text or ''}"
        else:
            text = node.text or ""
        if text.strip():
            self.blocks.append(_Block(text))


def _is_format_vocabulary(tag: str, name: str, value: str) -> bool:
    """Whether an attribute holds the file format's own vocabulary (ruling R64): an address of a
    namespace or schema, the type of a relationship, or a font."""
    return (
        value[:32].casefold().startswith(_FORMAT_ADDRESSES)
        or (tag == _RELATIONSHIP and name == "Type")
        or tag == _RUN_FONTS
        or _FONT_NAMES.get(tag) == name
    )


def _parsed(data: bytes) -> etree._Element | None:
    """The root of ``data`` read as XML, comments and processing instructions kept; None when
    it is not XML. Nothing is fetched and no entity is expanded."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError:
        return None


def _part_hits(
    part: str,
    data: bytes,
    needles: _Needles,
    in_bytes: _Needles,
    hider: _Hider,
) -> list[LeakHit]:
    """The hits in the part ``part`` (its name as a hit shows it) holding ``data``."""
    root = _parsed(data)
    if root is None:
        return _byte_hits(part, data, in_bytes, hider)
    hits = _block_hits(part, _Reader().read(root), needles, hider)
    if root.getroottree().docinfo.doctype:  # what its DTD declares is in no element
        hits += _byte_hits(part, data, in_bytes, hider)
    return hits


def _block_hits(part: str, blocks: list[_Block], needles: _Needles, hider: _Hider) -> list[LeakHit]:
    """The hits in the blocks of a part, searched all at once: each block folded on its own, the
    blocks joined by a character no needle holds."""
    words = [_words_of(block.text) for block in blocks] if needles.names else []
    compact = [normalize(block.text) for block in blocks] if needles.numbers else []
    word_offsets = _offsets(words)
    compact_offsets = _offsets(compact)
    exempt = {
        (index, *fixed) for index, block in enumerate(blocks) for fixed in _fixed_words(block)
    }
    found: dict[int, list[_Match]] = {}
    for match in needles.find("\x00".join(words), "\x00".join(compact)):
        offsets = word_offsets if match.name else compact_offsets
        index = bisect_right(offsets, match.start) - 1
        local = match.shifted(-offsets[index])
        if (index, local.start, local.end, local.key, local.name) in exempt:
            continue
        if blocks[index].bare and local.key.isdigit():  # a size, a colour or an id
            continue
        found.setdefault(index, []).append(local)
    hits = []
    for index in sorted(found):
        block = blocks[index]
        # What a %-decoded form holds that its block shows as it is, is that block's hit.
        shown = {m.key for m in found.get(block.decodes, [])} if block.decodes is not None else ()
        trace = _traced(block.text) if len(block.text) <= 4 * _CHUNK else None
        located = [
            (trace.source(match) if trace else _source(block.text, match), match)
            for match in found[index]
            if match.key not in shown
        ]
        for start, end, match in _outermost(
            (source, match) for source, match in located if source is not None
        ):
            context = hider.context(block.text, start, end, match.placeholder)
            context = context if block.label is None else f'{block.label}="{context}"'
            hits.append(LeakHit(part, match.placeholder, context))
        hits += [
            LeakHit(part, match.placeholder, match.placeholder)
            for source, match in located
            if source is None
        ]
    return hits


def _offsets(folded: list[str]) -> list[int]:
    """Where each of ``folded`` starts in the folded texts joined by one character."""
    return list(accumulate((len(text) + 1 for text in folded[:-1]), initial=0))


def _fixed_words(block: _Block) -> list[tuple[int, int, str, bool]]:
    """Where the field instructions of ``block`` hold a word that is exactly a field's name
    (PAGE) or the format keyword or picture right after a format switch (\\* MERGEFORMAT),
    unquoted, as (start, end, word, in words) in each folded form of the block (ruling R31).
    Such a word is no hit for a value spelt like it. A switch itself (\\h) has fewer letters than
    any value searched for."""
    words = [
        (start + word_start, start + word_end)
        for start, end in block.instructions
        for word_start, word_end in _field_words(block.text[start:end])
    ]
    trace = _traced(block.text) if words else None
    if trace is None:
        return []
    fixed = []
    for word_start, word_end in words:
        for folded, starts, name in (
            (trace.words, trace.word_starts, True),
            (trace.compact, trace.compact_starts, False),
        ):
            low, high = bisect_left(starts, word_start), bisect_left(starts, word_end)
            word = folded[low:high].strip()
            if len(word.replace(" ", "")) >= MIN_LENGTH:
                fixed.append((low, low + len(word), word, name))
    return fixed


def _field_words(instruction: str) -> Iterator[tuple[int, int]]:
    previous = ""
    for match in INSTRUCTION_WORD.finditer(instruction):
        bare = match.group(2)
        if bare is not None and (
            bare.upper() in FIELD_NAMES or previous.upper() in FORMAT_SWITCHES
        ):
            yield match.span(2)
        previous = match.group(1) if bare is None else bare


def _byte_hits(part: str, data: bytes, in_bytes: _Needles, hider: _Hider) -> list[LeakHit]:
    """The hits in the bytes of a part read as UTF-8 and as UTF-16 (from either byte, as the
    text may start at an odd offset)."""
    if not in_bytes:
        return []
    hits = []
    for text in (
        data.decode("utf-8", "ignore"),
        data.decode("utf-16-le", "ignore"),
        data[1:].decode("utf-16-le", "ignore"),
    ):
        located = [(_source(text, match), match) for match in in_bytes.matches(text)]
        for start, end, match in _outermost(
            (source, match) for source, match in located if source is not None
        ):
            context = hider.context(text, start, end, match.placeholder)
            plain = context.replace(_CUT, "")
            shown = context if plain.isascii() and plain.isprintable() else BINARY_PART
            hits.append(LeakHit(part, match.placeholder, shown))
        hits += [
            LeakHit(part, match.placeholder, BINARY_PART)
            for source, match in located
            if source is None
        ]
    return hits


# ---- bare surnames (ruling R52) -----------------------------------------------------------------


def _surname_hits(
    pkg: DocxPackage,
    entries: list[KeyEntry],
    people: list[tuple[KeyEntry, list[str]]],
    hider: _Hider,
) -> dict[str, list[LeakHit]]:
    """The places where a person's bare surname stands as their name in the document's text,
    by part, in the order they stand.

    One that a value or variant of the key holds ("Mr Smith") is left out: the search of the
    parts reports it. Of two forms of one surname at the same place ("van der Berg", "Berg"),
    the longer one counts.
    """
    if not people:
        return {}
    doc = extract_text(pkg)
    text = doc.text
    starts = [segment.start for segment in doc.segments]
    is_name = _name_test(entries, people)
    found = []
    for entry, forms in people:
        taken: list[tuple[int, int]] = []
        for form in forms:
            for match in flexible_pattern(form).finditer(text):
                start, end = match.span()
                if (
                    any(start < e and s < end for s, e in taken)
                    or crosses_a_line(text, start, end)
                    or not stands_as_a_name(text, start, end, is_name=is_name)
                ):
                    continue
                taken.append((start, end))
                segment = doc.segments[bisect_right(starts, start) - 1]
                paragraph = text[segment.start : segment.end]
                local_start, local_end = start - segment.start, end - segment.start
                if hider.covers(paragraph, local_start, local_end):
                    continue
                context = hider.context(paragraph, local_start, local_end, entry.placeholder)
                hit = LeakHit(hider.name(segment.part), entry.placeholder, context)
                found.append((start, segment.part, hit))
    by_part: dict[str, list[LeakHit]] = {}
    for _, part, hit in sorted(found, key=lambda f: f[0]):
        by_part.setdefault(part, []).append(hit)
    return by_part


def _name_test(
    entries: list[KeyEntry], people: list[tuple[KeyEntry, list[str]]]
) -> Callable[[str], bool]:
    """Whether a word is a name of the key's people and companies, their surnames too: the
    names a connective does not make a phrase of ("Price and Smith"), as for the sweep."""
    names = {
        normalize(form)
        for entry in entries
        if entry.type in _PEOPLE_AND_COMPANIES
        for form in (entry.value, *entry.variants)
    }
    names |= {normalize(form) for _, forms in people for form in forms}
    return lambda word: normalize(word) in names
