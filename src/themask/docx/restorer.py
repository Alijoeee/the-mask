"""Replacing stretches of a paragraph's text in the Word XML, however Word split them into runs.

The masker uses this to put placeholders in place of confidential values, and the restore step to
put the real values back in place of the placeholders. Positions are those of the text map:
``reader.paragraph_nodes`` gives a paragraph's text and the ``w:t`` and ``w:instrText`` nodes that
hold it. The new text goes into the first node that holds part of the stretch, so it takes that
run's formatting (its ``w:rPr``). The rest of the stretch is cut out of the nodes after it, and a
node left empty is deleted, with its run when nothing but formatting is left in the run. Tabs,
breaks and hyphens, which the text map reads as characters without a node of their own, are
deleted when they lie inside the stretch. A tab or line break in the new text can be written the
way Word writes one, as a ``w:tab`` or ``w:br`` of the run (``breaks``), which the restore needs
for a value that has one.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from lxml import etree

from themask.docx.package import NS
from themask.docx.reader import _CHARACTERS, View, paragraph_nodes

_R = f"{{{NS['w']}}}r"
_RPR = f"{{{NS['w']}}}rPr"
_T = f"{{{NS['w']}}}t"
# How Word writes a tab and a line break in a run: as elements of their own, not as characters.
_MARKS = {"\t": f"{{{NS['w']}}}tab", "\n": f"{{{NS['w']}}}br"}
_MARK = re.compile("([\t\n])")
_XML_SPACE = f"{{{NS['xml']}}}space"
# The spaces XML drops at either end of a w:t's text unless the w:t says xml:space="preserve".
_XML_WHITESPACE = " \t\r\n"


@dataclass(frozen=True)
class _Piece:
    """An element of a paragraph that holds its text ``[start:end]``.

    ``node`` is True for a node of the text map (``w:t``, ``w:instrText``), which can take new
    text, and False for a tab, break or hyphen, which can only be deleted.
    """

    elem: etree._Element
    start: int
    end: int
    node: bool

    def within(self, start: int, end: int) -> bool:
        """Whether the piece is part of the stretch ``[start:end]``.

        A piece that holds characters must share at least one with it. A piece that holds none
        (an empty ``w:t``, a soft hyphen) must lie inside it, not at either end.
        """
        if self.start < self.end:
            return self.start < end and start < self.end
        return start < self.start < end


def replace_in_paragraph(
    p: etree._Element, view: View, replacements: list[tuple[int, int, str]], *, breaks: bool = False
) -> int:
    """Replaces stretches of paragraph ``p``'s text, as ``view`` reads it; returns how many.

    Each replacement ``(start, end, text)`` puts ``text`` in place of the paragraph's
    ``[start:end]``, the positions counted as ``paragraph_nodes(p, view)`` counts them. The
    replacements must be in order and must not overlap, though two may touch. Text outside the
    view (deleted text in the accepted view) is never changed. A stretch that holds no character
    of a ``w:t`` or ``w:instrText`` (an empty one, a tab alone) is skipped and not counted: there
    is no node to put its text in. With ``breaks``, each "\t" and "\n" of a new text becomes a
    ``w:tab`` or ``w:br`` in the run, and the text after it a node of its own after that.

    Raises ValueError for replacements out of order, overlapping or outside the text, before
    anything changes.
    """
    text, nodes = paragraph_nodes(p, view)
    _check(replacements, len(text))
    pieces = [_Piece(n.elem, n.start, n.end, node=True) for n in nodes] + _characters(p, view)
    edited: dict[etree._Element, None] = {}  # the nodes whose text changed, in order
    doomed: list[etree._Element] = []
    made = 0
    # From the last replacement to the first: the text of a node before the stretch being
    # replaced is then still the text the map read, so the earlier positions still hold.
    for start, end, new in reversed(replacements):
        if start == end:
            continue
        covered = [piece for piece in pieces if piece.within(start, end)]
        holders = [piece for piece in covered if piece.node and piece.start < piece.end]
        if not holders:
            continue
        first = min(holders, key=lambda piece: piece.start)
        for piece in covered:
            if not piece.node:
                doomed.append(piece.elem)
                continue
            old = piece.elem.text or ""
            cut_from = max(start - piece.start, 0)
            cut_to = min(end, piece.end) - piece.start
            if piece is first and breaks and _MARK.search(new):
                _write_with_marks(piece.elem, old[:cut_from], new, old[cut_to:], edited)
            else:
                piece.elem.text = old[:cut_from] + (new if piece is first else "") + old[cut_to:]
            edited[piece.elem] = None
        made += 1
    for node in edited:
        if node.text:
            _keep_spaces(node)
        else:
            doomed.append(node)
    for element in doomed:
        _delete(element)
    return made


def _check(replacements: list[tuple[int, int, str]], length: int) -> None:
    previous_end = 0
    for start, end, _text in replacements:
        if start < previous_end or end < start or end > length:
            raise ValueError(
                "Replacements must be in order, must not overlap and must lie within the "
                f"paragraph's {length} characters; {start}-{end} does not."
            )
        previous_end = end


def _characters(p: etree._Element, view: View) -> list[_Piece]:
    """The tabs, breaks and hyphens the text map reads in ``p``, at their places in its text.

    The reader gives them no node, so their places are found by asking the reader itself: in a
    copy of the paragraph each of them becomes a ``w:t`` holding the same character. A ``w:t``
    is run content like they are, so the reader reads it in exactly the places it would read
    them, and at the same position. Which elements count as characters, and which character
    each stands for, is the reader's own table (``_CHARACTERS``), so the two never disagree.
    """
    originals = list(p.iter(*_CHARACTERS))
    if not originals:
        return []
    twin = copy.deepcopy(p)
    original_of: dict[etree._Element, etree._Element] = {}
    for original, character in zip(originals, list(twin.iter(*_CHARACTERS)), strict=True):
        stand_in = etree.Element(_T)
        stand_in.text = _CHARACTERS[character.tag]
        character.getparent().replace(character, stand_in)
        original_of[stand_in] = original
    _text, nodes = paragraph_nodes(twin, view)
    return [
        _Piece(original_of[n.elem], n.start, n.end, node=False)
        for n in nodes
        if n.elem in original_of
    ]


def _write_with_marks(
    node: etree._Element, head: str, new: str, tail: str, edited: dict[etree._Element, None]
) -> None:
    """Writes ``head + new + tail`` into ``node``, each tab or line break of ``new`` as Word does.

    The text up to the first mark stays in ``node``. Each mark becomes a ``w:tab`` or ``w:br``
    after it in the run, followed by a node of ``node``'s kind with the text up to the next mark;
    ``tail`` ends the last one. The new nodes join ``edited``, so that an empty one is deleted
    and one with spaces at an end keeps them. The nodes after ``node`` are not part of the text
    map's positions, so the replacements still to come, all before this one, are not moved.
    """
    pieces = _MARK.split(new)
    node.text = head + pieces[0]
    last = node
    for mark, text in zip(pieces[1::2], pieces[2::2], strict=True):
        element = etree.Element(_MARKS[mark])
        last.addnext(element)
        last = etree.Element(node.tag)
        last.text = text
        element.addnext(last)
        edited[last] = None
    last.text = (last.text or "") + tail


def _keep_spaces(node: etree._Element) -> None:
    """Marks a node whose text starts or ends with a space, so that Word keeps the space."""
    text = node.text
    if text[0] in _XML_WHITESPACE or text[-1] in _XML_WHITESPACE:
        node.set(_XML_SPACE, "preserve")


def _delete(element: etree._Element) -> None:
    """Takes ``element`` out of its run, and the run out too when it holds nothing else."""
    parent = element.getparent()
    parent.remove(element)
    if parent.tag == _R and all(child.tag == _RPR for child in parent):
        parent.getparent().remove(parent)
