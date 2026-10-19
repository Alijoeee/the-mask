"""Restoring a Word file: the values back in every part, the AI's formatting kept, nothing lost.

The brief's three tests run on supply-01 exported the way the app exports it (``masked_case``)
and changed the way an AI tool might change it (``tests.helpers.simulate_ai``). The rest pin the
controller's decisions for the Word half of Task 18, on that file and on small files written by
hand: the round trip's report, confirmed and not; a placeholder Word split across runs put back
in its first run, with that run's formatting; headers, footnotes and comments restored, and an
unknown placeholder listed once for the whole file; the banner and the instruction for the AI
deleted with the empty paragraph after them and nothing in them restored, but emptied where the
paragraph has to stay, and a paragraph that ends a section never deleted; a value with a line
break and a tab written as Word writes them (decision 2); field instructions left as they are
(decision 3); a text box's fallback copy restored and counted once; changed placeholders waiting
for the owner, a one-sided bracket kept (R79); the AI's file never changed, and no file ever
written over.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from lxml import etree

from tests.fixtures.docx import MakeDocx
from tests.fixtures.restore import CASE, NOW
from tests.helpers import SPLIT_RSID, simulate_ai
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import extract_text
from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.placeholders import find_placeholders
from themask.restore.docx_restore import restore_docx

DASH = "\N{EN DASH}"
W = f"{{{NS['w']}}}"
# A banner the AI tool rewrote: quoted, in italics, its brackets escaped (ruling R78).
REWRITTEN_BANNER = "> *" + BANNER_TEXT.replace("[COMPANY_1]", r"\[COMPANY_1\]") + "*"
# Word keeps a text box twice: as DrawingML in mc:Choice and as VML in mc:Fallback.
TEXT_BOX = (
    '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor><a:graphic>'
    "<a:graphicData><wps:wsp><wps:txbx><w:txbxContent>{inside}</w:txbxContent></wps:txbx>"
    "</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
    "<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>{inside}</w:txbxContent>"
    "</v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>"
)


def p(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def italic(text: str) -> str:
    """A paragraph of one run in italics holding ``text``, as the banner is written."""
    return f"<w:p><w:r><w:rPr><w:i/></w:rPr><w:t>{escape(text)}</w:t></w:r></w:p>"


def text_of(path: Path) -> str:
    return extract_text(DocxPackage.open(path)).text


def paragraphs_of(path: Path) -> list[str]:
    """The text of each paragraph directly in the body of the Word file at ``path``."""
    body = DocxPackage.open(path).xml("word/document.xml").find(f"{W}body")
    return ["".join(t.text or "" for t in q.iter(f"{W}t")) for q in body.iterchildren(f"{W}p")]


def test_docx_roundtrip(masked_case: tuple[Path, Case], tmp_path: Path) -> None:
    masked, case = masked_case
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    out, rep = restore_docx(ai, case, confirm_altered=True)
    text = extract_text(DocxPackage.open(out)).text
    for e in case.entries:
        assert e.value in text
    assert "[PERSON_9]" in text and rep.unknown == ["[PERSON_9]"] and rep.banner_removed
    assert BANNER_TEXT not in text and out.name == f"ai {DASH} restored.docx"
    assert b"[COMPANY_1]" not in DocxPackage.open(out).raw("word/comments.xml")


def test_docx_formatting_kept(masked_case: tuple[Path, Case], tmp_path: Path) -> None:
    masked, case = masked_case
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    out, _ = restore_docx(ai, case, True)
    amount = next(e.value for e in case.entries if e.placeholder == "[AMOUNT_1]")
    r = (
        DocxPackage.open(out)
        .xml("word/document.xml")
        .xpath(f".//w:r[w:t[contains(text(),'{amount}')]]", namespaces=NS)[0]
    )
    assert r.find("w:rPr/w:b", NS) is not None


def test_never_overwrites(masked_case: tuple[Path, Case], tmp_path: Path) -> None:
    masked, case = masked_case
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    a, _ = restore_docx(ai, case, True)
    b, _ = restore_docx(ai, case, True)
    assert a != b and b.name == f"ai {DASH} restored (2).docx"


def test_the_ai_file_is_left_as_it_is(masked_case: tuple[Path, Case], tmp_path: Path) -> None:
    masked, case = masked_case
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    before = hashlib.sha256(ai.read_bytes()).hexdigest()
    out, _ = restore_docx(ai, case, confirm_altered=True)
    assert hashlib.sha256(ai.read_bytes()).hexdigest() == before
    assert out.parent == ai.parent  # the restored file goes next to it


def test_the_round_trip_report(masked_case: tuple[Path, Case], tmp_path: Path) -> None:
    # The masked file holds only exact placeholders of the key; the banner holds one of them.
    # Restored: all of those but the banner's, the one the AI changed once it is confirmed, and
    # the [COMPANY_1] of the AI's comment besides. [PERSON_9] is not in the key.
    masked, case = masked_case
    found = find_placeholders(text_of(masked))
    key = {entry.placeholder for entry in case.entries}
    assert all(match.exact and match.placeholder in key for match in found)
    placed = len(found) - len(find_placeholders(BANNER_TEXT))
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    _, confirmed = restore_docx(ai, case, confirm_altered=True, out_dir=tmp_path / "confirmed")
    assert confirmed.summary() == f"{placed + 1} placeholders restored, 0 need your check."
    assert confirmed.altered_restored == 1
    out, waiting = restore_docx(ai, case, confirm_altered=False, out_dir=tmp_path / "waiting")
    assert waiting.summary() == f"{placed} placeholders restored, 1 need your check."
    (item,) = waiting.needs_check
    assert (item.match.raw, item.status) == ("[PERSON 1]", "altered")
    assert item.entry is not None and item.entry.placeholder == "[PERSON_1]"
    assert "[PERSON 1]" in text_of(out)


def test_a_placeholder_split_across_runs_comes_back_in_its_first_run(
    masked_case: tuple[Path, Case], tmp_path: Path
) -> None:
    masked, case = masked_case
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    out, _ = restore_docx(ai, case, confirm_altered=True)
    company = next(e.value for e in case.entries if e.placeholder == "[COMPANY_1]")
    first_half = f".//w:r[@w:rsidR='{SPLIT_RSID}']"
    (before,) = DocxPackage.open(ai).xml("word/document.xml").xpath(first_half, namespaces=NS)
    root = DocxPackage.open(out).xml("word/document.xml")
    (after,) = root.xpath(first_half, namespaces=NS)
    assert before.findtext("w:t", namespaces=NS) == "[COMP"
    # The value is in the first half's run, with its formatting, italics and all; nothing is
    # left of the second half.
    assert after.findtext("w:t", namespaces=NS) == company
    assert etree.tostring(after.find("w:rPr", NS)) == etree.tostring(before.find("w:rPr", NS))
    assert after.find("w:rPr/w:i", NS) is not None
    assert all("ANY_1]" not in (t.text or "") for t in root.iter(f"{W}t"))


def test_headers_footnotes_and_comments_are_restored(make_docx: MakeDocx) -> None:
    path = make_docx(
        p("Body for [PERSON_1] and [PERSON_9]."),
        parts={
            "word/header1.xml": p("[COMPANY_1] - confidential"),
            "word/footnotes.xml": f'<w:footnote w:id="1">{p("Paid to [COMPANY_1] by [PERSON_9].")}'
            "</w:footnote>",
            "word/comments.xml": f'<w:comment w:id="0" w:author="AI">'
            f"{p('Ask [PERSON_1] about **[AMOUNT_1]**.')}</w:comment>",
        },
    )
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert text_of(out) == (
        "Body for John Smith and [PERSON_9].\n"
        "Acme Supplies Ltd - confidential\n"
        "Paid to Acme Supplies Ltd by [PERSON_9]."
    )
    comments = DocxPackage.open(out).xml("word/comments.xml")
    assert "".join(comments.itertext()) == "Ask John Smith about EUR 1,250,000."
    assert rep.summary() == "5 placeholders restored, 0 need your check."
    assert rep.unknown == ["[PERSON_9]"] and rep.altered_restored == 1


@pytest.mark.parametrize(
    "line",
    [BANNER_TEXT, AI_INSTRUCTION, REWRITTEN_BANNER],
    ids=["banner", "instruction", "rewritten"],
)
def test_the_banner_goes_with_one_empty_paragraph_after_it(make_docx: MakeDocx, line: str) -> None:
    # Its example placeholders are neither restored nor listed before it goes; of the two empty
    # paragraphs after it, one goes with it.
    empty = '<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:rPr><w:i/></w:rPr></w:r></w:p>'
    path = make_docx(f"{italic(line)}{empty}<w:p/>{p('Hello [PERSON_1]')}")
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert paragraphs_of(out) == ["", "Hello John Smith"]
    assert rep.banner_removed and (rep.restored, rep.unknown, rep.needs_check) == (1, [], [])


def test_a_paragraph_that_ends_a_section_is_never_deleted(make_docx: MakeDocx) -> None:
    # It holds the page setup of the section before it, so deleting it would change the layout.
    section_end = '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr></w:p>'
    path = make_docx(f"{italic(BANNER_TEXT)}{section_end}{p('Hello [PERSON_1]')}")
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    body = DocxPackage.open(out).xml("word/document.xml").find(f"{W}body")
    assert len(body.findall(f"{W}p/{W}pPr/{W}sectPr")) == 1
    assert paragraphs_of(out) == ["", "Hello John Smith"] and rep.banner_removed


def test_a_banner_line_in_a_paragraph_with_more_is_cut_out(make_docx: MakeDocx) -> None:
    path = make_docx(
        f"<w:p><w:r><w:t>{BANNER_TEXT}</w:t><w:br/><w:t>Hello [PERSON_1]</w:t></w:r></w:p>"
    )
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert paragraphs_of(out) == ["Hello John Smith"] and text_of(out) == "Hello John Smith"
    assert rep.banner_removed and rep.restored == 1


def test_a_banner_outside_the_body_is_emptied_not_deleted(make_docx: MakeDocx) -> None:
    # A header has to keep a paragraph; so does a table cell, a text box, a note or a comment.
    path = make_docx(p("Hello [PERSON_1]"), parts={"word/header1.xml": italic(BANNER_TEXT)})
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    header = DocxPackage.open(out).xml("word/header1.xml")
    assert len(header.findall("w:p", NS)) == 1 and "".join(header.itertext()) == ""
    assert text_of(out) == "Hello John Smith\n" and rep.banner_removed and rep.restored == 1


def test_a_banner_beside_a_picture_is_emptied_not_deleted(make_docx: MakeDocx) -> None:
    # Only the banner goes: a paragraph that holds anything else stays, and so does the empty
    # paragraph after it.
    path = make_docx(
        f"<w:p><w:r><w:t>{BANNER_TEXT}</w:t></w:r><w:r><w:drawing/></w:r></w:p><w:p/>"
        f"{p('Hello [PERSON_1]')}"
    )
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    body = DocxPackage.open(out).xml("word/document.xml").find(f"{W}body")
    first = body.find(f"{W}p")
    assert first.find(f".//{W}drawing") is not None and first.find(f".//{W}t") is None
    assert paragraphs_of(out) == ["", "", "Hello John Smith"] and rep.banner_removed


def test_a_value_with_a_line_break_and_a_tab_is_written_as_word_writes_them(
    make_docx: MakeDocx,
) -> None:
    # Decision 2: a "\n" in a value becomes a w:br and a "\t" a w:tab, in the run of the value.
    case = Case(
        "BRK",
        NOW,
        [],
        [],
        [
            KeyEntry("[ADDRESS_1]", PlaceholderType.ADDRESS, "Line 1\nLine 2", []),
            KeyEntry("[CUSTOM_1]", PlaceholderType.CUSTOM, "Name:\tValue", []),
        ],
    )
    out, rep = restore_docx(make_docx(p("To [ADDRESS_1] or [CUSTOM_1].")), case, False)
    assert text_of(out) == "To Line 1\nLine 2 or Name:\tValue." and rep.restored == 2
    (run,) = DocxPackage.open(out).xml("word/document.xml").iter(f"{W}r")
    assert [etree.QName(child).localname for child in run] == ["t", "br", "t", "tab", "t"]
    assert [t.text for t in run.iter(f"{W}t")] == ["To Line 1", "Line 2 or Name:", "Value."]


def test_a_placeholder_in_a_field_instruction_is_left_as_it_is(make_docx: MakeDocx) -> None:
    # Decision 3: the AI reads the field's result, not its instruction; only the result is put
    # back, and the instruction's placeholder is not reported either.
    field = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> HYPERLINK "mailto:[PERSON_1]" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>[PERSON_1]</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    out, rep = restore_docx(make_docx(field), CASE, confirm_altered=True)
    root = DocxPackage.open(out).xml("word/document.xml")
    assert root.findtext(".//w:instrText", namespaces=NS) == ' HYPERLINK "mailto:[PERSON_1]" '
    assert root.findtext(".//w:t", namespaces=NS) == "John Smith"
    assert (rep.restored, rep.unknown, rep.needs_check) == (1, [], [])


def test_a_text_box_and_its_fallback_copy_are_restored_and_counted_once(
    make_docx: MakeDocx,
) -> None:
    box = TEXT_BOX.format(inside=p("[PERSON_1] signs"))
    out, rep = restore_docx(make_docx(f"<w:p>{box}</w:p>"), CASE, confirm_altered=True)
    root = DocxPackage.open(out).xml("word/document.xml")
    assert [t.text for t in root.iter(f"{W}t")] == ["John Smith signs", "John Smith signs"]
    assert rep.summary() == "1 placeholders restored, 0 need your check."


@pytest.mark.parametrize(
    ("confirm_altered", "expected", "waiting"),
    [
        (True, "For [Buyer, John Smith] and John Smith.", 0),
        (False, "For [Buyer, PERSON_1] and person_1.", 2),
    ],
)
def test_changed_placeholders_wait_for_the_owner_and_a_one_sided_bracket_stays(
    make_docx: MakeDocx, confirm_altered: bool, expected: str, waiting: int
) -> None:
    path = make_docx(p("For [Buyer, PERSON_1] and person_1."))
    out, rep = restore_docx(path, CASE, confirm_altered)
    assert text_of(out) == expected and len(rep.needs_check) == waiting
    assert rep.altered_restored == 2 - waiting


def test_a_file_without_placeholders_comes_back_unchanged(make_docx: MakeDocx) -> None:
    path = make_docx(
        p("No placeholders here, only [Name] and Company 1."),
        parts={"word/header1.xml": p("A header")},
    )
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert rep.summary() == "0 placeholders restored, 0 need your check."
    assert not rep.banner_removed and rep.unknown == []
    before, after = DocxPackage.open(path), DocxPackage.open(out)
    assert after.names() == before.names()
    for name in before.names():
        assert etree.tostring(after.xml(name), method="c14n") == etree.tostring(
            before.xml(name), method="c14n"
        ), name


def test_the_restored_file_goes_into_the_folder_asked_for(
    make_docx: MakeDocx, tmp_path: Path
) -> None:
    path = make_docx(p("[PERSON_1]"))
    folder = tmp_path / "restored" / "here"
    out, _ = restore_docx(path, CASE, confirm_altered=True, out_dir=folder)
    assert out == folder / f"{path.stem} {DASH} restored.docx" and text_of(out) == "John Smith"
