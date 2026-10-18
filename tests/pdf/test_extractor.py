"""The PDF reader: a text PDF's headings, paragraphs and tables, in reading order.

The brief's tests run on the corpus: supply-01 (five text pages, each with the running header and
the footer "Page N of 5 · Confidential", and a pricing table on page 4), scanned-01 (pictures only)
and mixed-01 (page 2 a picture). The corpus PDFs are typeset from the same contracts as their Word
twins, so the paragraphs read from a PDF can be checked against the Word file's, one for one.
Small PDFs made by ``make_pdf`` cover what the corpus does not have: bare page numbers, a PDF
without any text, headings told by their weight, and paragraphs set close together.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import docx
import pytest

from tests.fixtures.pdf import PICTURE, Line, MakePdf
from themask.errors import ScannedPdfError
from themask.pdf.extractor import SCANNED_PDF_MESSAGE, extract_blocks

HEADER = "Northwind / Thamesgate \N{EM DASH} Supply Agreement"
FOOTER = "Page 1 of 5 \N{MIDDLE DOT} Confidential"
LETTER_LABEL = re.compile(r"^\([a-z]\) ")  # "(a) ": Word numbers these items itself


def test_blocks_and_report(corpus: Path) -> None:
    blocks, rep = extract_blocks(corpus / "supply-01.pdf")
    assert (
        rep.image_only_pages == []
        and any(b.kind == "table" for b in blocks)
        and rep.repeated_lines_removed
    )


def test_running_header_once(corpus: Path) -> None:
    blocks, _ = extract_blocks(corpus / "supply-01.pdf")
    joined = "\n".join(b.text for b in blocks)
    assert joined.count("Confidential") == 1


def test_scanned_refused(corpus: Path) -> None:
    with pytest.raises(ScannedPdfError):
        extract_blocks(corpus / "scanned-01.pdf")


def test_mixed_lists_image_pages(corpus: Path) -> None:
    _, rep = extract_blocks(corpus / "mixed-01.pdf")
    assert rep.image_only_pages == [2]


# ---- running headers and footers -------------------------------------------------------------


def test_running_lines_are_kept_once_as_the_first_blocks(corpus: Path) -> None:
    blocks, report = extract_blocks(corpus / "supply-01.pdf")
    assert report.pages == 5
    assert report.repeated_lines_removed == [HEADER, FOOTER]
    assert [(b.kind, b.text, b.page) for b in blocks[:3]] == [
        ("paragraph", HEADER, 1),
        ("paragraph", FOOTER, 1),
        ("heading", "SUPPLY AGREEMENT", 1),
    ]
    joined = "\n".join(b.text for b in blocks)
    assert joined.count("Northwind / Thamesgate") == 1 and "Page 2 of 5" not in joined


def test_the_running_lines_of_the_text_pages_of_a_mixed_pdf(corpus: Path) -> None:
    blocks, report = extract_blocks(corpus / "mixed-01.pdf")
    assert report.pages == 5
    assert report.repeated_lines_removed == [
        "Westerkade / Liffey \N{EM DASH} Data Processing Agreement",
        "Page 1 of 5 \N{MIDDLE DOT} Confidential",
    ]
    assert 2 not in {b.page for b in blocks}
    assert "\n".join(b.text for b in blocks).count("Confidential") == 1


def test_bare_page_numbers_are_running_lines(make_pdf: MakePdf) -> None:
    words = ("one", "two", "three")
    pdf = make_pdf(
        "numbered.pdf",
        [
            [Line(400, f"The text of part {word}."), Line(800, str(n))]
            for n, word in enumerate(words, 1)
        ],
    )
    blocks, report = extract_blocks(pdf)
    assert report.repeated_lines_removed == ["1"]
    assert [(b.text, b.page) for b in blocks] == [
        ("1", 1),
        ("The text of part one.", 1),
        ("The text of part two.", 2),
        ("The text of part three.", 3),
    ]


def test_a_line_on_one_page_only_is_no_running_line(make_pdf: MakePdf) -> None:
    pdf = make_pdf(
        "short.pdf", [[Line(60, "Letterhead"), Line(400, "Body"), Line(800, "Footnote")]]
    )
    blocks, report = extract_blocks(pdf)
    assert report.repeated_lines_removed == []
    assert [b.text for b in blocks] == ["Letterhead", "Body", "Footnote"]


# ---- pages without text ----------------------------------------------------------------------


def test_a_pdf_without_any_text_is_refused(make_pdf: MakePdf) -> None:
    with pytest.raises(ScannedPdfError) as refused:
        extract_blocks(make_pdf("no-text.pdf", [PICTURE, []]))  # a scanned page and a blank one
    assert refused.value.user_message == SCANNED_PDF_MESSAGE
    assert SCANNED_PDF_MESSAGE == (
        "This PDF is a scan without selectable text. The MASK cannot read it yet."
    )


def test_a_blank_page_is_no_image_page(make_pdf: MakePdf) -> None:
    blocks, report = extract_blocks(make_pdf("blank.pdf", [[Line(100, "Text")], [], PICTURE]))
    assert (report.pages, report.image_only_pages) == (3, [3])
    assert [(b.text, b.page) for b in blocks] == [("Text", 1)]


# ---- paragraphs and headings -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["supply-01", "supply-04", "supply-05", "supply-10"])
def test_the_paragraphs_are_those_of_the_word_twin(corpus: Path, name: str) -> None:
    """Every paragraph and heading of the PDF is one of its Word twin, whole and in order.

    These four contracts have no footnotes, whose marks and notes a PDF writes differently.
    """
    blocks, report = extract_blocks(corpus / f"{name}.pdf")
    read = [LETTER_LABEL.sub("", b.text) for b in blocks if b.kind != "table"]
    word = [p.text for p in docx.Document(str(corpus / f"{name}.docx")).paragraphs]
    assert read[:2] == report.repeated_lines_removed
    assert read[2:] == [text for text in word if text.strip()]


def test_headings_and_their_sizes(corpus: Path) -> None:
    blocks, _ = extract_blocks(corpus / "supply-01.pdf")
    headings = [(b.text, b.size) for b in blocks if b.kind == "heading"]
    assert headings[:3] == [
        ("SUPPLY AGREEMENT", 16),
        ("1. DEFINITIONS AND INTERPRETATION", 12),
        ("2. SUPPLY OF THE GOODS", 12),
    ]
    assert headings[-1] == ("SCHEDULE 1 \N{EM DASH} GOODS AND PRICES", 12)
    assert len(headings) == 14  # the title, twelve clauses and the schedule
    kinds = {b.text: (b.kind, b.size) for b in blocks}
    assert kinds["BETWEEN:"] == ("paragraph", 10)  # bold, but in the size of the body text


def test_headings_by_size_or_by_weight(make_pdf: MakePdf) -> None:
    lines = [
        Line(100, "Bold and larger", size=11, bold=True),
        Line(130, "Larger but plain", size=11),
        Line(160, "Twelve points", size=12),
        Line(190, "The body text of this page."),
        Line(220, "More body text of this page."),
        Line(250, "Bold in the size of the body", bold=True),
    ]
    blocks, _ = extract_blocks(make_pdf("headings.pdf", [lines]))
    assert [(b.kind, b.text, b.size) for b in blocks] == [
        ("heading", "Bold and larger", 11),
        ("paragraph", "Larger but plain", 11),
        ("heading", "Twelve points", 12),
        ("paragraph", "The body text of this page.", 10),
        ("paragraph", "More body text of this page.", 10),
        ("paragraph", "Bold in the size of the body", 10),
    ]


def test_paragraphs_set_close_together(make_pdf: MakePdf) -> None:
    """1 pt of white between the lines of a paragraph, 4 pt between paragraphs.

    4 pt is less than the 6 pt that parts paragraphs of 10 pt text, but more than twice the
    median gap of the page, so the paragraphs stay apart.
    """
    lines = [
        Line(100, "First paragraph, line one,"),
        Line(111, "line two,"),
        Line(122, "line three."),
        Line(136, "Second paragraph, line one,"),
        Line(147, "line two."),
        Line(161, "Third paragraph."),
    ]
    blocks, _ = extract_blocks(make_pdf("close.pdf", [lines]))
    assert [b.text for b in blocks] == [
        "First paragraph, line one, line two, line three.",
        "Second paragraph, line one, line two.",
        "Third paragraph.",
    ]


def test_small_print_under_a_large_title(make_pdf: MakePdf) -> None:
    """Two lines of 8 pt text 9.6 pt apart, on a page where most of the text is 30 pt."""
    title = ["MASTER SUPPLY", "AGREEMENT", "OF THE PARTIES"]
    lines = [Line(120 + 40 * n, text, size=30, bold=True) for n, text in enumerate(title)]
    lines += [Line(300, "Small print one", size=8), Line(309.6, "Small print two", size=8)]
    blocks, _ = extract_blocks(make_pdf("cover.pdf", [lines]))
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "MASTER SUPPLY AGREEMENT OF THE PARTIES"),
        ("paragraph", "Small print one Small print two"),
    ]


def test_a_raised_footnote_mark_stays_in_its_line(corpus: Path) -> None:
    blocks, _ = extract_blocks(corpus / "nda-01.pdf")
    texts = [b.text for b in blocks]
    assert any(t.endswith("for their compliance with this Agreement.1") for t in texts)
    assert not [t for t in texts if t.isdigit()]  # no mark on a line of its own


# ---- tables ----------------------------------------------------------------------------------


def test_a_table_stands_where_it_is_and_is_read_once(corpus: Path) -> None:
    blocks, _ = extract_blocks(corpus / "supply-01.pdf")
    (index,) = [i for i, b in enumerate(blocks) if b.kind == "table"]
    table = blocks[index]
    assert blocks[index - 1].text == "SCHEDULE 1 \N{EM DASH} GOODS AND PRICES"
    assert blocks[index + 1].text == "Prices agreed by G. Baker and J. Parker on 18 January 2026."
    assert table.page == 4
    assert table.rows == [
        ["Product", "Annual volume", "Unit price", "Discount", "Annual value"],
        ["Stainless threaded rod", "9,750 kg", "EUR 13.10", "7 per cent", "EUR 118,784.25"],
        ["Countersunk wood screws", "6,250 kg", "EUR 7.40", "3.5 per cent", "EUR 44,631.25"],
        ["Nylon wall plugs", "7,250 kg", "EUR 10.05", "1 per cent", "EUR 72,133.88"],
        ["Total", "", "", "", "EUR 235,549.38"],
    ]
    assert table.text.splitlines() == ["\t".join(row) for row in table.rows]
    joined = "\n".join(b.text for b in blocks)
    assert joined.count("Stainless threaded rod") == 1


# ---- speed -----------------------------------------------------------------------------------


def test_twenty_four_pages_are_read_quickly(corpus: Path) -> None:
    started = time.perf_counter()
    blocks, report = extract_blocks(corpus / "supply-10.pdf")
    assert time.perf_counter() - started < 10
    assert report.pages == 24
    assert len(" ".join(b.text for b in blocks).split()) > 12000
