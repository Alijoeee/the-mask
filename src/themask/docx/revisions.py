"""Accepting or rejecting every tracked change of a Word file, in place.

A masked copy carries only the final text: ``accept_all`` keeps what the changes put in and drops
what they took out, as Word's "Accept All Changes" does. For a redline review the app also makes
the version from before the changes: ``reject_all`` does the opposite. Both work on every text
part (the document, headers, footers, footnotes and endnotes), the VML copy of a text box in
``mc:Fallback`` included: the reader does not read that copy and the cleaner deletes it later, but
until then it must not keep text that the side kept does not have. Afterwards
``reader.has_revisions`` is False, and the result read in the accepted view is the side kept.

What each kind of revision becomes, accepting / rejecting:

- content put in (``w:ins``, ``w:moveTo``): kept without its wrapper / removed. Content taken out
  (``w:del``, ``w:moveFrom``): removed / kept, its ``w:delText`` and ``w:delInstrText`` becoming
  ``w:t`` and ``w:instrText``. Deleted text outside any deletion, as a damaged file may hold it,
  is removed / kept as text, the way the reader's two views read it. A move's range markers go.
- a change of properties (``w:rPrChange`` and the other ``*Change`` records): the record goes and
  the current properties stay / the properties go back to the old ones the record holds (see
  ``_restore``). A numbering change only goes: it holds no old properties.
- a paragraph mark put in (``w:pPr/w:rPr/w:ins``, ``w:moveTo``): the mark stays / the paragraph is
  joined with the next one; a mark taken out (``w:del``, ``w:moveFrom``): the other way round.
  Joining puts the paragraph's content in front of the next paragraph's, whose properties win, as
  when Word joins two paragraphs. A paragraph with no paragraph after it in its cell, text box or
  story keeps its mark.
- a row put in (``w:trPr/w:ins``) or a cell (``w:cellIns``): kept / removed; a row or cell taken out
  (``w:trPr/w:del``, ``w:cellDel``): the other way round; a cell merge (``w:cellMerge``) loses its
  mark only. A row left without cells goes, and so does a table left without rows.

Nothing else is changed. The text of the result is the reader's view of the side kept, except
where a paragraph mark, a row or a cell changed: there is no line break between the texts of two
joined paragraphs, and a removed row or cell leaves no (empty) paragraphs behind. Both functions
return the number of revision elements the text parts held, so a second run returns 0 and changes
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from themask.docx.package import NS, DocxPackage


def _w(name: str) -> str:
    return f"{{{NS['w']}}}{name}"


_P = _w("p")
_PPR = _w("pPr")
_RPR = _w("rPr")
_SECT_PR = _w("sectPr")
_TBL = _w("tbl")
_TR = _w("tr")
_TR_PR = _w("trPr")
_TC = _w("tc")
_TC_PR = _w("tcPr")
_T = _w("t")
_INSTR_TEXT = _w("instrText")
_DEL_TEXT = _w("delText")
_DEL_INSTR_TEXT = _w("delInstrText")

_INS, _DEL, _MOVE_FROM, _MOVE_TO = (_w(n) for n in ("ins", "del", "moveFrom", "moveTo"))
# What a change put in or took out: content, or the mark of a paragraph or a row.
_TRACKED = frozenset({_INS, _DEL, _MOVE_FROM, _MOVE_TO})
_CELL_INS, _CELL_DEL, _CELL_MERGE = (_w(n) for n in ("cellIns", "cellDel", "cellMerge"))
_CELL_MARKS = frozenset({_CELL_INS, _CELL_DEL, _CELL_MERGE})
_NUMBERING_CHANGE = _w("numberingChange")
# A change of properties holds the old properties in an element named like the one it sits in:
# a w:rPrChange in a w:rPr holds the old w:rPr.
_PROPERTY_CHANGES = frozenset(
    _w(name)
    for name in (
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "tblPrExChange",
        "trPrChange",
        "tcPrChange",
    )
)
_REVISIONS = _TRACKED | _CELL_MARKS | _PROPERTY_CHANGES | {_NUMBERING_CHANGE}
_MOVE_RANGES = frozenset(
    _w(name)
    for name in ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")
)

# What old properties cannot hold, so it stays when they come back: old paragraph properties have
# no place for the run properties of the paragraph's mark nor for its section break, and old
# section properties none for the section's headers and footers.
_KEPT_FIRST = {_SECT_PR: frozenset({_w("headerReference"), _w("footerReference")})}
_KEPT_LAST = {_PPR: frozenset({_RPR, _SECT_PR})}
# Properties a file may leave out: when none are left, the element goes.
_OPTIONAL = frozenset({_RPR, _PPR, _TR_PR, _TC_PR, _w("tblPrEx")})

# Markup that may stand between two paragraphs as well as inside one: when the two are joined,
# it goes between their contents.
_MARKUP = frozenset(
    _w(name)
    for name in (
        "bookmarkStart",
        "bookmarkEnd",
        "commentRangeStart",
        "commentRangeEnd",
        "permStart",
        "permEnd",
        "proofErr",
        "customXmlInsRangeStart",
        "customXmlInsRangeEnd",
        "customXmlDelRangeStart",
        "customXmlDelRangeEnd",
        "customXmlMoveFromRangeStart",
        "customXmlMoveFromRangeEnd",
        "customXmlMoveToRangeStart",
        "customXmlMoveToRangeEnd",
    )
)


@dataclass(frozen=True)
class _Side:
    """The side of the changes that is kept: accepting keeps what they put in, rejecting the rest."""

    accept: bool
    gone: frozenset[str]  # the content, paragraph marks and rows that go
    gone_cell: str  # the mark of a cell that goes


_ACCEPT = _Side(accept=True, gone=frozenset({_DEL, _MOVE_FROM}), gone_cell=_CELL_DEL)
_REJECT = _Side(accept=False, gone=frozenset({_INS, _MOVE_TO}), gone_cell=_CELL_INS)


def accept_all(pkg: DocxPackage) -> int:
    """Accepts every tracked change of the text parts, leaving the final text.

    Returns the number of revision elements the text parts held: 0 when there were none.
    """
    return _resolve(pkg, _ACCEPT)


def reject_all(pkg: DocxPackage) -> int:
    """Rejects every tracked change of the text parts, leaving the text from before the changes.

    Returns the number of revision elements the text parts held: 0 when there were none.
    """
    return _resolve(pkg, _REJECT)


def _resolve(pkg: DocxPackage, side: _Side) -> int:
    roots = [pkg.xml(part) for part in pkg.TEXT_PARTS]
    count = sum(1 for root in roots for _revision in root.iter(*_REVISIONS))
    for root in roots:
        # Rows, cells and paragraph marks come before content, as their marks are w:ins and w:del
        # too. Old properties come back last, once the marks they may hold have gone.
        _drop_move_ranges(root)
        _resolve_rows(root, side)
        _resolve_cells(root, side)
        _resolve_paragraph_marks(root, side)
        _resolve_content(root, side)
        _resolve_property_changes(root, side)
        _resolve_deleted_text(root, side)
    return count


def _drop_move_ranges(root: etree._Element) -> None:
    """The range markers of a move hold nothing, and go on both sides."""
    _remove_all(list(root.iter(*_MOVE_RANGES)))


def _resolve_rows(root: etree._Element, side: _Side) -> None:
    """A row put in or taken out, as the marks in its own w:trPr say."""
    for props in list(root.iter(_TR_PR)):
        row = props.getparent()
        marks = [m for m in props if m.tag in _TRACKED]
        if not marks or not _is(row, _TR):
            continue
        if any(m.tag in side.gone for m in marks):
            _remove_row(row)
        else:
            _remove_all(marks)


def _resolve_cells(root: etree._Element, side: _Side) -> None:
    """A cell put in, taken out or merged, as the mark in its own w:tcPr says.

    A cell mark anywhere else, as in the old properties of a w:tcPrChange, only goes.
    """
    for mark in list(root.iter(*_CELL_MARKS)):
        props = mark.getparent()
        cell = None if props is None else props.getparent()
        if mark.tag == side.gone_cell and _is(props, _TC_PR) and _is(cell, _TC):
            _remove_cell(cell)
        else:
            _remove(mark)


def _resolve_paragraph_marks(root: etree._Element, side: _Side) -> None:
    """A paragraph mark put in or taken out, as the marks in the paragraph's w:pPr/w:rPr say.

    When the side kept has no such mark, the paragraph joins the next one; so a mark that was
    put in and then taken out goes on both sides.
    """
    for para in list(root.iter(_P)):
        marks = _mark_revisions(para)
        if not marks:
            continue
        if any(m.tag in side.gone for m in marks) and _join_with_next(para):
            continue
        _remove_all(marks)


def _resolve_content(root: etree._Element, side: _Side) -> None:
    """Content put in or taken out: kept without its wrapper, or removed with it.

    The marks of rows and paragraph marks are resolved by now. The marks left that hold no
    content (an inserted numbering, a mark inside old properties) go either way; those holding
    the properties of a math control character keep them or drop them as if they were content.
    """
    for change in list(root.iter(*_TRACKED)):
        if change.tag in side.gone:
            _remove(change)
        else:
            _unwrap(change)


def _resolve_property_changes(root: etree._Element, side: _Side) -> None:
    """Accepting, the records of property changes go; rejecting, their old properties come back.

    In document order: the change of a paragraph mark's properties, in the w:pPr/w:rPr, comes
    before the w:pPrChange at the end of the w:pPr, so when neither had properties before, the
    w:pPr goes with them.
    """
    for record in list(root.iter(*_PROPERTY_CHANGES, _NUMBERING_CHANGE)):
        if side.accept or record.tag == _NUMBERING_CHANGE:
            _remove(record)
        else:
            _restore(record)


def _resolve_deleted_text(root: etree._Element, side: _Side) -> None:
    """Deleted text left after the content: removed when accepting, kept as text when rejecting.

    Accepting, any left is outside a deletion, and the accepted view does not read it. Rejecting,
    the rejected view reads every one left: w:delText becomes w:t and w:delInstrText becomes
    w:instrText, their xml:space kept.
    """
    for text in list(root.iter(_DEL_TEXT, _DEL_INSTR_TEXT)):
        if side.accept:
            _remove(text)
        else:
            text.tag = _T if text.tag == _DEL_TEXT else _INSTR_TEXT


def _mark_revisions(para: etree._Element) -> list[etree._Element]:
    """The revisions of a paragraph's mark: w:ins, w:del, w:moveFrom, w:moveTo in w:pPr/w:rPr."""
    props = para.find(_PPR)
    mark = None if props is None else props.find(_RPR)
    return [] if mark is None else [m for m in mark if m.tag in _TRACKED]


def _join_with_next(para: etree._Element) -> bool:
    """Puts the content of ``para`` in front of the next paragraph's and takes ``para`` out.

    The next paragraph's properties win; markup between the two goes between their contents.
    Changes nothing and returns False when no paragraph follows in the same container.
    """
    between = []
    following = para.getnext()
    while following is not None and following.tag in _MARKUP:
        between.append(following)
        following = following.getnext()
    if not _is(following, _P):
        return False
    props = following.find(_PPR)
    at = 0 if props is None else following.index(props) + 1
    for offset, child in enumerate([c for c in para if c.tag != _PPR] + between):
        following.insert(at + offset, child)
    _remove(para)
    return True


def _restore(record: etree._Element) -> None:
    """Rejecting a change of properties: the element it sits in gets the old properties back.

    What the old properties cannot hold stays where it is (``_KEPT_FIRST``, ``_KEPT_LAST``). A
    record without old properties means there were none: the element goes, unless the file needs
    it (a table's w:tblPr, a section's w:sectPr) or something stayed in it.
    """
    current = record.getparent()
    if current is None:
        return
    old = record.find(current.tag)
    first = [c for c in current if c.tag in _KEPT_FIRST.get(current.tag, ())]
    last = [c for c in current if c.tag in _KEPT_LAST.get(current.tag, ())]
    restored = [] if old is None else list(old)
    for child in list(current):
        current.remove(child)
    current.extend(first + restored + last)
    if len(current) == 0 and current.tag in _OPTIONAL:
        _remove(current)


def _remove_row(row: etree._Element) -> None:
    table = next(row.iterancestors(_TBL), None)
    _remove(row)
    if table is not None and next(table.iter(_TR), None) is None:
        _remove(table)


def _remove_cell(cell: etree._Element) -> None:
    row = next(cell.iterancestors(_TR), None)
    _remove(cell)
    if row is not None and next(row.iter(_TC), None) is None:
        _remove_row(row)


def _unwrap(element: etree._Element) -> None:
    """Puts the children of ``element`` in its place."""
    for child in list(element):
        element.addprevious(child)
    _remove(element)


def _is(element: etree._Element | None, tag: str) -> bool:
    return element is not None and bool(element.tag == tag)


def _remove_all(elements: list[etree._Element]) -> None:
    for element in elements:
        _remove(element)


def _remove(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)
