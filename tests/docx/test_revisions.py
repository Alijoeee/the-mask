"""Accepting and rejecting every tracked change: the text of the masked copy and of the "before".

A revision resolved the wrong way is text the masker never sees: deleted text left in a masked
copy, or a "before" copy without the text the changes took out. Besides the corpus, the file from
``tests/fixtures/revisions.py`` holds one of each kind of revision, and small hand-written files
cover what it does not: changes inside changes, moved paragraphs, marks that cannot be joined,
whole tables, records without old properties, footnotes and endnotes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from lxml import etree

from tests.fixtures.docx import MakeDocx
from tests.fixtures.revisions import deleted_run, para, run, write_paragraph_marks
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import extract_text, has_revisions
from themask.docx.revisions import accept_all, reject_all

W = NS["w"]
Resolve = Callable[[DocxPackage], int]
SIDES = pytest.mark.parametrize("resolve", [accept_all, reject_all], ids=["accept", "reject"])

# The text of the file with one of each kind of revision, paragraph by paragraph: the body (a
# text box after the paragraph it sits in, the table cell by cell), then the header and footer.
ACCEPTED = [
    "The Buyer shall pay EUR 2,000 within 45 days.",
    "Made bold by a formatting change.",
    "Centred by a paragraph change.",
    "Clause A. End of A.",
    "Clause B. Moved sentence. End of B.",
    "First half, ",
    "second half.",
    "Joined together.",  # the deleted paragraph mark joined the two
    "A numbered item.",
    "Text box: ",
    "Box new",
    "Stray text is shown.",
    "Item",
    "Price",
    "Added row",
    "EUR 500",
    "Kept cell",
    "Inserted cell",
    "Merged cell",
    "Shaded cell",
    "End.",
    "Draft v2",
    "Confidential draft",
]
REJECTED = [
    "The Buyer shall pay EUR 1,000 within 30 days.",
    "Made bold by a formatting change.",
    "Centred by a paragraph change.",
    "Clause A. Moved sentence. End of A.",
    "Clause B. End of B.",
    "First half, second half.",  # the inserted paragraph mark is taken out
    "Joined ",
    "together.",
    "A numbered item.",
    "Text box: ",
    "Box old",
    "Stray text is not shown.",
    "Item",
    "Price",
    "Removed row",
    "EUR 900",
    "Kept cell",
    "Deleted cell",
    "Merged cell",
    "Shaded cell",
    "End.",
    "Draft v1",
    "Confidential",
]
# The revision elements of that file: 4 in the first paragraph; 1 each for the formatting,
# paragraph and numbering changes, the move's two halves and the two paragraph marks; 2 in each
# copy of the text box; in the table the table, row and exception changes (3), the inserted and
# the deleted row (1 + 2 cells x 2 each), the inserted, deleted and merged cell and the shading
# change (4); the section change; 2 in the header and 1 in the footer.
REVISION_COUNT = 4 + 7 + 4 + 3 + 5 + 5 + 4 + 1 + 2 + 1

# Every element a tracked change leaves in the XML, the range markers of a move and deleted text
# among them.
LEFTOVERS = tuple(
    f"{{{W}}}{name}"
    for name in (
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "moveFromRangeStart",
        "moveFromRangeEnd",
        "moveToRangeStart",
        "moveToRangeEnd",
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "tblPrExChange",
        "trPrChange",
        "tcPrChange",
        "numberingChange",
        "cellIns",
        "cellDel",
        "cellMerge",
        "delText",
        "delInstrText",
    )
)

A = 'w:id="1" w:author="A" w:date="2026-10-01T09:00:00Z"'
B = 'w:id="2" w:author="B" w:date="2026-10-02T09:00:00Z"'


def w(name: str) -> str:
    return f"{{{W}}}{name}"


def leftovers(pkg: DocxPackage) -> list[str]:
    return [str(e.tag) for part in pkg.TEXT_PARTS for e in pkg.xml(part).iter(*LEFTOVERS)]


def lines(pkg: DocxPackage) -> list[str]:
    return extract_text(pkg).text.split("\n")


def paragraph(pkg: DocxPackage, text: str) -> etree._Element:
    """The paragraph whose text is ``text``."""
    dt = extract_text(pkg)
    return next(s.para for s in dt.segments if dt.text[s.start : s.end] == text)


def child_tags(element: etree._Element) -> list[str]:
    return [str(child.tag).split("}")[1] for child in element]


def resolved(path: Path, resolve: Resolve) -> DocxPackage:
    pkg = DocxPackage.open(path)
    resolve(pkg)
    return pkg


def mark(*kinds: str) -> str:
    """The run properties of a paragraph mark with these revisions (ins, del, moveFrom, moveTo)."""
    return "<w:rPr>" + "".join(f"<w:{k} {A}/>" for k in kinds) + "</w:rPr>"


# ---- the brief -------------------------------------------------------------------------------


def test_accept_text(rev_pkg: DocxPackage) -> None:
    accept_all(rev_pkg)
    first = extract_text(rev_pkg).text.splitlines()[0]
    assert first == "The Buyer shall pay EUR 2,000 within 45 days."


def test_reject_text(rev_pkg: DocxPackage) -> None:
    reject_all(rev_pkg)
    first = extract_text(rev_pkg).text.splitlines()[0]
    assert first == "The Buyer shall pay EUR 1,000 within 30 days."


def test_no_revisions_left(rev_pkg: DocxPackage) -> None:
    accept_all(rev_pkg)
    assert not has_revisions(rev_pkg)


def test_reject_restores_old_formatting(rev_pkg: DocxPackage) -> None:
    reject_all(rev_pkg)
    r = rev_pkg.xml("word/document.xml").find(".//w:r[w:t='bold']", NS)
    assert r is not None and r.find("w:rPr/w:b", NS) is None


def test_paragraph_marks(rev_pkg_marks: DocxPackage) -> None:
    a = rev_pkg_marks.copy()
    accept_all(a)
    assert extract_text(a).text.count("\n") == 1
    r = rev_pkg_marks.copy()
    reject_all(r)
    assert extract_text(r).text.count("\n") == 2


def test_corpus_tracked_docs_resolve(corpus: Path) -> None:
    manifest = json.loads((corpus / "manifest.json").read_text())
    for doc in (d for d in manifest if "tracked_changes" in d["features"]):
        pkg = DocxPackage.open(corpus / doc["file"])
        accept_all(pkg)
        assert not has_revisions(pkg), doc["file"]


# ---- the file with one of each kind of revision ----------------------------------------------


def test_accept_gives_the_final_text_of_every_part(rev_pkg: DocxPackage) -> None:
    accept_all(rev_pkg)
    assert lines(rev_pkg) == ACCEPTED


def test_reject_gives_the_text_before_the_changes(rev_pkg: DocxPackage) -> None:
    reject_all(rev_pkg)
    assert lines(rev_pkg) == REJECTED


@SIDES
def test_no_revision_marks_left_on_either_side(rev_pkg: DocxPackage, resolve: Resolve) -> None:
    resolve(rev_pkg)
    assert not has_revisions(rev_pkg)
    assert leftovers(rev_pkg) == []


@SIDES
def test_the_count_and_a_second_run(rev_pkg: DocxPackage, resolve: Resolve) -> None:
    assert resolve(rev_pkg) == REVISION_COUNT
    after = {part: rev_pkg.raw(part) for part in rev_pkg.TEXT_PARTS}
    assert resolve(rev_pkg) == 0
    assert {part: rev_pkg.raw(part) for part in rev_pkg.TEXT_PARTS} == after


def test_accept_keeps_the_new_properties(rev_pkg: DocxPackage) -> None:
    accept_all(rev_pkg)
    root = rev_pkg.xml("word/document.xml")
    bold = root.find(".//w:r[w:t='bold']", NS)
    assert bold is not None and bold.find("w:rPr/w:b", NS) is not None
    centred = paragraph(rev_pkg, "Centred by a paragraph change.")
    assert centred.find("w:pPr/w:jc", NS).get(w("val")) == "center"
    assert centred.find("w:pPr/w:rPr/w:i", NS) is not None
    table = root.find(".//w:tbl", NS)
    assert table.find("w:tblPr/w:tblW", NS).get(w("type")) == "pct"
    header_row = table.find("w:tr", NS)
    assert child_tags(header_row.find("w:trPr", NS)) == ["tblHeader"]
    assert child_tags(header_row.find("w:tblPrEx", NS)) == ["tblBorders"]
    shaded = paragraph(rev_pkg, "Shaded cell").getparent()
    assert child_tags(shaded.find("w:tcPr", NS)) == ["tcW", "shd"]
    section = root.find("w:body/w:sectPr", NS)
    assert section.find("w:pgSz", NS).get(w("w")) == "12240"


def test_reject_restores_the_old_properties(rev_pkg: DocxPackage) -> None:
    reject_all(rev_pkg)
    root = rev_pkg.xml("word/document.xml")
    bold = root.find(".//w:r[w:t='bold']", NS)
    assert bold is not None and bold.find("w:rPr", NS) is None  # plain before: no properties
    # The alignment goes back; the mark's italic, which is not a paragraph property, stays.
    centred = paragraph(rev_pkg, "Centred by a paragraph change.")
    assert child_tags(centred.find("w:pPr", NS)) == ["jc", "rPr"]
    assert centred.find("w:pPr/w:jc", NS).get(w("val")) == "right"
    assert centred.find("w:pPr/w:rPr/w:i", NS) is not None
    table = root.find(".//w:tbl", NS)
    assert table.find("w:tblPr/w:tblW", NS).get(w("type")) == "auto"
    header_row = table.find("w:tr", NS)
    assert child_tags(header_row) == ["tc", "tc"]  # no row properties nor exceptions before
    shaded = paragraph(rev_pkg, "Shaded cell").getparent()
    assert child_tags(shaded.find("w:tcPr", NS)) == ["tcW"]
    # The page size goes back; the header and footer, which the old section properties cannot
    # name, stay.
    section = root.find("w:body/w:sectPr", NS)
    assert child_tags(section) == ["headerReference", "footerReference", "pgSz", "pgMar"]
    assert section.find("w:pgSz", NS).get(w("w")) == "11906"


@SIDES
def test_a_numbering_change_keeps_the_numbering(rev_pkg: DocxPackage, resolve: Resolve) -> None:
    resolve(rev_pkg)
    numbering = paragraph(rev_pkg, "A numbered item.").find("w:pPr/w:numPr", NS)
    assert child_tags(numbering) == ["ilvl", "numId"]


def test_a_deleted_paragraph_mark_joins_the_next_paragraph(rev_pkg: DocxPackage) -> None:
    accept_all(rev_pkg)
    joined = paragraph(rev_pkg, "Joined together.")
    assert [t.text for t in joined.iter(w("t"))] == ["Joined ", "together."]
    assert joined.find("w:pPr/w:jc", NS).get(w("val")) == "both"  # the next paragraph's


def test_an_inserted_paragraph_mark_is_taken_out(rev_pkg: DocxPackage) -> None:
    reject_all(rev_pkg)
    joined = paragraph(rev_pkg, "First half, second half.")
    assert joined.find("w:pPr", NS) is None  # the next paragraph's properties: none


def test_the_marks_of_three_paragraphs(tmp_path: Path) -> None:
    deleted = DocxPackage.open(write_paragraph_marks(tmp_path / "del.docx", "del"))
    inserted = DocxPackage.open(write_paragraph_marks(tmp_path / "ins.docx", "ins"))
    for pkg, accepted, rejected in (
        (deleted, "One\nTwoThree", "One\nTwo\nThree"),
        (inserted, "One\nTwo\nThree", "One\nTwoThree"),
    ):
        a, r = pkg.copy(), pkg.copy()
        assert accept_all(a) == 1 and reject_all(r) == 1
        assert extract_text(a).text == accepted and extract_text(r).text == rejected
        assert leftovers(a) == leftovers(r) == []


@SIDES
def test_the_move_leaves_no_range_markers(rev_pkg: DocxPackage, resolve: Resolve) -> None:
    resolve(rev_pkg)
    names = ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")
    assert not list(rev_pkg.xml("word/document.xml").iter(*(w(n) for n in names)))


@pytest.mark.parametrize(
    ("resolve", "kept"), [(accept_all, "new"), (reject_all, "old")], ids=["accept", "reject"]
)
def test_the_fallback_copy_of_a_text_box_is_resolved_too(
    rev_pkg: DocxPackage, resolve: Resolve, kept: str
) -> None:
    # The reader skips mc:Fallback (ruling R16), so text left there would never be masked
    # before the cleaner removes the fallback; it must hold no deleted text and no change.
    resolve(rev_pkg)
    fallback = rev_pkg.xml("word/document.xml").find(".//mc:Fallback", NS)
    assert fallback is not None
    assert "".join(e.text or "" for e in fallback.iter(w("t"), w("delText"))) == f"Box {kept}"
    assert not list(fallback.iter(*LEFTOVERS))


def test_deleted_text_outside_a_deletion(rev_pkg: DocxPackage) -> None:
    a, r = rev_pkg.copy(), rev_pkg.copy()
    accept_all(a)
    stray = paragraph(a, "Stray text is shown.")
    assert [t.text for t in stray.iter(w("t"))] == ["Stray text is ", "shown."]
    reject_all(r)  # read as text in the rejected view, so it is text in the "before" copy
    stray = paragraph(r, "Stray text is not shown.")
    texts = list(stray.iter(w("t")))
    assert [t.text for t in texts] == ["Stray text is ", "not ", "shown."]
    assert texts[1].get(f"{{{NS['xml']}}}space") == "preserve"


def test_rows_and_cells(rev_pkg: DocxPackage) -> None:
    a, r = rev_pkg.copy(), rev_pkg.copy()
    accept_all(a)
    reject_all(r)
    for pkg, row_texts in (
        (a, [["Item", "Price"], ["Added row", "EUR 500"], ["Kept cell", "Inserted cell"]]),
        (r, [["Item", "Price"], ["Removed row", "EUR 900"], ["Kept cell", "Deleted cell"]]),
    ):
        rows = pkg.xml("word/document.xml").findall(".//w:tr", NS)
        texts = [["".join(t.text or "" for t in c.iter(w("t"))) for c in row] for row in rows]
        assert [[t for t in row if t] for row in texts] == [
            *row_texts,
            ["Merged cell", "Shaded cell"],
        ]


@SIDES
def test_the_result_is_saved_and_opens_again(
    rev_pkg: DocxPackage, resolve: Resolve, tmp_path: Path
) -> None:
    import docx

    resolve(rev_pkg)
    out = tmp_path / "resolved.docx"
    rev_pkg.save(out)
    assert docx.Document(str(out)).paragraphs
    again = DocxPackage.open(out)
    assert extract_text(again).text == extract_text(rev_pkg).text
    assert not has_revisions(again)


# ---- the corpus ------------------------------------------------------------------------------


def test_corpus_deleted_secrets_are_only_on_the_before_side(corpus: Path) -> None:
    # Accepting gives exactly the reader's accepted view and rejecting its rejected view (these
    # files change no paragraph marks); a value only in deleted text is nowhere in the XML of
    # the accepted file, and is in the text of the rejected one.
    manifest = json.loads((corpus / "manifest.json").read_text())
    tracked = [d for d in manifest if "tracked_changes" in d["features"]]
    assert len(tracked) >= 3
    for doc in tracked:
        path = corpus / doc["file"]
        truth = json.loads((corpus / doc["truth"]).read_text(encoding="utf-8"))
        deleted = [t["value"] for t in truth if t.get("only_in_deletion")]
        original = DocxPackage.open(path)
        accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
        assert not has_revisions(accepted) and not has_revisions(rejected), doc["file"]
        assert leftovers(accepted) == leftovers(rejected) == [], doc["file"]
        assert extract_text(accepted).text == extract_text(original, "accepted").text
        assert extract_text(rejected).text == extract_text(original, "rejected").text
        for value in deleted:
            assert value not in extract_text(accepted).text, (doc["file"], value)
            for part in accepted.TEXT_PARTS:
                assert value.encode() not in accepted.raw(part), (doc["file"], part, value)
            assert value in extract_text(rejected).text, (doc["file"], value)


def test_a_file_without_revisions_is_left_as_it_is(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    before = {part: etree.tostring(pkg.xml(part)) for part in pkg.TEXT_PARTS}
    assert accept_all(pkg) == 0 and reject_all(pkg) == 0
    assert {part: etree.tostring(pkg.xml(part)) for part in pkg.TEXT_PARTS} == before


# ---- files written by hand -------------------------------------------------------------------


def test_changes_inside_changes(make_docx: MakeDocx) -> None:
    body = para(
        f'<w:hyperlink r:id="rId1"><w:ins {A}>{run("new")}</w:ins></w:hyperlink>'
        # inserted by one reviewer, then deleted by another: gone on both sides
        f"<w:ins {A}><w:del {B}>{deleted_run('short-lived')}</w:del></w:ins>"
        f"<w:del {A}><w:ins {B}>{run('never there')}</w:ins></w:del>"
        f"<w:moveFrom {A}>{deleted_run(' moved')}</w:moveFrom>"  # moved away, held as w:delText
    )
    path = make_docx(body)
    accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
    assert lines(accepted) == ["new"] and lines(rejected) == [" moved"]
    original = DocxPackage.open(path)
    assert lines(accepted) == extract_text(original, "accepted").text.split("\n")
    assert lines(rejected) == extract_text(original, "rejected").text.split("\n")
    assert leftovers(accepted) == leftovers(rejected) == []
    assert rejected.xml("word/document.xml").find(".//w:hyperlink", NS) is not None


def test_a_deleted_field_instruction(make_docx: MakeDocx) -> None:
    field = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:delInstrText xml:space="preserve"> PAGE </w:delInstrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{deleted_run('3')}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    path = make_docx(para(run("Page ") + f"<w:del {A}>{field}</w:del>"))
    accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
    assert lines(accepted) == ["Page "]
    assert not list(accepted.xml("word/document.xml").iter(w("fldChar")))
    assert lines(rejected) == ["Page  PAGE 3"]
    instruction = rejected.xml("word/document.xml").find(".//w:instrText", NS)
    assert instruction is not None and instruction.text == " PAGE "
    assert instruction.get(f"{{{NS['xml']}}}space") == "preserve"


def test_a_whole_paragraph_moved(make_docx: MakeDocx) -> None:
    # Word moves a paragraph with range markers between the paragraphs, the content and the mark
    # of the paragraph at its old place marked moveFrom and at its new place moveTo.
    move = 'w:name="move1" w:author="A"'
    body = (
        para(run("A"))
        + f'<w:moveFromRangeStart w:id="10" {move}/>'
        + para(f"<w:moveFrom {A}>{run('Moved')}</w:moveFrom>", mark("moveFrom"))
        + '<w:moveFromRangeEnd w:id="10"/>'
        + para(run("B"))
        + f'<w:moveToRangeStart w:id="11" {move}/>'
        + para(f"<w:moveTo {A}>{run('Moved')}</w:moveTo>", mark("moveTo"))
        + '<w:moveToRangeEnd w:id="11"/>'
        + para(run("C"))
    )
    path = make_docx(body)
    accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
    assert lines(accepted) == ["A", "B", "Moved", "C"]  # no empty paragraph at the old place
    assert lines(rejected) == ["A", "Moved", "B", "C"]
    assert leftovers(accepted) == leftovers(rejected) == []


@pytest.mark.parametrize(
    ("resolve", "gone"), [(accept_all, "del"), (reject_all, "ins")], ids=["accept", "reject"]
)
def test_marks_join_in_a_chain_and_take_the_markup_between_along(
    make_docx: MakeDocx, resolve: Resolve, gone: str
) -> None:
    body = (
        para(run("1"), mark(gone))
        + '<w:bookmarkStart w:id="0" w:name="here"/>'
        + para(run("2"), '<w:jc w:val="center"/>' + mark(gone))
        + '<w:bookmarkEnd w:id="0"/>'
        + para(run("3"), '<w:jc w:val="both"/>')
    )
    pkg = resolved(make_docx(body), resolve)
    assert lines(pkg) == ["123"]
    joined = paragraph(pkg, "123")
    assert child_tags(joined) == ["pPr", "r", "bookmarkStart", "r", "bookmarkEnd", "r"]
    assert child_tags(joined.find("w:pPr", NS)) == ["jc"]
    assert joined.find("w:pPr/w:jc", NS).get(w("val")) == "both"


@pytest.mark.parametrize(
    ("resolve", "gone"), [(accept_all, "del"), (reject_all, "ins")], ids=["accept", "reject"]
)
def test_a_mark_with_no_paragraph_after_it_stays(
    make_docx: MakeDocx, resolve: Resolve, gone: str
) -> None:
    # Word never writes these (the last mark of a cell or of the document cannot be taken out),
    # but a file may: the paragraph keeps its mark and loses the revision.
    def table(text: str) -> str:
        cell = para(run(text), mark(gone))
        return f"<w:tbl><w:tblPr/><w:tblGrid/><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"

    texts = ["Last in its cell", "Before a table", "Second table", "Last of the body"]
    body = (
        table(texts[0])
        + para(run(texts[1]), mark(gone))
        + table(texts[2])
        + para(run(texts[3]), mark(gone))
    )
    pkg = resolved(make_docx(body), resolve)
    assert lines(pkg) == texts
    assert leftovers(pkg) == []


@SIDES
def test_a_mark_inserted_then_deleted_joins_on_both_sides(
    make_docx: MakeDocx, resolve: Resolve
) -> None:
    body = para(run("Gone mark, "), mark("ins", "del")) + para(run("next"))
    assert lines(resolved(make_docx(body), resolve)) == ["Gone mark, next"]


def test_a_paragraph_change_keeps_the_mark_and_the_section_break(make_docx: MakeDocx) -> None:
    # The old paragraph properties cannot hold the mark's run properties nor a section break,
    # and old section properties cannot name headers or footers: those stay as they are.
    props = (
        '<w:jc w:val="center"/><w:rPr><w:b/></w:rPr>'
        '<w:sectPr><w:headerReference w:type="default" r:id="rId1"/>'
        f'<w:pgSz w:w="11906" w:h="16838"/><w:sectPrChange {A}><w:sectPr>'
        '<w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:sectPrChange></w:sectPr>'
        f'<w:pPrChange {B}><w:pPr><w:jc w:val="left"/><w:ind w:left="720"/></w:pPr>'
        "</w:pPrChange>"
    )
    path = make_docx(
        para(run("Section one"), props) + para(run("Section two")),
        parts={"word/header1.xml": para(run("Header"))},
    )
    accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
    first = paragraph(accepted, "Section one").find("w:pPr", NS)
    assert child_tags(first) == ["jc", "rPr", "sectPr"]
    assert child_tags(first.find("w:sectPr", NS)) == ["headerReference", "pgSz"]
    assert first.find("w:sectPr/w:pgSz", NS).get(w("w")) == "11906"
    first = paragraph(rejected, "Section one").find("w:pPr", NS)
    assert child_tags(first) == ["jc", "ind", "rPr", "sectPr"]
    assert first.find("w:jc", NS).get(w("val")) == "left"
    assert first.find("w:rPr/w:b", NS) is not None
    assert child_tags(first.find("w:sectPr", NS)) == ["headerReference", "pgSz"]
    assert first.find("w:sectPr/w:pgSz", NS).get(w("w")) == "12240"
    assert lines(accepted) == lines(rejected) == ["Section one", "Section two", "Header"]


def test_a_change_record_without_old_properties(make_docx: MakeDocx) -> None:
    # No old properties means none before: the element goes, unless the file needs it (a
    # table's properties) or it still holds what the record does not cover (the mark).
    body = (
        f'<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:i/></w:rPr><w:pPrChange {A}/></w:pPr>'
        f"<w:r><w:rPr><w:b/><w:rPrChange {A}/></w:rPr><w:t>Plain before</w:t></w:r></w:p>"
        # the mark's formatting and the paragraph's both changed from nothing
        f'<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:b/><w:rPrChange {A}><w:rPr/>'
        f"</w:rPrChange></w:rPr><w:pPrChange {B}><w:pPr/></w:pPrChange></w:pPr>"
        f"{run('Nothing before')}</w:p>"
        f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblPrChange {A}/></w:tblPr>'
        f"<w:tblGrid/><w:tr><w:trPr><w:cantSplit/><w:trPrChange {A}/></w:trPr>"
        f'<w:tc><w:tcPr><w:shd w:val="clear" w:fill="FFFF00"/><w:tcPrChange {A}/></w:tcPr>'
        f"{para(run('Cell'))}</w:tc></w:tr></w:tbl>{para('')}"
    )
    path = make_docx(body)
    rejected = resolved(path, reject_all)
    root = rejected.xml("word/document.xml")
    first = paragraph(rejected, "Plain before")
    assert child_tags(first.find("w:pPr", NS)) == ["rPr"]
    assert first.find("w:r/w:rPr", NS) is None
    assert child_tags(paragraph(rejected, "Nothing before")) == ["r"]
    assert child_tags(root.find(".//w:tbl", NS)) == ["tblPr", "tblGrid", "tr"]
    assert len(root.find(".//w:tblPr", NS)) == 0
    assert child_tags(root.find(".//w:tr", NS)) == ["tc"]
    assert child_tags(root.find(".//w:tc", NS)) == ["p"]
    accepted = resolved(path, accept_all)
    root = accepted.xml("word/document.xml")
    assert child_tags(paragraph(accepted, "Plain before").find("w:pPr", NS)) == ["jc", "rPr"]
    assert child_tags(paragraph(accepted, "Nothing before").find("w:pPr", NS)) == ["jc", "rPr"]
    assert child_tags(root.find(".//w:tblPr", NS)) == ["tblW"]
    assert child_tags(root.find(".//w:trPr", NS)) == ["cantSplit"]
    assert child_tags(root.find(".//w:tcPr", NS)) == ["shd"]
    assert leftovers(accepted) == leftovers(rejected) == []


def test_revision_marks_inside_old_properties_are_not_brought_back(make_docx: MakeDocx) -> None:
    # The marks of the current properties say what was inserted or deleted; a mark kept inside
    # the old properties of a change record (some only a damaged file has) does not come back
    # when the record is rejected, and does not remove the paragraph, row or cell it sits in.
    body = (
        f"<w:p><w:pPr><w:rPr><w:b/><w:rPrChange {A}><w:rPr><w:ins {B}/></w:rPr></w:rPrChange>"
        f"</w:rPr></w:pPr>{run('Mark')}</w:p>"
        f'<w:p><w:pPr><w:pPrChange {A}><w:pPr><w:numPr><w:numId w:val="1"/>'
        f'<w:numberingChange {B} w:original="%1."/></w:numPr></w:pPr></w:pPrChange></w:pPr>'
        f"{run('Next')}</w:p>"
        f"<w:tbl><w:tblPr/><w:tblGrid/><w:tr>"
        f"<w:trPr><w:cantSplit/><w:trPrChange {A}><w:trPr><w:ins {B}/></w:trPr></w:trPrChange>"
        f'</w:trPr><w:tc><w:tcPr><w:shd w:val="clear" w:fill="FF0000"/>'
        f"<w:tcPrChange {A}><w:tcPr><w:cellIns {B}/></w:tcPr></w:tcPrChange></w:tcPr>"
        f"{para(run('Cell'))}</w:tc></w:tr></w:tbl>{para('')}"
    )
    path = make_docx(body)
    accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
    for pkg in (accepted, rejected):
        assert lines(pkg) == ["Mark", "Next", "Cell", ""]
        assert leftovers(pkg) == []
    assert child_tags(paragraph(rejected, "Next").find("w:pPr/w:numPr", NS)) == ["numId"]
    row = rejected.xml("word/document.xml").find(".//w:tr", NS)
    assert child_tags(row) == ["tc"] and child_tags(row.find("w:tc", NS)) == ["p"]
    row = accepted.xml("word/document.xml").find(".//w:tr", NS)
    assert child_tags(row.find("w:trPr", NS)) == ["cantSplit"]
    assert child_tags(row.find("w:tc/w:tcPr", NS)) == ["shd"]


def test_marks_that_hold_no_text(make_docx: MakeDocx) -> None:
    # An inserted numbering (w:numPr/w:ins) goes on both sides, the numbering staying; the
    # properties of a math control character inserted or deleted are kept or dropped like text.
    math = "http://schemas.openxmlformats.org/officeDocument/2006/math"

    def control(kind: str) -> str:
        return (
            f'<m:oMath xmlns:m="{math}"><m:r><m:t>x</m:t></m:r>'
            f"<m:ctrlPr><w:{kind} {A}><w:rPr><w:b/></w:rPr></w:{kind}></m:ctrlPr></m:oMath>"
        )

    body = (
        para(run("Numbered"), f'<w:numPr><w:numId w:val="1"/><w:ins {A}/></w:numPr>')
        + para(control("ins"))
        + para(control("del"))
    )
    path = make_docx(body)
    for resolve, inserted, deleted in ((accept_all, ["rPr"], []), (reject_all, [], ["rPr"])):
        pkg = resolved(path, resolve)
        assert child_tags(paragraph(pkg, "Numbered").find("w:pPr/w:numPr", NS)) == ["numId"]
        controls = pkg.xml("word/document.xml").iter(f"{{{math}}}ctrlPr")
        assert [child_tags(c) for c in controls] == [inserted, deleted]
        assert leftovers(pkg) == []


@pytest.mark.parametrize(
    ("kind", "resolve", "left"),
    [
        ("ins", reject_all, ["Before", "After"]),
        ("ins", accept_all, ["Before", "Row 1", "Row 2", "After"]),
        ("del", accept_all, ["Before", "After"]),
        ("del", reject_all, ["Before", "Row 1", "Row 2", "After"]),
    ],
)
def test_a_whole_table_inserted_or_deleted(
    make_docx: MakeDocx, kind: str, resolve: Resolve, left: list[str]
) -> None:
    # Word marks every row of the table, and the content and the mark of every cell.
    def row(text: str) -> str:
        content = run(text) if kind == "ins" else deleted_run(text)
        cell = para(f"<w:{kind} {A}>{content}</w:{kind}>", mark(kind))
        return f"<w:tr><w:trPr><w:{kind} {A}/></w:trPr><w:tc>{cell}</w:tc></w:tr>"

    table = f"<w:tbl><w:tblPr/><w:tblGrid/>{row('Row 1')}{row('Row 2')}</w:tbl>"
    pkg = resolved(make_docx(para(run("Before")) + table + para(run("After"))), resolve)
    assert lines(pkg) == left
    tables = pkg.xml("word/document.xml").findall(".//w:tbl", NS)
    assert len(tables) == (1 if "Row 1" in left else 0)  # a table with no rows left goes too
    assert leftovers(pkg) == []


@SIDES
def test_a_row_left_without_cells_goes(make_docx: MakeDocx, resolve: Resolve) -> None:
    cell_mark = "cellDel" if resolve is accept_all else "cellIns"
    gone = f"<w:tc><w:tcPr><w:{cell_mark} {A}/></w:tcPr>{para(run('Gone cell'))}</w:tc>"
    body = (
        f"<w:tbl><w:tblPr/><w:tblGrid/><w:tr><w:tc>{para(run('Kept'))}</w:tc></w:tr>"
        f"<w:tr>{gone}</w:tr></w:tbl>"
        f"<w:tbl><w:tblPr/><w:tblGrid/><w:tr>{gone}</w:tr></w:tbl>{para(run('After'))}"
    )
    pkg = resolved(make_docx(body), resolve)
    assert lines(pkg) == ["Kept", "After"]
    root = pkg.xml("word/document.xml")
    assert len(root.findall(".//w:tbl", NS)) == 1 and len(root.findall(".//w:tr", NS)) == 1


def test_every_text_part_and_only_those(make_docx: MakeDocx) -> None:
    change = para(run("Note: ") + f"<w:del {A}>{deleted_run('secret')}</w:del>")
    change += para(f"<w:ins {B}>{run('public')}</w:ins>")
    path = make_docx(
        para(run("Body")),
        parts={
            "word/footnotes.xml": f'<w:footnote w:id="1">{change}</w:footnote>',
            "word/endnotes.xml": f'<w:endnote w:id="1">{change}</w:endnote>',
            "word/footer2.xml": change,
            "word/comments.xml": f'<w:comment w:id="0">{change}</w:comment>',
        },
    )
    comments = DocxPackage.open(path).raw("word/comments.xml")
    accepted, rejected = resolved(path, accept_all), resolved(path, reject_all)
    # document, footer, footnotes, endnotes; the comments, removed before masking, are not text
    assert lines(accepted) == ["Body", *["Note: ", "public"] * 3]
    assert lines(rejected) == ["Body", *["Note: secret", ""] * 3]
    assert accept_all(DocxPackage.open(path)) == 6
    assert accepted.raw("word/comments.xml") == comments
