"""The PDF reader: a text PDF's headings, paragraphs and tables, in reading order.

The brief's tests run on the corpus: supply-01 (five text pages, each with the running header and
the footer "Page N of 5 · Confidential", and a pricing table on page 4), scanned-01 (pictures only)
and mixed-01 (page 2 a picture). The corpus PDFs are typeset from the same contracts as their Word
twins, so the paragraphs read from a PDF can be checked against the Word file's, one for one.
Small PDFs made by ``make_pdf`` cover what the corpus does not have: bare page numbers, numbered
headings at the tops of pages, scans with stamped page numbers, a PDF without any text, headings
told by their weight, body text in 12 pt, paragraphs set close together, text drawn twice, lines
that end in a hyphen, a table with text beside a short row, and PDFs that are locked or damaged.
PDFs written by hand (``hand_pdf``) have text in a hidden layer and glyphs without Unicode.
supply-01 typeset again with a watermark shows that rotated text is left out.
"""

from __future__ import annotations

import re
import time
import tracemalloc
from pathlib import Path
from typing import Any

import docx
import pytest

from tests.fixtures.pdf import LAYER, PICTURE, Line, MakePdf, Page, Picture, Rule, hand_pdf
from themask.errors import ProtectedFileError, ScannedPdfError, UnsupportedFileError
from themask.pdf.extractor import SCANNED_PDF_MESSAGE, extract_blocks

HEADER = "Northwind / Thamesgate \N{EM DASH} Supply Agreement"
FOOTER = "Page 1 of 5 \N{MIDDLE DOT} Confidential"
LETTER_LABEL = re.compile(r"^\([a-z]\) ")  # "(a) ": Word numbers these items itself
# Content streams for ``hand_pdf``: a note in the layer /oc1, a clause outside it, and five glyphs
# of the font /F2, which has no map to Unicode.
NOTE = b"/OC /oc1 BDC BT /F1 10 Tf 72 700 Td (Hidden note: walk-away EUR 2,000,000) Tj ET EMC"
CLAUSE = b"BT /F1 10 Tf 72 650 Td (Visible clause text.) Tj ET"
CODES = b"BT /F2 10 Tf 72 700 Td <004E006F007200740068> Tj ET"


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
    assert report.pages == 5 and report.hidden_layers == []
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


def test_numbered_headings_at_the_tops_of_pages_are_kept(make_pdf: MakePdf) -> None:
    """Each schedule starts a page with "SCHEDULE n" in the top band: none is a running line."""
    pages: list[Page] = [[Line(84, "1. The Supplier shall deliver the Goods.")]]
    for n, title in enumerate(["PRICES", "DELIVERY ADDRESSES", "SERVICE LEVELS"], 1):
        pages.append(
            [
                Line(84, f"SCHEDULE {n}", size=12, bold=True),
                Line(104, title, size=12, bold=True),
                Line(130, f"The terms of schedule {n}."),
            ]
        )
    blocks, report = extract_blocks(make_pdf("schedules.pdf", pages))
    assert report.repeated_lines_removed == []
    assert [(b.text, b.page) for b in blocks] == [
        ("1. The Supplier shall deliver the Goods.", 1),
        ("SCHEDULE 1", 2),
        ("PRICES", 2),
        ("The terms of schedule 1.", 2),
        ("SCHEDULE 2", 3),
        ("DELIVERY ADDRESSES", 3),
        ("The terms of schedule 2.", 3),
        ("SCHEDULE 3", 4),
        ("SERVICE LEVELS", 4),
        ("The terms of schedule 3.", 4),
    ]


def test_a_heading_is_never_a_running_line(make_pdf: MakePdf) -> None:
    """ "Price page 1" to "Price page 3" would repeat as a page number does; they are headings."""
    pages: list[Page] = [
        [
            Line(84, f"Price page {n}", size=12, bold=True),
            Line(130, f"The prices of part {word} are in the table below."),
        ]
        for n, word in enumerate(("one", "two", "three"), 1)
    ]
    blocks, report = extract_blocks(make_pdf("price-pages.pdf", pages))
    assert report.repeated_lines_removed == []
    assert [b.text for b in blocks if b.kind == "heading"] == [
        "Price page 1",
        "Price page 2",
        "Price page 3",
    ]


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


def _stamped(layout: str) -> list[Page]:
    """A page for each letter of ``layout``, "t" a page of text and "s" a scanned page, each one
    stamped "Page N of M" at its foot, as a PDF tool numbers the pages of a file."""
    pages: list[Page] = []
    for n, kind in enumerate(layout, 1):
        stamp = Line(812, f"Page {n} of {len(layout)}")
        if kind == "s":
            pages.append(Picture([stamp]))
        else:
            pages.append([Line(100, f"Clause {n}. The Buyer shall pay within 30 days."), stamp])
    return pages


@pytest.mark.parametrize("layout", ["s", "sss"])
def test_scans_stamped_with_page_numbers_are_refused(make_pdf: MakePdf, layout: str) -> None:
    with pytest.raises(ScannedPdfError):
        extract_blocks(make_pdf("stamped.pdf", _stamped(layout)))


def test_a_stamped_scan_between_text_pages_is_listed(make_pdf: MakePdf) -> None:
    blocks, report = extract_blocks(make_pdf("stamped.pdf", _stamped("tst")))
    assert report.image_only_pages == [2]
    assert report.repeated_lines_removed == ["Page 1 of 3"]
    assert [(b.text, b.page) for b in blocks] == [
        ("Page 1 of 3", 1),
        ("Clause 1. The Buyer shall pay within 30 days.", 1),
        ("Clause 3. The Buyer shall pay within 30 days.", 3),
    ]


def test_a_pdf_of_glyph_codes_only_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScannedPdfError):
        extract_blocks(hand_pdf(tmp_path / "codes.pdf", [CODES]))


def test_a_page_of_glyph_codes_is_listed_and_left_out(tmp_path: Path) -> None:
    blocks, report = extract_blocks(hand_pdf(tmp_path / "codes.pdf", [CLAUSE, CODES]))
    assert [(b.text, b.page) for b in blocks] == [("Visible clause text.", 1)]
    assert report.image_only_pages == [2]


def test_a_few_glyph_codes_in_a_line_are_left_out(tmp_path: Path) -> None:
    content = b"BT /F1 10 Tf 72 700 Td (Payment within thirty days) Tj /F2 10 Tf <0001> Tj ET"
    blocks, report = extract_blocks(hand_pdf(tmp_path / "some-codes.pdf", [content]))
    assert [b.text for b in blocks] == ["Payment within thirty days"]
    assert report.image_only_pages == []


# ---- hidden layers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layers",
    [b"<< /Order [3 0 R] /OFF [3 0 R] >>", b"<< /BaseState /OFF >>"],
    ids=["off", "all-off-but-those-on"],
)
def test_text_in_a_hidden_layer_is_left_out(tmp_path: Path, layers: bytes) -> None:
    pdf = hand_pdf(tmp_path / "hidden.pdf", [NOTE + b"\n" + CLAUSE], layers=layers)
    blocks, report = extract_blocks(pdf)
    assert [b.text for b in blocks] == ["Visible clause text."]
    assert report.hidden_layers == [LAYER]


def test_text_in_a_layer_that_is_shown_is_read(tmp_path: Path) -> None:
    pdf = hand_pdf(tmp_path / "shown.pdf", [NOTE + b"\n" + CLAUSE], layers=b"<< /Order [3 0 R] >>")
    blocks, report = extract_blocks(pdf)
    assert [b.text for b in blocks] == [
        "Hidden note: walk-away EUR 2,000,000",
        "Visible clause text.",
    ]
    assert report.hidden_layers == []


# ---- locked and damaged files ----------------------------------------------------------------


def test_a_pdf_that_asks_for_a_password_is_refused(make_pdf: MakePdf) -> None:
    locked = make_pdf("locked.pdf", [[Line(100, "Secret terms")]], user_password="secret")
    with pytest.raises(ProtectedFileError) as refused:
        extract_blocks(locked)
    assert refused.value.user_message == (
        "This PDF is protected or encrypted. Please provide an unprotected copy."
    )


def test_a_pdf_locked_only_against_copying_is_read(make_pdf: MakePdf) -> None:
    """Encrypted with an owner's password only, a PDF opens without one, so it is read."""
    pdf = make_pdf("owner.pdf", [[Line(100, "Open terms")]], owner_password="owner")
    blocks, _ = extract_blocks(pdf)
    assert [b.text for b in blocks] == ["Open terms"]


@pytest.mark.parametrize("damage", ["garbage", "truncated", "empty"])
def test_a_damaged_pdf_is_refused(corpus: Path, tmp_path: Path, damage: str) -> None:
    whole = (corpus / "supply-01.pdf").read_bytes()
    damaged = {
        "garbage": b"This is not a PDF at all.",
        "truncated": whole[: len(whole) // 2],
        "empty": b"",
    }
    path = tmp_path / f"{damage}.pdf"
    path.write_bytes(damaged[damage])
    with pytest.raises(UnsupportedFileError) as refused:
        extract_blocks(path)
    assert refused.value.user_message == (
        "This is not a readable PDF. It may be damaged or incomplete. Please provide another copy."
    )


# ---- paragraphs and headings -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "paragraphs"),
    [("supply-01", 107), ("supply-04", 107), ("supply-05", 107), ("supply-10", 370)],
)
def test_the_paragraphs_are_those_of_the_word_twin(
    corpus: Path, name: str, paragraphs: int
) -> None:
    """Every paragraph and heading of the PDF is one of its Word twin, whole and in order.

    These four contracts have no footnotes, whose marks and notes a PDF writes differently.
    """
    blocks, report = extract_blocks(corpus / f"{name}.pdf")
    read = [LETTER_LABEL.sub("", b.text) for b in blocks if b.kind != "table"]
    word = [p.text for p in docx.Document(str(corpus / f"{name}.docx")).paragraphs]
    word = [text for text in word if text.strip()]
    assert read[:2] == report.repeated_lines_removed
    assert (len(read) - 2, len(word)) == (paragraphs, paragraphs)
    assert read[2:] == word


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


def test_body_text_in_12_pt_is_no_heading(make_pdf: MakePdf) -> None:
    """A heading is larger than the body text of its page: 12 pt alone does not make one."""
    lines = [
        Line(100, "1. DEFINITIONS", size=14, bold=True),
        Line(130, "1.1 The Buyer shall pay the Supplier", size=12),
        Line(145.6, "within thirty days of the invoice.", size=12),
        Line(169.2, "BETWEEN:", size=12, bold=True),
        Line(192.8, "1.2 Each party shall keep the terms of this Agreement secret.", size=12),
    ]
    blocks, _ = extract_blocks(make_pdf("twelve.pdf", [lines]))
    assert [(b.kind, b.text, b.size) for b in blocks] == [
        ("heading", "1. DEFINITIONS", 14),
        (
            "paragraph",
            "1.1 The Buyer shall pay the Supplier within thirty days of the invoice.",
            12,
        ),
        ("paragraph", "BETWEEN:", 12),
        ("paragraph", "1.2 Each party shall keep the terms of this Agreement secret.", 12),
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


def test_text_drawn_twice_to_look_bold_is_read_once(make_pdf: MakePdf) -> None:
    lines = [
        Line(100, "This Agreement is made between"),
        Line(114, "Northwind Trading B.V."),
        Line(114, "Northwind Trading B.V.", x=72.3),
        Line(128, "and the Supplier."),
    ]
    blocks, _ = extract_blocks(make_pdf("fake-bold.pdf", [lines]))
    assert [b.text for b in blocks] == [
        "This Agreement is made between Northwind Trading B.V. and the Supplier."
    ]


def test_a_line_that_ends_in_a_hyphen_goes_on_without_a_space(make_pdf: MakePdf) -> None:
    """Word breaks a line after the hyphen of "anne-marie" or "NW-2026-0417"; a dash stays one."""
    lines = [
        Line(100, "Notices go to anne-"),
        Line(112, "marie.dupont@north-wind.example under order NW-"),
        Line(124, "2026-0417 of the Buyer, at EUR 5 -"),
        Line(136, "net of VAT."),
    ]
    blocks, _ = extract_blocks(make_pdf("hyphen.pdf", [lines]))
    assert [b.text for b in blocks] == [
        (
            "Notices go to anne-marie.dupont@north-wind.example under order NW-2026-0417 of the"
            " Buyer, at EUR 5 - net of VAT."
        )
    ]


def test_small_print_under_a_large_title(make_pdf: MakePdf) -> None:
    """Two lines of 8 pt text 9.6 pt apart, on a page where most of the text is 30 pt.

    The lines stay apart (read together, their letters would interleave). The title is the
    page's median size, so it is no heading here: a heading is larger than the page's text.
    """
    title = ["MASTER SUPPLY", "AGREEMENT", "OF THE PARTIES"]
    lines = [Line(120 + 40 * n, text, size=30, bold=True) for n, text in enumerate(title)]
    lines += [Line(300, "Small print one", size=8), Line(309.6, "Small print two", size=8)]
    blocks, _ = extract_blocks(make_pdf("cover.pdf", [lines]))
    assert [b.text for b in blocks] == [
        "MASTER SUPPLY AGREEMENT OF THE PARTIES",
        "Small print one Small print two",
    ]


def test_a_raised_footnote_mark_stays_in_its_line(corpus: Path) -> None:
    blocks, _ = extract_blocks(corpus / "nda-01.pdf")
    texts = [b.text for b in blocks]
    assert any(t.endswith("for their compliance with this Agreement.1") for t in texts)
    assert not [t for t in texts if t.isdigit()]  # no mark on a line of its own


# ---- rotated text ----------------------------------------------------------------------------


def test_a_watermark_and_a_note_up_the_margin_are_left_out(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """supply-01 typeset again with a diagonal "DRAFT COPY" across every page and a reference
    running up its left margin reads exactly as the corpus file without them.

    Read with the rest, the letters of the watermark land inside the lines of the body text
    ("shall pRay") and come out as headings of their own.
    """
    from tools.corpus import pdf_writer
    from tools.make_corpus import CATALOGUE, build_spec

    show_page = pdf_writer._Canvas.showPage

    def show_page_with_marks(canvas: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 72)
        canvas.translate(110, 220)
        canvas.rotate(45)
        canvas.drawString(0, 0, "DRAFT COPY")
        canvas.restoreState()
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.translate(40, 300)
        canvas.rotate(90)
        canvas.drawString(0, 0, "REF NW-2026-0417 / DRAFT 3")
        canvas.restoreState()
        show_page(canvas)

    monkeypatch.setattr(pdf_writer._Canvas, "showPage", show_page_with_marks)
    planned = next(planned for planned in CATALOGUE if planned.name == "supply-01")
    spec = build_spec(
        planned.seed,
        planned.kind,
        planned.features,
        parties=planned.parties,
        project=planned.project,
        bare_amount=planned.bare_amount,
    )
    pdf_writer.write_pdf(spec, tmp_path / "draft.pdf")
    assert extract_blocks(tmp_path / "draft.pdf") == extract_blocks(corpus / "supply-01.pdf")


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


def test_text_beside_a_short_row_of_a_table_is_read(make_pdf: MakePdf) -> None:
    """A ruled table whose first row is narrower than the others, and text beside that row:
    inside the outline of the table, but in none of its cells."""
    rules = [Rule(72, 100, 272, 100)]
    rules += [Rule(72, top, 472, top) for top in (120, 150, 170)]
    rules += [Rule(x, 100, x, 170) for x in (72, 172, 272)]
    rules += [Rule(x, 120, x, 170) for x in (372, 472)]
    texts = [
        (113, 76, "Product"),
        (113, 176, "Price"),
        (113, 300, "Agreed by G. Baker"),
        (131, 76, "NW-"),
        (143, 76, "2026-0417"),
        (135, 176, "EUR 10"),
        (135, 276, "per kg"),
        (135, 376, "net"),
        (163, 76, "Total"),
        (163, 176, "EUR 20"),
    ]
    lines = [Line(baseline, text, size=9, x=x) for baseline, x, text in texts]
    page = [*rules, *lines, Line(200, "A paragraph under the table.")]
    blocks, _ = extract_blocks(make_pdf("short-row.pdf", [page]))
    assert [(b.kind, b.rows if b.kind == "table" else b.text) for b in blocks] == [
        (
            "table",
            [
                ["Product", "Price", "", ""],
                ["NW-2026-0417", "EUR 10", "per kg", "net"],
                ["Total", "EUR 20", "", ""],
            ],
        ),
        ("paragraph", "Agreed by G. Baker"),
        ("paragraph", "A paragraph under the table."),
    ]


# ---- speed -----------------------------------------------------------------------------------


def test_twenty_four_pages_are_read_quickly(corpus: Path) -> None:
    started = time.perf_counter()
    blocks, report = extract_blocks(corpus / "supply-10.pdf")
    assert time.perf_counter() - started < 10
    assert report.pages == 24
    assert len(" ".join(b.text for b in blocks).split()) > 12000


@pytest.mark.slow  # tracemalloc makes reading five times slower
def test_twenty_four_pages_are_read_in_little_memory(corpus: Path) -> None:
    """Each page is let go once it is read: kept, the 24 pages of supply-10 took 141 MB."""
    tracemalloc.start()
    try:
        extract_blocks(corpus / "supply-10.pdf")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 60_000_000
