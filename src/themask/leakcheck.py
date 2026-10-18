"""The leak check: proof that nothing marked is left anywhere in a masked Word file (spec 8.5).

``scan_package`` opens the finished file and searches all of it for every value of the case's
key and every variant of it. Values are compared normalised (``textnorm.normalize``: case,
spacing and punctuation folded away, digits kept), so "1.250.000" is found for "1,250,000" and
"NL91ABNA0417164300" for "NL91 ABNA 0417 1643 00". It searches:

* every part that is XML, whatever it is (the document, headers, footers, notes, comments,
  properties, settings, numbering, styles, custom XML, [Content_Types].xml, every .rels): the
  text of its elements, a paragraph's text as one, so a value Word split across runs is found
  whole; its XML comments and processing instructions; and every attribute value on its own
  (ruling R19). Relationship targets and field instructions are searched %-decoded as well
  (ruling R26). A word of a field instruction that is exactly a field's name or the format
  keyword after a format switch (PAGE, \\* MERGEFORMAT) is no hit for a value spelt like it;
  anything else in an instruction is, a value of several words or a path led by a backslash
  too (ruling R31);
* every other part (pictures, embedded files, a part that is not valid XML): its bytes read as
  UTF-8 and as UTF-16, for the values of at least six characters that are not all digits, which
  stray bytes do not spell by chance (ruling R14 b);
* the file's own name and the name of every part.

A value of fewer than four characters once normalised is not searched for: it would be found
everywhere. ``unverifiable`` names the placeholders whose value and variants are all that short,
which the export reports as not checkable (ruling R14 c). A value of digits only counts only
where no other digit touches it, so "1250" is not found in "11250" nor "2025" in "120250"
(ruling R14). A person's bare surname is never in the key (ruling R52); it is searched for in
the document's text and counts where it stands as a person's name, the way the sweep took it:
"Smith shall attend" is a hit, "the Price" is not.

A hit says where it is and shows about forty characters round it, with the hit, every other
value and variant of the key and every person's surname in them replaced by placeholders, so
that no hit ever shows what it found; a part whose name holds a value is shown with the value
hidden too. ``rescan_detection`` runs the detection again on the masked file and lists what it
finds that the owner never marked. Nothing here writes to the log.
"""

from __future__ import annotations

import re
import zipfile
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Collection, Iterable, Iterator
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
# In the bytes of a part that is not XML, a value is searched for only when it is at least this
# long and not all digits.
MIN_RAW_LENGTH = 6

# Where a hit is that is in no part: the file's own name, the name of a part.
FILE_NAME = "<file name>"
PART_NAME = "<part name>"
# What a hit in the bytes of a part shows when the bytes round it are not plain text.
BINARY_PART = "<binary part>"

# How much of the text a hit shows on either side of it, and how much further it reaches to
# show a word it cuts whole.
_SIDE = 20
_WORD_REACH = 10
# The ellipsis that shows where a hit's text was cut.
_CUT = "\N{HORIZONTAL ELLIPSIS}"

_W = NS["w"]
# The elements whose text is read as one: a paragraph of WordprocessingML or of DrawingML.
_PARAGRAPHS = frozenset({f"{{{_W}}}p", f"{{{NS['a']}}}p"})
_INSTRUCTION_TEXTS = frozenset({f"{{{_W}}}instrText", f"{{{_W}}}delInstrText"})
_INSTRUCTION = f"{{{_W}}}instr"
_RELATIONSHIP = f"{{{RELS_NS}}}Relationship"
_NAMES = frozenset({PlaceholderType.PERSON, PlaceholderType.COMPANY})


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
    needles = _needles(entries, MIN_LENGTH)
    people = _surnames(entries)
    if not needles and not people:
        return []
    hider = _Hider(needles, people)
    in_bytes = {
        key: placeholder
        for key, placeholder in needles.items()
        if len(key) >= MIN_RAW_LENGTH and not key.isdigit()
    }
    by_surname = _surname_hits(pkg, entries, people, hider)
    hits = [
        LeakHit(FILE_NAME, match.placeholder, hider.name(path.name))
        for match in _matches(normalize(path.stem), needles)
    ]
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            shown = hider.name(info.filename)
            hits += [
                LeakHit(PART_NAME, match.placeholder, shown)
                for match in _matches(normalize(info.filename), needles)
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


# ---- what is searched for -----------------------------------------------------------------------


def _needles(entries: Iterable[KeyEntry], shortest: int) -> dict[str, str]:
    """Each value and variant of ``entries`` normalised, with its entry's placeholder.

    A form shorter than ``shortest`` is left out; one that two entries share keeps the first
    entry's placeholder.
    """
    needles: dict[str, str] = {}
    for entry in entries:
        for form in (entry.value, *entry.variants):
            key = normalize(form)
            if len(key) >= shortest:
                needles.setdefault(key, entry.placeholder)
    return needles


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


@dataclass(frozen=True)
class _Match:
    """Where a needle stands in a normalised text: ``key`` at ``start``-``end``."""

    start: int
    end: int
    key: str
    placeholder: str


def _everywhere(folded: str, needles: dict[str, str]) -> Iterator[_Match]:
    """Every place in ``folded`` where a needle stands, overlapping ones too."""
    for key, placeholder in needles.items():
        at = folded.find(key)
        while at >= 0:
            yield _Match(at, at + len(key), key, placeholder)
            at = folded.find(key, at + 1)


def _matches(
    folded: str, needles: dict[str, str], exempt: Collection[tuple[int, int, str]] = ()
) -> list[_Match]:
    """The hits in ``folded``, a normalised text, in order.

    A needle of digits only counts only where no other digit touches it, and a needle never
    counts at a stretch ``exempt`` gives for it (start, end, needle). Of two hits one of which
    holds the other, only the outer one is kept: "Northwind Trading B.V." left in a file is one
    hit, not one for each variant in it.
    """
    found = []
    for match in _everywhere(folded, needles):
        touched = match.key.isdigit() and (
            folded[match.start - 1 : match.start].isdigit()
            or folded[match.end : match.end + 1].isdigit()
        )
        if not touched and (match.start, match.end, match.key) not in exempt:
            found.append(match)
    kept: list[_Match] = []
    reach = -1
    for match in sorted(found, key=lambda m: (m.start, m.start - m.end, m.key)):
        if match.end > reach:
            kept.append(match)
            reach = match.end
    return kept


# ---- what normalised text comes from ------------------------------------------------------------

# Normalising a text piece by piece gives what normalising it whole gives as long as every piece
# but the first starts with an ASCII character: NFKC leaves such a character as it is and never
# joins it to the character before, and case folding and dropping what is not a letter or digit
# go character by character. Each normalised character is traced back to its piece.
_PIECE = re.compile(r"[\x00-\x7f][^\x00-\x7f]*|[^\x00-\x7f]+")
_ASCII_LETTER_OR_DIGIT = re.compile(r"[A-Za-z0-9]")
_ASCII = re.compile(r"[\x00-\x7f]")
# Long texts are traced in chunks of about this many characters.
_CHUNK = 2048


def _folded(text: str) -> tuple[str, list[int], list[int]] | None:
    """``normalize(text)``, with the start and the end in ``text`` of what each of its
    characters comes from; None should tracing it ever give another text than ``normalize``.
    """
    if text.isascii():
        starts = [m.start() for m in _ASCII_LETTER_OR_DIGIT.finditer(text)]
        return "".join(text[i] for i in starts).lower(), starts, [i + 1 for i in starts]
    pieces: list[str] = []
    starts = []
    ends: list[int] = []
    for piece in _PIECE.finditer(text):
        folded = normalize(piece.group())
        pieces.append(folded)
        starts += [piece.start()] * len(folded)
        ends += [piece.end()] * len(folded)
    whole = "".join(pieces)
    return (whole, starts, ends) if whole == normalize(text) else None


def _source(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Where in ``text`` the characters ``start``-``end`` of ``normalize(text)`` come from.

    A long text is cut into chunks before ASCII characters, and only the chunks that hold the
    stretch are traced.
    """
    low = 0
    done = 0  # how long normalize(text[:low]) is
    while low < len(text):
        high = _chunk_end(text, low)
        size = len(normalize(text[low:high]))
        if done + size > start:
            while done + size < end and high < len(text):
                high = _chunk_end(text, high)
                size = len(normalize(text[low:high]))
            traced = _folded(text[low:high])
            if traced is None or done + size < end:
                return None
            _, starts, ends = traced
            return low + starts[start - done], low + ends[end - 1 - done]
        done += size
        low = high
    return None


def _chunk_end(text: str, low: int) -> int:
    cut = _ASCII.search(text, low + _CHUNK)
    return cut.start() if cut else len(text)


# ---- what a hit shows ---------------------------------------------------------------------------


class _Hider:
    """Hides the key's values in what a hit shows (see ``LeakHit``): every value and variant,
    normalised and wherever it stands, and every person's bare surname as a word."""

    def __init__(self, needles: dict[str, str], people: list[tuple[KeyEntry, list[str]]]) -> None:
        self._needles = needles
        self._surnames = [
            (flexible_pattern(form), entry.placeholder) for entry, forms in people for form in forms
        ]
        # A value spaced or punctuated out is longer in the text than normalised; the stretch
        # searched round a hit is wide enough for the longest one to be seen whole.
        self._margin = _SIDE + 40 + 4 * max(map(len, needles), default=0)

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
        traced = _folded(text)
        if traced is None:
            return False
        folded, starts, ends = traced
        return any(
            starts[m.start] <= start and end <= ends[m.end - 1]
            for m in _everywhere(folded, self._needles)
        )

    def _spans(self, text: str) -> list[tuple[int, int, str]] | None:
        """Every stretch of ``text`` to hide, with its placeholder; None when ``text`` cannot be
        traced."""
        traced = _folded(text)
        if traced is None:
            return None
        folded, starts, ends = traced
        spans = [
            (starts[m.start], ends[m.end - 1], m.placeholder)
            for m in _everywhere(folded, self._needles)
        ]
        spans += [
            (m.start(), m.end(), placeholder)
            for pattern, placeholder in self._surnames
            for m in pattern.finditer(text)
        ]
        return spans

    def _shows(self, text: str) -> bool:
        """Whether ``text`` still shows a value, a variant or a surname of the key."""
        folded = normalize(text)
        return any(key in folded for key in self._needles) or any(
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


@dataclass
class _Block:
    """A text searched as one: the text of a paragraph, a text outside paragraphs, an XML
    comment, or an attribute's value.

    ``label`` is the name of the attribute that holds it; ``instructions`` are where field
    instructions stand in it, and ``decodes`` is the block it is the %-decoded form of.
    """

    text: str
    label: str | None = None
    instructions: list[tuple[int, int]] = field(default_factory=list)
    decodes: int | None = None


class _Paragraph:
    """The text of a paragraph, read piece by piece, and where its field instructions are."""

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
        if element.tag in _PARAGRAPHS:
            paragraph = _Paragraph()
            self._paragraphs.append((len(self.blocks), paragraph))
            self.blocks.append(_Block(""))
        for name, value in element.attrib.items():
            self._attribute(element, name, value)
        instruction = element.tag in _INSTRUCTION_TEXTS
        if element.text:
            self._text(element.text, paragraph, instruction)
        for child in element:
            if isinstance(child.tag, str):
                self._element(child, paragraph)
            elif child.tag is not etree.Entity:  # a comment or a processing instruction
                self._loose(child)
            if child.tail:
                self._text(child.tail, paragraph, instruction)

    def _attribute(self, element: etree._Element, name: str, value: str) -> None:
        label = name.rpartition("}")[2]
        instruction = name == _INSTRUCTION
        self.blocks.append(_Block(value, label, [(0, len(value))] if instruction else []))
        decoded = instruction or (element.tag == _RELATIONSHIP and name == "Target")
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
    needles: dict[str, str],
    in_bytes: dict[str, str],
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


def _block_hits(
    part: str, blocks: list[_Block], needles: dict[str, str], hider: _Hider
) -> list[LeakHit]:
    """The hits in the blocks of a part, searched all at once: each block normalised on its own,
    the blocks joined by a character no needle holds."""
    folded = [normalize(block.text) for block in blocks]
    offsets = list(accumulate((len(text) + 1 for text in folded[:-1]), initial=0))
    exempt = {
        (offsets[index] + start, offsets[index] + end, key)
        for index, block in enumerate(blocks)
        if block.instructions
        for start, end, key in _fixed_words(block)
    }
    found: dict[int, list[_Match]] = {}
    for match in _matches("\x00".join(folded), needles, exempt):
        found.setdefault(bisect_right(offsets, match.start) - 1, []).append(match)
    hits = []
    for index in sorted(found):
        block = blocks[index]
        # What a %-decoded form holds that its block shows as it is, is that block's hit.
        shown = {m.key for m in found.get(block.decodes, [])} if block.decodes is not None else ()
        for match in found[index]:
            if match.key in shown:
                continue
            at = offsets[index]
            context = _block_context(block, match.start - at, match.end - at, match, hider)
            hits.append(LeakHit(part, match.placeholder, context))
    return hits


def _block_context(block: _Block, start: int, end: int, match: _Match, hider: _Hider) -> str:
    source = _source(block.text, start, end)
    if source is None:
        context = match.placeholder
    else:
        context = hider.context(block.text, *source, match.placeholder)
    return context if block.label is None else f'{block.label}="{context}"'


def _fixed_words(block: _Block) -> list[tuple[int, int, str]]:
    """Where the field instructions of ``block`` hold a word that is exactly a field's name
    (PAGE) or the format keyword or picture right after a format switch (\\* MERGEFORMAT),
    unquoted, as (start, end, word) in the normalised block (ruling R31). Such a word is no hit
    for a value spelt like it. A switch itself (\\h) has fewer letters than any value searched
    for."""
    words = [
        (start + word_start, start + word_end)
        for start, end in block.instructions
        for word_start, word_end in _field_words(block.text[start:end])
    ]
    traced = _folded(block.text) if words else None
    if traced is None:
        return []
    folded, starts, _ = traced
    fixed = []
    for word_start, word_end in words:
        low, high = bisect_left(starts, word_start), bisect_left(starts, word_end)
        if high - low >= MIN_LENGTH:
            fixed.append((low, high, folded[low:high]))
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


def _byte_hits(part: str, data: bytes, in_bytes: dict[str, str], hider: _Hider) -> list[LeakHit]:
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
        for match in _matches(normalize(text), in_bytes):
            hits.append(LeakHit(part, match.placeholder, _byte_context(text, match, hider)))
    return hits


def _byte_context(text: str, match: _Match, hider: _Hider) -> str:
    source = _source(text, match.start, match.end)
    if source is None:
        return BINARY_PART
    context = hider.context(text, *source, match.placeholder)
    plain = context.replace(_CUT, "")
    return context if plain.isascii() and plain.isprintable() else BINARY_PART


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
        if entry.type in _NAMES
        for form in (entry.value, *entry.variants)
    }
    names |= {normalize(form) for _, forms in people for form in forms}
    return lambda word: normalize(word) in names
