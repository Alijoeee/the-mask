"""The leak check: proof that nothing marked is left anywhere in a masked Word file (spec 8.5).

``scan_package`` opens the finished file and searches all of it for every value of the case's
key and every variant of it, however the file cases, spaces and punctuates it. How a value is
compared depends on its type; a variant is compared as its entry's type:

* a name (PERSON, COMPANY, ADDRESS, CUSTOM, EMAIL, URL) by its words (ruling R63): case folded,
  punctuation and spacing folded to single spaces, and found only where it starts and ends on the
  edge of a word. "S. Hall" is found as "S Hall" but not in "shall", "Page" is not found in
  PAGEREF nor "B. Lee" in "reasonable endeavours". Names are folded a second way as well, with
  the punctuation that has no space beside it dropped (ruling R68), so "Acme BV" is found for
  "Acme B.V." and "North-wind" for "Northwind"; an initial's full stop before a word still parts
  them ("S.Hall" is no "shall"). A match in either fold is a hit;
* a number (AMOUNT, PERCENT, QUANTITY, IBAN, ID, PHONE) by its letters and digits alone
  (``textnorm.normalize``), so "1.250.000" is found for "1,250,000" and "NL91ABNA0417164300" for
  "NL91 ABNA 0417 1643 00". Where it starts or ends with a digit, it counts only where no other
  digit touches it there in the text itself (ruling R65): right beside it, or beyond a single
  space, full stop, comma or apostrophe ("1250" is not found in "11250", "EUR 1,250" not in
  "EUR 12,500"). A tab, a line break or any other mark parts two numbers ("Instalment 2<tab>
  125,000"), and so does a footnote mark; cents after it ("125,000.00") are no other number.

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

What is the file format's own vocabulary and never the document's content is not searched (rulings
R64, R66, R67): the namespace and schema addresses (values starting with "http://schemas.",
"http://www.w3.org" or "urn:schemas-microsoft-com") and the type of every relationship; the fonts
that ship with Office, Windows and macOS (any other font is a name like any text); Word's own
theme and scheme names; Word's built-in style names, their ids and the references to them; the
Application, AppVersion and Template of the file's extended properties; for a value of digits
only, an attribute that is a bare number or hex code (a size, a colour, an id), the whole text of
an element that bears none of the document's text when it is a bare number (a drawing's position,
the word count of the extended properties), and a drawing's geometry (VML shapes, DrawingML shape
guides); and for a name, the names of the standard parts every Word file has (word/document.xml,
docProps/core.xml ...), with the content types and relationship targets that name them. The
file's own name and the name of any other part are searched.

A value of fewer than four letters and digits is not searched for: it would be found everywhere.
``unverifiable`` names the placeholders whose value and variants are all that short, which the
export reports as not checkable (ruling R14 c). A person's bare surname is never in the key
(ruling R52); it is searched for in the document's text and counts where it stands as a person's
name, the way the sweep took it: "Smith shall attend" is a hit, "the Price" is not.

A hit says where it is and shows about forty characters round it, with every stretch that
normalises to a value, a variant or a surname of the key (wherever it stands, glued to other
letters or not: ruling R69) replaced by its placeholder, so that no hit ever shows what it found;
a part whose name holds a value is shown with the value hidden too. A hit counts the places in its
part that read the same (``LeakHit.count``), and ``hits_by_placeholder`` totals them.
``rescan_detection`` runs the detection again on the masked file and lists what it finds that the
owner never marked. Nothing here writes to the log.
"""

from __future__ import annotations

import posixpath
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

from lxml import etree

from themask.detect.grouping import PersonName
from themask.detect.pipeline import CombinedText, analyze
from themask.detect.sweep import crosses_a_line, is_searchable, stands_as_a_name
from themask.docx.masker import FIELD_NAMES, FORMAT_SWITCHES, INSTRUCTION_WORD, percent_decoded
from themask.docx.package import NS, RELS_NS, TYPES_NS, DocxPackage
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
    with every stretch that normalises to a value, a variant or a surname of the key replaced by
    its placeholder, and an ellipsis where the text was cut; it never shows a value. A hit in an
    attribute shows the attribute's name (``descr="Logo of [COMPANY_1]"``), a hit in a name shows
    the name, and a hit in the bytes of a part that are not plain text shows ``BINARY_PART``.
    ``count`` is how many places in the part hold the value and read the same (ruling R69).
    """

    part: str
    placeholder: str
    context: str
    count: int = 1


def hits_by_placeholder(hits: Iterable[LeakHit]) -> dict[str, int]:
    """How many places the hits find for each placeholder: their counts added up."""
    totals: dict[str, int] = {}
    for hit in hits:
        totals[hit.placeholder] = totals.get(hit.placeholder, 0) + hit.count
    return totals


def scan_package(path: Path, entries: list[KeyEntry]) -> list[LeakHit]:
    """Every place in the Word file at ``path`` that still holds a value of ``entries``.

    The hits come in the order of the zip, after any in the file's name: for each part, one for
    its name, then those in it in the order they stand; hits that read the same are one, with
    their places counted. An empty list means the file is clean of every value that can be
    checked (see ``unverifiable``). Raises what ``DocxPackage.open`` raises for a file that is
    not a Word file, and lets every other error through.
    """
    pkg = DocxPackage.open(path)
    needles = _Needles.of(entries)
    people = _surnames(entries)
    if not needles and not people:
        return []
    hider = _Hider(needles, people)
    in_bytes = needles.for_bytes()
    by_surname = _surname_hits(pkg, entries, people, hider)
    with zipfile.ZipFile(path) as archive:
        parts = [(info.filename, archive.read(info)) for info in archive.infolist()]
    roots = [_parsed(data) for _, data in parts]
    styles = _built_in_style_ids(root for root in roots if root is not None)
    hits = [
        LeakHit(FILE_NAME, match.placeholder, hider.name(path.name))
        for match in _in_a_name(path.stem, needles)
    ]
    for (name, data), root in zip(parts, roots, strict=True):
        standard = _is_standard_part(name)  # its name holds no name of ours (ruling R64 f)
        shown = hider.name(name, names=not standard)
        hits += [
            LeakHit(PART_NAME, match.placeholder, shown)
            for match in _in_a_name(name, needles)
            if not (standard and match.name)
        ]
        if root is None:
            hits += _byte_hits(shown, data, in_bytes, hider)
        else:
            hits += _block_hits(shown, _Reader(name, styles).read(root), needles, hider)
            if root.getroottree().docinfo.doctype:  # what its DTD declares is in no element
                hits += _byte_hits(shown, data, in_bytes, hider)
        hits += by_surname.pop(name, [])
    for rest in by_surname.values():
        hits += rest
    return _counted(hits)


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


def _counted(hits: list[LeakHit]) -> list[LeakHit]:
    """``hits`` with those that read the same taken as one, their places counted, in order."""
    counts: dict[tuple[str, str, str], int] = {}
    for hit in hits:
        key = (hit.part, hit.placeholder, hit.context)
        counts[key] = counts.get(key, 0) + hit.count
    return [LeakHit(*key, count) for key, count in counts.items()]


# ---- folding ------------------------------------------------------------------------------------


def _character_classes() -> tuple[str, str]:
    """The marks (accents and the like) of Unicode, and its invisible format characters (a soft
    hyphen, a zero-width space), each as the inside of a character class."""
    found: dict[bool, list[list[int]]] = {True: [], False: []}
    for code in range(sys.maxunicode + 1):
        category = unicodedata.category(chr(code))
        if category in ("Mn", "Mc", "Me", "Cf"):
            spans = found[category != "Cf"]
            if spans and spans[-1][1] == code - 1:
                spans[-1][1] = code
            else:
                spans.append([code, code])
    return _class_of(found[True]), _class_of(found[False])


def _class_of(spans: Iterable[Iterable[int]]) -> str:
    pieces = []
    for first, last in (tuple(span) for span in spans):
        pieces.append(re.escape(chr(first)) + ("" if first == last else "-" + re.escape(chr(last))))
    return "".join(pieces)


_MARK_CLASS, _FORMAT_CLASS = _character_classes()
# A mark belongs to the letter before it, and a format character shows nothing, so neither parts
# two words: both are dropped.
_MARKS = re.compile(f"[{_MARK_CLASS}{_FORMAT_CLASS}]+")
_NOT_A_LETTER_OR_DIGIT = re.compile(r"[\W_]+")
# The second way of folding a name drops what is neither a letter, a digit nor a space where no
# space stands beside it ("B.V.", "North-wind"), but keeps a word break after an initial's full
# stop before a word ("S.Hall"), where dropping it would make another word.
_GLUED = re.compile(r"(?<!\s)(?:[^\w\s]|_)+(?!\s)")
_INITIAL = re.compile(r"(?<![^\W_])([^\W\d_])\.(?=[^\W\d_]{2})")


def _prefolded(text: str) -> str:
    """``text`` in NFKC form and case folded as ``normalize`` does it, the dotless i as i, its
    marks and format characters dropped: what every way of folding starts from."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _MARKS.sub("", folded.replace("\N{LATIN SMALL LETTER DOTLESS I}", "i"))


def _folds(text: str) -> tuple[str, str, str]:
    """``text`` folded the three ways it is searched: by its words (every run of anything else
    than letters and digits one space, none at either end: ruling R63), by its words with glued
    punctuation dropped (ruling R68), and by its letters and digits alone (``normalize``)."""
    pre = _prefolded(text)
    words = _NOT_A_LETTER_OR_DIGIT.sub(" ", pre).strip()
    tight = _NOT_A_LETTER_OR_DIGIT.sub(" ", _GLUED.sub("", _INITIAL.sub(r"\1 ", pre))).strip()
    return words, tight, _NOT_A_LETTER_OR_DIGIT.sub("", pre)


# The views of a folded text: by words, by words with glued punctuation dropped, by letters and
# digits.
_WORDS, _TIGHT, _COMPACT = 0, 1, 2


@dataclass(frozen=True)
class _Trace:
    """A text folded the three ways, with the start and the end in the text of what each folded
    character comes from."""

    folded: tuple[str, str, str]
    starts: tuple[list[int], list[int], list[int]]
    ends: tuple[list[int], list[int], list[int]]

    def source(self, match: _Match) -> tuple[int, int]:
        """Where in the text ``match``, found in one of the folded texts, comes from."""
        return self.starts[match.view][match.start], self.ends[match.view][match.end - 1]

    def position(self, view: int, at: int) -> int:
        """The first folded character of ``view`` that comes from ``at`` or after in the text."""
        return bisect_left(self.starts[view], at)


# Folding a text piece by piece gives what folding it whole gives as long as each piece is one
# character and the marks (and the Hangul vowels and finals) that join it: NFKC only ever joins a
# character to those. Each folded character is traced back to its piece; the full stops and
# spaces of the second fold are decided on the whole folded text afterwards.
_JOINING = _MARK_CLASS + _class_of([(0x1160, 0x11FF), (0xD7B0, 0xD7FF)])
_PIECE = re.compile(f"[^{_JOINING}][{_JOINING}]*|[{_JOINING}]+")


def _traced(text: str) -> _Trace | None:
    """``text`` folded and traced back; None should tracing it ever fold it otherwise than
    ``_folds`` does."""
    pre: list[str] = []
    pre_starts: list[int] = []
    pre_ends: list[int] = []
    if text.isascii():
        for at, char in enumerate(text):
            pre.append(char.lower())
            pre_starts.append(at)
            pre_ends.append(at + 1)
    else:
        for piece in _PIECE.finditer(text):
            folded = _prefolded(piece.group())
            pre += folded
            pre_starts += [piece.start()] * len(folded)
            pre_ends += [piece.end()] * len(folded)
    prefolded = "".join(pre)
    guarded = _INITIAL.sub(r"\1 ", prefolded)
    glued = [False] * len(guarded)
    for run in _GLUED.finditer(guarded):
        glued[run.start() : run.end()] = [True] * (run.end() - run.start())
    views: list[tuple[str, list[int], list[int]]] = []
    for kind in (_WORDS, _TIGHT, _COMPACT):
        chars: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        for at, char in enumerate(guarded if kind == _TIGHT else prefolded):
            if kind == _TIGHT and glued[at]:
                continue
            if not (char.isalnum() and char != "_"):
                if kind == _COMPACT or not chars or chars[-1] == " ":
                    continue
                char = " "
            chars.append(char)
            starts.append(pre_starts[at])
            ends.append(pre_ends[at])
        if chars and chars[-1] == " ":
            del chars[-1], starts[-1], ends[-1]
        views.append(("".join(chars), starts, ends))
    three = (views[0][0], views[1][0], views[2][0])
    if three != _folds(text):
        return None
    return _Trace(
        three,
        (views[0][1], views[1][1], views[2][1]),
        (views[0][2], views[1][2], views[2][2]),
    )


# A long text is traced only round what was found in it, in chunks of about this many characters
# cut where two ASCII letters or digits stand on either side: every way of folding cuts there too,
# so the folded chunks laid end to end are the folded text.
_CHUNK = 2048
_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z0-9]{2})(?=[A-Za-z0-9]{2})")


def _source(text: str, match: _Match) -> tuple[int, int] | None:
    """Where in ``text`` the folded characters of ``match`` come from; None should ``text`` not
    trace."""
    low = 0
    done = 0  # how long the folded text before ``low`` is
    while low < len(text):
        high = _chunk_end(text, low)
        size = len(_folds(text[low:high])[match.view])
        if done + size > match.start:
            while done + size < match.end and high < len(text):
                high = _chunk_end(text, high)
                size = len(_folds(text[low:high])[match.view])
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
    """A needle ``key`` found at ``start``-``end`` of one ``view`` of a folded text."""

    start: int
    end: int
    key: str
    placeholder: str
    view: int

    @property
    def name(self) -> bool:
        """Whether it is a name's match (by words) rather than a number's."""
        return self.view != _COMPACT

    @property
    def digits(self) -> bool:
        """Whether its needle is digits only."""
        return self.key.replace(" ", "").isdigit()

    def shifted(self, by: int) -> _Match:
        return _Match(self.start + by, self.end + by, self.key, self.placeholder, self.view)


# What may stand on either side of a name found in a folded text: nothing, a space, or the
# character that parts the texts of two blocks.
_WORD_EDGES = frozenset({"", " ", "\x00"})


@dataclass(frozen=True)
class _Needles:
    """The key as the scan looks for it: each name folded both ways by its words (rulings R63,
    R68) and each number by its letters and digits, with its entry's placeholder. A form shorter
    than ``MIN_LENGTH`` is left out; one that two entries share keeps the first one's placeholder.
    """

    names: dict[str, str]
    tight: dict[str, str]
    numbers: dict[str, str]

    @classmethod
    def of(cls, entries: Iterable[KeyEntry]) -> _Needles:
        names: dict[str, str] = {}
        tight: dict[str, str] = {}
        numbers: dict[str, str] = {}
        for entry in entries:
            for form in (entry.value, *entry.variants):
                words, glued, compact = _folds(form)
                if len(compact) < MIN_LENGTH:
                    continue
                if entry.type in NAME_TYPES:
                    names.setdefault(words, entry.placeholder)
                    tight.setdefault(glued, entry.placeholder)
                else:
                    numbers.setdefault(compact, entry.placeholder)
        return cls(names, tight, numbers)

    def __bool__(self) -> bool:
        return bool(self.names or self.numbers)

    @property
    def longest(self) -> int:
        return max(map(len, [*self.names, *self.numbers]), default=0)

    def for_bytes(self) -> _Needles:
        """The needles looked for in bytes: at least ``MIN_RAW_LENGTH`` letters and digits long
        and not all digits (ruling R14 b)."""

        def wanted(key: str) -> bool:
            compact = key.replace(" ", "")
            return len(compact) >= MIN_RAW_LENGTH and not compact.isdigit()

        return _Needles(
            {key: ph for key, ph in self.names.items() if wanted(key)},
            {key: ph for key, ph in self.tight.items() if wanted(key)},
            {key: ph for key, ph in self.numbers.items() if wanted(key)},
        )

    def find(self, folded: tuple[str, str, str]) -> Iterator[_Match]:
        """Every place where a needle stands in a text folded the three ways: a name on the edges
        of words, a number anywhere (``_located`` judges the digits round it)."""
        for view, needles in ((_WORDS, self.names), (_TIGHT, self.tight)):
            text = folded[view]
            for key, placeholder in needles.items():
                at = text.find(key)
                while at >= 0:
                    end = at + len(key)
                    if text[at - 1 : at] in _WORD_EDGES and text[end : end + 1] in _WORD_EDGES:
                        yield _Match(at, end, key, placeholder, view)
                    at = text.find(key, at + 1)
        compact = folded[_COMPACT]
        for key, placeholder in self.numbers.items():
            at = compact.find(key)
            while at >= 0:
                yield _Match(at, at + len(key), key, placeholder, _COMPACT)
                at = compact.find(key, at + 1)


# Ruling R65: what may stand between two digits of one number, and the cents after a number.
_NUMBER_SEPARATORS = frozenset(" .,'\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}")
_CENTS = re.compile(r"[.,][0-9]{2}(?![0-9])")


def _touched(text: str, start: int, end: int, key: str) -> bool:
    """Whether another digit touches the number found at ``text[start:end]`` on a side where its
    needle ``key`` starts or ends with a digit (ruling R65): right beside it, or beyond a single
    space, full stop, comma or apostrophe. A tab, a line break, any other mark or the end of the
    text parts them, and so do cents after it."""
    if key[:1].isdecimal() and _digit_at(text, start - 1, -1):
        return True
    return key[-1:].isdecimal() and not _CENTS.match(text, end) and _digit_at(text, end, 1)


def _digit_at(text: str, at: int, step: int) -> bool:
    """Whether ``text[at]`` is a digit, or a number's separator with a digit beyond it."""
    if not 0 <= at < len(text):
        return False
    if text[at].isdecimal():
        return True
    beyond = at + step
    return text[at] in _NUMBER_SEPARATORS and 0 <= beyond < len(text) and text[beyond].isdecimal()


Located = list[tuple[int, int, _Match]]


def _located(text: str, matches: Iterable[_Match], trace: _Trace | None) -> Located:
    """The matches at their places in ``text``, in order: a number that another digit touches
    left out (ruling R65), and of two matches one of which holds the other only the outer one
    ("Northwind Trading B.V." left in a file is one place, not one for each of its variants). A
    match that cannot be placed stands at -1."""
    placed = []
    for match in matches:
        source = trace.source(match) if trace is not None else _source(text, match)
        if source is None:
            placed.append(((-1, -1), match))
        elif match.name or not _touched(text, *source, match.key):
            placed.append((source, match))
    kept: Located = []
    reach = -2
    for (start, end), match in sorted(placed, key=lambda p: (p[0][0], -p[0][1], p[1].key)):
        if start < 0 or end > reach:
            kept.append((start, end, match))
            reach = max(reach, end)
    return kept


def _in_a_name(name: str, needles: _Needles) -> list[_Match]:
    """The places in a file's or a part's name where a needle stands."""
    return [match for _, _, match in _located(name, needles.find(_folds(name)), _traced(name))]


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
    """Hides the key's values in what a hit shows (see ``LeakHit``): every stretch that normalises
    to a value, a variant or a surname of the key, wherever it stands and whatever stands beside
    it (ruling R69), and every surname as a word."""

    def __init__(self, needles: _Needles, people: list[tuple[KeyEntry, list[str]]]) -> None:
        self._needles = needles
        self._keys: dict[str, str] = {}  # normalised forms, with their placeholders
        for key, placeholder in [*needles.names.items(), *needles.numbers.items()]:
            self._keys.setdefault(key.replace(" ", ""), placeholder)
        self._name_keys = {key.replace(" ", "") for key in needles.names}
        for entry, forms in people:
            for form in forms:
                compact = normalize(form)
                if len(compact) >= MIN_LENGTH:
                    self._keys.setdefault(compact, entry.placeholder)
                    self._name_keys.add(compact)
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

    def name(self, name: str, names: bool = True) -> str:
        """``name`` with every value in it hidden; only the numbers, without ``names`` (the name
        of a standard part)."""
        spans = self._spans(name, names)
        shown = name if spans is None else _replaced(name, _merged(spans), 0, len(name))
        return _CUT if self._shows(shown, names) else shown

    def covers(self, text: str, start: int, end: int) -> bool:
        """Whether a value or a variant of the key, found as the scan finds it, stands in ``text``
        round ``start``-``end``."""
        trace = _traced(text)
        if trace is None:
            return False
        located = _located(text, self._needles.find(trace.folded), trace)
        return any(low <= start and end <= high for low, high, _ in located)

    def _spans(self, text: str, names: bool = True) -> list[tuple[int, int, str]] | None:
        """Every stretch of ``text`` to hide, with its placeholder (only the numbers, without
        ``names``); None when ``text`` cannot be traced."""
        trace = _traced(text)
        if trace is None:
            return None
        compact = trace.folded[_COMPACT]
        starts, ends = trace.starts[_COMPACT], trace.ends[_COMPACT]
        spans = []
        for key, placeholder in self._keys.items():
            if not names and key in self._name_keys:
                continue
            at = compact.find(key)
            while at >= 0:
                spans.append((starts[at], ends[at + len(key) - 1], placeholder))
                at = compact.find(key, at + 1)
        if names:
            spans += [
                (m.start(), m.end(), placeholder)
                for pattern, placeholder in self._surnames
                for m in pattern.finditer(text)
            ]
        return spans

    def _shows(self, text: str, names: bool = True) -> bool:
        """Whether ``text`` still holds what normalises to a value, a variant or a surname of the
        key (only a number, without ``names``)."""
        compact = normalize(text)
        if any(key in compact for key in self._keys if names or key not in self._name_keys):
            return True
        return names and any(pattern.search(text) for pattern, _ in self._surnames)


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


# ---- the file format's own vocabulary (rulings R64, R66, R67) -----------------------------------


def _listed(text: str) -> frozenset[str]:
    """The comma-separated names in ``text``, compared as ``_vocabulary_key`` compares them."""
    return frozenset(_vocabulary_key(name) for name in text.split(",") if name.strip())


def _vocabulary_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


# The fonts that ship with Office, Windows and macOS (ruling R66), in their own names and in the
# names East Asian Word writes for them, and the families whose every member ships so.
_OFFICE_FONTS = _listed(
    """
    Agency FB, Aharoni, Algerian, Andalus, Angsana New, AngsanaUPC, Aparajita, Aptos,
    Aptos Display, Aptos Mono, Aptos Narrow, Aptos Serif, Arabic Typesetting, Arial, Arial Black,
    Arial Narrow, Arial Rounded MT Bold, Arial Unicode MS, Bahnschrift, Baskerville Old Face,
    Batang, BatangChe, Bauhaus 93, Bell MT, Berlin Sans FB, Bernard MT Condensed, Bierstadt,
    Book Antiqua, Bookman Old Style, Bodoni MT, Britannic Bold, Broadway, Browallia New,
    BrowalliaUPC, Brush Script MT, Calibri, Calibri Light, Californian FB, Calisto MT, Cambria,
    Cambria Math, Candara, Candara Light, Castellar, Centaur, Century, Century Gothic,
    Century Schoolbook, Chiller, Colonna MT, Comic Sans MS, Consolas, Constantia, Cooper Black,
    Copperplate Gothic Bold, Copperplate Gothic Light, Corbel, Corbel Light, Cordia New,
    CordiaUPC, Courier, Courier New, Curlz MT, DaunPenh, David, DengXian, DengXian Light,
    DilleniaUPC, DokChampa, Dotum, DotumChe, Ebrima, Edwardian Script ITC, Elephant,
    Engravers MT, Estrangelo Edessa, EucrosiaUPC, Euphemia, FangSong, Felix Titling, Footlight MT
    Light, Forte, Franklin Gothic Book, Franklin Gothic Demi, Franklin Gothic Demi Cond,
    Franklin Gothic Heavy, Franklin Gothic Medium, Franklin Gothic Medium Cond, FrankRuehl,
    FreesiaUPC, Freestyle Script, French Script MT, Gabriola, Gadugi, Garamond, Gautami, Georgia,
    Gigi, Gill Sans MT, Gill Sans MT Condensed, Gisha, Gloucester MT Extra Condensed, Goudy Old
    Style, Goudy Stout, Grandview, Gulim, GulimChe, Gungsuh, GungsuhChe, Haettenschweiler,
    Harlow Solid Italic, Harrington, High Tower Text, Impact, Imprint MT Shadow, Informal Roman,
    IrisUPC, Iskoola Pota, JasmineUPC, Javanese Text, Jokerman, Juice ITC, KaiTi, Kalinga,
    Kartika, Khmer UI, KodchiangUPC, Kokila, Kristen ITC, Kunstler Script, Lao UI, Latha,
    Leelawadee, Leelawadee UI, Levenim MT, LilyUPC, Lucida Bright, Lucida Calligraphy,
    Lucida Console, Lucida Fax, Lucida Handwriting, Lucida Sans, Lucida Sans Typewriter,
    Lucida Sans Unicode, Magneto, Maiandra GD, Malgun Gothic, Mangal, Marlett, Matura MT Script
    Capitals, Meiryo, Meiryo UI, Microsoft Himalaya, Microsoft JhengHei, Microsoft JhengHei UI,
    Microsoft New Tai Lue, Microsoft PhagsPa, Microsoft Sans Serif, Microsoft Tai Le,
    Microsoft Uighur, Microsoft YaHei, Microsoft YaHei UI, Microsoft Yi Baiti, MingLiU,
    MingLiU-ExtB, MingLiU_HKSCS, MingLiU_HKSCS-ExtB, Miriam, Miriam Fixed, Mistral, Modern No. 20,
    Mongolian Baiti, Monotype Corsiva, MoolBoran, MS Gothic, MS Mincho, MS PGothic, MS PMincho,
    MS Reference Sans Serif, MS Reference Specialty, MS Sans Serif, MS Serif, MS UI Gothic,
    MT Extra, MV Boli, Myanmar Text, Narkisim, Niagara Engraved, Niagara Solid, Nirmala UI,
    NSimSun, Nyala, OCR A Extended, Old English Text MT, Onyx, Palace Script MT, Palatino Linotype,
    Papyrus, Parchment, Perpetua, Perpetua Titling MT, Plantagenet Cherokee, Playbill, PMingLiU,
    PMingLiU-ExtB, Poor Richard, Pristina, Raavi, Rage Italic, Ravie, Rockwell, Rockwell
    Condensed, Rockwell Extra Bold, Rod, Sakkal Majalla, Script MT Bold, Seaford, Segoe Print,
    Segoe Script, Shonar Bangla, Showcard Gothic, Shruti, SimHei, Simplified Arabic,
    Simplified Arabic Fixed, SimSun, Skeena, Snap ITC, Stencil, Sylfaen, Symbol, Tahoma, Tempus
    Sans ITC, Tenorite, Times New Roman, Traditional Arabic, Trebuchet MS, Tunga, Tw Cen MT,
    Tw Cen MT Condensed, Urdu Typesetting, Utsaah, Vani, Verdana, Vijaya, Viner Hand ITC, Vivaldi,
    Vladimir Script, Vrinda, Webdings, Wide Latin, Wingdings, Wingdings 2, Wingdings 3,
    American Typewriter, Andale Mono, Apple Chancery, Apple Color Emoji, Apple SD Gothic Neo,
    Arial Hebrew, Avenir, Avenir Next, Avenir Next Condensed, Baskerville, Big Caslon, Bodoni 72,
    Bradley Hand, Chalkboard, Chalkboard SE, Chalkduster, Charter, Cochin, Copperplate, Courier,
    Didot, Futura, Geneva, Gill Sans, Helvetica, Helvetica Neue, Herculanum, Hoefler Text,
    Kailasa, Lucida Grande, Marker Felt, Menlo, Monaco, Noteworthy, Optima, Palatino, Phosphate,
    Savoye LET, Skia, Snell Roundhand, STFangsong, STHeiti, STKaiti, STSong, Superclarendon,
    Thonburi, Times, Trattatello, Zapf Dingbats, Zapfino,
    宋体, 新宋体, 黑体, 楷体, 仿宋, 微软雅黑, 等线, 等线 Light, 新細明體, 細明體, 微軟正黑體, 標楷體,
    맑은 고딕, 바탕, 바탕체, 굴림, 굴림체, 돋움, 돋움체, 궁서, 궁서체, ＭＳ ゴシック, ＭＳ 明朝,
    ＭＳ Ｐゴシック, ＭＳ Ｐ明朝, メイリオ, 游ゴシック, 游明朝, 游ゴシック Light
    """
)
_OFFICE_FONT_FAMILIES = (
    "noto ",
    "yu gothic",
    "yu mincho",
    "simsun",
    "segoe ui",
    "sitka ",
    "hiragino ",
    "pingfang ",
    "sf pro",
    "sf mono",
    "heiti ",
    "songti ",
)


def _is_office_font(name: str) -> bool:
    """Whether ``name`` is a font that ships with Office, Windows or macOS, or a reference to a
    theme's fonts ("+mn-lt"), or nothing."""
    key = _vocabulary_key(name)
    return (
        not key
        or key.startswith("+")
        or key in _OFFICE_FONTS
        or key.startswith(_OFFICE_FONT_FAMILIES)
    )


# Word's own names for its themes and their colour, font and format schemes (ruling R66).
_OFFICE_THEMES = _listed(
    """
    Office Theme, Office, Office 2007 - 2010, Office 2013 - 2022, Office Classic, Office Classic 2,
    Adjacency, Angles, Apex, Apothecary, Aspect, Atlas, Austin, Badge, Banded, Basis, Berlin,
    Black Tie, Celestial, Circuit, Civic, Clarity, Composite, Concourse, Couture, Crop, Damask,
    Depth, Dividend, Droplet, Elemental, Equity, Essential, Executive, Facet, Flow, Foundry, Frame,
    Gallery, Grid, Hardcover, Headlines, Horizon, Integral, Ion, Ion Boardroom, Madison,
    Main Event, Median, Mesh, Metro, Metropolitan, Module, Newsprint, Opulent, Organic, Oriel,
    Origin, Paper, Parallax, Perspective, Pushpin, Quotable, Retrospect, Savon, Slice, Slipstream,
    Solstice, Technic, Thatch, Trek, Urban, Vapor Trail, Verve, View, Waveform, Wisp, Wood Type,
    Grayscale, Blue Warm, Blue, Blue II, Blue Green, Green, Green Yellow, Yellow, Yellow Orange,
    Orange, Orange Red, Red Orange, Red, Red Violet, Violet, Violet II, Marquee, Subtle Solids,
    Banded Edge, Smokey Glass, Glow Edge, Grunge Texture, Frosted Glass, Top Shadow, Inset,
    Milk Glass, Riblet, Reflection, Extreme Shadow
    """
)


def _is_office_scheme(name: str) -> bool:
    """Whether ``name`` is one of Word's own theme or scheme names; a font scheme may be named
    after its fonts ("Calibri", "Arial Black-Arial")."""
    return _vocabulary_key(name) in _OFFICE_THEMES or all(
        _is_office_font(font) for font in name.split("-")
    )


def _built_in_style_names() -> frozenset[str]:
    """Word's built-in style names (ruling R67), and the "... Char" styles linked to them."""
    names = set(
        _listed(
            """
            Normal, Normal Indent, Normal (Web), Normal Table, Table Normal, Default Paragraph Font,
            No List, No Spacing, Title, Subtitle, Quote, Intense Quote, Strong, Emphasis,
            Subtle Emphasis, Intense Emphasis, Subtle Reference, Intense Reference, Book Title,
            Bibliography, TOC Heading, List Paragraph, Caption, Header, Footer, Footnote Text,
            Footnote Reference, Endnote Text, Endnote Reference, Annotation Text,
            Annotation Reference, Annotation Subject, Comment Text, Comment Reference,
            Comment Subject, Balloon Text, Index Heading, Table of Figures, Table of Authorities,
            TOA Heading, Envelope Address, Envelope Return, Line Number, Page Number, Macro,
            Macro Text, Closing, Signature, E-mail Signature, Salutation, Date, Message Header,
            Note Heading, Block Text, Plain Text, Document Map, Hyperlink, FollowedHyperlink,
            Placeholder Text, Revision, Mention, Hashtag, Smart Hyperlink, Smart Link,
            Unresolved Mention, Table Grid, Table Grid Light, Grid Table Light, Table Theme,
            Table Contemporary, Table Elegant, Table Professional, HTML Top of Form,
            HTML Bottom of Form, HTML Acronym, HTML Address, HTML Cite, HTML Code,
            HTML Definition, HTML Keyboard, HTML Preformatted, HTML Sample, HTML Typewriter,
            HTML Variable
            """
        )
    )
    numbered = {
        "heading": 9,
        "index": 9,
        "toc": 9,
        "list": 5,
        "list bullet": 5,
        "list number": 5,
        "list continue": 5,
        "body text": 3,
        "body text indent": 3,
        "body text first indent": 2,
        "outline list": 3,
        "plain table": 5,
        "table simple": 3,
        "table classic": 4,
        "table colorful": 3,
        "table columns": 5,
        "table grid": 8,
        "table list": 8,
        "table 3d effects": 3,
        "table subtle": 2,
        "table web": 3,
    }
    for base, last in numbered.items():
        names.add(base)
        names.update(f"{base} {number}" for number in range(1, last + 1))
    accented = [
        "light shading",
        "light list",
        "light grid",
        "medium shading 1",
        "medium shading 2",
        "medium list 1",
        "medium list 2",
        "medium grid 1",
        "medium grid 2",
        "medium grid 3",
        "dark list",
        "colorful shading",
        "colorful list",
        "colorful grid",
    ]
    accented += [
        f"{kind} table {number}{suffix}"
        for kind in ("grid", "list")
        for number, suffix in enumerate(
            (" light", "", "", "", " dark", " colorful", " colorful"), start=1
        )
    ]
    for base in accented:
        names.add(base)
        names.update(f"{base} accent {number}" for number in range(1, 7))
    return frozenset(names | {f"{name} char" for name in names})


_BUILT_IN_STYLES = _built_in_style_names()


def _is_built_in_style(name: str) -> bool:
    return _vocabulary_key(name) in _BUILT_IN_STYLES


_W = NS["w"]
_A = NS["a"]
_MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_VAL = f"{{{_W}}}val"
_STYLES, _STYLE = f"{{{_W}}}styles", f"{{{_W}}}style"
_STYLE_ID, _STYLE_NAME = f"{{{_W}}}styleId", f"{{{_W}}}name"
_LATENT_STYLE = f"{{{_W}}}lsdException"
# What names a style by its id.
_STYLE_REFERENCES = frozenset(
    f"{{{_W}}}{name}" for name in ("pStyle", "rStyle", "tblStyle", "basedOn", "next", "link")
)


def _built_in_style_ids(roots: Iterable[etree._Element]) -> frozenset[str]:
    """The ids, case folded, of the styles in the package's style parts that have built-in names."""
    ids = set()
    for root in roots:
        if root.tag != _STYLES:
            continue
        for style in root.iterchildren(_STYLE):
            name = style.find(_STYLE_NAME)
            style_id = style.get(_STYLE_ID)
            if style_id and name is not None and _is_built_in_style(name.get(_VAL, "")):
                ids.add(style_id.casefold())
    return frozenset(ids)


# ---- the parts ----------------------------------------------------------------------------------

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
# The fonts a file names: every attribute of w:rFonts (the theme's fonts and the hint by keyword,
# the rest by name), and these attributes of these elements.
_RUN_FONTS = f"{{{_W}}}rFonts"
_FONT_KEYWORDS = frozenset(
    f"{{{_W}}}{name}" for name in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme", "hint")
)
_FONT_NAMES = {
    f"{{{_W}}}font": f"{{{_W}}}name",  # the font table
    f"{{{_A}}}latin": "typeface",
    f"{{{_A}}}ea": "typeface",
    f"{{{_A}}}cs": "typeface",
    f"{{{_A}}}font": "typeface",
}
# The names of a theme and of its colour, font and format schemes ("Office").
_SCHEMES = frozenset(
    f"{{{_A}}}{name}" for name in ("theme", "clrScheme", "fontScheme", "fmtScheme")
)
# The program and the template the extended properties name.
_PROGRAM = frozenset(f"{{{NS['ep']}}}{name}" for name in ("Application", "AppVersion", "Template"))

# A size, a colour, an id or a count: never searched for a value of digits only where it is an
# attribute's whole value, or the whole text of an element that bears none of the document's
# text.
_BARE_NUMBER = re.compile(
    r"[-+]?(?:[0-9]+(?:\.[0-9]+)?(?:%|pt|pc|pi|in|cm|mm|px|em|ex)?|[0-9a-f]+)", re.IGNORECASE
)
# The elements that bear the document's text: its texts and instructions, and the core
# properties. Comments and processing instructions bear text as well.
_TEXT_BEARING = _SHOWN_TEXTS | _INSTRUCTION_TEXTS
_TEXT_BEARING_NAMESPACES = (f"{{{NS['dc']}}}", f"{{{NS['cp']}}}")
# A drawing's geometry, never searched for a value of digits only either: every attribute of a
# VML element but those that hold text (a watermark's string, alt text, a title, a link), and the
# formula of a DrawingML shape guide ("val 16667").
_VML = "{urn:schemas-microsoft-com:"
_VML_TEXTS = frozenset({"string", "alt", "title", "href"})
_SHAPE_GUIDE = f"{{{_A}}}gd"

# The parts every Word file names alike, and their relationships parts (ruling R64 f): what they
# are called is no name of the document's, nor are the content types and the relationship targets
# that name them.
_STANDARD_PART = re.compile(
    r"\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:core|app|custom)\.xml"
    r"|word/(?:document|styles|stylesWithEffects|settings|webSettings|fontTable|numbering"
    r"|footnotes|endnotes|comments)\.xml"
    r"|word/theme/theme[0-9]+\.xml|word/(?:header|footer)[0-9]+\.xml|word/glossary/.+",
    re.IGNORECASE,
)
_DEFAULT = f"{{{TYPES_NS}}}Default"
_OVERRIDE = f"{{{TYPES_NS}}}Override"


@dataclass
class _Block:
    """A text searched as one: the text a paragraph shows, another text, an XML comment, or an
    attribute's value.

    ``label`` is the name of the attribute that holds it. ``no_digits`` says that no value of
    digits only is searched for in it (a size, a count, a drawing's geometry: ruling R64), and
    ``no_names`` that no name is (the file format's own words). ``instructions`` are where field
    instructions stand in it. ``decodes`` is the block it is the %-decoded form of, and
    ``origins`` where in that block's text each of its characters begins.
    """

    text: str
    label: str | None = None
    instructions: list[tuple[int, int]] = field(default_factory=list)
    decodes: int | None = None
    origins: list[int] = field(default_factory=list)
    no_digits: bool = False
    no_names: bool = False


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
    """Reads the XML part ``part`` into the blocks to search, in document order; ``styles`` are
    the ids of the package's built-in styles."""

    def __init__(self, part: str, styles: frozenset[str]) -> None:
        self.blocks: list[_Block] = []
        self._paragraphs: list[tuple[int, _Paragraph]] = []
        self._styles = styles
        # Where the targets of a relationships part are read from: the folder of the part it
        # serves (the package's root for _rels/.rels).
        self._folder = posixpath.dirname(posixpath.dirname(part))

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
                    self._decoded(index, start, end, None, True)
        return self.blocks

    def _element(self, element: etree._Element, paragraph: _Paragraph | None) -> None:
        # The depth of the recursion is the depth of the XML, which the parser keeps to 256.
        tag = element.tag
        if tag in _PARAGRAPHS:
            paragraph = _Paragraph()
            self._paragraphs.append((len(self.blocks), paragraph))
            self.blocks.append(_Block(""))
        for name, value in element.attrib.items():
            self._attribute(element, name, value)
        if paragraph is not None and tag in _SHOWN_CHARACTERS:
            paragraph.add(_SHOWN_CHARACTERS[tag], False)
        instruction = tag in _INSTRUCTION_TEXTS
        shown_in = paragraph if instruction or tag in _SHOWN_TEXTS else None
        bearing = tag in _TEXT_BEARING or tag.startswith(_TEXT_BEARING_NAMESPACES)
        if element.text and tag not in _PROGRAM:
            self._text(element.text, shown_in, instruction, bearing)
        for child in element:
            if isinstance(child.tag, str):
                self._element(child, paragraph)
            elif child.tag is not etree.Entity:  # a comment or a processing instruction
                self._loose(child)
            if child.tail:
                self._text(child.tail, shown_in, instruction, bearing)

    def _attribute(self, element: etree._Element, name: str, value: str) -> None:
        tag = element.tag
        if _is_format_vocabulary(tag, name, value):
            return
        label = name.rpartition("}")[2]
        instruction = name == _INSTRUCTION
        block = _Block(
            value,
            label,
            [(0, len(value))] if instruction else [],
            no_digits=_is_geometry(tag, label, value),
            no_names=self._names_the_format(element, name, value),
        )
        self.blocks.append(block)
        decoded = instruction or (tag == _RELATIONSHIP and name == "Target")
        if decoded and "%" in value:
            self._decoded(len(self.blocks) - 1, 0, len(value), label, instruction)

    def _names_the_format(self, element: etree._Element, name: str, value: str) -> bool:
        """Whether an attribute holds a name of the file format's own: one that names a standard
        part (ruling R64 f) or a built-in style (ruling R67)."""
        tag = element.tag
        if tag == _DEFAULT:
            return True
        if tag == _OVERRIDE:
            return _is_standard_part(element.get("PartName", ""))
        if tag == _RELATIONSHIP and name == "Target" and element.get("TargetMode") != "External":
            return _is_standard_part(_target_part(self._folder, value))
        if tag == _LATENT_STYLE:  # latent styles are Word's own
            return name == _STYLE_NAME
        if (tag == _STYLE and name == _STYLE_ID) or (tag in _STYLE_REFERENCES and name == _VAL):
            return value.casefold() in self._styles
        if tag == _STYLE_NAME and name == _VAL:
            parent = element.getparent()
            return parent is not None and parent.tag == _STYLE and _is_built_in_style(value)
        return False

    def _text(
        self, text: str, paragraph: _Paragraph | None, instruction: bool, bearing: bool
    ) -> None:
        if paragraph is not None:
            paragraph.add(text, instruction)
            return
        if text.isspace():  # the layout of the XML between elements: nothing to find
            return
        # A bare number in an element that bears no text is a position or a count (ruling R64).
        no_digits = not bearing and _BARE_NUMBER.fullmatch(text.strip()) is not None
        spans = [(0, len(text))] if instruction else []
        self.blocks.append(_Block(text, None, spans, no_digits=no_digits))
        if instruction and "%" in text:
            self._decoded(len(self.blocks) - 1, 0, len(text), None, True)

    def _decoded(self, of: int, start: int, end: int, label: str | None, instruction: bool) -> None:
        """Adds the %-decoded form of ``self.blocks[of].text[start:end]`` (ruling R26)."""
        source = self.blocks[of]
        decoded, origins = percent_decoded(source.text[start:end])
        block = _Block(
            decoded,
            label,
            [(0, len(decoded))] if instruction else [],
            decodes=of,
            origins=[start + origin for origin in origins],
            no_names=source.no_names,
        )
        self.blocks.append(block)

    def _loose(self, node: etree._Element) -> None:
        """A comment or a processing instruction: a text of its own."""
        if node.tag is etree.ProcessingInstruction:
            text = f"{node.target} {node.text or ''}"
        else:
            text = node.text or ""
        if text.strip():
            self.blocks.append(_Block(text))


def _is_format_vocabulary(tag: str, name: str, value: str) -> bool:
    """Whether an attribute holds the file format's own vocabulary, searched for nothing: an
    address of a namespace or schema, the type of a relationship (ruling R64), a font that ships
    with Office, Windows or macOS, or one of Word's own theme and scheme names (ruling R66)."""
    return (
        value[:32].casefold().startswith(_FORMAT_ADDRESSES)
        or (tag == _RELATIONSHIP and name == "Type")
        or (tag == _RUN_FONTS and (name in _FONT_KEYWORDS or _is_office_font(value)))
        or (_FONT_NAMES.get(tag) == name and _is_office_font(value))
        or (tag in _SCHEMES and name == "name" and _is_office_scheme(value))
    )


def _is_geometry(tag: str, label: str, value: str) -> bool:
    """Whether an attribute is a bare number or hex code, or a drawing's geometry: no value of
    digits only is searched for in it (ruling R64)."""
    return (
        _BARE_NUMBER.fullmatch(value) is not None
        or (tag.startswith(_VML) and label not in _VML_TEXTS)
        or (tag == _SHAPE_GUIDE and label == "fmla")
    )


def _is_standard_part(name: str) -> bool:
    """Whether ``name``, a part's name or a content type's PartName, is one of the parts every
    Word file names alike, or the relationships part of one (ruling R64 f)."""
    name = _unquoted(name).lstrip("/")
    if _STANDARD_PART.fullmatch(name):
        return True
    folder, _, file = name.rpartition("/")
    if posixpath.basename(folder) != "_rels" or not file.endswith(".rels"):
        return False
    served = posixpath.join(posixpath.dirname(folder), file.removesuffix(".rels"))
    return _STANDARD_PART.fullmatch(served) is not None


def _target_part(folder: str, target: str) -> str:
    """The part a relationship's ``target`` names, read from ``folder``."""
    target = _unquoted(target)
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(folder, target))


def _unquoted(text: str) -> str:
    return percent_decoded(text)[0]


def _parsed(data: bytes) -> etree._Element | None:
    """The root of ``data`` read as XML, comments and processing instructions kept; None when
    it is not XML. Nothing is fetched and no entity is expanded."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError:
        return None


def _block_hits(part: str, blocks: list[_Block], needles: _Needles, hider: _Hider) -> list[LeakHit]:
    """The hits in the blocks of a part, one for each place. The blocks are searched all at once,
    each folded on its own and the folded texts joined by a character no needle holds."""
    folds = [_folds(block.text) for block in blocks]
    joined = (
        "\x00".join(f[_WORDS] for f in folds),
        "\x00".join(f[_TIGHT] for f in folds),
        "\x00".join(f[_COMPACT] for f in folds),
    )
    offsets = [_offsets([f[view] for f in folds]) for view in (_WORDS, _TIGHT, _COMPACT)]
    found: dict[int, list[_Match]] = {}
    for match in needles.find(joined):
        index = bisect_right(offsets[match.view], match.start) - 1
        block = blocks[index]
        if (match.name and block.no_names) or (block.no_digits and match.digits):
            continue
        found.setdefault(index, []).append(match.shifted(-offsets[match.view][index]))
    located: dict[int, Located] = {}
    for index in sorted(found):
        block = blocks[index]
        trace = _traced(block.text) if len(block.text) <= 4 * _CHUNK else None
        exempt = _fixed_words(block, trace) if block.instructions else set()
        candidates = [m for m in found[index] if (m.view, m.start, m.end, m.key) not in exempt]
        located[index] = _located(block.text, candidates, trace)
    hits = []
    for index in sorted(located):
        block = blocks[index]
        for start, end, match in located[index]:
            if block.decodes is not None and _shown_undecoded(block, start, end, located):
                continue  # the block it is decoded from holds this place as it is
            if start < 0:
                context = match.placeholder
            else:
                context = hider.context(block.text, start, end, match.placeholder)
            context = context if block.label is None else f'{block.label}="{context}"'
            hits.append(LeakHit(part, match.placeholder, context))
    return hits


def _shown_undecoded(block: _Block, start: int, end: int, located: dict[int, Located]) -> bool:
    """Whether a place found in a %-decoded block is one the block it decodes holds as it is."""
    if start < 0 or block.decodes is None:
        return False
    low, high = block.origins[start], block.origins[end]
    return any(s <= low and high <= e for s, e, _ in located.get(block.decodes, []) if s >= 0)


def _offsets(folded: list[str]) -> list[int]:
    """Where each of ``folded`` starts in the folded texts joined by one character."""
    return list(accumulate((len(text) + 1 for text in folded[:-1]), initial=0))


def _fixed_words(block: _Block, trace: _Trace | None) -> set[tuple[int, int, int, str]]:
    """Where the field instructions of ``block`` hold a word that is exactly a field's name
    (PAGE) or the format keyword or picture right after a format switch (\\* MERGEFORMAT),
    unquoted, as (view, start, end, word) in each folded form of the block (ruling R31). Such a
    word is no hit for a value spelt like it. A switch itself (\\h) has fewer letters than any
    value searched for."""
    words = [
        (start + word_start, start + word_end)
        for start, end in block.instructions
        for word_start, word_end in _field_words(block.text[start:end])
    ]
    if not words or trace is None:
        return set()
    fixed = set()
    for word_start, word_end in words:
        for view in (_WORDS, _TIGHT, _COMPACT):
            low, high = trace.position(view, word_start), trace.position(view, word_end)
            word = trace.folded[view][low:high].strip()
            if len(word.replace(" ", "")) >= MIN_LENGTH:
                fixed.add((view, low, low + len(word), word))
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
    text may start at an odd offset). The same bytes may read as a value more than one way, so
    for each value the reading that finds it most often counts."""
    if not in_bytes:
        return []
    best: dict[str, list[LeakHit]] = {}
    for text in (
        data.decode("utf-8", "ignore"),
        data.decode("utf-16-le", "ignore"),
        data[1:].decode("utf-16-le", "ignore"),
    ):
        found: dict[str, list[LeakHit]] = {}
        for start, end, match in _located(text, in_bytes.find(_folds(text)), None):
            context = BINARY_PART
            if start >= 0:
                shown = hider.context(text, start, end, match.placeholder)
                plain = shown.replace(_CUT, "")
                context = shown if plain.isascii() and plain.isprintable() else BINARY_PART
            found.setdefault(match.placeholder, []).append(
                LeakHit(part, match.placeholder, context)
            )
        for placeholder, hits in found.items():
            if len(hits) > len(best.get(placeholder, [])):
                best[placeholder] = hits
    return [hit for hits in best.values() for hit in hits]


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
                part = hider.name(segment.part, names=not _is_standard_part(segment.part))
                found.append((start, segment.part, LeakHit(part, entry.placeholder, context)))
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
