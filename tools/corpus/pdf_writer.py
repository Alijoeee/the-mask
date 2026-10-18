"""Writing a contract as a PDF: with a text layer, scanned, or a mixture of the two.

A text PDF is laid out by reportlab in the built-in Helvetica family (no font files): a running
header ("Northwind / Thamesgate — Supply Agreement") and a footer ("Page 2 of 5 · Confidential") on
every page, then the blocks of the contract in reading order and, last, its footnotes gathered in a
"NOTES" block. No paragraph or table is split across pages, so a page break never cuts a value in
two. Text sizes follow the role: title 16 pt, headings 12 pt, body text 10 pt, so a reader can tell
the headings by their size.

A scanned PDF has no text at all: each page is typeset with Pillow (``ImageDraw``) into a picture
at 150 dpi and placed by reportlab. A mixed PDF is a text PDF in which one page is such a picture,
holding the blocks that page holds as text in the all-text PDF.

The scan is set in Bitstream Vera Sans, which ships inside reportlab (Pillow's own default font has
no €, £, ß, é or em dash). The files are the same every time: reportlab runs in ``invariant`` mode
(a fixed date and file identifier) and the pictures are written without time stamps.
"""

from __future__ import annotations

import io
import math
import re
import string
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from PIL import Image as Picture
from PIL import ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, PageBreak, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import Paragraph as PdfParagraph
from reportlab.platypus import Table as PdfTable

from tools.corpus.model import (
    Block,
    ContractSpec,
    FootnoteRef,
    Image,
    Inline,
    Paragraph,
    Span,
    Table,
)

# ---- page and looks --------------------------------------------------------------------------

PAGE_W, PAGE_H = A4  # in points
MARGIN = 2.5 * cm  # between the paper's edge and the text
EDGE = 1.25 * cm  # between the paper's edge and the header or footer
_FRAME_PADDING = 6  # points platypus keeps free inside the margins of its frame
_LEADING = 1.3  # the height of a line as a multiple of the font size
_RUNNING_SIZE = 8.5  # font size of the running header and the footer
_FOOTER = "Page {number} of {count} \N{MIDDLE DOT} Confidential"
_ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
_FACES = {False: "Helvetica", True: "Helvetica-Bold"}


@dataclass(frozen=True)
class _Look:
    """How a paragraph style looks in a PDF: font size and weight, and the space round it."""

    size: float  # in points
    bold: bool = False
    before: float = 0.0
    after: float = 6.0


_LOOKS = {
    "Title": _Look(16, bold=True, after=12),
    "Heading 1": _Look(12, bold=True, before=8),
    "Normal": _Look(10),
    "List Paragraph": _Look(10),
    "Footnote Text": _Look(10, after=3),
}
_CELL = _Look(9, after=0)  # the text in table cells


def _look(style: str) -> _Look:
    try:
        return _LOOKS[style]
    except KeyError:
        raise ValueError(f"No PDF look for the paragraph style {style!r}.") from None


# ---- what to write ---------------------------------------------------------------------------


def _shown(inlines: Iterable[Inline]) -> Iterator[Span | FootnoteRef]:
    """What a reader sees of ``inlines``: no hidden text and no tracked deletions.

    Raises ValueError for a character the built-in Helvetica cannot show (the narrow no-break
    space of some numbers, for one): reportlab would draw it as a black box.
    """
    for inline in inlines:
        if isinstance(inline, FootnoteRef):
            yield inline
        elif isinstance(inline, Span):
            if inline.hidden or inline.revision == "del":
                continue
            try:
                inline.text.encode("cp1252")  # WinAnsi, the encoding of the built-in fonts
            except UnicodeEncodeError as error:
                character = inline.text[error.start]
                raise ValueError(f"{character!r} is not in WinAnsi: {inline.text!r}") from error
            yield inline
        else:
            raise TypeError(f"A {type(inline).__name__} cannot be written in the body of a PDF.")


def _blocks(spec: ContractSpec) -> list[Block]:
    """The blocks of the PDF: those of the contract and, last, a "NOTES" block of its footnotes."""
    notes: list[Block] = []
    if spec.footnotes:
        notes.append(Paragraph((Span("NOTES"),), "Heading 1", "left", keep_with_next=True))
        for number, note in enumerate(spec.footnotes, start=1):
            notes.append(Paragraph((FootnoteRef(number), *note), "Footnote Text", "left"))
    return [*spec.body, *notes]


def _labels(blocks: Sequence[Block]) -> dict[int, str]:
    """The label "(a)", "(b)" ... of each paragraph of a lettered list, by index of the block."""
    counts: dict[int, int] = {}
    labels = {}
    for index, block in enumerate(blocks):
        if isinstance(block, Paragraph) and block.list_id is not None:
            counts[block.list_id] = counts.get(block.list_id, 0) + 1
            labels[index] = f"({string.ascii_lowercase[counts[block.list_id] - 1]})"
    return labels


def _running_header(spec: ContractSpec) -> str:
    """The header of every page: "<Short A> / <Short B> — <Title>"."""
    paragraphs = ([s for s in _shown(p.inlines) if isinstance(s, Span)] for p in spec.header)
    return " ".join("".join(span.text for span in spans) for spans in paragraphs)


# ---- text pages ------------------------------------------------------------------------------


class _Drawn:
    """A flowable that remembers which block of the contract it draws."""

    block = -1


class _Whole(_Drawn, PdfParagraph):
    """A paragraph that never splits across pages."""

    def split(self, availWidth: float, availHeight: float) -> list[Flowable]:
        return []


class _WholeTable(_Drawn, PdfTable):
    """A table that never splits across pages."""

    def split(self, availWidth: float, availHeight: float) -> list[Flowable]:
        return []


class _Picture(_Drawn, PdfImage):
    """A picture on a page of text."""


def _markup(inlines: Iterable[Inline]) -> str:
    """``inlines`` as reportlab paragraph markup."""
    parts = []
    for shown in _shown(inlines):
        if isinstance(shown, FootnoteRef):
            parts.append(f"<super>{shown.number}</super>")
            continue
        text = escape(shown.text)
        if shown.bold:
            text = f"<b>{text}</b>"
        if shown.italic:
            text = f"<i>{text}</i>"
        parts.append(text)
    return "".join(parts)


def _paragraph(block: Paragraph, label: str | None) -> _Whole:
    look = _look(block.style)
    style = ParagraphStyle(
        block.style,
        fontName=_FACES[look.bold],
        fontSize=look.size,
        leading=look.size * _LEADING,
        alignment=_ALIGN[block.align],
        leftIndent=block.indent * cm,
        # An item of a lettered list hangs its label in the margin; the first line of a numbered
        # clause starts out in the margin.
        firstLineIndent=0 if label else -block.hanging * cm,
        bulletIndent=(block.indent - block.hanging) * cm,
        bulletFontName="Helvetica",
        bulletFontSize=look.size,
        spaceBefore=look.before,
        spaceAfter=look.after,
        keepWithNext=int(block.keep_with_next),
    )
    return _Whole(_markup(block.inlines), style, bulletText=label)


def _table(block: Table) -> _WholeTable:
    """The table with ruled cells and a shaded header row, narrowed to fit between the margins."""
    fit = min(1.0, (PAGE_W - 2 * MARGIN) / (sum(block.widths) * cm))
    style = ParagraphStyle(
        "Cell", fontName="Helvetica", fontSize=_CELL.size, leading=_CELL.size * _LEADING
    )
    rows = [[PdfParagraph(_markup(cell), style) for cell in row] for row in block.rows]
    table = _WholeTable(rows, colWidths=[w * cm * fit for w in block.widths], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    table.spaceAfter = 6
    return table


def _picture(block: Image) -> _Picture:
    width, height = Picture.open(io.BytesIO(block.png)).size
    shown = block.width * cm
    place = {"center": "CENTER", "right": "RIGHT"}.get(block.align, "LEFT")
    picture = _Picture(io.BytesIO(block.png), shown, shown * height / width, hAlign=place)
    picture.spaceAfter = 6
    picture.keepWithNext = 1  # a logo stays with the title, a signature with the line it signs
    return picture


def _flowables(blocks: Sequence[Block], indexes: Iterable[int]) -> list[Flowable]:
    """The flowables of the blocks at ``indexes``, each noting the index of its block."""
    labels = _labels(blocks)
    flowables: list[Flowable] = []
    for index in indexes:
        block = blocks[index]
        flowable: _Whole | _WholeTable | _Picture
        if isinstance(block, Paragraph):
            flowable = _paragraph(block, labels.get(index))
        elif isinstance(block, Table):
            flowable = _table(block)
        elif isinstance(block, Image):
            flowable = _picture(block)
        else:
            raise TypeError(f"A {type(block).__name__} cannot be written to a PDF.")
        flowable.block = index
        flowables.append(flowable)
    return flowables


class _Canvas(Canvas):
    """A canvas that writes "Page N of M" in the footer of every page once M is known."""

    def __init__(self, *args: Any, pictures: frozenset[int] = frozenset(), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pictures = pictures  # these pages hold their footer in the picture
        self._states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        count = len(self._states)
        for number, state in enumerate(self._states, start=1):
            self.__dict__.update(state)
            if number not in self._pictures:
                self.setFont("Helvetica", _RUNNING_SIZE)
                self.drawCentredString(PAGE_W / 2, EDGE, _FOOTER.format(number=number, count=count))
            super().showPage()
        super().save()


class _Document(SimpleDocTemplate):
    """A document that notes which blocks it puts on each page."""

    def __init__(self, target: io.BytesIO, title: str) -> None:
        side = MARGIN - _FRAME_PADDING
        super().__init__(
            target,
            pagesize=A4,
            title=title,
            invariant=1,
            leftMargin=side,
            rightMargin=side,
            topMargin=side,
            bottomMargin=side,
        )
        self.placed: dict[int, list[int]] = {}

    def afterFlowable(self, flowable: Flowable) -> None:
        if isinstance(flowable, _Drawn):
            self.placed.setdefault(self.page, []).append(flowable.block)

    def afterPage(self) -> None:
        self.placed.setdefault(self.page, [])


def _build(
    title: str, header: str, chunks: Sequence[list[Flowable]], pictures: dict[int, bytes]
) -> tuple[bytes, dict[int, list[int]]]:
    """The PDF of ``chunks`` and the indexes of the blocks it puts on each page.

    Each chunk starts a new page. An empty chunk is a page that is a picture: ``pictures`` has the
    PNG of each such page by its page number.
    """
    story: list[Flowable] = []
    for chunk in chunks:
        if story:
            story.append(PageBreak())
        story.extend(chunk or [Spacer(1, 1)])

    def decorate(canvas: Canvas, document: _Document) -> None:
        if document.page in pictures:
            png = ImageReader(io.BytesIO(pictures[document.page]))
            canvas.drawImage(png, 0, 0, PAGE_W, PAGE_H)
        else:
            canvas.setFont("Helvetica", _RUNNING_SIZE)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - EDGE - _RUNNING_SIZE, header)

    def canvas_maker(*args: Any, **kwargs: Any) -> _Canvas:
        return _Canvas(*args, pictures=frozenset(pictures), **kwargs)

    out = io.BytesIO()
    document = _Document(out, title)
    document.build(story, onFirstPage=decorate, onLaterPages=decorate, canvasmaker=canvas_maker)
    return out.getvalue(), document.placed


# ---- scanned pages ---------------------------------------------------------------------------

_DPI = 150
_PX = _DPI / 72  # pixels per point
_CM = _DPI / 2.54  # pixels per centimetre
_PAGE = (round(PAGE_W * _PX), round(PAGE_H * _PX))
_TEXT = _PAGE[0] - 2 * MARGIN * _PX  # the width of the text, in pixels
_FONTS = Path(reportlab.__file__).parent / "fonts"
_VERA = {
    (False, False): "Vera.ttf",
    (True, False): "VeraBd.ttf",
    (False, True): "VeraIt.ttf",
    (True, True): "VeraBI.ttf",
}
_MARK = 0.7  # a footnote mark is this fraction of the size of the text, raised by 0.4 of that size
_SHADE = 225  # the grey of the header row of a table; text is 0 on a ground of 255

_Frag = tuple[str, bool, bool, bool]  # text, bold, italic, a footnote mark
_Word = list[_Frag]
_Line = tuple[list[tuple[float, _Word]], float]  # words with their x, and the width of the line


@dataclass(frozen=True)
class _Text:
    x: float
    y: float  # of the baseline
    text: str
    font: ImageFont.FreeTypeFont


@dataclass(frozen=True)
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float
    fill: int | None


@dataclass(frozen=True)
class _Paste:
    x: float
    y: float
    picture: Picture.Image


_Op = _Text | _Box | _Paste


@dataclass
class _Plan:
    """A block laid out in pixels: what to draw (from y = 0), its height and the space round it."""

    ops: list[_Op]
    height: float
    before: float
    after: float
    keep: bool  # stays on the page of the plan after it


@cache
def _font(bold: bool, italic: bool, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONTS / _VERA[bold, italic]), size)


def _words(inlines: Iterable[Inline], bold: bool) -> list[_Word]:
    """``inlines`` as words: stretches of text between spaces, in fragments of one style each."""
    words: list[_Word] = [[]]
    for shown in _shown(inlines):
        if isinstance(shown, FootnoteRef):
            words[-1].append((str(shown.number), bold, False, True))
            continue
        for n, part in enumerate(re.split(r"[ \t\r\n]+", shown.text)):
            if n and words[-1]:
                words.append([])
            if part:
                # Vera has no glyph for the no-break space: it stays in its word, as a space.
                text = part.replace("\N{NO-BREAK SPACE}", " ")
                words[-1].append((text, bold or shown.bold, shown.italic, False))
    return [word for word in words if word]


def _face(frag: _Frag, size: float) -> tuple[str, ImageFont.FreeTypeFont]:
    text, bold, italic, mark = frag
    return text, _font(bold, italic, size * (_MARK if mark else 1))


def _baseline(size: float, bold: bool) -> float:
    """The baseline of a line of text of ``size`` pixels, from the top of the line."""
    ascent, descent = _font(bold, False, size).getmetrics()
    return (size * _LEADING - ascent - descent) / 2 + ascent


def _wrap(
    words: Sequence[_Word], size: float, bold: bool, first: float, width: float
) -> list[_Line]:
    """``words`` in lines: the first ``first`` pixels wide at most, the others ``width``."""
    space = _font(bold, False, size).getlength(" ")
    lines: list[_Line] = []
    line: list[tuple[float, _Word]] = []
    end, limit = 0.0, first
    for word in words:
        length = sum(font.getlength(text) for text, font in (_face(frag, size) for frag in word))
        x = end + space if line else 0.0
        if line and x + length > limit:
            lines.append((line, end))
            line, x, limit = [], 0.0, width
        line.append((x, word))
        end = x + length
    return [*lines, (line, end)] if line else lines


def _typeset(
    words: Sequence[_Word],
    size: float,
    bold: bool,
    start: float,
    left: float,
    right: float,
    align: str,
) -> tuple[list[_Text], int]:
    """``words`` set between ``left`` and ``right`` pixels (the first line from ``start``).

    Returns the text as drawing ops, with y = 0 at the top of the first line, and the number of
    lines. Justified text is set left aligned.
    """
    ops = []
    lines = _wrap(words, size, bold, right - start, right - left)
    for n, (line, width) in enumerate(lines):
        x0 = start if n == 0 else left
        shift = {"center": (right - x0 - width) / 2, "right": right - x0 - width}.get(align, 0.0)
        baseline = n * size * _LEADING + _baseline(size, bold)
        for offset, word in line:
            x = x0 + shift + offset
            for frag in word:
                text, font = _face(frag, size)
                ops.append(_Text(x, baseline - (0.4 * size if frag[3] else 0.0), text, font))
                x += font.getlength(text)
    return ops, len(lines)


def _paragraph_plan(block: Paragraph, label: str | None, scale: float) -> _Plan:
    look = _look(block.style)
    size = look.size * _PX * scale
    left = block.indent * _CM
    start = left if label else left - block.hanging * _CM
    words = _words(block.inlines, look.bold)
    ops, lines = _typeset(words, size, look.bold, start, left, _TEXT, block.align)
    plan = _Plan(
        [*ops],
        lines * size * _LEADING,
        look.before * _PX * scale,
        look.after * _PX * scale,
        block.keep_with_next,
    )
    if label:
        x, font = (block.indent - block.hanging) * _CM, _font(False, False, size)
        plan.ops.append(_Text(x, _baseline(size, False), label, font))
    return plan


def _table_plan(block: Table, scale: float) -> _Plan:
    """The table as boxes and text, each row as high as its tallest cell.

    Vera is wider than Helvetica, so if every cell fits on one line between the margins each
    column is made as wide as its longest cell, and no amount is broken over two lines.
    """
    size = _CELL.size * _PX * scale
    side, top, bottom = (pt * _PX * scale for pt in (6, 3, 4))  # the paddings of the text PDF
    words = [[_words(cell, False) for cell in row] for row in block.rows]
    target = min(_TEXT, sum(block.widths) * _CM)  # the width of the table, as in the text PDF
    columns = [w * target / sum(block.widths) for w in block.widths]
    one_line = [
        max(
            (_wrap(cell, size, False, math.inf, math.inf)[0][1] if cell else 0.0) for cell in column
        )
        + 2 * side
        + 1
        for column in zip(*words, strict=True)
    ]
    if sum(one_line) <= target:
        spare = target - sum(one_line)
        columns = [wide + spare * w / target for wide, w in zip(one_line, columns, strict=True)]
    ops: list[_Op] = []
    y = 0.0
    for number, row in enumerate(words):
        x, cells = 0.0, []
        for cell, wide in zip(row, columns, strict=True):
            text, lines = _typeset(cell, size, False, side, side, wide - side, "left")
            cells.append((x, wide, text, lines))
            x += wide
        height = max(1, *(lines for *_, lines in cells)) * size * _LEADING + top + bottom
        for x, wide, text, _ in cells:
            ops.append(_Box(x, y, x + wide, y + height, _SHADE if number == 0 else None))
            ops.extend(replace(t, x=t.x + x, y=t.y + y + top) for t in text)
        y += height
    return _Plan(ops, y, 0.0, 6 * _PX * scale, keep=False)


def _picture_plan(block: Image, scale: float) -> _Plan:
    picture = Picture.open(io.BytesIO(block.png)).convert("L")
    width = round(block.width * _CM * scale)
    height = round(width * picture.height / picture.width)
    x = {"center": (_TEXT - width) / 2, "right": _TEXT - width}.get(block.align, 0.0)
    resized = picture.resize((width, height), Picture.Resampling.LANCZOS)
    return _Plan([_Paste(x, 0.0, resized)], height, 0.0, 6 * _PX * scale, keep=True)


def _plans(blocks: Sequence[Block], indexes: Iterable[int], scale: float) -> list[_Plan]:
    labels = _labels(blocks)
    plans = []
    for index in indexes:
        block = blocks[index]
        if isinstance(block, Paragraph):
            plans.append(_paragraph_plan(block, labels.get(index), scale))
        elif isinstance(block, Table):
            plans.append(_table_plan(block, scale))
        elif isinstance(block, Image):
            plans.append(_picture_plan(block, scale))
        else:
            raise TypeError(f"A {type(block).__name__} cannot be written to a PDF.")
    return plans


def _fit(
    unit: Sequence[_Plan], y: float, after: float, top: bool, limit: float
) -> list[float] | None:
    """The y of each plan of ``unit`` set from ``y``, below something with ``after`` space under it.

    Returns None if the unit would run past ``limit``. At the ``top`` of a page nothing comes
    before the unit, so there is no space before it either.
    """
    ys = []
    for n, plan in enumerate(unit):
        if n or not top:
            y += max(after, plan.before)
        ys.append(y)
        y += plan.height
        after = plan.after
    return ys if y <= limit else None


def _paginate(plans: Sequence[_Plan], limit: float) -> list[list[tuple[_Plan, float]]]:
    """``plans`` on pages ``limit`` pixels high, each with its y.

    A plan that is to be kept with the next one starts a unit, which goes on one page whole.
    """
    pages: list[list[tuple[_Plan, float]]] = [[]]
    y, after, start = 0.0, 0.0, 0
    while start < len(plans):
        end = start
        while plans[end].keep and end + 1 < len(plans):
            end += 1
        unit, start = plans[start : end + 1], end + 1
        ys = _fit(unit, y, after, not pages[-1], limit)
        if ys is None and pages[-1]:
            pages.append([])
            ys = _fit(unit, 0.0, 0.0, True, limit)
        if ys is None:
            raise ValueError("A block is taller than a page.")
        pages[-1].extend(zip(unit, ys, strict=True))
        y, after = ys[-1] + unit[-1].height, unit[-1].after
    return pages


def _render(placed: Sequence[tuple[_Plan, float]], number: int, count: int, header: str) -> bytes:
    """One page as a PNG: grey on white, with the running header and the footer."""
    page = Picture.new("L", _PAGE, 255)
    draw = ImageDraw.Draw(page)
    margin = MARGIN * _PX
    for plan, y in placed:
        top = margin + y
        for op in plan.ops:
            if isinstance(op, _Text):
                draw.text((margin + op.x, top + op.y), op.text, font=op.font, fill=0, anchor="ls")
            elif isinstance(op, _Box):
                box = (margin + op.x0, top + op.y0, margin + op.x1, top + op.y1)
                draw.rectangle(box, fill=op.fill, outline=0)
            else:
                page.paste(op.picture, (round(margin + op.x), round(top + op.y)))
    small = _font(False, False, _RUNNING_SIZE * _PX)
    right, base = _PAGE[0] - margin, (EDGE + _RUNNING_SIZE) * _PX
    draw.text((right, base), header, font=small, fill=0, anchor="rs")
    footer = _FOOTER.format(number=number, count=count)
    draw.text((_PAGE[0] / 2, (PAGE_H - EDGE) * _PX), footer, font=small, fill=0, anchor="ms")
    out = io.BytesIO()
    page.save(out, "PNG", dpi=(_DPI, _DPI))  # no time stamp: the same page is the same bytes
    return out.getvalue()


def _scan(
    blocks: Sequence[Block],
    indexes: Sequence[int],
    header: str,
    *,
    first: int = 1,
    count: int | None = None,
    one_page: bool = False,
) -> list[bytes]:
    """The blocks at ``indexes`` as PNG pages, numbered from ``first`` out of ``count`` pages.

    With ``one_page`` the text is made smaller, a little at a time, until it fits on one page.
    """
    scale = 1.0
    while True:
        pages = _paginate(_plans(blocks, indexes, scale), _PAGE[1] - 2 * MARGIN * _PX)
        if len(pages) == 1 or not one_page:
            break
        scale -= 0.02
        if scale < 0.5:
            raise ValueError("The blocks do not fit on one page at any reasonable size.")
    total = first + len(pages) - 1 if count is None else count
    return [_render(page, first + n, total, header) for n, page in enumerate(pages)]


# ---- the three kinds of PDF ------------------------------------------------------------------


def write_pdf(spec: ContractSpec, path: Path) -> list[int]:
    """Write ``spec`` as a PDF with a text layer; returns its picture pages (none)."""
    blocks = _blocks(spec)
    story = _flowables(blocks, range(len(blocks)))
    data, _ = _build(spec.title, _running_header(spec), [story], {})
    path.write_bytes(data)
    return []


def write_scanned_pdf(spec: ContractSpec, path: Path) -> list[int]:
    """Write ``spec`` as a PDF of pictures only, with no text layer; returns all its pages."""
    blocks, header = _blocks(spec), _running_header(spec)
    scans = _scan(blocks, range(len(blocks)), header)
    pictures = dict(enumerate(scans, start=1))
    data, _ = _build(spec.title, header, [[] for _ in scans], pictures)
    path.write_bytes(data)
    return list(pictures)


def write_mixed_pdf(spec: ContractSpec, path: Path, image_page: int = 2) -> list[int]:
    """Write ``spec`` as a PDF with a text layer except on page ``image_page``, a picture.

    That page holds the blocks the all-text PDF has on it, set smaller if they do not fit
    otherwise. Returns ``[image_page]``.
    """
    blocks, header = _blocks(spec), _running_header(spec)
    everything = _flowables(blocks, range(len(blocks)))
    _, placed = _build(spec.title, header, [everything], {})
    count = len(placed)
    if not 1 <= image_page <= count:
        raise ValueError(f"There is no page {image_page}: the PDF has {count} pages.")
    if [i for n in range(1, count + 1) for i in placed[n]] != list(range(len(blocks))):
        raise ValueError("The all-text PDF does not hold every block of the contract once.")
    (scan,) = _scan(
        blocks, placed[image_page], header, first=image_page, count=count, one_page=True
    )
    before = [i for n in range(1, image_page) for i in placed[n]]
    after = [i for n in range(image_page + 1, count + 1) for i in placed[n]]
    chunks = [_flowables(blocks, before)] if before else []
    chunks.append([])
    chunks.extend([_flowables(blocks, after)] if after else [])
    data, again = _build(spec.title, header, chunks, {image_page: scan})
    if again != {**placed, image_page: []}:
        raise ValueError("The text pages of the mixed PDF are not those of the all-text PDF.")
    path.write_bytes(data)
    return [image_page]
