"""Reading a text PDF as blocks: its headings, paragraphs and tables, in reading order.

What is read. pdfplumber reads each page, and of it only the text that a reader of the PDF sees:

- Text in a layer (optional content) that the PDF's default view hides is left out. A second pass
  over the page with pdfminer follows every marked-content sequence and form XObject, resolves
  each /OC to its layer or membership dictionary in the resources of the stream being drawn, and
  marks each character drawn inside hidden content. Text in layers that are shown stays. The
  report names the layers off by default whose content was left out. A PDF whose layers cannot be
  read that way is refused with ``UnsupportedFileError``.
- Text set at an angle is left out: a character pdfplumber does not count as upright, or whose
  baseline runs more than 10 degrees off the horizontal (pdfplumber counts text at 45 degrees as
  upright), such as a diagonal "DRAFT" watermark or a reference running up the margin. Read with
  the rest, its letters would land inside the lines of the body text. A page whose text is all
  rotated, including a page turned with /Rotate so that its text runs up or down, therefore reads
  as having no text: such pages are not supported.
- A character drawn twice in the same place, as some PDFs fake bold type, is read once.
- A glyph of a font without a map to Unicode, which pdfplumber reads as "(cid:78)", is left out,
  as are the characters a Word file cannot hold (NUL and the other control characters).

Nothing else of the PDF is read: not its properties, annotations, form fields or attachments. The
report's notes say, page by page, where unreadable characters or rotated text were left out.

Pages left out. A page whose text is mostly glyph codes has no real text, and is left out. So is a
page with a picture whose text, once the running headers and footers (below) are taken out, all
lies in its top and bottom bands: a scanned page, whatever is stamped on it (page or Bates
numbers). Both are listed in the report as image-only pages. A PDF in which no page keeps
anything to read is refused with ``ScannedPdfError``. A PDF that cannot be opened is refused
too: with ``ProtectedFileError`` when it asks for a password (or is encrypted in a way pdfminer
cannot undo), and with ``UnsupportedFileError`` when it is not a PDF or is damaged or cut short.
A PDF encrypted with an owner's password only opens without one, so it is read.

Blocks. On a page, each table pdfplumber finds becomes a table block where it stands, and the
characters in its cells are left out of the paragraphs, so nothing is read twice; text inside the
outline of a table but in none of its cells stays with the paragraphs. The other characters are
read as lines from top to bottom (``extract_text_lines``, with enough tolerance that a raised
footnote mark stays in its line). Consecutive lines of one size make one paragraph while the white
space between them stays small: at most twice the median gap between the lines of the page, and
under 0.6 times their font size (6 pt in 10 pt text, which is also the limit on a page with too
few lines for a median). The median alone would not do: on a page of short paragraphs most gaps
are gaps between paragraphs. The lines of a paragraph, or of a table cell, are joined with a
space, but a line that ends in a hyphen right after a word goes on without one, so that "anne-"
and "marie.dupont@north-wind.example", or "NW-" and "2026-0417", come together whole. A line
larger than the median size of the page's text is a heading when it is set in 12 pt or more, or
in bold. A page set in columns is read line by line across the columns: such pages are not
supported.

Running headers and footers: a line in the top or bottom 12 % of its page whose text, normalised,
is found there on at least 60 % of the pages with text, and on two pages or more, is a running
line. A line shaped like a heading (bold, or larger than the page's text) is compared whole, so
that "SCHEDULE 1" and "SCHEDULE 2" stay two lines while a running title in bold repeats. Any
other line is compared without its digits when it numbers its page: when it has the word "page"
("Page 3 of 24"), is a number of one to four digits (a bare "3"), or holds the page's own number
on its own ("Pagina 3 van 24" or "Supply Agreement – 3" on page 3). The first occurrence of a
running line is kept, among the first blocks of the document, and all the others are removed:
the first ``len(report.repeated_lines_removed)`` blocks are the running lines, one each.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from itertools import groupby, pairwise
from operator import itemgetter
from pathlib import Path
from typing import Any, Literal, cast

import pdfplumber
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar
from pdfminer.pdfdocument import PDFDocument, PDFEncryptionError
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager, PDFStackT
from pdfminer.pdftypes import PDFObjRef, resolve1, stream_value
from pdfminer.psexceptions import PSException
from pdfminer.psparser import LIT, PSLiteral, literal_name
from pdfminer.utils import Matrix, Rect, decode_text
from pdfplumber.page import Page
from pdfplumber.utils.clustering import cluster_objects
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from themask.errors import MaskError, ProtectedFileError, ScannedPdfError, UnsupportedFileError
from themask.textnorm import normalize

SCANNED_PDF_MESSAGE = "This PDF is a scan without selectable text. The MASK cannot read it yet."
PROTECTED_PDF_MESSAGE = "This PDF is protected or encrypted. Please provide an unprotected copy."
NOT_A_PDF_MESSAGE = (
    "This is not a readable PDF. It may be damaged or incomplete. Please provide another copy."
)
LAYERS_MESSAGE = (
    "This PDF uses layers that The MASK cannot separate from the visible text. Please flatten it"
    " (for example print it to a new PDF) and try again."
)

BlockKind = Literal["heading", "paragraph", "table"]

# What is read.
_SLANT = math.tan(math.radians(10))  # the most a baseline may run off the horizontal
_GLYPH_CODE = re.compile(r"\(cid:\d+\)")  # what pdfplumber reads for a glyph with no Unicode
_COPY_TOLERANCE = 1.0  # points: a character this close to the same character is a copy of it
_SAME_GLYPH = itemgetter("upright", "text", "fontname", "size")
_OPTIONAL = "OC"  # the marked-content tag of optional content
_OFF = LIT("OFF")
_LAYER, _MEMBERSHIP = LIT("OCG"), LIT("OCMD")
_CELL_BAND = 10.0  # points: table cells are looked up by bands of the page this high
# What a Word file cannot hold: control characters but tab, line feed and carriage return; lone
# surrogates; U+FFFE and U+FFFF.
_NOT_IN_WORD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

# Running headers and footers.
_BAND = 0.12  # the top and the bottom 12 % of the height of the page
_RUNNING_PERCENT = 60  # on at least this share of the pages with text ...
_RUNNING_PAGES = 2  # ... and on at least two pages: a line on one page repeats nothing
_DIGITS = re.compile(r"\d")
_PAGE_WORD = re.compile(r"\bpage\b", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"[\W_]*(?:\d[\W_]*){1,4}")  # all of a line: "3", "- 3 -", "3/24"

# Lines, paragraphs and headings.
# How far above or below its line a character may stand, as a raised footnote mark does: half the
# page's text size, but never 5 pt or more, so that the lines of small print under a large title
# stay apart (the corpus sets its marks 3.4 pt above their 10 pt lines).
_LINE_TOLERANCE = 0.5
_MAX_LINE_TOLERANCE = 5.0
_PARAGRAPH_GAP = 0.6  # × the font size: white space this high, or higher, parts two paragraphs
_LINE_GAPS = 2  # so does white space higher than this many median line gaps of the page
_GAPS_FOR_A_MEDIAN = 3
_SAME_SIZE = 0.5  # points: the most two lines of one paragraph differ in size
_HEADING_SIZE = 12.0  # points: a line larger than the page's text and this large is a heading
_WORD_HYPHEN = re.compile(r"\S-$")  # a line that ends in a hyphen right after a word


@dataclass
class Block:
    """A heading, a paragraph or a table of a PDF, and the page it is on (counted from 1).

    ``text`` is the text of a heading or a paragraph, its lines joined, or of a table, a row to a
    line with a tab between the cells, whose text ``rows`` holds. ``size`` is the font size of a
    heading or a paragraph in points, and 0 for a table.
    """

    kind: BlockKind
    text: str
    rows: list[list[str]] | None
    page: int
    size: float = 0.0


@dataclass
class PdfReport:
    """What reading a PDF left out.

    ``image_only_pages`` are the pages, counted from 1, with nothing to read: a picture, or text
    that is mostly glyph codes. ``repeated_lines_removed`` has each running header or footer
    once, in the words of the place where it is first found, which is the one kept.
    ``hidden_layers`` names the layers off by default whose content was left out. ``notes`` says,
    in plain words and page by page, what other text was left out: "page 3: 4 unreadable
    characters left out", "page 5: rotated text left out".
    """

    pages: int
    image_only_pages: list[int]
    repeated_lines_removed: list[str]
    hidden_layers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class _Line:
    text: str
    top: float
    bottom: float
    x0: float
    size: float  # the size of most of its characters, in points
    bold: bool  # most of its characters are bold


@dataclass
class _Table:
    top: float
    x0: float
    rows: list[list[str]]


@dataclass
class _Page:
    number: int
    height: float
    text_size: float  # the median size of the characters read outside tables
    items: list[_Line | _Table]  # in reading order
    pictures: bool  # it shows a picture
    codes: bool  # its text is mostly glyph codes: it has no real text
    notes: list[str]  # what else was left out of it, in plain words
    layers: set[str]  # the hidden layers whose text was left out of it


class _LayersUnreadable(Exception):
    """The layers of a PDF cannot be read, so its hidden text cannot be told from the rest."""


def extract_blocks(pdf: Path) -> tuple[list[Block], PdfReport]:
    """The headings, paragraphs and tables of ``pdf`` in reading order, and what was left out.

    The running headers and footers come first, once each; then the blocks of each page, in page
    order. Raises ScannedPdfError when no page has anything to read, ProtectedFileError when the
    PDF asks for a password and UnsupportedFileError when it cannot be read, or its layers cannot.
    """
    try:
        with pdfplumber.open(pdf) as document:
            off = _layers_off(document.doc)
            pages = [_read_and_close(page, off) for page in document.pages]
    except _LayersUnreadable as error:
        raise UnsupportedFileError(LAYERS_MESSAGE) from error
    except (PdfminerException, MalformedPDFException, PSException) as error:
        raise _refusal(error) from error
    running = _take_running_lines([page for page in pages if page.items])
    for page in pages:
        if page.pictures and all(_stamped(item, page) for item in page.items):
            page.items = []  # a scanned page: what is stamped on it is no content
    if not any(page.items for page in pages):
        raise ScannedPdfError(SCANNED_PDF_MESSAGE)
    blocks = running + [block for page in pages for block in _blocks(page)]
    hidden = set().union(*(page.layers for page in pages))
    report = PdfReport(
        pages=len(pages),
        image_only_pages=[p.number for p in pages if not p.items and (p.pictures or p.codes)],
        repeated_lines_removed=[block.text for block in running],
        hidden_layers=list(dict.fromkeys(name for name in off.values() if name in hidden)),
        notes=[note for page in pages for note in page.notes],
    )
    return blocks, report


def _refusal(error: Exception) -> MaskError:
    """What to tell the owner about a PDF pdfplumber could not open or read.

    pdfplumber wraps what pdfminer raises in a PdfminerException that holds it.
    """
    causes = (error, *error.args, error.__cause__, error.__context__)
    if any(isinstance(cause, PDFEncryptionError) for cause in causes):
        return ProtectedFileError(PROTECTED_PDF_MESSAGE)
    return UnsupportedFileError(NOT_A_PDF_MESSAGE)


# ---- one page --------------------------------------------------------------------------------


def _read_and_close(page: Page, off: dict[int, str]) -> _Page:
    """Read ``page``, then let pdfplumber drop what it keeps of it, so memory stays small."""
    try:
        return _read(page, off)
    finally:
        page.close()


def _read(page: Page, off: dict[int, str]) -> _Page:
    """The lines and tables of ``page`` in reading order: top to bottom, then left to right.

    ``off`` has the layers the PDF's default view turns off, by object number.
    """
    chars = page.chars
    hidden, layers = _hidden_chars(page, off) if off else (set(), set())
    left_out = hidden | _copies(chars)
    rotated = sum(1 for char in chars if id(char) not in left_out and not _level(char))
    shown = page.filter(_shown(left_out))
    pictures = bool(shown.images)
    codes = sum(1 for char in shown.chars if _GLYPH_CODE.fullmatch(char["text"]))
    letters = sum(1 for char in shown.chars if not char["text"].isspace()) - codes
    notes = [f"page {page.page_number}: rotated text left out"] if rotated else []
    number, height = page.page_number, float(page.height)
    if codes > letters:  # mostly glyph codes: no real text
        return _Page(number, height, 0.0, [], pictures, True, notes, layers)
    if codes:
        unreadable = "1 unreadable character" if codes == 1 else f"{codes} unreadable characters"
        notes.insert(0, f"page {page.page_number}: {unreadable} left out")
    level = shown.filter(_not_a_glyph_code) if codes else shown
    tables = level.find_tables()
    cells = [cell for table in tables for cell in table.cells]
    outside = level.filter(_outside(cells)) if cells else level
    sizes = [char["size"] for char in outside.chars if not char["text"].isspace()]
    text_size = statistics.median(sizes) if sizes else 0.0
    items: list[_Line | _Table] = []
    if sizes:
        tolerance = min(_LINE_TOLERANCE * text_size, _MAX_LINE_TOLERANCE)
        lines = outside.extract_text_lines(y_tolerance=tolerance)
        items.extend(line for line in map(_line, lines) if line.text)
    for table in tables:
        rows = [[_cell(cell) for cell in row] for row in table.extract()]
        if any(any(row) for row in rows):
            items.append(_Table(table.bbox[1], table.bbox[0], rows))
    items.sort(key=lambda item: (item.top, item.x0))
    return _Page(number, height, text_size, items, pictures, False, notes, layers)


def _copies(chars: list[dict[str, Any]]) -> set[int]:
    """The ids of the characters that repeat one drawn within 1 pt of them, as a PDF draws a word
    twice to fake bold type: of each such group, the one nearest the top left is kept.

    This is the rule of pdfplumber's ``dedupe_chars``, which also puts the characters it keeps
    back in their order by looking each one up in the list: slow on a full page.
    """
    copies: set[int] = set()
    for _, same in groupby(sorted(chars, key=_SAME_GLYPH), key=_SAME_GLYPH):
        for row in cluster_objects(list(same), itemgetter("doctop"), _COPY_TOLERANCE):
            for spot in cluster_objects(row, itemgetter("x0"), _COPY_TOLERANCE):
                first = min(spot, key=itemgetter("doctop", "x0"))
                copies.update(id(char) for char in spot if char is not first)
    return copies


def _level(char: dict[str, Any]) -> bool:
    """Whether ``char`` is set upright on a baseline within 10 degrees of the horizontal."""
    a, b = char["matrix"][0], char["matrix"][1]  # where the baseline runs: (a, b)
    return bool(char["upright"]) and a > 0 and abs(b) <= _SLANT * a


def _shown(left_out: set[int]) -> Callable[[dict[str, Any]], bool]:
    """A test that keeps every object but the characters in ``left_out`` (by id) and those set
    at an angle."""

    def test(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        return id(obj) not in left_out and _level(obj)

    return test


def _not_a_glyph_code(obj: dict[str, Any]) -> bool:
    return obj.get("object_type") != "char" or not _GLYPH_CODE.fullmatch(obj["text"])


def _outside(
    cells: Sequence[tuple[float, float, float, float]],
) -> Callable[[dict[str, Any]], bool]:
    """A test that keeps every object but the characters whose middle is inside one of ``cells``.

    The cells are found by the band of the page a character is in, so that a table of hundreds of
    cells costs no more than a few.
    """
    bands: dict[int, list[tuple[float, float, float, float]]] = {}
    for cell in cells:
        for band in range(int(cell[1] // _CELL_BAND), int(cell[3] // _CELL_BAND) + 1):
            bands.setdefault(band, []).append(cell)

    def test(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        x, y = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
        near = bands.get(int(y // _CELL_BAND), ())
        return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in near)

    return test


def _line(line: dict[str, Any]) -> _Line:
    chars = [char for char in line["chars"] if not char["text"].isspace()]
    sizes = Counter(round(char["size"], 1) for char in chars)
    size = max(sizes, key=lambda s: (sizes[s], s)) if sizes else 0.0
    bold = 2 * sum("bold" in char["fontname"].lower() for char in chars) > len(chars)
    text = _NOT_IN_WORD.sub("", line["text"]).strip()
    return _Line(text, float(line["top"]), float(line["bottom"]), float(line["x0"]), size, bold)


def _cell(text: str | None) -> str:
    """The text of a table cell on one line: the lines of a cell are one paragraph of it."""
    lines = (line.strip() for line in (text or "").split("\n"))
    return _NOT_IN_WORD.sub("", _join(lines)).strip()


def _join(lines: Iterable[str]) -> str:
    """Lines as one text: a space between two lines, but none after a hyphen that ends a word."""
    parts: list[str] = []
    for line in filter(None, lines):
        if parts and not _WORD_HYPHEN.search(parts[-1]):
            parts.append(" ")
        parts.append(line)
    return "".join(parts)


# ---- layers ----------------------------------------------------------------------------------


def _layers_off(document: PDFDocument) -> dict[int, str]:
    """The layers (optional content groups) the PDF's default view turns off: their names, by
    object number. Raises _LayersUnreadable when the PDF has layers that cannot be read."""
    if "OCProperties" not in document.catalog:
        return {}
    properties = resolve1(document.catalog["OCProperties"])
    config = resolve1(properties.get("D")) if isinstance(properties, dict) else None
    if not isinstance(config, dict):
        raise _LayersUnreadable
    off = _references(config.get("OFF"))
    if resolve1(config.get("BaseState")) is _OFF:  # every layer is off but those turned on
        on = {ref.objid for ref in _references(config.get("ON"))}
        off += [ref for ref in _references(properties.get("OCGs")) if ref.objid not in on]
    names: dict[int, str] = {}
    for ref in off:
        layer = resolve1(ref)
        if not isinstance(layer, dict):
            raise _LayersUnreadable
        name = resolve1(layer.get("Name"))
        names.setdefault(ref.objid, decode_text(name) if isinstance(name, bytes) else "")
    return names


def _references(value: object) -> list[PDFObjRef]:
    """The object references in the array ``value``: none when it is missing."""
    items = resolve1(value)
    if items is None:
        return []
    if not isinstance(items, list) or not all(isinstance(item, PDFObjRef) for item in items):
        raise _LayersUnreadable
    return items


_Hiding = tuple[bool, frozenset[str]]  # hidden by default, and the layers off by default it uses
_SHOWN: _Hiding = (False, frozenset())


def _hiding(content: object, off: dict[int, str]) -> _Hiding:
    """Whether optional content marked with ``content`` (a layer or a membership dictionary,
    or a reference to one) is hidden by default, and the layers off by default it depends on."""
    if isinstance(content, PDFObjRef):
        target = resolve1(content)
        if isinstance(target, dict) and target.get("Type") is _LAYER:
            return (True, frozenset([off[content.objid]])) if content.objid in off else _SHOWN
        content = target
    if not isinstance(content, dict):
        raise _LayersUnreadable
    kind = content.get("Type")
    if kind is _LAYER:  # a layer written in place, not in the PDF's list: never turned off
        return _SHOWN
    if kind is not _MEMBERSHIP:
        raise _LayersUnreadable
    if content.get("VE") is not None:
        shown, used = _expression(content["VE"], off)
        return not shown, used
    groups = resolve1(content.get("OCGs"))
    refs = [groups] if isinstance(groups, PDFObjRef) else _references(content.get("OCGs"))
    if not refs:
        return _SHOWN  # a membership of no layer does not hide anything
    states = [ref.objid not in off for ref in refs]  # on by default
    used = frozenset(off[ref.objid] for ref in refs if ref.objid in off)
    policy = literal_name(resolve1(content.get("P", LIT("AnyOn"))))
    visible = {
        "AnyOn": any(states),
        "AllOn": all(states),
        "AnyOff": not all(states),
        "AllOff": not any(states),
    }.get(policy)
    if visible is None:
        raise _LayersUnreadable
    return not visible, used


def _expression(expression: object, off: dict[int, str]) -> tuple[bool, frozenset[str]]:
    """Whether a visibility expression (/VE) shows its content by default, and its layers off."""
    if isinstance(expression, PDFObjRef) and isinstance(resolve1(expression), dict):
        return (
            (False, frozenset([off[expression.objid]]))
            if expression.objid in off
            else (
                True,
                frozenset(),
            )
        )
    expression = resolve1(expression)
    if not isinstance(expression, list) or not expression:
        raise _LayersUnreadable
    operator, operands = literal_name(expression[0]), expression[1:]
    values = [_expression(operand, off) for operand in operands]
    used = frozenset().union(*(layers for _, layers in values))
    shown = [value for value, _ in values]
    if operator == "Not" and len(shown) == 1:
        return not shown[0], used
    if operator in ("And", "Or") and shown:
        return (all(shown) if operator == "And" else any(shown)), used
    raise _LayersUnreadable


class _LayerDevice(PDFPageAggregator):
    """A device that keeps the marked-content sequences and form XObjects being drawn on a stack,
    and notes for each character drawn whether hidden optional content holds it.

    The interpreter resolves what each /OC names before it begins a sequence, and tells the
    device a form's /OC before it begins the figure, because only the interpreter knows the
    resources of the stream being drawn.
    """

    def __init__(self, rsrcmgr: PDFResourceManager, off: dict[int, str]) -> None:
        super().__init__(rsrcmgr)
        self.off = off
        self.tags: list[_Hiding] = []  # each open marked-content sequence
        self.figures: list[tuple[_Hiding, int]] = []  # each open form, with the depth of tags
        self.form_content: object = None  # the /OC of the form about to be drawn
        self.drawn: list[tuple[str, float, _Hiding]] = []  # each character: text, y0, hiding

    def begin_tag(self, tag: PSLiteral, props: PDFStackT | None = None) -> None:
        self.tags.append(_hiding(props, self.off) if tag.name == _OPTIONAL else _SHOWN)

    def end_tag(self) -> None:
        if self.tags:
            self.tags.pop()

    def begin_figure(self, name: str, bbox: Rect, matrix: Matrix) -> None:
        super().begin_figure(name, bbox, matrix)
        content, self.form_content = self.form_content, None
        hiding = _hiding(content, self.off) if content is not None else _SHOWN
        self.figures.append((hiding, len(self.tags)))

    def end_figure(self, name: str) -> None:
        if self.figures:
            _, depth = self.figures.pop()
            del self.tags[depth:]  # a form closes what it opened
        super().end_figure(name)

    def render_char(self, *args: Any, **kwargs: Any) -> float:
        advance = super().render_char(*args, **kwargs)
        char = cast(LTChar, self.cur_item._objs[-1])
        open_ = [*self.tags, *(hiding for hiding, _ in self.figures)]
        hidden = any(is_hidden for is_hidden, _ in open_)
        used = frozenset().union(*(layers for is_hidden, layers in open_ if is_hidden))
        self.drawn.append((char.get_text(), char.y0, (hidden, used)))
        return advance


class _LayerInterpreter(PDFPageInterpreter):
    """An interpreter that resolves the /OC of each marked-content sequence and form XObject in
    the resources of the stream it draws, for its ``_LayerDevice``."""

    def do_BDC(self, tag: PDFStackT, props: PDFStackT) -> None:
        if isinstance(tag, PSLiteral) and tag.name == _OPTIONAL:
            props = cast(PDFStackT, self._optional_content(props))
        super().do_BDC(tag, props)

    def do_Do(self, xobjid_arg: PDFStackT) -> None:
        device = cast(_LayerDevice, self.device)
        xobj = self.xobjmap.get(literal_name(xobjid_arg))
        device.form_content = stream_value(xobj).get("OC") if xobj is not None else None
        try:
            super().do_Do(xobjid_arg)
        finally:
            device.form_content = None

    def _optional_content(self, props: PDFStackT) -> object:
        """What an /OC sequence names: a property list in place, or one in the resources."""
        if isinstance(props, dict):
            return props
        properties = resolve1(self.resources.get("Properties")) if self.resources else None
        if not isinstance(props, PSLiteral) or not isinstance(properties, dict):
            raise _LayersUnreadable
        content = properties.get(props.name)
        if content is None:
            raise _LayersUnreadable
        return content


def _hidden_chars(page: Page, off: dict[int, str]) -> tuple[set[int], set[str]]:
    """The ids of the characters of ``page`` in optional content hidden by default, and the names
    of the layers they are hidden by.

    pdfplumber lists the characters of a page in the order they are drawn, as the device notes
    them, so the two are paired one by one; any difference between them refuses the PDF.
    """
    device = _LayerDevice(page.pdf.rsrcmgr, off)
    try:
        _LayerInterpreter(page.pdf.rsrcmgr, device).process_page(page.page_obj)
    except _LayersUnreadable:
        raise
    except Exception as error:  # whatever stops this pass, the layers stay unread
        raise _LayersUnreadable from error
    chars = page.chars
    if len(chars) != len(device.drawn):
        raise _LayersUnreadable
    hidden: set[int] = set()
    layers: set[str] = set()
    for char, (text, y0, (is_hidden, used)) in zip(chars, device.drawn, strict=True):
        if char["text"] != text or abs(char["y0"] - y0) > 0.01:
            raise _LayersUnreadable
        if is_hidden:
            hidden.add(id(char))
            layers |= used
    return hidden, layers


# ---- running headers and footers -------------------------------------------------------------


def _take_running_lines(pages: list[_Page]) -> list[Block]:
    """Remove the running lines from ``pages``; returns each once, as a block, as first found."""
    found: dict[str, set[int]] = {}
    for page in pages:
        for line in _band_lines(page):
            found.setdefault(_running_key(line, page), set()).add(page.number)
    running = {
        key
        for key, numbers in found.items()
        if len(numbers) >= _RUNNING_PAGES and 100 * len(numbers) >= _RUNNING_PERCENT * len(pages)
    }
    kept: dict[str, Block] = {}
    for page in pages:
        taken = [line for line in _band_lines(page) if _running_key(line, page) in running]
        for line in taken:
            kind: BlockKind = "heading" if _is_heading(line, page) else "paragraph"
            block = Block(kind, line.text, None, page.number, line.size)
            kept.setdefault(_running_key(line, page), block)
        gone = {id(line) for line in taken}
        page.items = [item for item in page.items if id(item) not in gone]
    return list(kept.values())


def _band_lines(page: _Page) -> Iterator[_Line]:
    """The lines of ``page`` in its top or bottom 12 %, where running lines are."""
    for item in page.items:
        if isinstance(item, _Line) and _in_band(item, page):
            yield item


def _in_band(line: _Line, page: _Page) -> bool:
    return line.bottom <= _BAND * page.height or line.top >= (1 - _BAND) * page.height


def _stamped(item: _Line | _Table, page: _Page) -> bool:
    """Whether ``item`` could be stamped on a scanned page: a line in its top or bottom band."""
    return isinstance(item, _Line) and _in_band(item, page)


def _running_key(line: _Line, page: _Page) -> str:
    """What the copies of a running line have in common (see the module notes)."""
    key = normalize(line.text)
    shaped_like_a_heading = line.bold or line.size > page.text_size
    if not shaped_like_a_heading and _numbers_the_page(line.text, page.number):
        return _DIGITS.sub("", key)
    return key


def _numbers_the_page(text: str, number: int) -> bool:
    """Whether ``text`` numbers page ``number``: it has the word "page", is a number of one to
    four digits, or holds ``number`` itself, not as part of a longer number."""
    own = re.compile(rf"(?<![\d.,]){number}(?!\d|[.,]\d)")
    return bool(_PAGE_WORD.search(text) or _PAGE_NUMBER.fullmatch(text) or own.search(text))


# ---- paragraphs and headings -----------------------------------------------------------------


def _blocks(page: _Page) -> Iterator[Block]:
    """The blocks of ``page``: its tables, and its lines grouped into paragraphs and headings."""
    lines = [item for item in page.items if isinstance(item, _Line)]
    gaps = [gap for gap in (b.top - a.bottom for a, b in pairwise(lines)) if gap > 0]
    line_gap = statistics.median(gaps) if len(gaps) >= _GAPS_FOR_A_MEDIAN else None
    group: list[_Line] = []
    for item in page.items:
        if isinstance(item, _Line) and group and _same_block(group[-1], item, page, line_gap):
            group.append(item)
            continue
        if group:
            yield _text_block(group, page)
            group = []
        if isinstance(item, _Table):
            text = "\n".join("\t".join(row) for row in item.rows)
            yield Block("table", text, item.rows, page.number)
        else:
            group = [item]
    if group:
        yield _text_block(group, page)


def _same_block(above: _Line, line: _Line, page: _Page, line_gap: float | None) -> bool:
    """Whether ``line`` goes on from the line ``above`` it, in one paragraph or heading."""
    if _is_heading(above, page) != _is_heading(line, page):
        return False
    if abs(above.size - line.size) > _SAME_SIZE:
        return False
    gap = line.top - above.bottom
    if gap >= _PARAGRAPH_GAP * line.size:
        return False
    return line_gap is None or gap <= _LINE_GAPS * line_gap


def _is_heading(line: _Line, page: _Page) -> bool:
    """Larger than the text of the page, and set in 12 pt or more or in bold."""
    return line.size > page.text_size and (line.size >= _HEADING_SIZE or line.bold)


def _text_block(lines: list[_Line], page: _Page) -> Block:
    kind: BlockKind = "heading" if _is_heading(lines[0], page) else "paragraph"
    return Block(kind, _join(line.text for line in lines), None, page.number, lines[0].size)
