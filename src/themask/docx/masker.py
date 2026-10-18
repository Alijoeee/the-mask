"""The masked copy: placeholders in place of the values, everywhere a Word file keeps them.

``apply_mask`` writes each replacement of a ``MaskPlan`` into the XML at the place the text map
gives it, through ``restorer.replace_in_paragraph``: a value Word split across runs is replaced as
a whole, and its placeholder takes the formatting of the value's first run. Paragraphs, tables,
numbering, styles and sections are never touched. A value can also sit where the text map does
not reach, and is taken out there too:

* the instruction of a simple field (``w:fldSimple/@w:instr``) has every replaced value masked,
  however the instruction cases and spaces it (``flexible_pattern``). The instructions of other
  fields (``w:instrText``) are part of the text map and are masked with the text;
* a hyperlink whose address holds a replaced value, compared normalised and also %-decoded (a
  ``mailto:`` address may write its "@" as "%40"), becomes plain runs, and the relationship that
  held the address is removed;
* a bookmark whose name holds a replaced value is renamed ``bm<N>``, and the links and field
  instructions that refer to it follow, so they still work (ruling R23).

``insert_banner`` puts the note for the AI at the top of the document. ``new_case_code`` and
``neutral_name`` give the masked file a name that says nothing about the parties.
"""

from __future__ import annotations

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
# The leak check looks for values of at least this many normalised characters (ruling R14). A
# new bookmark name must not hold one; a shorter value is in too many names to avoid.
_CHECKED_LENGTH = 4
_NAME_PART = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

# The plan's replacements in one paragraph, its positions counted from the paragraph's start.
Edits = list[tuple[int, int, str]]


@dataclass
class MaskReport:
    """What ``apply_mask`` changed.

    ``replaced`` counts the plan's replacements that were made. One whose stretch holds no text
    node is skipped (see ``replace_in_paragraph``); one that lies inside a field instruction's
    reference to a renamed bookmark is made by the bookmark's new name instead of its
    placeholder. ``hyperlinks_unwrapped`` counts the links turned into plain runs,
    ``instr_fields_masked`` the simple-field instructions changed, and ``bookmarks_renamed`` the
    bookmarks given a new name.
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
    keys = {key for key in map(normalize, values) if key}
    renames = _bookmark_renames(pkg, keys)
    replaced = 0
    for index, segment in enumerate(doc_text.segments):
        planned = edits.get(index, [])
        references = _references_in_instructions(segment.para, renames)
        if planned or references:
            merged, used, taken_in = _merge(planned, references)
            made = replace_in_paragraph(segment.para, "accepted", merged)
            replaced += made - used + taken_in  # a renamed reference is always made
    bookmarks = _rename_bookmarks(pkg, renames)
    fields = _mask_simple_fields(pkg, values, renames)
    links = _unwrap_hyperlinks(pkg, keys)
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


# ---- bookmarks and field instructions ---------------------------------------------------------


def _holds_value(text: str, keys: Iterable[str]) -> bool:
    folded = normalize(text)
    return any(key in folded for key in keys)


def _bookmark_renames(pkg: DocxPackage, keys: set[str]) -> dict[str, str]:
    """A new name for each bookmark whose name holds a replaced value, by its old name casefolded.

    The new names are bm1, bm2, ... in document order, leaving out the names bookmarks already
    have (Word compares them without case) and any that would hold a value itself.
    """
    if not keys:
        return {}
    names = [
        bookmark.get(_NAME, "")
        for part in pkg.TEXT_PARTS
        for bookmark in pkg.xml(part).iter(_BOOKMARK_START)
    ]
    taken = {name.casefold() for name in names}
    checked = {key for key in keys if len(key) >= _CHECKED_LENGTH}
    renames: dict[str, str] = {}
    number = 0
    for name in names:
        if name.casefold() in renames or not _holds_value(name, keys):
            continue
        number += 1
        while f"bm{number}" in taken or _holds_value(f"bm{number}", checked):
            number += 1
        renames[name.casefold()] = f"bm{number}"
    return renames


def _rename_bookmarks(pkg: DocxPackage, renames: dict[str, str]) -> int:
    """Gives the bookmarks their new names, and the links to them too; returns how many."""
    if not renames:
        return 0
    renamed = 0
    for part in pkg.TEXT_PARTS:
        root = pkg.xml(part)
        for bookmark in root.iter(_BOOKMARK_START):
            new = renames.get(bookmark.get(_NAME, "").casefold())
            if new is not None:
                bookmark.set(_NAME, new)
                renamed += 1
        for link in root.iter(_HYPERLINK):
            new = renames.get(link.get(_ANCHOR, "").casefold())
            if new is not None:
                link.set(_ANCHOR, new)
    return renamed


def _renamed_words(instruction: str, renames: dict[str, str]) -> Edits:
    """The words of a field instruction that name a renamed bookmark, with its new name.

    That covers REF, PAGEREF and NOTEREF fields and a HYPERLINK's ``\\l`` target alike, and a
    word in quotes as well as one without.
    """
    found: Edits = []
    for word in _INSTRUCTION_WORD.finditer(instruction):
        group = 1 if word.group(1) is not None else 2
        new = renames.get(word.group(group).casefold())
        if new is not None:
            found.append((word.start(group), word.end(group), new))
    return found


def _references_in_instructions(p: etree._Element, renames: dict[str, str]) -> Edits:
    """Where the ``w:instrText`` of paragraph ``p`` names a renamed bookmark, and its new name.

    An instruction can be split over several ``w:instrText`` nodes; nodes that follow on from
    one another are read as one instruction.
    """
    if not renames or next(p.iter(_INSTR_TEXT), None) is None:
        return []
    text, nodes = paragraph_nodes(p, "accepted")
    found: Edits = []
    for start, end in _instruction_stretches(nodes):
        words = _renamed_words(text[start:end], renames)
        found += [(start + s, start + e, new) for s, e, new in words]
    return found


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


def _mask_simple_fields(pkg: DocxPackage, values: dict[str, str], renames: dict[str, str]) -> int:
    """Masks the replaced values in every simple field's instruction; returns how many changed.

    A reference to a renamed bookmark is renamed first, so it keeps working.
    """
    if not values and not renames:
        return 0
    patterns = [(flexible_pattern(value), placeholder) for value, placeholder in values.items()]
    changed = 0
    for part in pkg.TEXT_PARTS:
        for field in pkg.xml(part).iter(_FLD_SIMPLE):
            instruction = field.get(_INSTR)
            if instruction is None:
                continue
            new = instruction
            for start, end, name in reversed(_renamed_words(new, renames)):
                new = new[:start] + name + new[end:]
            new = _masked(new, patterns)
            if new != instruction:
                field.set(_INSTR, new)
                changed += 1
    return changed


def _masked(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> str:
    """``text`` with every match of a pattern replaced by its placeholder, in a single pass.

    Of matches that overlap, the one that starts first wins, then the longer one. The text is
    searched once, so a value is never looked for inside a placeholder just written.
    """
    matches = sorted(
        (
            (match.start(), match.end(), placeholder)
            for pattern, placeholder in patterns
            for match in pattern.finditer(text)
        ),
        key=lambda m: (m[0], m[0] - m[1]),
    )
    pieces: list[str] = []
    at = 0
    for start, end, placeholder in matches:
        if start >= at:
            pieces += [text[at:start], placeholder]
            at = end
    return "".join(pieces) + text[at:]


# ---- hyperlinks -------------------------------------------------------------------------------


def _unwrap_hyperlinks(pkg: DocxPackage, keys: set[str]) -> int:
    """Turns every link whose address holds a replaced value into plain runs; returns how many.

    The relationship that held the address goes too, unless something else in the part still
    refers to it (a shape's click link, say), as the file would not open without it.
    """
    if not keys:
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
            and _address_holds_value(rel.get("Target", ""), keys)
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


def _address_holds_value(target: str, keys: set[str]) -> bool:
    return _holds_value(target, keys) or _holds_value(unquote(target), keys)


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
