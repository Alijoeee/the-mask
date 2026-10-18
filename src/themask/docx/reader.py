"""The text map: a Word file's text as one string, and where every character of it lives.

``extract_text`` joins the text of every paragraph of the text parts (the document, then the
headers, footers, footnotes and endnotes) with "\\n", and keeps a ``Segment`` for each paragraph
telling where its text begins and ends in that string. ``paragraph_nodes`` gives one paragraph's
text together with its ``TextNode``s, the ``w:t`` and ``w:instrText`` elements that hold it, so a
later step can change exactly the characters it found, however Word split them across runs.

There are two views of the same file. "accepted" is the text with every tracked change accepted:
insertions and moves in their new place are read, deletions and moves from their old place are
not. "rejected" is the text with every change rejected: the other way round. Hidden text is read
like any other text (the cleaner removes it later). A text box is a paragraph of its own, read
where it sits in the document; Word stores each text box twice, as DrawingML in ``mc:Choice`` and
as VML in ``mc:Fallback``, and only ``mc:Choice`` is read (ruling R16: the cleaner deletes every
fallback, so no unmasked copy is left behind).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from lxml import etree

from themask.docx.package import NS, DocxPackage

View = Literal["accepted", "rejected"]
NodeKind = Literal["t", "instr"]

_VIEWS: tuple[View, ...] = ("accepted", "rejected")


def _w(name: str) -> str:
    return f"{{{NS['w']}}}{name}"


_P = _w("p")
_R = _w("r")
_T = _w("t")
_INSTR_TEXT = _w("instrText")
_DEL_TEXT = _w("delText")
_DEL_INSTR_TEXT = _w("delInstrText")
_ALTERNATE_CONTENT = f"{{{NS['mc']}}}AlternateContent"
_CHOICE = f"{{{NS['mc']}}}Choice"
_FALLBACK = f"{{{NS['mc']}}}Fallback"
_COMMENT_REFERENCE = _w("commentReference")

# What some run content stands for in the text; it has no node, as there is nothing to change.
_CHARACTERS = {
    _w("tab"): "\t",
    _w("br"): "\n",
    _w("cr"): "\n",
    _w("noBreakHyphen"): "\N{NON-BREAKING HYPHEN}",
    _w("softHyphen"): "",  # only shown where Word breaks the line
}
# Never entered while walking a paragraph: a paragraph nested in it (in a text box or a table of
# a text box) is a segment of its own; properties hold no text, and the revision marks in them
# (an inserted paragraph mark, a formatting change) change none; a fallback copy is not read.
_NO_TEXT = frozenset(
    {
        _P,
        _w("pPr"),
        _w("rPr"),
        _w("sdtPr"),
        _w("sdtEndPr"),
        _w("customXmlPr"),
        _w("smartTagPr"),
        _FALLBACK,
    }
)
# Read only in one view: what a tracked change put in, and what it took out.
_INSERTED = frozenset({_w("ins"), _w("moveTo")})
_DELETED = frozenset({_w("del"), _w("moveFrom")})

_REVISIONS = tuple(
    _w(name)
    for name in (
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "trPrChange",
        "tcPrChange",
        "numberingChange",
    )
)


@dataclass(frozen=True)
class TextNode:
    """A text element of a paragraph: its text is the paragraph's ``text[start:end]``.

    ``kind`` is "t" for ``w:t`` (and ``w:delText`` in the rejected view) and "instr" for a field
    instruction, ``w:instrText`` (and ``w:delInstrText`` in the rejected view).
    """

    elem: etree._Element
    start: int
    end: int
    kind: NodeKind


@dataclass(frozen=True)
class Segment:
    """One paragraph of ``part``: its text is ``DocText.text[start:end]``."""

    part: str
    para: etree._Element
    start: int
    end: int


@dataclass
class DocText:
    """The text of a Word file in one view, and the paragraph every stretch of it comes from."""

    text: str
    segments: list[Segment]


def paragraph_nodes(p: etree._Element, view: View) -> tuple[str, list[TextNode]]:
    """The text of paragraph ``p`` in ``view``, and the nodes that hold it, in document order.

    Every run of the paragraph is read, also inside hyperlinks, content controls, smart tags,
    simple fields, custom XML and tracked changes (those of the view). A tab stands for "\\t", a
    line or page break for "\\n", a non-breaking hyphen for itself and a soft hyphen for nothing.
    Paragraphs nested in this one, in a text box, are not part of its text.
    """
    _check(view)
    walk = _Walk(view)
    walk.container(p)
    return "".join(walk.pieces), walk.nodes


def extract_text(pkg: DocxPackage, view: View = "accepted") -> DocText:
    """The text of every paragraph of the package's text parts, joined with "\\n".

    The parts come in the order of ``pkg.TEXT_PARTS`` and the paragraphs of each in document
    order, a text box's after the paragraph it sits in and a table's cell by cell. Every
    paragraph has a segment, an empty one too, so each offset in the text maps back to it.
    """
    _check(view)
    texts: list[str] = []
    segments: list[Segment] = []
    start = 0
    for part in pkg.TEXT_PARTS:
        for para in _paragraphs(pkg.xml(part)):
            text, _nodes = paragraph_nodes(para, view)
            segments.append(Segment(part, para, start, start + len(text)))
            texts.append(text)
            start += len(text) + 1
    return DocText("\n".join(texts), segments)


def has_revisions(pkg: DocxPackage) -> bool:
    """Whether a text part holds a tracked change of the text or of its formatting."""
    return any(_contains(pkg.xml(part), _REVISIONS) for part in pkg.TEXT_PARTS)


def has_comments(pkg: DocxPackage) -> bool:
    """Whether the file has a comments part, or a text part refers to a comment."""
    return "word/comments.xml" in pkg.names() or any(
        _contains(pkg.xml(part), (_COMMENT_REFERENCE,)) for part in pkg.TEXT_PARTS
    )


def _check(view: str) -> None:
    if view not in _VIEWS:
        raise ValueError(f"Unknown view {view!r}: it is 'accepted' or 'rejected'.")


def _paragraphs(root: etree._Element) -> Iterator[etree._Element]:
    """Every paragraph of a part in document order, nested ones too, none of a fallback copy."""
    for para in root.iter(_P):
        if next(para.iterancestors(_FALLBACK), None) is None:
            yield para


def _contains(root: etree._Element, tags: tuple[str, ...]) -> bool:
    return next(root.iter(*tags), None) is not None


class _Walk:
    """Collects the text and nodes of one paragraph in one view."""

    def __init__(self, view: View) -> None:
        self.view = view
        self.pieces: list[str] = []
        self.nodes: list[TextNode] = []
        self.length = 0

    def container(self, element: etree._Element) -> None:
        """Walks the runs in ``element``, however deep, skipping ``_NO_TEXT`` and the other view."""
        for child in element:
            tag = child.tag
            if tag == _R:
                self.run(child)
            elif tag in _NO_TEXT or not isinstance(tag, str):  # str: not a comment or a PI
                continue
            elif tag in _INSERTED:
                if self.view == "accepted":
                    self.container(child)
            elif tag in _DELETED:
                if self.view == "rejected":
                    self.container(child)
            else:
                self.container(child)

    def run(self, run: etree._Element) -> None:
        for child in run:
            tag = child.tag
            if tag == _T:
                self.node(child, "t")
            elif tag == _INSTR_TEXT:
                self.node(child, "instr")
            elif tag == _DEL_TEXT:
                if self.view == "rejected":
                    self.node(child, "t")
            elif tag == _DEL_INSTR_TEXT:
                if self.view == "rejected":
                    self.node(child, "instr")
            elif tag in _CHARACTERS:
                self.add(_CHARACTERS[tag])
            elif tag == _ALTERNATE_CONTENT:
                for choice in child.iterchildren(_CHOICE):  # the choice stands in for run content
                    self.run(choice)
            elif tag in _NO_TEXT or not isinstance(tag, str):
                continue
            else:
                # Anything else (a drawing, a picture, an object, a phonetic guide) is walked
                # like a container: runs inside it are read, while the paragraphs of a text box
                # in it are skipped, being segments of their own.
                self.container(child)

    def node(self, element: etree._Element, kind: NodeKind) -> None:
        text = element.text or ""
        self.nodes.append(TextNode(element, self.length, self.length + len(text), kind))
        self.add(text)

    def add(self, text: str) -> None:
        self.pieces.append(text)
        self.length += len(text)
