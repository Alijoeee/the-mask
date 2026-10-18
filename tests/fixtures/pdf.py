"""Small PDF files for the tests of the PDF reader, for the cases the corpus does not have.

``make_pdf`` writes A4 pages from a few ``Line``s each, every line placed by its baseline, in
Helvetica (Helvetica-Bold when ``bold``) or, when ``embedded``, in Bitstream Vera Sans embedded as
a TrueType font. An embedded font comes with a map from its codes to Unicode, which is how a real
PDF can hand a reader characters such as NUL, which a Word file cannot hold. A page can also be
``PICTURE``, a picture with no text (a scanned page), or have no lines at all (a blank page).

With a ``user_password`` the PDF is encrypted and asks for that password before it opens; with
only an ``owner_password`` it is encrypted too but opens without one (the owner's password only
guards permissions such as copying).
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import pytest


@dataclass(frozen=True)
class Line:
    """A line of text whose baseline is ``baseline`` points below the top of the page."""

    baseline: float
    text: str
    size: float = 10
    bold: bool = False
    embedded: bool = False


PICTURE: Literal["picture"] = "picture"
Page = Sequence[Line] | Literal["picture"]


class MakePdf(Protocol):
    def __call__(
        self,
        name: str,
        pages: Sequence[Page],
        *,
        user_password: str = "",
        owner_password: str = "",
    ) -> Path: ...


_LEFT = 72.0  # the left edge of every line, in points


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
            if page == PICTURE:
                png = io.BytesIO()
                Image.new("L", (124, 175), 200).save(png, "PNG")
                canvas.drawImage(ImageReader(io.BytesIO(png.getvalue())), 0, 0, width, height)
            else:
                for line in page:
                    font = (
                        "Vera" if line.embedded else "Helvetica-Bold" if line.bold else "Helvetica"
                    )
                    canvas.setFont(font, line.size)
                    canvas.drawString(_LEFT, height - line.baseline, line.text)
            canvas.showPage()
        canvas.save()
        return path

    return make
