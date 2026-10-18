"""The text map: which text a Word file holds in each view, and where every character of it lives.

Later steps find values in ``DocText.text`` and change the XML through the map, so a text node the
map misses is text that cannot be masked. Besides the corpus, small hand-written paragraphs cover
what the corpus does not have: fields, tabs and breaks, nested tables, content controls, moves.
"""

from __future__ import annotations

import json
import time
from itertools import pairwise
from pathlib import Path

import pytest

from tests.fixtures.docx import MakeDocx, paragraph
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import (
    extract_text,
    has_comments,
    has_revisions,
    paragraph_nodes,
)

W = NS["w"]
VIEWS = ("accepted", "rejected")


def p(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


# ---- the corpus ------------------------------------------------------------------------------


def test_extract_text_covers_all_parts(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    dt = extract_text(pkg)
    assert {s.part for s in dt.segments} >= {
        "word/document.xml",
        "word/header1.xml",
        "word/footer1.xml",
    }
    assert "Confidential" in dt.text


def test_views(corpus: Path) -> None:
    # supply-03 has tracked changes with a secret only in deleted text.
    pkg = DocxPackage.open(corpus / "supply-03.docx")
    truth = json.loads((corpus / "supply-03.truth.json").read_text())
    deleted = next(t["value"] for t in truth if t.get("only_in_deletion"))
    assert deleted not in extract_text(pkg, "accepted").text
    assert deleted in extract_text(pkg, "rejected").text
    assert has_revisions(pkg)


def test_split_runs_map_back(corpus: Path) -> None:
    # supply-01 writes "Northwind Trading B.V." across three runs.
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    dt = extract_text(pkg)
    i = dt.text.index("Northwind Trading B.V.")
    seg = next(s for s in dt.segments if s.start <= i < s.end)
    text, nodes = paragraph_nodes(seg.para, "accepted")
    lo, hi = i - seg.start, i - seg.start + len("Northwind Trading B.V.")
    covering = [n for n in nodes if n.start < hi and n.end > lo]
    assert text[lo:hi] == "Northwind Trading B.V." and len(covering) >= 3


def test_offsets_round_trip(corpus: Path) -> None:
    for path in sorted(corpus.glob("*.docx")):
        pkg = DocxPackage.open(path)
        for view in VIEWS:
            dt = extract_text(pkg, view)
            assert dt.segments[0].start == 0 and dt.segments[-1].end == len(dt.text), path.name
            for before, after in pairwise(dt.segments):
                assert after.start == before.end + 1 and dt.text[before.end] == "\n"
            for s in dt.segments:
                text, nodes = paragraph_nodes(s.para, view)
                assert dt.text[s.start : s.end] == text, (path.name, view, text)
                for n in nodes:
                    assert text[n.start : n.end] == (n.elem.text or "")


def test_every_text_node_is_mapped_exactly_once(corpus: Path) -> None:
    # Worked out without the walk: every w:t and w:instrText (rejected: w:delText and
    # w:delInstrText too) outside the other view's changes and outside mc:Fallback is the node of
    # exactly one segment, and nothing else is.
    fallback = f"{{{NS['mc']}}}Fallback"
    for path in sorted(corpus.glob("*.docx")):
        pkg = DocxPackage.open(path)
        for view, kinds, others in (
            ("accepted", ("t", "instrText"), ("del", "moveFrom")),
            ("rejected", ("t", "instrText", "delText", "delInstrText"), ("ins", "moveTo")),
        ):
            outside = {fallback, *(f"{{{W}}}{o}" for o in others)}
            expected = [
                e
                for part in pkg.TEXT_PARTS
                for e in pkg.xml(part).iter(*(f"{{{W}}}{k}" for k in kinds))
                if not any(a.tag in outside for a in e.iterancestors())
            ]
            mapped = [
                n.elem
                for s in extract_text(pkg, view).segments
                for n in paragraph_nodes(s.para, view)[1]
            ]
            assert len(mapped) == len(set(mapped)), (path.name, view)
            assert set(mapped) == set(expected), (path.name, view)


def test_every_truth_value_is_in_its_view(corpus: Path) -> None:
    # Hidden text is part of the text (the cleaner removes it later); deleted text only shows
    # when the changes are rejected.
    for path in sorted(corpus.glob("*.docx")):
        pkg = DocxPackage.open(path)
        accepted = extract_text(pkg, "accepted").text
        rejected = extract_text(pkg, "rejected").text
        for t in json.loads(path.with_suffix(".truth.json").read_text(encoding="utf-8")):
            forms = [t["value"], *t["variants"]]
            if t.get("only_in_deletion"):
                assert t["value"] not in accepted, (path.name, t["value"])
                assert all(f in rejected for f in forms), (path.name, forms)
            else:
                assert all(f in accepted for f in forms), (path.name, forms)


def test_text_box_is_read_once(corpus: Path) -> None:
    # Word stores a text box twice: DrawingML in mc:Choice, VML in mc:Fallback (ruling R16).
    for name in ("services-03.docx", "nda-04.docx", "dpa-03.docx"):
        dt = extract_text(DocxPackage.open(corpus / name))
        assert dt.text.count("Text box note") == 1, name
        seg = next(s for s in dt.segments if "Text box note" in dt.text[s.start : s.end])
        assert next(seg.para.iterancestors(f"{{{NS['mc']}}}Choice"), None) is not None


def test_footnotes_and_running_heads(corpus: Path) -> None:
    dt = extract_text(DocxPackage.open(corpus / "supply-06.docx"))
    with_acme = {s.part for s in dt.segments if "Acme" in dt.text[s.start : s.end]}
    assert {"word/header1.xml", "word/footer1.xml", "word/footnotes.xml"} <= with_acme


def test_thirty_pages_are_read_quickly(corpus: Path) -> None:
    started = time.perf_counter()
    dt = extract_text(DocxPackage.open(corpus / "supply-10.docx"))
    assert time.perf_counter() - started < 2
    assert len(dt.text.split()) > 12000


# ---- paragraphs written by hand --------------------------------------------------------------


def test_tabs_breaks_and_hyphens() -> None:
    para = paragraph(
        '<w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'  # a tab stop, no text
        "<w:r><w:t>Name:</w:t><w:tab/><w:t>John</w:t><w:br/><w:t>Smith</w:t><w:cr/></w:r>"
        "<w:r><w:t>co</w:t><w:noBreakHyphen/><w:t>op</w:t><w:softHyphen/><w:t>er</w:t><w:t/>"
        '<w:br w:type="page"/><w:t>ate</w:t></w:r>'
    )
    text, nodes = paragraph_nodes(para, "accepted")
    assert text == "Name:\tJohn\nSmith\nco\N{NON-BREAKING HYPHEN}oper\nate"
    assert [(n.start, n.end) for n in nodes] == [
        (0, 5),
        (6, 10),
        (11, 16),
        (17, 19),
        (20, 22),
        (22, 24),
        (24, 24),  # an empty w:t is still a node of the map
        (25, 28),
    ]
    assert {n.kind for n in nodes} == {"t"}
    assert all(text[n.start : n.end] == (n.elem.text or "") for n in nodes)


def test_field_instructions_are_nodes_of_their_own_kind() -> None:
    para = paragraph(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> HYPERLINK "mailto:jane@acme.example" '
        "</w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>jane@acme.example</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    text, nodes = paragraph_nodes(para, "accepted")
    assert text == ' HYPERLINK "mailto:jane@acme.example" jane@acme.example'
    assert [n.kind for n in nodes] == ["instr", "t"]
    assert nodes[0].elem.tag == f"{{{W}}}instrText" and nodes[1].elem.tag == f"{{{W}}}t"


# Every kind of container, each holding one letter, and markers that hold none.
CONTAINERS = (
    '<w:pPr><w:rPr><w:ins w:id="1" w:author="A"/></w:rPr></w:pPr>'  # an inserted paragraph mark
    '<w:bookmarkStart w:id="0" w:name="start"/><w:proofErr w:type="spellStart"/>'
    '<w:hyperlink r:id="rId1"><w:r><w:t>A</w:t></w:r></w:hyperlink>'
    '<w:sdt><w:sdtPr><w:alias w:val="Party"/></w:sdtPr>'
    "<w:sdtContent><w:r><w:t>B</w:t></w:r></w:sdtContent></w:sdt>"
    '<w:smartTag w:uri="urn:example" w:element="place">'
    '<w:smartTagPr><w:attr w:name="n" w:val="v"/></w:smartTagPr>'
    "<w:r><w:t>C</w:t></w:r></w:smartTag>"
    '<w:fldSimple w:instr="PAGE"><w:r><w:t>D</w:t></w:r></w:fldSimple>'
    '<w:customXml w:element="party"><w:r><w:t>E</w:t></w:r></w:customXml>'
    '<w:ins w:id="2" w:author="A"><w:r><w:t>F</w:t></w:r></w:ins>'
    '<w:moveTo w:id="3" w:author="A"><w:r><w:t>G</w:t></w:r></w:moveTo>'
    '<w:del w:id="4" w:author="A"><w:r><w:delText>H</w:delText></w:r></w:del>'
    '<w:moveFrom w:id="5" w:author="A"><w:r><w:delText>I</w:delText></w:r></w:moveFrom>'
    '<w:del w:id="6" w:author="A"><w:r><w:delInstrText> PAGE </w:delInstrText></w:r></w:del>'
    '<w:dir w:val="rtl"><w:r><w:t>J</w:t></w:r></w:dir>'  # a container the list does not name
    '<w:r><w:rPr><w:b/><w:rPrChange w:id="7" w:author="A"><w:rPr/></w:rPrChange></w:rPr>'
    "<w:t>K</w:t></w:r>"
    '<w:bookmarkEnd w:id="0"/>'
)


def test_every_container_is_walked_in_both_views() -> None:
    para = paragraph(CONTAINERS)
    accepted, accepted_nodes = paragraph_nodes(para, "accepted")
    rejected, rejected_nodes = paragraph_nodes(para, "rejected")
    assert accepted == "ABCDEFGJK"
    assert rejected == "ABCDEHI PAGE JK"
    assert [n.kind for n in accepted_nodes] == ["t"] * 9
    assert [n.kind for n in rejected_nodes] == ["t"] * 7 + ["instr", "t", "t"]
    assert [n.elem.tag.split("}")[1] for n in rejected_nodes][5:8] == [
        "delText",
        "delText",
        "delInstrText",
    ]


def test_deleted_text_is_only_in_the_rejected_view_wherever_it_is() -> None:
    # Even deleted text left outside its w:del, as a damaged file might have it.
    para = paragraph("<w:r><w:t>kept</w:t><w:delText> stray</w:delText></w:r>")
    assert paragraph_nodes(para, "accepted")[0] == "kept"
    assert paragraph_nodes(para, "rejected")[0] == "kept stray"


def test_changes_inside_changes() -> None:
    para = paragraph(
        '<w:hyperlink r:id="rId1"><w:ins w:id="1" w:author="A"><w:r><w:t>new</w:t></w:r></w:ins>'
        "</w:hyperlink>"
        # inserted by one reviewer, then deleted by another: gone in both views
        '<w:ins w:id="2" w:author="A"><w:del w:id="3" w:author="B">'
        "<w:r><w:delText>short-lived</w:delText></w:r></w:del></w:ins>"
    )
    assert paragraph_nodes(para, "accepted")[0] == "new"
    assert paragraph_nodes(para, "rejected")[0] == ""


def test_only_the_choice_of_alternate_content_is_read() -> None:
    para = paragraph(
        '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:t>new</w:t></mc:Choice>'
        "<mc:Fallback><w:t>old</w:t></mc:Fallback></mc:AlternateContent></w:r>"
        '<mc:AlternateContent><mc:Choice Requires="w14"><w:r><w:t>X</w:t></w:r></mc:Choice>'
        "<mc:Fallback><w:r><w:t>Y</w:t></w:r></mc:Fallback></mc:AlternateContent>"
    )
    text, nodes = paragraph_nodes(para, "accepted")
    assert text == "newX" and len(nodes) == 2


def test_runs_inside_other_run_content_are_read() -> None:
    # A phonetic guide holds runs of its own inside the run it annotates.
    para = paragraph(
        "<w:r><w:ruby><w:rubyPr/><w:rt><w:r><w:t>Tokyo</w:t></w:r></w:rt>"
        "<w:rubyBase><w:r><w:t>Tōkyō</w:t></w:r></w:rubyBase></w:ruby></w:r>"
    )
    assert paragraph_nodes(para, "accepted")[0] == "TokyoTōkyō"


def test_unknown_view_is_refused(corpus: Path) -> None:
    with pytest.raises(ValueError):
        paragraph_nodes(paragraph(""), "final")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        extract_text(DocxPackage.open(corpus / "supply-01.docx"), "final")  # type: ignore[arg-type]


# ---- documents written by hand ---------------------------------------------------------------

TEXT_BOX = (
    '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor><a:graphic>'
    "<a:graphicData><wps:wsp><wps:txbx><w:txbxContent>{inside}</w:txbxContent></wps:txbx>"
    "</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
    "<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>{inside}</w:txbxContent>"
    "</v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>"
)


def test_text_box_paragraphs_follow_the_paragraph_they_sit_in(make_docx: MakeDocx) -> None:
    box = TEXT_BOX.format(inside=p("In the box"))
    path = make_docx(
        f'<w:p><w:r><w:t xml:space="preserve">Before </w:t></w:r>{box}'
        f"<w:r><w:t>after</w:t></w:r></w:p>{p('Next')}"
    )
    dt = extract_text(DocxPackage.open(path))
    assert dt.text == "Before after\nIn the box\nNext"


def test_a_text_box_without_a_modern_copy_is_read(make_docx: MakeDocx) -> None:
    # Older files have the VML text box on its own, outside any mc:AlternateContent.
    vml = f"<w:r><w:pict><v:shape><v:textbox><w:txbxContent>{p('Old box')}</w:txbxContent>"
    vml += "</v:textbox></v:shape></w:pict></w:r>"
    dt = extract_text(DocxPackage.open(make_docx(f"<w:p>{vml}</w:p>")))
    assert dt.text == "\nOld box"


def test_tables_nested_tables_and_content_controls(make_docx: MakeDocx) -> None:
    def cell(content: str) -> str:
        return f"<w:tc><w:tcPr/>{content}</w:tc>"

    inner = f"<w:tbl><w:tr>{cell(p('Inner 1'))}{cell(p('Inner 2'))}</w:tr></w:tbl>"
    body = (
        p("Before")
        + "<w:tbl><w:tblPr/>"
        + f"<w:tr>{cell(p('A1'))}{cell(p('B1') + inner + p('B1 after'))}</w:tr>"
        + f"<w:tr>{cell(p('A2'))}<w:sdt><w:sdtContent>{cell(p('B2'))}</w:sdtContent></w:sdt></w:tr>"
        + "</w:tbl>"
        + f"<w:sdt><w:sdtPr/><w:sdtContent>{p('In a content control')}</w:sdtContent></w:sdt>"
        + p("After")
    )
    dt = extract_text(DocxPackage.open(make_docx(body)))
    assert dt.text.split("\n") == [
        "Before",
        "A1",
        "B1",
        "Inner 1",
        "Inner 2",
        "B1 after",
        "A2",
        "B2",
        "In a content control",
        "After",
    ]


def test_empty_paragraphs_keep_their_place(make_docx: MakeDocx) -> None:
    dt = extract_text(DocxPackage.open(make_docx(f"<w:p/>{p('A')}<w:p/><w:p/>{p('B')}")))
    assert dt.text == "\nA\n\n\nB"
    assert [(s.start, s.end) for s in dt.segments] == [(0, 0), (1, 2), (3, 3), (4, 4), (5, 6)]


def test_parts_in_order_and_comments_left_out(make_docx: MakeDocx) -> None:
    path = make_docx(
        p("Body"),
        parts={
            "word/footer1.xml": p("Footer 1"),
            "word/header2.xml": p("Header 2"),
            "word/header1.xml": p("Header 1"),
            "word/endnotes.xml": f'<w:endnote w:id="1">{p("Endnote")}</w:endnote>',
            "word/footnotes.xml": f'<w:footnote w:id="1">{p("Footnote")}</w:footnote>',
            "word/comments.xml": f'<w:comment w:id="0">{p("A comment")}</w:comment>',
        },
    )
    dt = extract_text(DocxPackage.open(path))
    assert dt.text.split("\n") == [
        "Body",
        "Header 1",
        "Header 2",
        "Footer 1",
        "Footnote",
        "Endnote",
    ]
    assert [s.part for s in dt.segments] == [
        "word/document.xml",
        "word/header1.xml",
        "word/header2.xml",
        "word/footer1.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
    ]


# ---- revisions and comments ------------------------------------------------------------------

A = 'w:id="1" w:author="A"'
TABLE = "<w:tbl>{tbl}<w:tr>{tr}<w:tc>{tc}<w:p/></w:tc></w:tr></w:tbl>"
NUMBERED = "<w:numPr><w:ilvl w:val='0'/><w:numId w:val='1'/>{change}</w:numPr>"
# One document for each kind of revision, holding nothing else.
REVISIONS = {
    "ins": f"<w:p><w:ins {A}><w:r><w:t>x</w:t></w:r></w:ins></w:p>",
    "del": f"<w:p><w:del {A}><w:r><w:delText>x</w:delText></w:r></w:del></w:p>",
    "moveFrom": f"<w:p><w:moveFrom {A}><w:r><w:delText>x</w:delText></w:r></w:moveFrom></w:p>",
    "moveTo": f"<w:p><w:moveTo {A}><w:r><w:t>x</w:t></w:r></w:moveTo></w:p>",
    "rPrChange": (
        f"<w:p><w:r><w:rPr><w:b/><w:rPrChange {A}><w:rPr/></w:rPrChange></w:rPr></w:r></w:p>"
    ),
    "pPrChange": (
        f"<w:p><w:pPr><w:jc w:val='left'/><w:pPrChange {A}><w:pPr/></w:pPrChange></w:pPr></w:p>"
    ),
    "sectPrChange": f"<w:p/><w:sectPr><w:sectPrChange {A}><w:sectPr/></w:sectPrChange></w:sectPr>",
    "tblPrChange": TABLE.format(
        tbl=f"<w:tblPr><w:tblPrChange {A}><w:tblPr/></w:tblPrChange></w:tblPr>", tr="", tc=""
    ),
    "trPrChange": TABLE.format(
        tbl="", tr=f"<w:trPr><w:trPrChange {A}><w:trPr/></w:trPrChange></w:trPr>", tc=""
    ),
    "tcPrChange": TABLE.format(
        tbl="", tr="", tc=f"<w:tcPr><w:tcPrChange {A}><w:tcPr/></w:tcPrChange></w:tcPr>"
    ),
    "numberingChange": "<w:p><w:pPr>"
    + NUMBERED.format(change=f"<w:numberingChange {A} w:original='%1.'/>")
    + "</w:pPr></w:p>",
}


@pytest.mark.parametrize("body", REVISIONS.values(), ids=list(REVISIONS))
def test_has_revisions_finds_every_kind(make_docx: MakeDocx, body: str) -> None:
    assert has_revisions(DocxPackage.open(make_docx(body)))


def test_has_revisions_looks_in_every_text_part_and_only_there(
    make_docx: MakeDocx, corpus: Path
) -> None:
    change = f"<w:p><w:ins {A}><w:r><w:t>x</w:t></w:r></w:ins></w:p>"
    assert has_revisions(DocxPackage.open(make_docx(p("Body"), parts={"word/footer3.xml": change})))
    in_comment = f'<w:comment w:id="0">{change}</w:comment>'  # comments are not text parts
    assert not has_revisions(
        DocxPackage.open(make_docx(p("Body"), parts={"word/comments.xml": in_comment}))
    )
    assert not has_revisions(DocxPackage.open(corpus / "supply-01.docx"))


def test_has_comments(corpus: Path, make_docx: MakeDocx) -> None:
    assert has_comments(DocxPackage.open(corpus / "supply-02.docx"))
    assert not has_comments(DocxPackage.open(corpus / "supply-01.docx"))
    pkg = DocxPackage.open(corpus / "supply-02.docx")
    pkg.remove_part("word/comments.xml")
    assert has_comments(pkg)  # the references in the text are still there
    assert has_comments(DocxPackage.open(make_docx(p("Body"), parts={"word/comments.xml": ""})))
    reference = '<w:p><w:r><w:commentReference w:id="0"/></w:r></w:p>'
    assert has_comments(
        DocxPackage.open(make_docx(p("Body"), parts={"word/header1.xml": reference}))
    )
