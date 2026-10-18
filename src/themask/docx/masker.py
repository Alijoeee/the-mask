"""The masked copy: placeholders in place of the values, everywhere a Word file keeps them.

``apply_mask`` writes each replacement of a ``MaskPlan`` into the XML at the place the text map
gives it, through ``restorer.replace_in_paragraph``: a value Word split across runs is replaced as
a whole, and its placeholder takes the formatting of the value's first run. Paragraphs, tables,
numbering, styles and sections are never touched. A value can also sit where the text map does
not reach, or in a form the plan's search does not find, and is taken out there too:

* field instructions, both ``w:fldSimple/@w:instr`` and the ``w:instrText`` of other fields,
  have every replaced value masked, however they case and space it (``flexible_pattern``), and
  also where they %-escape it, as a ``mailto:`` address may ("%20" for a space, "%40" for "@";
  ruling R26);
* a hyperlink whose address holds a replaced value becomes plain runs, and the relationship that
  held the address is removed;
* a bookmark whose name holds a replaced value is renamed ``bm<N>``, or ``_bm<N>`` when its
  name starts with "_" as the bookmarks Word hides do, and the links and field instructions that
  refer to it follow, so they still work (ruling R23). A link anchor that names no bookmark, and
  a word of a field instruction, that holds a value is renamed the same way (ruling R27).

Whether an address or a name holds a value is decided the way the leak check decides it (ruling
R14), so that the masker takes out what the leak check would find: the value normalised, at
least four characters long, and a value of digits only where no other digit touches it. A
shorter value, such as the "5" of "5%", is in too many addresses and names to mean anything
there (ruling R27).

``insert_banner`` puts the note for the AI at the top of the document. ``new_case_code`` and
``neutral_name`` give the masked file a name that says nothing about the parties.
"""

from __future__ import annotations

import codecs
import random
import re
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
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
# to the next space or quote (group 2). A bookmark is named by one such word.
_INSTRUCTION_WORD = re.compile(r'"([^"]*)"|([^\s"]+)')
# The names of Word's fields. In an instruction such a word names the field, even when a value
# is spelt like it or like part of it ("Page" in PAGEREF, "Link" in HYPERLINK), and is never
# renamed; nor is the format a switch takes ("\* MERGEFORMAT").
_FIELD_NAMES = frozenset(
    {
        "ADDRESSBLOCK", "ADVANCE", "ASK", "AUTHOR", "AUTONUM", "AUTONUMLGL", "AUTONUMOUT",
        "AUTOTEXT", "AUTOTEXTLIST", "BARCODE", "BIBLIOGRAPHY", "BIDIOUTLINE", "CITATION",
        "COMMENTS", "COMPARE", "CONTROL", "CREATEDATE", "DATABASE", "DATE", "DDE", "DDEAUTO",
        "DISPLAYBARCODE", "DOCPROPERTY", "DOCVARIABLE", "EDITTIME", "EMBED", "EQ", "FILENAME",
        "FILESIZE", "FILLIN", "FORMCHECKBOX", "FORMDROPDOWN", "FORMTEXT", "GLOSSARY",
        "GOTOBUTTON", "GREETINGLINE", "HYPERLINK", "IF", "IMPORT", "INCLUDE", "INCLUDEPICTURE",
        "INCLUDETEXT", "INDEX", "INFO", "KEYWORDS", "LASTSAVEDBY", "LINK", "LISTNUM",
        "MACROBUTTON", "MERGEBARCODE", "MERGEFIELD", "MERGEREC", "MERGESEQ", "NEXT", "NEXTIF",
        "NOTEREF", "NUMCHARS", "NUMPAGES", "NUMWORDS", "PAGE", "PAGEREF", "PRINT", "PRINTDATE",
        "PRIVATE", "QUOTE", "RD", "REF", "REVNUM", "SAVEDATE", "SECTION", "SECTIONPAGES", "SEQ",
        "SET", "SHAPE", "SKIPIF", "STYLEREF", "SUBJECT", "SYMBOL", "TA", "TC", "TEMPLATE",
        "TIME", "TITLE", "TOA", "TOC", "USERADDRESS", "USERINITIALS", "USERNAME", "XE",
    }
)
_FORMAT_SWITCHES = frozenset({"\\*", "\\@", "\\#"})
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
# Each replaced value's pattern, with the placeholder that replaces it.
Patterns = list[tuple[re.Pattern[str], str]]


@dataclass
class MaskReport:
    """What ``apply_mask`` changed.

    ``replaced`` counts the plan's replacements that were made. One whose stretch holds no text
    node is skipped (see ``replace_in_paragraph``); one that lies inside a field instruction's
    reference to a renamed bookmark is made by the bookmark's new name instead of its
    placeholder. ``hyperlinks_unwrapped`` counts the links turned into plain runs.
    ``instr_fields_masked`` counts the field instructions changed besides the plan's
    replacements: simple-field instructions, and the ``w:instrText`` instructions that still
    held a value (%-escaped, or glued to other letters) after them. ``bookmarks_renamed``
    counts the bookmarks given a new name.
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
    patterns = [(flexible_pattern(value), placeholder) for value, placeholder in values.items()]
    finder = _ValueFinder(values)
    names = _names_to_change(pkg, finder)
    replaced = 0
    for index, segment in enumerate(doc_text.segments):
        planned = edits.get(index, [])
        references = _references_in_instructions(segment.para, names)
        if planned or references:
            merged, used, taken_in = _merge(planned, references)
            made = replace_in_paragraph(segment.para, "accepted", merged)
            replaced += made - used + taken_in  # a renamed reference is always made
    bookmarks = _rename_bookmarks(pkg, names)
    fields = _mask_simple_fields(pkg, patterns, names, finder)
    fields += _mask_field_codes(doc_text, patterns, names, finder)
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


def _merge(planned: Edits, references: Edits) -> tuple[Edits, int, int]:
    """The plan's replacements in a paragraph together with its references to renamed bookmarks.

    A reference takes the place of the replacements inside it: the bookmark's new name takes the
    value out as well, and keeps the reference working. A reference that a replacement covers
    only in part is left to the plan. Returns the replacements in order, how many of them are
    references, and how many of the plan's the references took in.
    """
    kept = list(planned)
    used: Edits = []
    taken_in = 0
    for start, end, name in references:
        inside = [r for r in kept if r[0] < end and start < r[1]]
        if all(start <= r[0] and r[1] <= end for r in inside):
            kept = [r for r in kept if r not in inside]
            used.append((start, end, name))
            taken_in += sum(1 for r in inside if r[0] < r[1])  # an empty one is never made
    return sorted(kept + used), len(used), taken_in


def _edited(text: str, edits: Edits) -> str:
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text


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
    """The bookmarks whose names hold a value, and the anchors that do and name no bookmark."""
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
        marked = {name.casefold() for name in bookmarks}
        dangling = [anchor for anchor in anchors if anchor.casefold() not in marked]
        for name in bookmarks + dangling:
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


def _renamed_words(
    instruction: str, names: _Names, finder: _ValueFinder | None = None
) -> Edits:
    """The words of a field instruction to rename, with their new names.

    A word that names a renamed bookmark or anchor gets its new name: that covers REF, PAGEREF
    and NOTEREF fields and a HYPERLINK's ``\\l`` target alike, a word in quotes as well as one
    without. Given ``finder``, a word that holds a value outside any placeholder is renamed as a
    bookmark would be: a reference such as ``REF AcmeOld``, where the value is glued to other
    letters and no pattern finds it (ruling R27). The field's name, its switches and their
    formats are never renamed, except where a word stands for a bookmark.
    """
    found: Edits = []
    previous = ""
    for word in _INSTRUCTION_WORD.finditer(instruction):
        group = 1 if word.group(1) is not None else 2
        name = word.group(group)
        if _may_be_renamed(name, previous):
            new = names.get(name)
            if new is None and finder is not None and finder.found_in(_outside_placeholders(name)):
                new = names.rename(name)
            if new is not None:
                found.append((word.start(group), word.end(group), new))
        previous = name
    return found


def _outside_placeholders(text: str) -> str:
    """``text`` without its placeholders, whose type names ("COMPANY") are no values."""
    return PLACEHOLDER_RE.sub(" ", text)


def _may_be_renamed(word: str, previous: str) -> bool:
    """Whether a word of a field instruction can be a bookmark's name or hold a value.

    Not a field's name, nor the format a switch takes, unless it stands where a bookmark's name
    does. (A switch itself, "\\h", is too short to hold a value.)
    """
    before = previous.upper()
    if before in _BOOKMARK_PLACES:
        return True
    return word.upper() not in _FIELD_NAMES and before not in _FORMAT_SWITCHES


def _value_edits(text: str, patterns: Patterns) -> Edits:
    """Where ``text`` holds a value, as written or %-escaped, and the placeholder to put there.

    The patterns run over the text and over the text with its %-escapes decoded (ruling R26).
    A value found in the decoded text is mapped back to the escaped stretch it came from, and
    only that stretch is replaced: every other escape stays as it was, since a decoded "%22"
    or "%5C" would change the instruction's quoting. Of matches that overlap, the one that
    starts first wins, then the longer one; and as the text is searched once, a value is never
    looked for inside a placeholder written for another.
    """
    found = [(m.start(), m.end(), ph) for pattern, ph in patterns for m in pattern.finditer(text)]
    decoded, starts = _percent_decoded(text)
    if decoded != text:
        found += [
            (starts[m.start()], starts[m.end()], ph)
            for pattern, ph in patterns
            for m in pattern.finditer(decoded)
        ]
    found.sort(key=lambda f: (f[0], f[0] - f[1]))
    edits: Edits = []
    at = 0
    for start, end, placeholder in found:
        if start >= at and end > start:
            edits.append((start, end, placeholder))
            at = end
    return edits


def _percent_decoded(text: str) -> tuple[str, list[int]]:
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


def _mask_simple_fields(
    pkg: DocxPackage, patterns: Patterns, names: _Names, finder: _ValueFinder
) -> int:
    """Takes the values out of every simple field's instruction; returns how many changed.

    In this order: a reference to a renamed bookmark gets its new name, so it keeps working;
    values, as written or %-escaped, become their placeholders; a word that still holds a value
    is renamed.
    """
    if not patterns:
        return 0
    changed = 0
    for part in pkg.TEXT_PARTS:
        for field in pkg.xml(part).iter(_FLD_SIMPLE):
            old = field.get(_INSTR)
            if old is None:
                continue
            new = _edited(old, _renamed_words(old, names))
            new = _edited(new, _value_edits(new, patterns))
            new = _edited(new, _renamed_words(new, names, finder))
            if new != old:
                field.set(_INSTR, new)
                changed += 1
    return changed


def _mask_field_codes(
    doc_text: DocText, patterns: Patterns, names: _Names, finder: _ValueFinder
) -> int:
    """Takes out of every ``w:instrText`` instruction what the plan's replacements left of the
    values; returns how many instructions changed.

    The plan replaced the values as the text writes them (the text map holds instructions) and
    the references to renamed bookmarks with them. Left are values %-escaped in an address and
    words that hold a value glued to other letters; the values as written are looked for again
    as well (ruling R26).
    """
    if not patterns:
        return 0
    changed = 0
    for segment in doc_text.segments:
        p = segment.para
        if next(p.iter(_INSTR_TEXT), None) is None:
            continue
        before = _instructions(p)
        for find in (
            partial(_value_edits, patterns=patterns),
            partial(_renamed_words, names=names, finder=finder),
        ):
            edits = _instruction_edits(p, find)
            if edits:
                replace_in_paragraph(p, "accepted", edits)
        changed += sum(old != new for old, new in zip(before, _instructions(p)))
    return changed


def _references_in_instructions(p: etree._Element, names: _Names) -> Edits:
    """Where the ``w:instrText`` of paragraph ``p`` names a renamed bookmark, and its new name."""
    if not names or next(p.iter(_INSTR_TEXT), None) is None:
        return []
    return _instruction_edits(p, partial(_renamed_words, names=names))


def _instruction_edits(p: etree._Element, find: Callable[[str], Edits]) -> Edits:
    """The edits ``find`` gives for each field instruction of paragraph ``p``, placed in its text.

    An instruction can be split over several ``w:instrText`` nodes; nodes that follow on from
    one another are read as one instruction.
    """
    text, nodes = paragraph_nodes(p, "accepted")
    return [
        (start + s, start + e, new)
        for start, end in _instruction_stretches(nodes)
        for s, e, new in find(text[start:end])
    ]


def _instructions(p: etree._Element) -> list[str]:
    text, nodes = paragraph_nodes(p, "accepted")
    return [text[start:end] for start, end in _instruction_stretches(nodes)]


def _instruction_stretches(nodes: list[TextNode]) -> list[tuple[int, int]]:
    stretches: list[tuple[int, int]] = []
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
