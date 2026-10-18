"""The masker: placeholders written into the Word XML where the text map says the values are.

The brief's tests run on the corpus. Hand-written paragraphs and documents cover what the corpus
does not have: a value across differently formatted runs, tabs and breaks inside a value, text
boxes, field instructions, bookmarks, and links in a header. The last test masks every corpus file
with its truth values and reads it back: the text must be the original text with exactly the
planned stretches replaced, and the paragraphs, tables, numbering and styles must not move.
"""

from __future__ import annotations

import itertools
import json
import random
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from xml.sax.saxutils import escape, quoteattr

import docx
import pytest
from lxml import etree

from tests.fixtures.docx import PACKAGE_RELS, MakeDocx, paragraph
from themask.docx import masker
from themask.docx.masker import (
    MaskReport,
    apply_mask,
    insert_banner,
    neutral_name,
    new_case_code,
)
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import DocText, extract_text, paragraph_nodes
from themask.docx.restorer import replace_in_paragraph
from themask.instruction import BANNER_TEXT
from themask.model import MaskPlan, Replacement
from themask.textnorm import flexible_pattern, normalize

W = NS["w"]
R = NS["r"]
XML_SPACE = f"{{{NS['xml']}}}space"
HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def plan_for(dt: DocText, value: str, ph: str) -> MaskPlan:
    return MaskPlan(
        [Replacement(m.start(), m.end(), ph) for m in re.finditer(re.escape(value), dt.text)]
    )


def plan_of(dt: DocText, placeholders: dict[str, str]) -> MaskPlan:
    """Every occurrence of each value (written exactly so); of two that overlap, the longer."""
    return longest_first(
        dt.text,
        [
            (m.start(), m.end(), placeholder)
            for value, placeholder in placeholders.items()
            for m in re.finditer(re.escape(value), dt.text)
        ],
    )


def longest_first(text: str, found: list[tuple[int, int, str]]) -> MaskPlan:
    """The replacements ``found`` in ``text`` that do not overlap, the longer of two that do."""
    free = bytearray(b"\x01" * len(text))
    chosen = []
    for start, end, placeholder in sorted(found, key=lambda f: (f[0] - f[1], f[0])):
        if all(free[start:end]):
            free[start:end] = bytes(end - start)
            chosen.append(Replacement(start, end, placeholder))
    return MaskPlan(chosen)


def p(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def links(*targets: str) -> bytes:
    """A .rels part relating to each target as an external hyperlink, as rId1, rId2, ..."""
    rows = "".join(
        f'<Relationship Id="rId{n}" Type="{HYPERLINK}" Target="{target}" TargetMode="External"/>'
        for n, target in enumerate(targets, start=1)
    )
    xml = f'<Relationships xmlns="{PACKAGE_RELS}">{rows}</Relationships>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml).encode()


def runs(element: etree._Element) -> list[tuple[str, str]]:
    """Each run in ``element``: its text, and the names of its formatting properties."""
    return [
        (
            "".join(t.text or "" for t in r.iter(f"{{{W}}}t")),
            " ".join(etree.QName(prop).localname for prop in r.findall("w:rPr/*", NS)),
        )
        for r in element.iter(f"{{{W}}}r")
    ]


def children(element: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in element]


def text_of(para: etree._Element) -> str:
    return paragraph_nodes(para, "accepted")[0]


# ---- the brief -------------------------------------------------------------------------------


def test_cross_run_replacement(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    dt = extract_text(pkg)
    rep = apply_mask(pkg, dt, plan_for(dt, "Northwind Trading B.V.", "[COMPANY_1]"))
    t = extract_text(pkg).text
    assert "Northwind Trading B.V." not in t and t.count("[COMPANY_1]") == rep.replaced >= 3


def test_formatting_of_first_run_kept(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    dt = extract_text(pkg)
    apply_mask(pkg, dt, plan_for(dt, "Northwind Trading B.V.", "[COMPANY_1]"))
    r = pkg.xml("word/document.xml").xpath(
        ".//w:r[w:t[contains(text(),'[COMPANY_1]')]]", namespaces=NS
    )[0]
    assert r.find("w:rPr/w:b", NS) is not None  # the party name is bold in the parties clause


def test_header_footer_footnote(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-06.docx")
    dt = extract_text(pkg)
    apply_mask(pkg, dt, plan_for(dt, "Acme", "[COMPANY_2]"))
    for part in ("word/header1.xml", "word/footer1.xml", "word/footnotes.xml"):
        assert b"Acme" not in etree.tostring(pkg.xml(part))


def test_mailto_hyperlink_unwrapped(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "services-01.docx")
    dt = extract_text(pkg)
    truth = json.loads((corpus / "services-01.truth.json").read_text())
    email = next(t["value"] for t in truth if t["type"] == "EMAIL")
    rep = apply_mask(pkg, dt, plan_for(dt, email, "[EMAIL_1]"))
    assert rep.hyperlinks_unwrapped >= 1
    assert email.encode() not in pkg.raw("word/_rels/document.xml.rels")


def test_banner_first(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    insert_banner(pkg)
    assert extract_text(pkg).text.startswith(BANNER_TEXT)


def test_names() -> None:
    code = new_case_code(random.Random(1))
    assert len(code) == 4 and set(code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    assert neutral_name("K4F7") == "MASKED-K4F7.docx"
    assert neutral_name("K4F7", "before") == "MASKED-K4F7-before.docx"
    assert neutral_name("K4F7", "2") == "MASKED-K4F7-2.docx"


def test_numbering_intact(corpus: Path, tmp_path: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    dt = extract_text(pkg)
    apply_mask(pkg, dt, plan_for(dt, "Northwind Trading B.V.", "[COMPANY_1]"))
    pkg.save(tmp_path / "m.docx")
    d = docx.Document(str(tmp_path / "m.docx"))
    assert any(
        para.style.name.startswith("List")
        or para._p.pPr is not None
        and para._p.pPr.numPr is not None
        for para in d.paragraphs
    )


# ---- replacing in a paragraph ----------------------------------------------------------------

SPLIT_PARTY = (
    '<w:r><w:t xml:space="preserve">(1) </w:t></w:r>'
    '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">Northwind </w:t></w:r>'
    '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">Trading </w:t></w:r>'
    '<w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>B.V.</w:t></w:r>'
    "<w:r><w:t>, the Supplier</w:t></w:r>"
)  # "(1) Northwind Trading B.V., the Supplier"


def test_a_value_across_three_runs_takes_the_first_runs_formatting() -> None:
    para = paragraph(SPLIT_PARTY)
    assert replace_in_paragraph(para, "accepted", [(4, 26, "[COMPANY_1]")]) == 1
    # The bold run holds the placeholder; the italic and the underlined run are gone.
    assert runs(para) == [("(1) ", ""), ("[COMPANY_1]", "b"), (", the Supplier", "")]


def test_two_replacements_in_one_paragraph() -> None:
    para = paragraph(
        "<w:r><w:t>Acme and Northwind</w:t></w:r>"
        '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> Trading </w:t></w:r>'
        "<w:r><w:t>B.V. agree</w:t></w:r>"
    )  # "Acme and Northwind Trading B.V. agree"
    made = replace_in_paragraph(para, "accepted", [(0, 4, "[COMPANY_1]"), (9, 31, "[COMPANY_2]")])
    assert made == 2
    assert runs(para) == [("[COMPANY_1] and [COMPANY_2]", ""), (" agree", "")]
    touching = paragraph("<w:r><w:t>AcmeNorthwind</w:t></w:r>")
    assert replace_in_paragraph(touching, "accepted", [(0, 4, "[A]"), (4, 13, "[B]")]) == 2
    assert text_of(touching) == "[A][B]"


TABS_AND_BREAKS = (
    "<w:r><w:t>Signed:</w:t><w:tab/><w:t>John</w:t></w:r>"
    "<w:r><w:tab/></w:r>"
    "<w:r><w:rPr><w:b/></w:rPr><w:t>Smith</w:t><w:br/><w:t>Director</w:t></w:r>"
)  # "Signed:\tJohn\tSmith\nDirector"


@pytest.mark.parametrize(
    ("start", "end", "text", "left"),
    [
        # a tab inside the value, alone in its run: the run goes with it
        (8, 18, "Signed:\t[X]\nDirector", [("Signed:[X]", ""), ("Director", "b")]),
        # a value that starts with a tab
        (
            7,
            12,
            "Signed:[X]\tSmith\nDirector",
            [("Signed:[X]", ""), ("", ""), ("SmithDirector", "b")],
        ),
        # a line break inside the value
        (13, 27, "Signed:\tJohn\t[X]", [("Signed:John", ""), ("", ""), ("[X]", "b")]),
    ],
    ids=["tab inside", "tab first", "break inside"],
)
def test_tabs_and_breaks_inside_a_value_go_with_it(
    start: int, end: int, text: str, left: list[tuple[str, str]]
) -> None:
    para = paragraph(TABS_AND_BREAKS)
    assert replace_in_paragraph(para, "accepted", [(start, end, "[X]")]) == 1
    assert text_of(para) == text and runs(para) == left


def test_a_soft_hyphen_inside_a_value_goes_with_it_and_spaces_are_kept() -> None:
    para = paragraph("<w:r><w:t>North</w:t><w:softHyphen/><w:t>wind Ltd</w:t></w:r>")
    assert replace_in_paragraph(para, "accepted", [(0, 9, "[COMPANY_1]")]) == 1
    assert children(para.find("w:r", NS)) == ["t", "t"]
    assert text_of(para) == "[COMPANY_1] Ltd"
    # " Ltd" now starts with a space, which Word drops unless told to keep it.
    assert para.findall("w:r/w:t", NS)[1].get(XML_SPACE) == "preserve"
    # A soft hyphen just after the value is not part of it.
    after = paragraph("<w:r><w:t>Acme</w:t><w:softHyphen/><w:t>Ltd</w:t></w:r>")
    assert replace_in_paragraph(after, "accepted", [(0, 4, "[COMPANY_1]")]) == 1
    assert children(after.find("w:r", NS)) == ["t", "softHyphen", "t"]


def test_emptied_nodes_and_runs_are_removed() -> None:
    para = paragraph(
        "<w:r><w:t>Acme</w:t></w:r><w:r><w:t>Ltd and others</w:t></w:r>"
        '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> (draft)</w:t></w:r>'
    )  # "AcmeLtd and others (draft)"
    assert replace_in_paragraph(para, "accepted", [(0, 7, "[COMPANY_1]"), (18, 26, "")]) == 2
    assert runs(para) == [("[COMPANY_1]", ""), (" and others", "")]
    assert para.findall("w:r/w:t", NS)[1].get(XML_SPACE) == "preserve"


def test_only_the_text_of_the_view_is_changed() -> None:
    # Task 18 restores the AI's file in the accepted view: deleted text is left as it is.
    para = paragraph(
        '<w:r><w:t xml:space="preserve">Paid to </w:t></w:r>'
        '<w:ins w:id="1" w:author="A"><w:r><w:t>Acme</w:t></w:r></w:ins>'
        '<w:del w:id="2" w:author="A"><w:r><w:delText>Northwind</w:delText><w:tab/></w:r></w:del>'
        '<w:r><w:t xml:space="preserve"> Ltd today</w:t></w:r>'
    )
    assert text_of(para) == "Paid to Acme Ltd today"
    deleted = etree.tostring(para.find("w:del", NS))
    assert replace_in_paragraph(para, "accepted", [(8, 16, "[COMPANY_1]")]) == 1
    assert text_of(para) == "Paid to [COMPANY_1] today"
    assert para.findtext("w:ins/w:r/w:t", namespaces=NS) == "[COMPANY_1]"
    assert etree.tostring(para.find("w:del", NS)) == deleted


def test_a_stretch_without_text_is_left_alone() -> None:
    # A tab alone, or nothing at all (at the end, or inside a word): there is no character of
    # a w:t to put the new text in place of.
    para = paragraph("<w:r><w:t>A</w:t><w:tab/><w:t>Bcd</w:t></w:r>")
    before = etree.tostring(para)
    stretches = [(1, 2, "[X]"), (3, 3, "[Y]"), (5, 5, "[Z]")]
    assert replace_in_paragraph(para, "accepted", stretches) == 0
    assert etree.tostring(para) == before


@pytest.mark.parametrize(
    "replacements",
    [
        [(2, 4, "x"), (0, 1, "y")],
        [(0, 3, "x"), (2, 4, "y")],
        [(3, 2, "x")],
        [(0, 99, "x")],
        [(-1, 2, "x")],
    ],
    ids=["unsorted", "overlapping", "backwards", "past the end", "before the start"],
)
def test_bad_replacements_are_refused(replacements: list[tuple[int, int, str]]) -> None:
    para = paragraph("<w:r><w:t>Acme Ltd</w:t></w:r>")
    with pytest.raises(ValueError):
        replace_in_paragraph(para, "accepted", replacements)


# ---- masking a document ----------------------------------------------------------------------


def test_every_place_text_lives(make_docx: MakeDocx) -> None:
    box = (
        '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor>'
        "<a:graphic><a:graphicData><wps:wsp><wps:txbx><w:txbxContent>"
        f"{p('Acme in a text box')}</w:txbxContent></wps:txbx></wps:wsp></a:graphicData>"
        "</a:graphic></wp:anchor></w:drawing></mc:Choice></mc:AlternateContent></w:r></w:p>"
    )
    old_box = (  # a VML text box on its own, as older files have it
        "<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>"
        f"{p('Acme in an old text box')}</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>"
    )
    cell = f"<w:tbl><w:tr><w:tc><w:tcPr/>{p('Acme in a cell')}</w:tc></w:tr></w:tbl>"
    path = make_docx(
        cell + box + old_box,
        parts={
            "word/header1.xml": p("Acme in the header"),
            "word/footnotes.xml": f'<w:footnote w:id="1">{p("Acme in a footnote")}</w:footnote>',
        },
    )
    pkg = DocxPackage.open(path)
    dt = extract_text(pkg)
    report = apply_mask(pkg, dt, plan_for(dt, "Acme", "[COMPANY_1]"))
    assert report.replaced == 5
    assert extract_text(pkg).text == dt.text.replace("Acme", "[COMPANY_1]")
    assert all(b"Acme" not in pkg.raw(part) for part in pkg.TEXT_PARTS)


def test_a_field_instruction_is_masked_like_text(make_docx: MakeDocx) -> None:
    pkg = DocxPackage.open(
        make_docx(
            '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> HYPERLINK "mailto:jane@acme.example" '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t>jane@acme.example</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        )
    )
    dt = extract_text(pkg)
    report = apply_mask(pkg, dt, plan_for(dt, "jane@acme.example", "[EMAIL_1]"))
    assert report.replaced == 2
    root = pkg.xml("word/document.xml")
    instruction = root.find(".//w:instrText", NS)
    assert instruction.text == ' HYPERLINK "mailto:[EMAIL_1]" '
    assert instruction.get(XML_SPACE) == "preserve"
    assert root.xpath(".//w:r[w:rPr/w:rStyle]/w:t/text()", namespaces=NS) == ["[EMAIL_1]"]


def test_simple_field_instructions_are_masked(make_docx: MakeDocx) -> None:
    pkg = DocxPackage.open(
        make_docx(
            p("Notices to Acme Supplies Ltd (the Company), attn Jane Doe (jane.doe@acme.example).")
            + p("Acme replies within ten days.")
            + "<w:p><w:fldSimple w:instr=' HYPERLINK \"mailto:JANE.DOE@ACME.EXAMPLE\" '>"
            "<w:r><w:t>write to us</w:t></w:r></w:fldSimple></w:p>"
            + "<w:p><w:fldSimple w:instr=' QUOTE \"Acme   Supplies Ltd, the company\" '>"
            "<w:r><w:t>quoted</w:t></w:r></w:fldSimple></w:p>"
            + '<w:p><w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>'
        )
    )
    dt = extract_text(pkg)
    placeholders = {
        "Acme Supplies Ltd": "[COMPANY_1]",
        "Acme": "[COMPANY_1]",
        "Company": "[CUSTOM_1]",
        "Jane Doe": "[PERSON_1]",
        "jane.doe@acme.example": "[EMAIL_1]",
    }
    report = apply_mask(pkg, dt, plan_of(dt, placeholders))
    assert report.instr_fields_masked == 2
    fields = pkg.xml("word/document.xml").iter(f"{{{W}}}fldSimple")
    # Found whatever its case and spacing. Of values that overlap there, the one that starts
    # first and then the longer one is replaced ("Acme Supplies Ltd", not "Acme"; the e-mail
    # address, not the "ACME" in it). And the instruction is searched once, so "company" is not
    # looked for again inside the [COMPANY_1] just written.
    assert [f.get(f"{{{W}}}instr") for f in fields] == [
        ' HYPERLINK "mailto:[EMAIL_1]" ',
        ' QUOTE "[COMPANY_1], the [CUSTOM_1]" ',
        "PAGE",
    ]


def test_a_link_is_unwrapped_only_when_its_target_holds_a_value(make_docx: MakeDocx) -> None:
    body = (
        '<w:p><w:r><w:t xml:space="preserve">Ask </w:t></w:r>'
        '<w:hyperlink r:id="rId1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
        "<w:t>Jane Doe</w:t></w:r></w:hyperlink>"
        '<w:r><w:t xml:space="preserve"> for the forms or </w:t></w:r>'
        '<w:hyperlink r:id="rId2"><w:r><w:t>write to her</w:t></w:r></w:hyperlink></w:p>'
    )
    targets = links("https://forms.example.org/", "mailto:jane.doe@acme.example")
    pkg = DocxPackage.open(make_docx(body, raw={"word/_rels/document.xml.rels": targets}))
    dt = extract_text(pkg)
    report = apply_mask(pkg, dt, plan_for(dt, "Jane Doe", "[PERSON_1]"))
    assert report == MaskReport(
        replaced=1, hyperlinks_unwrapped=1, instr_fields_masked=0, bookmarks_renamed=0
    )
    para = pkg.xml("word/document.xml").find("w:body/w:p", NS)
    # The first link points elsewhere and stays a link, now around the placeholder. The second
    # one's address holds the name (compared without case and punctuation), so it is unwrapped.
    assert children(para) == ["r", "hyperlink", "r", "r"]
    assert para.find("w:hyperlink", NS).get(f"{{{R}}}id") == "rId1"
    assert runs(para.find("w:hyperlink", NS)) == [("[PERSON_1]", "rStyle")]
    rels = pkg.raw("word/_rels/document.xml.rels")
    assert b"forms.example.org" in rels and b"jane" not in rels
    assert extract_text(pkg).text == "Ask [PERSON_1] for the forms or write to her"


def test_a_link_in_a_header_is_unwrapped_from_the_headers_relationships(
    make_docx: MakeDocx,
) -> None:
    header = (
        '<w:p><w:r><w:t xml:space="preserve">Questions: </w:t></w:r>'
        '<w:hyperlink r:id="rId1"><w:r><w:t xml:space="preserve">write </w:t></w:r>'
        "<w:r><w:rPr><w:b/></w:rPr><w:t>to us</w:t></w:r></w:hyperlink>"
        '<w:r><w:t xml:space="preserve"> or visit </w:t></w:r>'
        '<w:hyperlink r:id="rId2"><w:r><w:t>our site</w:t></w:r></w:hyperlink></w:p>'
    )
    # The address is %-escaped, as some programs write it.
    targets = links("mailto:jane.doe%40acme.example?subject=Notice", "https://www.example.org")
    path = make_docx(
        p("Notices to jane.doe@acme.example."),
        parts={"word/header1.xml": header},
        raw={"word/_rels/header1.xml.rels": targets},
    )
    pkg = DocxPackage.open(path)
    dt = extract_text(pkg)
    report = apply_mask(pkg, dt, plan_for(dt, "jane.doe@acme.example", "[EMAIL_1]"))
    assert report.hyperlinks_unwrapped == 1
    para = pkg.xml("word/header1.xml").find("w:p", NS)
    # The link's runs are where the link was, in their order and with their formatting.
    assert children(para) == ["r", "r", "r", "r", "hyperlink"]
    assert runs(para)[:4] == [
        ("Questions: ", ""),
        ("write ", ""),
        ("to us", "b"),
        (" or visit ", ""),
    ]
    rels = pkg.raw("word/_rels/header1.xml.rels")
    assert b"acme" not in rels and b'Id="rId2"' in rels
    assert (
        extract_text(pkg).text == "Notices to [EMAIL_1].\nQuestions: write to us or visit our site"
    )


def test_only_link_relationships_are_ever_removed(make_docx: MakeDocx) -> None:
    # The target of the document's relationship to its header, "header1.xml", holds the value
    # "Header" once normalised. It names a part of the file, not an address, and must stay.
    pkg = DocxPackage.open(
        make_docx(p("Header Ltd signs."), parts={"word/header1.xml": p("Draft")})
    )
    dt = extract_text(pkg)

    def relationships() -> list[tuple[str | None, str | None]]:
        rels = etree.fromstring(pkg.raw("word/_rels/document.xml.rels"))
        return [(r.get("Id"), r.get("Target")) for r in rels]

    before = relationships()
    assert apply_mask(pkg, dt, plan_for(dt, "Header", "[CUSTOM_1]")).replaced == 1
    assert relationships() == before == [("rId1", "header1.xml")]


def test_a_relationship_still_used_elsewhere_is_kept(make_docx: MakeDocx) -> None:
    # A shape's click link uses the same relationship: removing it would leave the file broken.
    body = (
        '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>Acme</w:t></w:r></w:hyperlink>'
        '<w:r><w:drawing><wp:inline><wp:docPr id="1" name="Logo"><a:hlinkClick r:id="rId1"/>'
        "</wp:docPr></wp:inline></w:drawing></w:r></w:p>"
    )
    targets = links("https://www.acme.example")
    pkg = DocxPackage.open(make_docx(body, raw={"word/_rels/document.xml.rels": targets}))
    dt = extract_text(pkg)
    assert apply_mask(pkg, dt, plan_for(dt, "Acme", "[COMPANY_1]")).hyperlinks_unwrapped == 1
    assert pkg.xml("word/document.xml").find(".//w:hyperlink", NS) is None
    assert b'Id="rId1"' in pkg.raw("word/_rels/document.xml.rels")


BOOKMARKS = (
    '<w:p><w:bookmarkStart w:id="0" w:name="Acme_Address"/>'
    '<w:r><w:t>Acme Supplies Ltd, 1 Main Street</w:t></w:r><w:bookmarkEnd w:id="0"/></w:p>'
    '<w:p><w:bookmarkStart w:id="1" w:name="bm1"/><w:r><w:t>Terms</w:t></w:r>'
    '<w:bookmarkEnd w:id="1"/></w:p>'
    '<w:p><w:hyperlink w:anchor="ACME_ADDRESS"><w:r><w:t>see above</w:t></w:r></w:hyperlink>'
    '<w:hyperlink w:anchor="bm1"><w:r><w:t xml:space="preserve"> and the terms</w:t></w:r>'
    "</w:hyperlink></w:p>"
    '<w:p><w:fldSimple w:instr=" REF Acme_Address \\h ">'
    "<w:r><w:t>Acme Supplies Ltd</w:t></w:r></w:fldSimple></w:p>"
    '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGEREF </w:instrText></w:r>'
    "<w:r><w:instrText>Acme_Address</w:instrText></w:r>"
    '<w:r><w:instrText xml:space="preserve"> \\h </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    "<w:p><w:fldSimple w:instr=' HYPERLINK \\l \"Acme_Address\" '>"
    "<w:r><w:t>back to the address</w:t></w:r></w:fldSimple></w:p>"
    '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> NOTEREF acme_address \\h </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>2</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
)


def test_bookmarks_named_after_a_value_are_renamed_with_their_references(
    make_docx: MakeDocx,
) -> None:
    # Ruling R23. The plan also replaces the "Acme" in the PAGEREF instruction (the text map
    # holds instructions); the new bookmark name takes its place, so the reference still works.
    pkg = DocxPackage.open(make_docx(BOOKMARKS))
    dt = extract_text(pkg)
    plan = plan_for(dt, "Acme", "[COMPANY_1]")
    assert len(plan.replacements) == 3
    report = apply_mask(pkg, dt, plan)
    # Four instructions changed: REF and HYPERLINK in simple fields, PAGEREF and NOTEREF.
    assert report == MaskReport(
        replaced=3, hyperlinks_unwrapped=0, instr_fields_masked=4, bookmarks_renamed=1
    )
    root = pkg.xml("word/document.xml")
    # "bm1" is taken, so the renamed bookmark is "bm2"; the other one is left alone. Bookmark
    # names are compared without case, as Word compares them.
    assert [b.get(f"{{{W}}}name") for b in root.iter(f"{{{W}}}bookmarkStart")] == ["bm2", "bm1"]
    assert [h.get(f"{{{W}}}anchor") for h in root.iter(f"{{{W}}}hyperlink")] == ["bm2", "bm1"]
    assert [f.get(f"{{{W}}}instr") for f in root.iter(f"{{{W}}}fldSimple")] == [
        " REF bm2 \\h ",
        ' HYPERLINK \\l "bm2" ',
    ]
    assert [i.text for i in root.iter(f"{{{W}}}instrText")] == [
        " PAGEREF ",
        "bm2",
        " \\h ",
        " NOTEREF bm2 \\h ",
    ]
    assert extract_text(pkg).text.split("\n") == [
        "[COMPANY_1] Supplies Ltd, 1 Main Street",
        "Terms",
        "see above and the terms",
        "[COMPANY_1] Supplies Ltd",
        " PAGEREF bm2 \\h 1",
        "back to the address",
        " NOTEREF bm2 \\h 2",
    ]
    assert b"acme" not in pkg.raw("word/document.xml").lower()


def test_hidden_bookmarks_dangling_anchors_and_glued_references_are_renamed(
    make_docx: MakeDocx,
) -> None:
    # Ruling R27. A bookmark Word hides ("_...") stays hidden; an anchor that names no bookmark,
    # and an instruction word with the value glued to other letters, where no pattern finds it,
    # are renamed like a bookmark, and the same old name always gets the same new one.
    body = (
        '<w:p><w:bookmarkStart w:id="0" w:name="_RefAcme"/>'
        '<w:r><w:t>Acme Supplies Ltd</w:t></w:r><w:bookmarkEnd w:id="0"/></w:p>'
        '<w:p><w:hyperlink w:anchor="_RefAcme"><w:r><w:t>above</w:t></w:r></w:hyperlink>'
        '<w:hyperlink w:anchor="AcmeOld"><w:r><w:t xml:space="preserve"> and the old one</w:t>'
        "</w:r></w:hyperlink></w:p>"
        '<w:p><w:fldSimple w:instr=" REF AcmeOld \\h "><w:r><w:t>old</w:t></w:r></w:fldSimple>'
        '<w:fldSimple w:instr=" PAGEREF AcmeBackup \\h "><w:r><w:t>3</w:t></w:r></w:fldSimple>'
        "</w:p>"
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGEREF AcmeArchive \\h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>2</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    # As the sweep finds it: "Acme" on its own, not inside "AcmeArchive".
    plan = MaskPlan(
        [
            Replacement(m.start(), m.end(), "[COMPANY_1]")
            for m in flexible_pattern("Acme").finditer(dt.text)
        ]
    )
    assert len(plan.replacements) == 1
    report = apply_mask(pkg, dt, plan)
    assert report == MaskReport(
        replaced=1, hyperlinks_unwrapped=0, instr_fields_masked=3, bookmarks_renamed=1
    )
    root = pkg.xml("word/document.xml")
    assert [b.get(f"{{{W}}}name") for b in root.iter(f"{{{W}}}bookmarkStart")] == ["_bm1"]
    assert [h.get(f"{{{W}}}anchor") for h in root.iter(f"{{{W}}}hyperlink")] == ["_bm1", "bm2"]
    # The instructions of fields are searched before those of simple fields.
    assert [f.get(f"{{{W}}}instr") for f in root.iter(f"{{{W}}}fldSimple")] == [
        " REF bm2 \\h ",
        " PAGEREF bm4 \\h ",
    ]
    assert [i.text for i in root.iter(f"{{{W}}}instrText")] == [" PAGEREF bm3 \\h "]
    assert b"acme" not in pkg.raw("word/document.xml").lower()


def test_field_names_switches_and_formats_are_never_renamed(make_docx: MakeDocx) -> None:
    # "Link", "Page" and "Format" are in HYPERLINK, PAGEREF, NUMPAGES and MERGEFORMAT, glued to
    # other letters; those words name the field and its format, not the companies. After REF,
    # PAGEREF, NOTEREF or \l, though, a word names a bookmark whatever it spells: the bookmark
    # "Link" is renamed, and every reference to it follows.
    simple = "".join(
        f"<w:fldSimple w:instr={quoteattr(instruction)}><w:r><w:t>x</w:t></w:r></w:fldSimple>"
        for instruction in (
            ' HYPERLINK \\l "_Ref1" ',
            " PAGEREF _Ref1 \\h \\* MERGEFORMAT ",
            " REF Link \\h ",
            " PAGEREF Link \\h ",
            " HYPERLINK \\l Link ",
        )
    )
    bookmark = (
        '<w:p><w:bookmarkStart w:id="0" w:name="Link"/><w:r><w:t>Terms</w:t></w:r>'
        '<w:bookmarkEnd w:id="0"/></w:p>'
    )
    body = (
        p("Link Group, Format Ltd and Page Industries sign.")
        + bookmark
        + f"<w:p>{simple}</w:p>"
        + field_code(" NUMPAGES ")
        + field_code(" NOTEREF Link ")
    )
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    plan = plan_of(dt, {"Link": "[COMPANY_1]", "Format": "[COMPANY_2]", "Page": "[COMPANY_3]"})
    assert len(plan.replacements) == 4  # one is the "Link" in the NOTEREF instruction
    report = apply_mask(pkg, dt, plan)
    assert report == MaskReport(4, 0, 4, 1)
    root = pkg.xml("word/document.xml")
    assert root.find(".//w:bookmarkStart", NS).get(f"{{{W}}}name") == "bm1"
    assert [f.get(f"{{{W}}}instr") for f in root.iter(f"{{{W}}}fldSimple")] == [
        ' HYPERLINK \\l "_Ref1" ',
        " PAGEREF _Ref1 \\h \\* MERGEFORMAT ",
        " REF bm1 \\h ",
        " PAGEREF bm1 \\h ",
        " HYPERLINK \\l bm1 ",
    ]
    assert [i.text for i in root.iter(f"{{{W}}}instrText")] == [" NUMPAGES ", " NOTEREF bm1 "]


def test_short_values_neither_unwrap_links_nor_rename_bookmarks(make_docx: MakeDocx) -> None:
    # Ruling R27: the "5" of "5%" is in too many addresses and names to mean anything there,
    # even where no other digit touches it ("_Toc5", "terms-5").
    bookmarks = "".join(
        f'<w:p><w:bookmarkStart w:id="{n}" w:name="{name}"/><w:r><w:t>Terms</w:t></w:r>'
        f'<w:bookmarkEnd w:id="{n}"/></w:p>'
        for n, name in enumerate(("_Toc150", "_Toc5"))
    )
    body = (
        p("A 5% discount applies.")
        + bookmarks
        + '<w:p><w:hyperlink w:anchor="_Toc5"><w:r><w:t>see the terms</w:t></w:r></w:hyperlink>'
        '<w:hyperlink r:id="rId1"><w:r><w:t xml:space="preserve"> online</w:t></w:r>'
        '</w:hyperlink><w:hyperlink r:id="rId2"><w:r><w:t xml:space="preserve"> or here</w:t>'
        "</w:r></w:hyperlink></w:p>"
        '<w:p><w:fldSimple w:instr=" PAGEREF _Toc150 \\h "><w:r><w:t>3</w:t></w:r></w:fldSimple></w:p>'
    )
    targets = links("https://www.example.org/terms-2025", "https://www.example.org/terms-5")
    pkg = DocxPackage.open(make_docx(body, raw={"word/_rels/document.xml.rels": targets}))
    dt = extract_text(pkg)
    report = apply_mask(pkg, dt, plan_for(dt, "5%", "[PERCENT_1]"))
    assert report == MaskReport(1, 0, 0, 0)
    root = pkg.xml("word/document.xml")
    names = [b.get(f"{{{W}}}name") for b in root.iter(f"{{{W}}}bookmarkStart")]
    assert names == ["_Toc150", "_Toc5"]
    assert root.find(".//w:hyperlink", NS).get(f"{{{W}}}anchor") == "_Toc5"
    assert root.find(".//w:fldSimple", NS).get(f"{{{W}}}instr") == " PAGEREF _Toc150 \\h "
    rels = pkg.raw("word/_rels/document.xml.rels")
    assert b"terms-2025" in rels and b"terms-5" in rels


def test_digits_count_only_where_no_other_digit_touches_them(make_docx: MakeDocx) -> None:
    # A phone number is digits only once normalised. The leak check (ruling R14) finds it in a
    # tel: address, so that link is unwrapped; "2,025" is not the 2025 inside "120250".
    body = (
        p("Call +31 20 451 2473 about the 2,025 units.")
        + '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>call us</w:t></w:r></w:hyperlink>'
        '<w:hyperlink r:id="rId2"><w:r><w:t xml:space="preserve"> or see the offer</w:t></w:r>'
        "</w:hyperlink></w:p>"
        '<w:p><w:bookmarkStart w:id="0" w:name="_Ref120250"/><w:r><w:t>Units</w:t></w:r>'
        '<w:bookmarkEnd w:id="0"/></w:p>'
    )
    targets = links("tel:+31204512473", "https://www.example.org/offer-120250")
    pkg = DocxPackage.open(make_docx(body, raw={"word/_rels/document.xml.rels": targets}))
    dt = extract_text(pkg)
    plan = plan_of(dt, {"+31 20 451 2473": "[PHONE_1]", "2,025": "[QUANTITY_1]"})
    report = apply_mask(pkg, dt, plan)
    assert report == MaskReport(2, 1, 0, 0)
    rels = pkg.raw("word/_rels/document.xml.rels")
    assert b"31204512473" not in rels and b"offer-120250" in rels
    root = pkg.xml("word/document.xml")
    assert root.find(".//w:bookmarkStart", NS).get(f"{{{W}}}name") == "_Ref120250"


def field_code(*instructions: str) -> str:
    """A paragraph holding one field, its instruction split over ``instructions``."""
    runs = "".join(
        f'<w:r><w:instrText xml:space="preserve">{instruction}</w:instrText></w:r>'
        for instruction in instructions
    )
    return (
        f'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>{runs}'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>link</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )


ESCAPED = {
    "John Smith": "[PERSON_1]",
    "1 Main Street": "[ADDRESS_1]",
    "jane.doe@acme.example": "[EMAIL_1]",
}
EMILE = "\N{LATIN CAPITAL LETTER E WITH ACUTE}mile Dupont"
MEETING = "mailto:office@example.org?subject=Meeting%20John%20Smith%20at%201%20Main%20Street"
MASKED_MEETING = "mailto:office@example.org?subject=Meeting%20[PERSON_1]%20at%20[ADDRESS_1]"


def test_escaped_values_in_simple_field_instructions_are_masked(make_docx: MakeDocx) -> None:
    # Ruling R26: an address may %-escape a value ("%20" for a space, "%40" for "@"). Only the
    # escaped value is replaced; the other escapes stay, so the %22 quotes do not end the address.
    pkg = DocxPackage.open(
        make_docx(
            p("Meet John Smith at 1 Main Street, or write to jane.doe@acme.example.")
            + f"<w:p><w:fldSimple w:instr=' HYPERLINK \"{MEETING}&amp;body=%22Hi%22\" '>"
            "<w:r><w:t>book</w:t></w:r></w:fldSimple></w:p>"
            + "<w:p><w:fldSimple w:instr=' HYPERLINK \"mailto:jane.doe%40acme.example\" '>"
            "<w:r><w:t>write</w:t></w:r></w:fldSimple></w:p>"
            + p(f"Copy to {EMILE}.")
            # "É" is two escapes: the placeholder replaces both, not just the second.
            + "<w:p><w:fldSimple w:instr=' HYPERLINK \"mailto:office@example.org?subject=For"
            "%20%C3%89mile%20Dupont\" '><w:r><w:t>copy</w:t></w:r></w:fldSimple></w:p>"
        )
    )
    dt = extract_text(pkg)
    report = apply_mask(pkg, dt, plan_of(dt, ESCAPED | {EMILE: "[PERSON_2]"}))
    assert report.replaced == 4 and report.instr_fields_masked == 3
    fields = pkg.xml("word/document.xml").iter(f"{{{W}}}fldSimple")
    assert [f.get(f"{{{W}}}instr") for f in fields] == [
        f' HYPERLINK "{MASKED_MEETING}&body=%22Hi%22" ',
        ' HYPERLINK "mailto:[EMAIL_1]" ',
        ' HYPERLINK "mailto:office@example.org?subject=For%20[PERSON_2]" ',
    ]


def test_escaped_values_in_field_codes_are_masked_even_across_nodes(make_docx: MakeDocx) -> None:
    # Ruling R26, for the w:instrText of a field: the text map holds the instruction, but the
    # plan's search does not find a value %-escaped in it. The second instruction is split over
    # two nodes in the middle of the escaped address.
    pkg = DocxPackage.open(
        make_docx(
            p("Meet John Smith at 1 Main Street, or write to jane.doe@acme.example.")
            + field_code(f' HYPERLINK "{MEETING}" ')
            + field_code(' HYPERLINK "mailto:jane.doe%40ac', 'me.example" ')
        )
    )
    dt = extract_text(pkg)
    plan = plan_of(dt, ESCAPED)
    assert len(plan.replacements) == 3  # in the first paragraph only
    report = apply_mask(pkg, dt, plan)
    assert report.replaced == 3 and report.instr_fields_masked == 2
    paragraphs = pkg.xml("word/document.xml").findall("w:body/w:p", NS)[1:]
    assert ["".join(i.text for i in para.iter(f"{{{W}}}instrText")) for para in paragraphs] == [
        f' HYPERLINK "{MASKED_MEETING}" ',
        ' HYPERLINK "mailto:[EMAIL_1]" ',
    ]
    assert b"acme" not in pkg.raw("word/document.xml")


def sweep_plan(dt: DocText, placeholders: dict[str, str]) -> MaskPlan:
    """As the analysis sweeps the text: each value wherever its flexible pattern finds it."""
    return longest_first(
        dt.text,
        [
            (m.start(), m.end(), placeholder)
            for value, placeholder in placeholders.items()
            for m in flexible_pattern(value).finditer(dt.text)
        ],
    )


def both_kinds(instruction: str) -> str:
    """``instruction`` as a simple field's, then as the w:instrText of another field."""
    simple = f"<w:fldSimple w:instr={quoteattr(instruction)}><w:r><w:t>x</w:t></w:r></w:fldSimple>"
    return f"<w:p>{simple}</w:p>" + field_code(escape(instruction))


def instructions_of(pkg: DocxPackage) -> list[str]:
    """The simple fields' instructions, then each paragraph's w:instrText read as one."""
    root = pkg.xml("word/document.xml")
    simple = [f.get(f"{{{W}}}instr") for f in root.iter(f"{{{W}}}fldSimple")]
    codes = [
        "".join(i.text or "" for i in para.findall(".//w:instrText", NS))
        for para in root.iter(f"{{{W}}}p")
    ]
    return simple + [code for code in codes if code]


SWEPT = {
    "John Smith": "[PERSON_1]",
    "John": "[PERSON_1]",
    "Acme Supplies Ltd": "[COMPANY_1]",
    "Acme Supplies": "[COMPANY_1]",
    "Acme": "[COMPANY_1]",
}


def test_an_escaped_value_is_masked_whole_in_both_kinds_of_field(make_docx: MakeDocx) -> None:
    # Fix round 2: the sweep finds "John" and "Acme" in the w:instrText, where "=" comes before
    # them. The instruction is still searched from what it holds, so the escaped "John Smith"
    # and "Acme Supplies Ltd" are replaced whole, as in a simple field: no surname or legal form
    # is left behind.
    address = "mailto:office@example.org?name=John%20Smith&subject=Acme%20Supplies%20Ltd"
    instruction = f' HYPERLINK "{address}" '
    body = p("John Smith of Acme Supplies Ltd signs.") + both_kinds(instruction)
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    plan = sweep_plan(dt, SWEPT)
    assert {dt.text[r.start : r.end] for r in plan.replacements} == {
        "John Smith",
        "Acme Supplies Ltd",
        "John",
        "Acme",
    }
    report = apply_mask(pkg, dt, plan)
    masked_address = "mailto:office@example.org?name=[PERSON_1]&subject=[COMPANY_1]"
    assert instructions_of(pkg) == [f' HYPERLINK "{masked_address}" '] * 2
    assert report.replaced == len(plan.replacements) and report.instr_fields_masked == 2


@pytest.mark.parametrize("delimiter", ["=", "/", "?", "&"])
def test_an_escaped_value_after_any_delimiter_is_masked_whole(
    make_docx: MakeDocx, delimiter: str
) -> None:
    address = f"https://forms.example.org/x{delimiter}John%20Smith{delimiter}Acme%20Supplies%20Ltd"
    body = p("John Smith of Acme Supplies Ltd signs.") + both_kinds(f' HYPERLINK "{address}" ')
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    apply_mask(pkg, dt, sweep_plan(dt, SWEPT))
    masked_address = f"https://forms.example.org/x{delimiter}[PERSON_1]{delimiter}[COMPANY_1]"
    assert instructions_of(pkg) == [f' HYPERLINK "{masked_address}" '] * 2


def test_a_value_is_never_found_inside_a_placeholder(make_docx: MakeDocx) -> None:
    # Ruling R30: "Company" is a value too, but not the COMPANY of a placeholder, whether the
    # masker writes it or the instruction held it already, as written or %-escaped.
    instructions = (
        ' HYPERLINK "https://www.example.org/?ref=Acme" ',
        ' QUOTE "[COMPANY_1] and the Company" ',
        ' HYPERLINK "https://www.example.org/?tag=%5BCOMPANY_1%5D" ',
    )
    body = p("Acme is the Company.") + "".join(map(both_kinds, instructions))
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    apply_mask(pkg, dt, sweep_plan(dt, {"Acme": "[COMPANY_1]", "Company": "[CUSTOM_1]"}))
    expected = [
        ' HYPERLINK "https://www.example.org/?ref=[COMPANY_1]" ',
        ' QUOTE "[COMPANY_1] and the [CUSTOM_1]" ',
        instructions[2],
    ]
    assert instructions_of(pkg) == expected + expected


def test_field_names_and_switches_are_never_replaced(make_docx: MakeDocx) -> None:
    # Ruling R30: the value "Page" (of Page Industries) is not the PAGE field, nor is "Upper"
    # (of Upper Crust Ltd) the format keyword of "\* Upper"; but a quoted "Page" in a QUOTE
    # field is text the field shows, and is replaced.
    instructions = (" PAGE ", " PAGE \\* MERGEFORMAT ", " PAGE \\* Upper ", ' QUOTE "Page" ')
    body = p("Page Industries and Upper Crust Ltd sign; Page delivers.") + "".join(
        map(both_kinds, instructions)
    )
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    values = {"Page Industries": "[COMPANY_1]", "Page": "[COMPANY_1]"}
    plan = sweep_plan(dt, values | {"Upper Crust Ltd": "[COMPANY_2]", "Upper": "[COMPANY_2]"})
    report = apply_mask(pkg, dt, plan)
    expected = [*instructions[:3], ' QUOTE "[COMPANY_1]" ']
    assert instructions_of(pkg) == expected + expected
    # The plan's replacements on the field codes' three PAGEs and one Upper are not made.
    assert report.replaced == len(plan.replacements) - 4 and report.instr_fields_masked == 2


def test_the_plans_own_placeholder_is_kept_inside_a_field_code(make_docx: MakeDocx) -> None:
    # Two people called Smith, told apart by the owner: the plan gives the one in the field code
    # [PERSON_2]. The instruction's search makes the plan's replacement there, placeholder and
    # all, rather than the first placeholder "Smith" has in the document.
    pkg = DocxPackage.open(make_docx(p("Smith signs first.") + field_code(' QUOTE "Smith" ')))
    dt = extract_text(pkg)
    first, second = (m.span() for m in re.finditer("Smith", dt.text))
    plan = MaskPlan([Replacement(*first, "[PERSON_1]"), Replacement(*second, "[PERSON_2]")])
    assert apply_mask(pkg, dt, plan).replaced == 2
    assert instructions_of(pkg) == [' QUOTE "[PERSON_2]" ']


def test_a_word_renamed_for_a_glued_value_takes_its_other_values_with_it(
    make_docx: MakeDocx,
) -> None:
    # "Smith" stands on its own in "AcmeOld_Smith", "Acme" is glued: the whole word is renamed,
    # and the placeholder for "Smith" goes with it.
    body = p("Acme and Smith sign.") + both_kinds(" REF AcmeOld_Smith \\h ")
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    apply_mask(pkg, dt, sweep_plan(dt, {"Acme": "[COMPANY_1]", "Smith": "[PERSON_1]"}))
    assert instructions_of(pkg) == [" REF bm1 \\h "] * 2


def test_the_formats_switches_take_are_never_renamed(make_docx: MakeDocx) -> None:
    # A date or number picture may hold text: a value standing on its own there is replaced, but
    # the picture is never renamed for a value glued to other letters ("AcmeCo"); the leak check
    # reports that one.
    instructions = (
        " DATE \\@ \"'AcmeCo' d MMMM yyyy\" ",
        " = 5 \\# \"0 'AcmeUnits'\" ",
        " DATE \\@ \"'Acme' d MMMM\" ",
    )
    body = p("Acme Supplies Ltd signs.") + "".join(map(both_kinds, instructions))
    pkg = DocxPackage.open(make_docx(body))
    dt = extract_text(pkg)
    apply_mask(pkg, dt, sweep_plan(dt, SWEPT))
    expected = [*instructions[:2], " DATE \\@ \"'[COMPANY_1]' d MMMM\" "]
    assert instructions_of(pkg) == expected + expected


def test_a_new_name_never_holds_a_value(make_docx: MakeDocx) -> None:
    # bm1 to bm9 are taken, and "bm10" would hold the value "BM10": the renamed bookmark is bm11.
    bookmarks = "".join(
        f'<w:p><w:bookmarkStart w:id="{n}" w:name="{name}"/><w:r><w:t>{name}</w:t></w:r>'
        f'<w:bookmarkEnd w:id="{n}"/></w:p>'
        for n, name in enumerate([f"bm{k}" for k in range(1, 10)] + ["Acme_Address"])
    )
    pkg = DocxPackage.open(make_docx(p("Part BM10 comes from Acme.") + bookmarks))
    dt = extract_text(pkg)
    apply_mask(pkg, dt, sweep_plan(dt, {"BM10": "[ID_1]", "Acme": "[COMPANY_1]"}))
    names = [
        b.get(f"{{{W}}}name") for b in pkg.xml("word/document.xml").iter(f"{{{W}}}bookmarkStart")
    ]
    assert names == [f"bm{k}" for k in range(1, 10)] + ["bm11"]


def test_a_replacement_across_paragraphs_is_refused_before_anything_changes(
    make_docx: MakeDocx,
) -> None:
    pkg = DocxPackage.open(make_docx(p("Acme") + p("Ltd") + p("Northwind") + p("BV")))
    dt = extract_text(pkg)  # "Acme\nLtd\nNorthwind\nBV"
    before = pkg.raw("word/document.xml")
    for plan in (
        # A good replacement in the first paragraph, then one over "wind\nB" in a later one.
        MaskPlan([Replacement(0, 4, "[X]"), Replacement(14, 20, "[Y]")]),
        MaskPlan([Replacement(0, 4, "[X]"), Replacement(19, 99, "[Y]")]),  # past the end
    ):
        with pytest.raises(ValueError):
            apply_mask(pkg, dt, plan)
        assert pkg.raw("word/document.xml") == before


def test_the_text_map_must_be_of_this_package_as_it_is(make_docx: MakeDocx) -> None:
    pkg = DocxPackage.open(make_docx(p("Acme Ltd")))
    dt = extract_text(pkg)
    plan = plan_for(dt, "Acme", "[COMPANY_1]")
    with pytest.raises(ValueError):
        apply_mask(pkg.copy(), dt, plan)  # a copy has paragraphs of its own
    paragraph_nodes(dt.segments[0].para, "accepted")[1][0].elem.text = "Northwind Ltd"
    with pytest.raises(ValueError):
        apply_mask(pkg, dt, plan)  # the paragraph has changed since it was read


def test_an_empty_plan_changes_nothing(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "services-01.docx")
    dt = extract_text(pkg)
    before = {name: pkg.raw(name) for name in pkg.names()}
    assert apply_mask(pkg, dt, MaskPlan([])) == MaskReport(0, 0, 0, 0)
    assert {name: pkg.raw(name) for name in pkg.names()} == before


# ---- banner and names ------------------------------------------------------------------------


def test_the_banner_is_an_italic_first_paragraph_with_an_empty_one_after(
    make_docx: MakeDocx,
) -> None:
    table = f"<w:tbl><w:tr><w:tc>{p('A cell')}</w:tc></w:tr></w:tbl>"
    pkg = DocxPackage.open(make_docx(table + p("Body") + "<w:sectPr/>"))
    insert_banner(pkg)
    body = pkg.xml("word/document.xml").find("w:body", NS)
    assert children(body) == ["p", "p", "tbl", "p", "sectPr"]  # the section stays last
    assert runs(body[0]) == [(BANNER_TEXT, "i")]
    assert len(body[1]) == 0
    assert extract_text(pkg).text == f"{BANNER_TEXT}\n\nA cell\nBody"


def test_new_case_code_never_returns_an_existing_code() -> None:
    first = new_case_code(random.Random(7))
    assert new_case_code(random.Random(7), existing={first}) != first
    # A case file whose name Finder shows in lower case still holds its code: macOS file names
    # ignore case.
    assert new_case_code(random.Random(7), existing={first.lower()}) != first
    assert re.fullmatch(f"[{CODE_ALPHABET}]{{4}}", new_case_code())


def test_new_case_code_refuses_when_every_code_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(masker, "CODE_ALPHABET", "AB")
    every = {"".join(code) for code in itertools.product("AB", repeat=4)}
    with pytest.raises(ValueError):
        new_case_code(random.Random(1), existing=every)
    assert new_case_code(random.Random(1), existing=every - {"ABBA"}) == "ABBA"


def test_neutral_names_are_plain_file_names() -> None:
    assert neutral_name("K4F7", "1-before") == "MASKED-K4F7-1-before.docx"
    for code, suffix in (("K4F7", "../x"), ("K4/F7", None), ("", None), ("K4F7", "")):
        with pytest.raises(ValueError):
            neutral_name(code, suffix)


# ---- the corpus ------------------------------------------------------------------------------


def truth_plan(dt: DocText, truth: list[dict[str, Any]]) -> MaskPlan:
    """Every occurrence of every truth value and variant; of two that overlap, the longer."""
    return longest_first(
        dt.text,
        [
            (m.start(), m.end(), f"[{entry['type']}_{number}]")
            for number, entry in enumerate(truth, start=1)
            for form in {entry["value"], *entry["variants"]}
            for m in re.finditer(re.escape(form), dt.text)
        ],
    )


def masked(text: str, plan: MaskPlan) -> str:
    """``text`` with the plan's replacements made in the string itself."""
    pieces, at = [], 0
    for r in plan.replacements:
        pieces += [text[at : r.start], r.placeholder]
        at = r.end
    return "".join(pieces) + text[at:]


STRUCTURE = tuple(
    f"{{{W}}}{tag}"
    for tag in ("p", "tbl", "tr", "tc", "pPr", "tblPr", "tblGrid", "trPr", "tcPr", "sectPr")
)


def layout(pkg: DocxPackage) -> list[bytes]:
    """The text parts without their text: paragraphs, tables and every property of them."""
    return [
        etree.tostring(e) if e.tag.endswith(("Pr", "Grid")) else e.tag.encode()
        for part in pkg.TEXT_PARTS
        for e in pkg.xml(part).iter(*STRUCTURE)
    ]


def leak_check_finds(values: list[str], text: str) -> bool:
    """Whether the leak check (ruling R14) finds one of ``values`` in ``text``: normalised, as
    written or %-decoded, four characters or more, a value of digits only where no digit
    touches it."""
    for form in (text, unquote(text)):
        folded = normalize(form)
        for key in {normalize(value) for value in values}:
            if len(key) < 4:
                continue
            if key.isdigit():
                if re.search(rf"(?<!\d){key}(?!\d)", folded):
                    return True
            elif key in folded:
                return True
    return False


def link_targets(pkg: DocxPackage) -> list[str]:
    """The target of every hyperlink relationship in the package."""
    return [
        r.get("Target", "")
        for name in pkg.names()
        if name.endswith(".rels")
        for r in etree.fromstring(pkg.raw(name))
        if r.get("Type") == HYPERLINK
    ]


def test_the_corpus_masked_with_its_truth(corpus: Path, tmp_path: Path) -> None:
    for path in sorted(corpus.glob("*.docx")):
        pkg = DocxPackage.open(path)
        dt = extract_text(pkg)
        truth = json.loads(path.with_suffix(".truth.json").read_text(encoding="utf-8"))
        plan = truth_plan(dt, truth)
        shape = layout(pkg)
        untouched = {n: pkg.raw(n) for n in ("word/styles.xml", "word/numbering.xml")}
        report = apply_mask(pkg, dt, plan)
        text = extract_text(pkg).text
        assert report.replaced == len(plan.replacements), path.name
        # Placeholders exactly where the plan put them, and nothing else changed in the text.
        assert text == masked(dt.text, plan), path.name
        forms = {f for entry in truth for f in (entry["value"], *entry["variants"])}
        assert [f for f in forms if f in text] == [], path.name
        assert layout(pkg) == shape, path.name
        assert {n: pkg.raw(n) for n in untouched} == untouched, path.name
        values = [dt.text[r.start : r.end] for r in plan.replacements]
        assert [t for t in link_targets(pkg) if leak_check_finds(values, t)] == [], path.name
        pkg.save(tmp_path / path.name)
        masked_paragraphs = docx.Document(str(tmp_path / path.name)).paragraphs
        assert len(masked_paragraphs) == len(docx.Document(str(path)).paragraphs), path.name
