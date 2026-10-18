"""Reading a text PDF as blocks: its headings, paragraphs and tables, in reading order.

pdfplumber reads each page. A page whose ``extract_text()`` is empty but which holds a picture is
an image-only page: it is left out and listed in the report. A PDF in which no page has any text
(every page a picture, or blank) is refused with ``ScannedPdfError``.

On a page with text, each table pdfplumber finds becomes a table block where it stands, and the
characters inside the table are left out of the paragraphs, so nothing is read twice. The other
characters are read as lines from top to bottom (``extract_text_lines``, with enough tolerance
that a raised footnote mark stays in its line). Consecutive lines of one size make one paragraph
while the white space between them stays small: at most twice the median gap between the lines
of the page, and under 0.6 times their font size (6 pt in 10 pt text, which is also the limit on
a page with too few lines for a median). The median alone would not do: on a page of short
paragraphs most gaps are gaps between paragraphs. A line set in 12 pt or more, or in bold in a
size larger than the median size of the page's text, is a heading.

Running headers and footers: a line in the top or bottom 12 % of its page whose text, normalised
and without its digits (so that "Page 3 of 24" and a bare "3" repeat as well), is found there on at
least 60 % of the pages with text, and on two pages or more, is a running line. Its first
occurrence is kept, among the first blocks of the document, and all the others are removed: the
first ``len(report.repeated_lines_removed)`` blocks are the running lines, one each.

Only the text of the pages is read: nothing of the PDF's properties, annotations, form fields or
attachments. Characters that a Word file cannot hold (NUL and the other control characters) are
left out.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import pdfplumber
from pdfplumber.page import Page

from themask.errors import ScannedPdfError
from themask.textnorm import normalize

SCANNED_PDF_MESSAGE = "This PDF is a scan without selectable text. The MASK cannot read it yet."

BlockKind = Literal["heading", "paragraph", "table"]

# Running headers and footers.
_BAND = 0.12  # the top and the bottom 12 % of the height of the page
_RUNNING_PERCENT = 60  # on at least this share of the pages with text ...
_RUNNING_PAGES = 2  # ... and on at least two pages: a line on one page repeats nothing
_DIGITS = re.compile(r"\d")

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
_HEADING_SIZE = 12.0  # points: a line this large is a heading, whatever its weight

# What a Word file cannot hold: control characters but tab, line feed and carriage return; lone
# surrogates; U+FFFE and U+FFFF.
_NOT_IN_WORD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


@dataclass
class Block:
    """A heading, a paragraph or a table of a PDF, and the page it is on (counted from 1).

    ``text`` is the text of a heading or a paragraph, its lines joined by spaces, or of a table,
    a row to a line with a tab between the cells, whose text ``rows`` holds. ``size`` is the font
    size of a heading or a paragraph in points, and 0 for a table.
    """

    kind: BlockKind
    text: str
    rows: list[list[str]] | None
    page: int
    size: float = 0.0


@dataclass
class PdfReport:
    """What reading a PDF left out.

    ``image_only_pages`` are the pages, counted from 1, that are only a picture.
    ``repeated_lines_removed`` has each running header or footer once, in the words of the place
    where it is first found, which is the one kept.
    """

    pages: int
    image_only_pages: list[int]
    repeated_lines_removed: list[str]


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
    text_size: float  # the median size of the characters outside tables
    items: list[_Line | _Table]  # in reading order
    image_only: bool


def extract_blocks(pdf: Path) -> tuple[list[Block], PdfReport]:
    """The headings, paragraphs and tables of ``pdf`` in reading order, and what was left out.

    The running headers and footers come first, once each; then the blocks of each page with
    text, in page order. Raises ScannedPdfError when no page has any text.
    """
    with pdfplumber.open(pdf) as document:
        pages = [_read(page) for page in document.pages]
    with_text = [page for page in pages if page.items]
    if not with_text:
        raise ScannedPdfError(SCANNED_PDF_MESSAGE)
    running = _take_running_lines(with_text)
    blocks = running + [block for page in with_text for block in _blocks(page)]
    report = PdfReport(
        pages=len(pages),
        image_only_pages=[page.number for page in pages if page.image_only],
        repeated_lines_removed=[block.text for block in running],
    )
    return blocks, report


# ---- one page --------------------------------------------------------------------------------


def _read(page: Page) -> _Page:
    """The lines and tables of ``page`` in reading order: top to bottom, then left to right."""
    tables = page.find_tables()
    boxes = [table.bbox for table in tables]
    outside = page.filter(_outside(boxes)) if boxes else page
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
    image_only = not items and bool(page.images) and not (page.extract_text() or "").strip()
    return _Page(page.page_number, float(page.height), text_size, items, image_only)


def _outside(boxes: list[tuple[float, float, float, float]]) -> Callable[[dict[str, Any]], bool]:
    """A test that keeps every object but the characters whose middle is inside one of ``boxes``."""

    def test(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        x, y = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in boxes)

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
    return _NOT_IN_WORD.sub("", (text or "").replace("\n", " ")).strip()


# ---- running headers and footers -------------------------------------------------------------


def _take_running_lines(pages: list[_Page]) -> list[Block]:
    """Remove the running lines from ``pages``; returns each one once, as a block, as first found."""
    found: dict[str, set[int]] = {}
    for page in pages:
        for line in _band_lines(page):
            found.setdefault(_running_key(line.text), set()).add(page.number)
    running = {
        key
        for key, numbers in found.items()
        if len(numbers) >= _RUNNING_PAGES and 100 * len(numbers) >= _RUNNING_PERCENT * len(pages)
    }
    kept: dict[str, Block] = {}
    for page in pages:
        taken = [line for line in _band_lines(page) if _running_key(line.text) in running]
        for line in taken:
            kind: BlockKind = "heading" if _is_heading(line, page) else "paragraph"
            kept.setdefault(
                _running_key(line.text), Block(kind, line.text, None, page.number, line.size)
            )
        gone = {id(line) for line in taken}
        page.items = [item for item in page.items if id(item) not in gone]
    return list(kept.values())


def _band_lines(page: _Page) -> Iterator[_Line]:
    """The lines of ``page`` in its top or bottom 12 %, where running headers and footers are."""
    for item in page.items:
        if isinstance(item, _Line) and (
            item.bottom <= _BAND * page.height or item.top >= (1 - _BAND) * page.height
        ):
            yield item


def _running_key(text: str) -> str:
    """What two copies of a running line have in common: "Page 2 of 5" is "Page 3 of 5"."""
    return _DIGITS.sub("", normalize(text))


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
    return line.size >= _HEADING_SIZE or (line.bold and line.size > page.text_size)


def _text_block(lines: list[_Line], page: _Page) -> Block:
    kind: BlockKind = "heading" if _is_heading(lines[0], page) else "paragraph"
    return Block(kind, " ".join(line.text for line in lines), None, page.number, lines[0].size)
