"""Small PDF files for the tests of the PDF reader, for the cases the corpus does not have.

``make_pdf`` writes A4 pages from a few ``Line``s each, every line placed by its baseline and its
left edge, in Helvetica (Helvetica-Bold when ``bold``) or, when ``embedded``, in Bitstream Vera Sans
embedded as a TrueType font. An embedded font comes with a map from its codes to Unicode, which is
how a real PDF can hand a reader characters such as NUL, which a Word file cannot hold. A ``Rule``
draws a straight line, as the ruling of a table does. A page can also be a ``Picture``: a picture
filling the page, as a scanned page is, with lines drawn over it, as a page number stamped on a
scan; ``PICTURE`` is one without lines. A page with nothing on it is blank.

With a ``user_password`` the PDF is encrypted and asks for that password before it opens; with
only an ``owner_password`` it is encrypted too but opens without one (the owner's password only
guards permissions such as copying).

``hand_pdf`` writes a PDF whose objects are written out by hand, for what reportlab cannot write:
text in a layer (optional content) and a font without a map to Unicode.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pytest


@dataclass(frozen=True)
class Line:
    """A line of text whose baseline is ``baseline`` points below the top of the page."""

    baseline: float
    text: str
    size: float = 10
    bold: bool = False
    embedded: bool = False
    x: float = 72.0  # its left edge, in points from the left of the page


@dataclass(frozen=True)
class Rule:
    """A straight line from (``x0``, ``top``) to (``x1``, ``bottom``), in points from the top left."""

    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class Picture:
    """A page that is a picture, with ``lines`` of text drawn over it."""

    lines: Sequence[Line] = ()


PICTURE = Picture()
Page = Sequence[Line | Rule] | Picture


class MakePdf(Protocol):
    def __call__(
        self,
        name: str,
        pages: Sequence[Page],
        *,
        user_password: str = "",
        owner_password: str = "",
    ) -> Path: ...


@pytest.fixture
def make_pdf(tmp_path: Path) -> MakePdf:
    """Write a PDF named ``name`` in a temporary folder from its ``pages``; returns its path."""

    def make(
        name: str, pages: Sequence[Page], *, user_password: str = "", owner_password: str = ""
    ) -> Path:
        # Imported here, not at the top: this module is loaded as a plugin for the whole suite,
        # and reportlab and Pillow are only needed by the tests that make a PDF.
        import reportlab
        from PIL import Image
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.pdfencrypt import StandardEncryption
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas

        vera = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
        pdfmetrics.registerFont(TTFont("Vera", str(vera)))
        width, height = A4
        path = tmp_path / name
        locked = user_password or owner_password
        encrypt = StandardEncryption(user_password, owner_password, canCopy=0) if locked else None
        canvas = Canvas(str(path), pagesize=A4, invariant=1, encrypt=encrypt)
        for page in pages:
            items: Sequence[Line | Rule] = page.lines if isinstance(page, Picture) else page
            if isinstance(page, Picture):
                png = io.BytesIO()
                Image.new("L", (124, 175), 200).save(png, "PNG")
                canvas.drawImage(ImageReader(io.BytesIO(png.getvalue())), 0, 0, width, height)
            for item in items:
                if isinstance(item, Rule):
                    canvas.setLineWidth(0.5)
                    canvas.line(item.x0, height - item.top, item.x1, height - item.bottom)
                    continue
                font = "Vera" if item.embedded else "Helvetica-Bold" if item.bold else "Helvetica"
                canvas.setFont(font, item.size)
                canvas.drawString(item.x, height - item.baseline, item.text)
            canvas.showPage()
        canvas.save()
        return path

    return make


# ---- PDFs written by hand --------------------------------------------------------------------

LAYER = "Internal notes"  # the name of the layer /oc1 of a hand-written PDF

_COMMON = [
    b"<< /Type /OCG /Name (%s) >>" % LAYER.encode(),  # 3: the layer /oc1
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",  # 4: /F1
    # 5, 6 and 7: /F2, a font whose glyphs have no map to Unicode, so a reader gets their codes.
    (
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Codes /Encoding /Identity-H"
        b" /DescendantFonts [6 0 R] >>"
    ),
    (
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Codes /CIDSystemInfo"
        b" << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor 7 0 R"
        b" /DW 500 >>"
    ),
    (
        b"<< /Type /FontDescriptor /FontName /Codes /Flags 4 /FontBBox [0 0 1000 1000]"
        b" /ItalicAngle 0 /Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 >>"
    ),
]
_RESOURCES = b"<< /Font << /F1 4 0 R /F2 5 0 R >> /Properties << /oc1 3 0 R >> >>"


def hand_pdf(path: Path, contents: Sequence[bytes], *, layers: bytes | None = None) -> Path:
    """Write a PDF with one A4 page for each content stream in ``contents``; returns ``path``.

    The pages can use the fonts /F1 (Helvetica) and /F2 (glyph codes only) and the layer /oc1,
    named ``LAYER``. ``layers`` is the default configuration of the layers (the /D dictionary of
    the catalog's /OCProperties); without it the PDF has no layers.
    """
    first = 3 + len(_COMMON)  # the number of the first page object
    kids = b" ".join(b"%d 0 R" % (first + 2 * n) for n in range(len(contents)))
    optional = b" /OCProperties << /OCGs [3 0 R] /D %s >>" % layers if layers else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R%s >>" % optional,
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(contents)),
        *_COMMON,
    ]
    for n, content in enumerate(contents):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources %s"
            b" /Contents %d 0 R >>" % (_RESOURCES, first + 2 * n + 1)
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    table = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        table,
    )
    path.write_bytes(bytes(out))
    return path
