"""The masked copy: placeholders in place of the values, everywhere a Word file keeps them.

``apply_mask`` writes each replacement of a ``MaskPlan`` into the XML at the place the text map
gives it, through ``restorer.replace_in_paragraph``: a value Word split across runs is replaced as
a whole, and its placeholder takes the formatting of the value's first run. Paragraphs, tables,
numbering, styles and sections are never touched. A value can also sit where the text map does
not reach, or in a form the plan's search does not find, and is taken out there too:

* every field instruction, a simple field's ``w:fldSimple/@w:instr`` and the ``w:instrText`` of
  any other field alike, is searched once, the same way, for every replaced value: however it
  cases and spaces the value (``flexible_pattern``), and where it %-escapes it, as a ``mailto:``
  address may ("%20" for a space, "%40" for "@"; ruling R26). The plan's replacements inside an
  instruction are made in that one search, so both kinds of field give the same result. The
  field's name and its switches stay as they are, even when a value is spelt like them ("Page"
  and ``PAGE``), and so does a placeholder already there (ruling R30);
* a hyperlink whose address holds a replaced value becomes plain runs, and the relationship that
  held the address is removed;
* a bookmark whose name holds a replaced value is renamed ``bm<N>``, or ``_bm<N>`` when its name
  starts with "_" as the bookmarks Word hides do, and the links and field instructions that
  refer to it follow, so they still work (ruling R23). A link anchor that names no bookmark, and
  a word of a field instruction, that holds a value is renamed the same way (ruling R27).

Whether an address or a name holds a value is decided the way the leak check decides it (ruling
R14), so that the masker takes out what the leak check would find: the value normalised, at
least four characters long, and a value of digits only where no other digit touches it. A
shorter value, such as the "5" of "5%", is in too many addresses and names to mean anything
there (ruling R27). It is still replaced where it stands in an instruction, so a reference such
as ``REF SAP_Section`` becomes ``REF [COMPANY_1]_Section`` and no longer finds its bookmark.

``insert_banner`` puts the note for the AI at the top of the document. ``new_case_code`` and
``neutral_name`` give the masked file a name that says nothing about the parties.
"""

from __future__ import annotations

import codecs
import random
import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote

from lxml import etree

from themask.docx.package import NS, RELS_NS, DocxPackage
from themask.docx.reader import DocText, Segment, TextNode, paragraph_nodes
from themask.docx.restorer import replace_in_paragraph
from themask.instruction import BANNER_TEXT
from themask.model import MaskPlan
from themask.placeholders import PLACEHOLDER_RE
from themask.textnorm import flexible_pattern, normalize

# A case code is four of these: capitals and digits without I, L, O, 0 and 1, which are easily
# taken for one another when a code is read out or typed.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4


def _w(name: str) -> str:
    return f"{{{NS['w']}}}{name}"


_BODY = _w("body")
_P = _w("p")
_R = _w("r")
_RPR = _w("rPr")
_ITALIC = _w("i")
_T = _w("t")
_FLD_SIMPLE = _w("fldSimple")
_INSTR = _w("instr")
_INSTR_TEXT = _w("instrText")
_HYPERLINK = _w("hyperlink")
_ANCHOR = _w("anchor")
_BOOKMARK_START = _w("bookmarkStart")
_NAME = _w("name")
_XML_SPACE = f"{{{NS['xml']}}}space"
_RELATIONSHIP = f"{{{RELS_NS}}}Relationship"
_REFERENCE = f"{{{NS['r']}}}"  # the namespace of every attribute that names a relationship
_LINK_ID = f"{_REFERENCE}id"
_HYPERLINK_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"

# A word of a field instruction: a quoted string (its content in group 1), or anything else up
# to the next space or quote (group 2). A bookmark is named by one such word. This, the field
# names and the format switches below are how the leak check reads an instruction too (ruling
# R31).
INSTRUCTION_WORD = re.compile(r'"([^"]*)"|([^\s"]+)')
# The names of Word's fields. Written as a word of an instruction, such a name is the field's,
# even when a value is spelt like it or like part of it ("Page" and PAGE or PAGEREF).
FIELD_NAMES = frozenset(
    {
        "ADDRESSBLOCK",
        "ADVANCE",
        "ASK",
        "AUTHOR",
        "AUTONUM",
        "AUTONUMLGL",
        "AUTONUMOUT",
        "AUTOTEXT",
        "AUTOTEXTLIST",
        "BARCODE",
        "BIBLIOGRAPHY",
        "BIDIOUTLINE",
        "CITATION",
        "COMMENTS",
        "COMPARE",
        "CONTROL",
        "CREATEDATE",
        "DATABASE",
        "DATE",
        "DDE",
        "DDEAUTO",
        "DISPLAYBARCODE",
        "DOCPROPERTY",
        "DOCVARIABLE",
        "EDITTIME",
        "EMBED",
        "EQ",
        "FILENAME",
        "FILESIZE",
        "FILLIN",
        "FORMCHECKBOX",
        "FORMDROPDOWN",
        "FORMTEXT",
        "GLOSSARY",
        "GOTOBUTTON",
        "GREETINGLINE",
        "HYPERLINK",
        "IF",
        "IMPORT",
        "INCLUDE",
        "INCLUDEPICTURE",
        "INCLUDETEXT",
        "INDEX",
        "INFO",
        "KEYWORDS",
        "LASTSAVEDBY",
        "LINK",
        "LISTNUM",
        "MACROBUTTON",
        "MERGEBARCODE",
        "MERGEFIELD",
        "MERGEREC",
        "MERGESEQ",
        "NEXT",
        "NEXTIF",
        "NOTEREF",
        "NUMCHARS",
        "NUMPAGES",
        "NUMWORDS",
        "PAGE",
        "PAGEREF",
        "PRINT",
        "PRINTDATE",
        "PRIVATE",
        "QUOTE",
        "RD",
        "REF",
        "REVNUM",
        "SAVEDATE",
        "SECTION",
        "SECTIONPAGES",
        "SEQ",
        "SET",
        "SHAPE",
        "SKIPIF",
        "STYLEREF",
        "SUBJECT",
        "SYMBOL",
        "TA",
        "TC",
        "TEMPLATE",
        "TIME",
        "TITLE",
        "TOA",
        "TOC",
        "USERADDRESS",
        "USERINITIALS",
        "USERNAME",
        "XE",
    }
)
# The switches that take a format: a keyword ("\* MERGEFORMAT") or a picture in quotes
# ('\@ "d MMMM yyyy"', '\# "0.00"').
FORMAT_SWITCHES = frozenset({"\\*", "\\@", "\\#"})
# After these words, a word names a bookmark, whatever it spells.
_BOOKMARK_PLACES = frozenset({"REF", "PAGEREF", "NOTEREF", "\\L"})
# A run of %-escapes, as an address writes the characters it may not hold ("%40" for "@").
_ESCAPES = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
# The leak check looks for values of at least this many normalised characters (ruling R14).
_CHECKED_LENGTH = 4
_NAME_PART = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

# Changes to a text: (start, end, new text), in order and not overlapping. In a paragraph, the
# positions count from its start.
Edits = list[tuple[int, int, str]]
Spans = list[tuple[int, int]]


@dataclass
class MaskReport:
    """What ``apply_mask`` changed.

    ``replaced`` counts the plan's replacements that were made. One whose stretch holds no text
    node is skipped (see ``replace_in_paragraph``), and so is one on a field's name or switch or
    inside a placeholder; one that lies inside a field instruction's reference to a renamed
    bookmark is made by the bookmark's new name instead of its placeholder.
    ``hyperlinks_unwrapped`` counts the links turned into plain runs, ``instr_fields_masked``
    the field instructions changed (``w:fldSimple`` and ``w:instrText`` alike), and
    ``bookmarks_renamed`` the bookmarks given a new name.
    """

    replaced: int
    hyperlinks_unwrapped: int
    instr_fields_masked: int
    bookmarks_renamed: int


def apply_mask(pkg: DocxPackage, doc_text: DocText, plan: MaskPlan) -> MaskReport:
    """Writes the plan's placeholders into ``pkg`` and takes the replaced values out elsewhere.

    ``doc_text`` must be what ``extract_text(pkg)`` gave for this very package object, in the
    accepted view, after its tracked changes were resolved: its segments point at the package's
    own paragraph elements, and the plan's positions count in its text. A copy of the package
    (``pkg.copy()``) has paragraphs of its own, so its text has to be read again.

    Raises ValueError, before anything changes, when a replacement does not lie inside one
    paragraph (the analysis never plans one across paragraphs), when a paragraph it changes is
    not one of this package's, or when that paragraph no longer reads as it did.
    """
    edits = _paragraph_edits(pkg, doc_text, plan)
    values = _values(doc_text, plan)
    finder = _ValueFinder(values)
    names = _names_to_change(pkg, finder)
    instructions = _Instructions(values, names, finder)
    replaced = 0
    fields = 0
    for index, segment in enumerate(doc_text.segments):
        made, changed = _mask_paragraph(segment.para, edits.get(index, []), instructions)
        replaced += made
        fields += changed
    fields += _mask_simple_fields(pkg, instructions)
    bookmarks = _rename_bookmarks(pkg, names)
    links = _unwrap_hyperlinks(pkg, finder)
    return MaskReport(
        replaced=replaced,
        hyperlinks_unwrapped=links,
        instr_fields_masked=fields,
        bookmarks_renamed=bookmarks,
    )


def insert_banner(pkg: DocxPackage, text: str = BANNER_TEXT) -> None:
    """Puts ``text``, in italics, as the document's first paragraph, with an empty one after it.

    Both come before anything else in the body; the body's last section stays last. The banner
    goes in after masking, as it is not part of the text the plan was made on.
    """
    body = pkg.xml(pkg.TEXT_PARTS[0]).find(_BODY)
    if body is None:
        raise ValueError("The document has no body to put the banner in.")
    banner = etree.Element(_P)
    run = etree.SubElement(banner, _R)
    etree.SubElement(etree.SubElement(run, _RPR), _ITALIC)
    node = etree.SubElement(run, _T)
    node.text = text
    if text != text.strip():
        node.set(_XML_SPACE, "preserve")
    body.insert(0, banner)
    body.insert(1, etree.Element(_P))


def new_case_code(rng: random.Random | None = None, existing: Iterable[str] = frozenset()) -> str:
    """A case code no case has yet: ``CODE_LENGTH`` characters of ``CODE_ALPHABET``.

    ``existing`` holds the codes in use: the ids of the stored cases and the names of the case
    files that cannot be read. They are compared without case, as macOS compares file names.
    ``rng`` is for tests; the code comes from the system's random source otherwise. Raises
    ValueError when every code is taken.
    """
    taken = {code.casefold() for code in existing}
    alphabet = set(CODE_ALPHABET.casefold())
    in_use = sum(1 for code in taken if len(code) == CODE_LENGTH and set(code) <= alphabet)
    if in_use >= len(CODE_ALPHABET) ** CODE_LENGTH:
        raise ValueError("Every case code is taken.")
    source = rng if rng is not None else random.SystemRandom()
    while True:
        code = "".join(source.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if code.casefold() not in taken:
            return code


def neutral_name(code: str, suffix: str | None = None) -> str:
    """The masked file's name: ``MASKED-<code>.docx``, or ``MASKED-<code>-<suffix>.docx``.

    ``suffix`` tells the files of one case apart: "2", "before", "1-after". Code and suffix are
    letters, digits and single hyphens, so the name is a plain file name and says nothing more;
    anything else raises ValueError.
    """
    for part in (code, suffix):
        if part is not None and _NAME_PART.fullmatch(part) is None:
            raise ValueError(f"{part!r} cannot be part of a masked file's name.")
    return f"MASKED-{code}.docx" if suffix is None else f"MASKED-{code}-{suffix}.docx"


# ---- the text ---------------------------------------------------------------------------------


def _paragraph_edits(pkg: DocxPackage, doc_text: DocText, plan: MaskPlan) -> dict[int, Edits]:
    """The plan's replacements by paragraph (the index of its segment), counted from its start.

    Checks, before anything changes, that each replacement lies inside one paragraph, and that
    each paragraph to change is one of this package's and still reads as it did.
    """
    starts = [segment.start for segment in doc_text.segments]
    edits: dict[int, Edits] = {}
    for r in plan.replacements:
        index = bisect_right(starts, r.start) - 1
        if index < 0 or r.end > doc_text.segments[index].end:
            raise ValueError(
                f"The replacement {r.placeholder} at {r.start}-{r.end} is not inside one paragraph."
            )
        start = doc_text.segments[index].start
        edits.setdefault(index, []).append((r.start - start, r.end - start, r.placeholder))
    for index in edits:
        _check_segment(pkg, doc_text, doc_text.segments[index])
    return edits


def _check_segment(pkg: DocxPackage, doc_text: DocText, segment: Segment) -> None:
    if segment.part not in pkg.names() or (
        segment.para.getroottree().getroot() is not pkg.xml(segment.part)
    ):
        raise ValueError("The text map was read from another package; read it from this one.")
    if paragraph_nodes(segment.para, "accepted")[0] != doc_text.text[segment.start : segment.end]:
        raise ValueError("A paragraph has changed since the text map was read; read it again.")


def _values(doc_text: DocText, plan: MaskPlan) -> dict[str, str]:
    """Each replaced value as the text writes it, with the placeholder of its first replacement."""
    values: dict[str, str] = {}
    for r in plan.replacements:
        value = doc_text.text[r.start : r.end]
        if value.strip():
            values.setdefault(value, r.placeholder)
    return values


def _mask_paragraph(
    p: etree._Element, planned: Edits, instructions: _Instructions
) -> tuple[int, int]:
    """Makes the plan's replacements in paragraph ``p`` and takes the values out of its field
    instructions, in one go; returns how many of the plan's replacements were made, and how
    many instructions changed.

    A replacement of the plan inside a ``w:instrText`` instruction is made by the instruction's
    own search (``_Instructions.edits``), which starts from the instruction as it stands, so
    that it gives the same result as the same instruction of a simple field.
    """
    with_instructions = bool(instructions) and next(p.iter(_INSTR_TEXT), None) is not None
    if not planned and not with_instructions:
        return 0, 0
    text, nodes = paragraph_nodes(p, "accepted") if with_instructions else ("", [])
    stretches = _instruction_stretches(nodes)
    in_text: Edits = []
    inside: list[Edits] = [[] for _ in stretches]
    for edit in planned:
        holder = next(
            (i for i, (s, e) in enumerate(stretches) if s <= edit[0] < edit[1] <= e), None
        )
        if holder is None:
            in_text.append(edit)
        else:
            inside[holder].append(edit)
    in_instructions: Edits = []
    made = 0
    changed = 0
    for (start, end), folded in zip(stretches, inside, strict=True):
        local = [(s - start, e - start, placeholder) for s, e, placeholder in folded]
        found = [
            (start + s, start + e, new)
            for s, e, new in instructions.edits(text[start:end], local)
            if not _overlaps(start + s, start + e, [(a, b) for a, b, _ in in_text])
        ]
        changed += bool(found)
        made += sum(1 for s, e, _ in folded if any(a <= s and e <= b for a, b, _ in found))
        in_instructions += found
    all_edits = sorted(in_text + in_instructions)
    if all_edits:
        # Every edit of an instruction is made, as an instruction is all text.
        made += replace_in_paragraph(p, "accepted", all_edits) - len(in_instructions)
    return made, changed


def _edited(text: str, edits: Edits) -> str:
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text


def _overlaps(start: int, end: int, spans: Spans) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


# ---- values in addresses and names ------------------------------------------------------------


class _ValueFinder:
    """Tells whether an address or a name holds one of the replaced values.

    The way the leak check tells it (ruling R14): compared normalised, as written and with its
    %-escapes decoded. A value of fewer than four characters once normalised never counts, and
    one of digits only counts only where no other digit touches it, so a phone number is found
    in "tel:+31204512473" but the value "2,025" is not in "_Ref120250".
    """

    def __init__(self, values: Iterable[str]) -> None:
        keys = {key for key in map(normalize, values) if len(key) >= _CHECKED_LENGTH}
        self._words = sorted(key for key in keys if not key.isdigit())
        numbers = sorted((key for key in keys if key.isdigit()), key=len, reverse=True)
        self._numbers = (
            re.compile(r"(?<!\d)(?:" + "|".join(map(re.escape, numbers)) + r")(?!\d)")
            if numbers
            else None
        )

    def __bool__(self) -> bool:
        return bool(self._words) or self._numbers is not None

    def found_in(self, text: str) -> bool:
        for form in (text, unquote(text)):
            folded = normalize(form)
            if any(word in folded for word in self._words):
                return True
            if self._numbers is not None and self._numbers.search(folded):
                return True
        return False


class _Names:
    """The new names of the bookmarks, link anchors and instruction words that hold a value.

    Old names are compared without case, as Word compares bookmark names. The new names are
    bm1, bm2, ... in the order they are asked for, with the "_" kept in front of a name that
    starts with one (Word hides those bookmarks); a name already in the file, or one that would
    hold a value itself, is never given.
    """

    def __init__(self, finder: _ValueFinder, taken: Iterable[str]) -> None:
        self._finder = finder
        self._taken = {name.casefold() for name in taken}
        self._new: dict[str, str] = {}
        self._number = 0

    def __bool__(self) -> bool:
        return bool(self._new)

    def get(self, name: str) -> str | None:
        """The new name given to ``name``, if it has one."""
        return self._new.get(name.casefold())

    def rename(self, name: str) -> str:
        """The new name for ``name``, given now if it has none yet."""
        new = self._new.get(name.casefold())
        if new is None:
            prefix = "_" if name.startswith("_") else ""
            while True:
                self._number += 1
                new = f"{prefix}bm{self._number}"
                if new.casefold() not in self._taken and not self._finder.found_in(new):
                    break
            self._taken.add(new.casefold())
            self._new[name.casefold()] = new
        return new


def _names_to_change(pkg: DocxPackage, finder: _ValueFinder) -> _Names:
    """The bookmarks and link anchors whose names hold a value, each given a new name.

    An anchor that names a renamed bookmark gets the bookmark's new name; one that names no
    bookmark gets a name of its own (ruling R27).
    """
    bookmarks = [
        bookmark.get(_NAME, "")
        for part in pkg.TEXT_PARTS
        for bookmark in pkg.xml(part).iter(_BOOKMARK_START)
    ]
    anchors = [
        link.get(_ANCHOR, "") for part in pkg.TEXT_PARTS for link in pkg.xml(part).iter(_HYPERLINK)
    ]
    names = _Names(finder, bookmarks + anchors)
    if finder:
        for name in bookmarks + anchors:
            if name and finder.found_in(name):
                names.rename(name)
    return names


def _rename_bookmarks(pkg: DocxPackage, names: _Names) -> int:
    """Gives the bookmarks and link anchors their new names; returns how many bookmarks."""
    if not names:
        return 0
    renamed = 0
    for part in pkg.TEXT_PARTS:
        root = pkg.xml(part)
        for bookmark in root.iter(_BOOKMARK_START):
            new = names.get(bookmark.get(_NAME, ""))
            if new is not None:
                bookmark.set(_NAME, new)
                renamed += 1
        for link in root.iter(_HYPERLINK):
            new = names.get(link.get(_ANCHOR, ""))
            if new is not None:
                link.set(_ANCHOR, new)
    return renamed


# ---- field instructions -----------------------------------------------------------------------


@dataclass(frozen=True)
class _Word:
    """A word of a field instruction: ``instruction[start:end]``, without its quotes.

    ``renamable``: it can name a bookmark, or hold a value glued to other letters. ``fixed``: it
    is the field's name, a switch, or the format keyword a switch takes, and is never changed.
    """

    start: int
    end: int
    text: str
    renamable: bool
    fixed: bool


def _words(instruction: str) -> list[_Word]:
    words: list[_Word] = []
    previous = ""
    for match in INSTRUCTION_WORD.finditer(instruction):
        quoted = match.group(1) is not None
        group = 1 if quoted else 2
        text = match.group(group)
        before = previous.upper()
        if before in _BOOKMARK_PLACES:  # a bookmark's name, whatever it spells
            renamable, fixed = True, False
        elif before in FORMAT_SWITCHES:  # a format keyword, or a picture that may hold text
            renamable, fixed = False, not quoted
        elif not quoted and (text.upper() in FIELD_NAMES or text.startswith("\\")):
            renamable, fixed = False, True
        else:
            renamable, fixed = True, False
        words.append(_Word(match.start(group), match.end(group), text, renamable, fixed))
        previous = text
    return words


class _Instructions:
    """Takes the replaced values out of field instructions, the same way for every kind of field."""

    def __init__(self, values: dict[str, str], names: _Names, finder: _ValueFinder) -> None:
        self._patterns = [(flexible_pattern(value), ph) for value, ph in values.items()]
        self._names = names
        self._finder = finder

    def __bool__(self) -> bool:
        return bool(self._patterns)

    def edits(self, instruction: str, planned: Edits | None = None) -> Edits:
        """The edits that take the values out of ``instruction``, positioned in it.

        One search of the instruction as it stands:

        * a word that names a renamed bookmark or anchor gets its new name, so that the
          reference keeps working: in a REF, PAGEREF or NOTEREF field or a HYPERLINK's ``\\l``,
          in quotes or not;
        * every replaced value, as written or %-escaped (ruling R26), and each of the plan's
          replacements inside the instruction (``planned``), becomes its placeholder. Of two
          that overlap, the one that starts first wins, then the longer one, then the plan's. A
          value found only %-escaped is mapped back to its escaped stretch, and only that
          stretch is replaced: every other escape stays, since a decoded "%22" or "%5C" would
          change the instruction's quoting;
        * a word that still holds a value, glued to other letters where no pattern finds it,
          is renamed like a bookmark (``REF AcmeOld``; ruling R27).

        Never changed: the field's name, its switches and the format keyword a switch takes, and
        a placeholder already in the instruction; a value found in one of them is skipped
        (ruling R30).
        """
        decoded, starts = percent_decoded(instruction)
        words = _words(instruction)
        renamed: Edits = []
        for word in words:
            new = self._names.get(word.text) if word.renamable else None
            if new is not None:
                renamed.append((word.start, word.end, new))
        placeholders = _placeholders(instruction, decoded, starts)
        kept: Spans = [(word.start, word.end) for word in words if word.fixed]
        kept += [(start, end) for start, end, _ in renamed]
        kept += placeholders
        candidates = [(s, e, ph, 1) for s, e, ph in self._matches(instruction, decoded, starts)]
        candidates += [(s, e, ph, 0) for s, e, ph in planned or [] if s < e]
        values = _leftmost_longest([c for c in candidates if not _overlaps(c[0], c[1], kept)])
        # What a word holds besides placeholders, those it held and those just written: their
        # type names ("COMPANY") are no values.
        blanks = values + [(start, end, "") for start, end in placeholders]
        done = {(start, end) for start, end, _ in renamed}
        glued: Edits = []
        for word in words:
            if not word.renamable or (word.start, word.end) in done:
                continue
            rest = _blanked(instruction, word.start, word.end, blanks)
            if self._finder.found_in(rest):
                glued.append((word.start, word.end, self._names.rename(word.text)))
        values = [v for v in values if not _overlaps(v[0], v[1], [(s, e) for s, e, _ in glued])]
        return sorted(renamed + values + glued)

    def _matches(self, instruction: str, decoded: str, starts: list[int]) -> Edits:
        """Every match of every value, in the instruction and in its %-decoded form."""
        found = [
            (match.start(), match.end(), placeholder)
            for pattern, placeholder in self._patterns
            for match in pattern.finditer(instruction)
        ]
        if decoded != instruction:
            found += [
                (starts[match.start()], starts[match.end()], placeholder)
                for pattern, placeholder in self._patterns
                for match in pattern.finditer(decoded)
            ]
        return found


def _placeholders(instruction: str, decoded: str, starts: list[int]) -> Spans:
    """Where ``instruction`` already holds a placeholder, written or %-escaped."""
    spans = [match.span() for match in PLACEHOLDER_RE.finditer(instruction)]
    if decoded != instruction:
        spans += [
            (starts[match.start()], starts[match.end()])
            for match in PLACEHOLDER_RE.finditer(decoded)
        ]
    return spans


def _leftmost_longest(candidates: list[tuple[int, int, str, int]]) -> Edits:
    """The candidates that do not overlap: of two that do, the one that starts first, then the
    longer one, then the one ranked first."""
    chosen: Edits = []
    at = 0
    for start, end, placeholder, _rank in sorted(
        candidates, key=lambda c: (c[0], c[0] - c[1], c[3])
    ):
        if start >= at and end > start:
            chosen.append((start, end, placeholder))
            at = end
    return chosen


def _blanked(text: str, start: int, end: int, edits: Edits) -> str:
    """``text[start:end]`` with every character an edit replaces blanked out."""
    chars = list(text[start:end])
    for edit_start, edit_end, _new in edits:
        for i in range(max(edit_start, start), min(edit_end, end)):
            chars[i - start] = " "
    return "".join(chars)


def percent_decoded(text: str) -> tuple[str, list[int]]:
    """``text`` with its %-escapes decoded as ``unquote`` decodes them, and where in ``text``
    each character of the result begins; a last entry, ``len(text)``, closes the list."""
    chars: list[str] = []
    starts: list[int] = []
    at = 0
    for run in _ESCAPES.finditer(text):
        chars += text[at : run.start()]
        starts += range(at, run.start())
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        begun = run.start()  # where the character being decoded began
        for i in range(run.start(), run.end(), 3):
            out = decoder.decode(bytes([int(text[i + 1 : i + 3], 16)]))
            if out:
                chars += out
                starts += [begun] + [i] * (len(out) - 1)
                begun = i + 3
        out = decoder.decode(b"", final=True)
        chars += out
        starts += [begun] * len(out)
        at = run.end()
    chars += text[at:]
    starts += range(at, len(text) + 1)
    return "".join(chars), starts


def _mask_simple_fields(pkg: DocxPackage, instructions: _Instructions) -> int:
    """Takes the values out of every simple field's instruction; returns how many changed."""
    if not instructions:
        return 0
    changed = 0
    for part in pkg.TEXT_PARTS:
        for field in pkg.xml(part).iter(_FLD_SIMPLE):
            old = field.get(_INSTR)
            if old is None:
                continue
            new = _edited(old, instructions.edits(old))
            if new != old:
                field.set(_INSTR, new)
                changed += 1
    return changed


def _instruction_stretches(nodes: list[TextNode]) -> Spans:
    """Where a paragraph's text holds field instructions: one stretch for each run of
    ``w:instrText`` nodes that follow on from one another, as an instruction can be split."""
    stretches: Spans = []
    for node in nodes:
        if node.kind != "instr":
            continue
        if stretches and stretches[-1][1] == node.start:
            stretches[-1] = (stretches[-1][0], node.end)
        else:
            stretches.append((node.start, node.end))
    return stretches


# ---- hyperlinks -------------------------------------------------------------------------------


def _unwrap_hyperlinks(pkg: DocxPackage, finder: _ValueFinder) -> int:
    """Turns every link whose address holds a replaced value into plain runs; returns how many.

    The relationship that held the address goes too, unless something else in the part still
    refers to it (a shape's click link, say), as the file would not open without it.
    """
    if not finder:
        return 0
    unwrapped = 0
    for part in pkg.TEXT_PARTS:
        try:
            rels = pkg.rels_of(part)
        except KeyError:  # a part without relationships has no link addresses
            continue
        doomed = {
            rel.get("Id"): rel
            for rel in rels.iterchildren(_RELATIONSHIP)
            if rel.get("Id") is not None
            and rel.get("Type") == _HYPERLINK_TYPE
            and finder.found_in(rel.get("Target", ""))
        }
        if not doomed:
            continue
        root = pkg.xml(part)
        for link in list(root.iter(_HYPERLINK)):
            if link.get(_LINK_ID) in doomed:
                _unwrap(link)
                unwrapped += 1
        still_used = _relationship_ids(root)
        for rel_id, rel in doomed.items():
            if rel_id not in still_used:
                rels.remove(rel)
    return unwrapped


def _unwrap(link: etree._Element) -> None:
    """Puts the content of a ``w:hyperlink`` in its place, so its runs stay where they were."""
    for child in list(link):
        link.addprevious(child)
    link.getparent().remove(link)


def _relationship_ids(root: etree._Element) -> set[str]:
    """Every relationship id an attribute in the part refers to (``r:id``, ``r:embed``, ...)."""
    return {
        value
        for element in root.iter(etree.Element)
        for name, value in element.attrib.items()
        if name.startswith(_REFERENCE)
    }
