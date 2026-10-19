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
written over. Ruling R88: placeholders in the AI's tracked changes are restored too, in what it
deleted or moved away as in what it inserted, by the same rules and counted the same way, and
nothing in unchanged text is reported twice. Ruling R90: a placeholder that a tracked change runs
through (a digit, a word, a type or a bracket of it changed) becomes one change of whole values,
right with the change accepted and with it rejected, or is left and listed when a form of it is
unknown or not confirmed. Ruling R91: ``plan_docx`` numbers every placeholder the restore deals
with, comments and deletions too, and the owner confirms changed ones by those numbers.
``simulate_ai`` copes with placeholders that share a run (review finding M4).
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
from themask.docx.reader import View, extract_text
from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.placeholders import find_placeholders
from themask.restore.docx_restore import plan_docx, restore_docx
from themask.restore.report import TRACKED_CHANGE

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


def run(text: str) -> str:
    """A run holding ``text``."""
    return f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def p(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f"<w:p>{run(text)}</w:p>"


def italic(text: str) -> str:
    """A paragraph of one run in italics holding ``text``, as the banner is written."""
    return f"<w:p><w:r><w:rPr><w:i/></w:rPr><w:t>{escape(text)}</w:t></w:r></w:p>"


def text_of(path: Path, view: View = "accepted") -> str:
    return extract_text(DocxPackage.open(path), view).text


# A key with two companies, for the changes an AI makes inside a placeholder (ruling R90).
PARTIES = Case(
    "TRK",
    NOW,
    [],
    [],
    [
        KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", []),
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", []),
        KeyEntry("[COMPANY_2]", PlaceholderType.COMPANY, "Brightwater BV", []),
    ],
)


def deleted(text: str) -> str:
    """A tracked deletion of the AI's holding ``text``."""
    return tracked("del", f'<w:r><w:delText xml:space="preserve">{escape(text)}</w:delText></w:r>')


def inserted(text: str) -> str:
    """A tracked insertion of the AI's holding ``text``."""
    return tracked("ins", run(text))


def changes(path: Path) -> list[tuple[str, str]]:
    """The tracked changes of the Word file at ``path``, in order: (ins or del, the text)."""
    root = DocxPackage.open(path).xml("word/document.xml")
    return [
        (etree.QName(change).localname, "".join(change.itertext()))
        for change in root.iter(f"{W}ins", f"{W}del")
    ]


def tracked(kind: str, content: str) -> str:
    """A tracked change of the AI's: ``w:ins``, ``w:del``, ``w:moveFrom`` or ``w:moveTo``."""
    return (
        f'<w:{kind} w:id="9" w:author="AI tool" w:date="2026-10-17T09:00:00Z">{content}</w:{kind}>'
    )


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


def test_tracked_changes_of_the_ai_are_restored_in_both_views(make_docx: MakeDocx) -> None:
    # R88: rejecting the AI's deletion must not bring a placeholder back, and accepting its
    # insertion must not either. Each keeps its run's formatting; the report counts both.
    deleted = "<w:r><w:rPr><w:b/></w:rPr><w:delText>[PERSON_1]</w:delText></w:r>"
    inserted = "<w:r><w:rPr><w:i/></w:rPr><w:t>[COMPANY_1]</w:t></w:r>"
    path = make_docx(
        f"<w:p>{run('Signed by ')}{tracked('del', deleted)}{tracked('ins', inserted)}"
        f"{run(' today.')}</w:p>"
    )
    out, rep = restore_docx(path, CASE, confirm_altered=False)
    assert text_of(out, "accepted") == "Signed by Acme Supplies Ltd today."
    assert text_of(out, "rejected") == "Signed by John Smith today."
    root = DocxPackage.open(out).xml("word/document.xml")
    (gone,) = root.iter(f"{W}delText")
    assert gone.text == "John Smith" and gone.getparent().find("w:rPr/w:b", NS) is not None
    (put_in,) = root.findall(".//w:ins/w:r", NS)
    assert put_in.findtext("w:t", namespaces=NS) == "Acme Supplies Ltd"
    assert put_in.find("w:rPr/w:i", NS) is not None
    assert rep.summary() == "2 placeholders restored, 0 need your check."


def test_a_move_is_restored_where_it_went_and_where_it_came_from(make_docx: MakeDocx) -> None:
    moved = "<w:r><w:t>[AMOUNT_1]</w:t></w:r>"
    path = make_docx(
        f"<w:p>{tracked('moveFrom', moved)}{run(' is due.')}</w:p>"
        f"<w:p>{run('Due: ')}{tracked('moveTo', moved)}</w:p>"
    )
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert text_of(out, "accepted") == " is due.\nDue: EUR 1,250,000"
    assert text_of(out, "rejected") == "EUR 1,250,000 is due.\nDue: "
    assert rep.restored == 2


@pytest.mark.parametrize("confirm_altered", [False, True])
def test_a_deletion_follows_the_same_rules_and_nothing_is_reported_twice(
    make_docx: MakeDocx, confirm_altered: bool
) -> None:
    # The unchanged "person_1" is read in both views but planned once; in the deletion an exact,
    # a changed and an unknown placeholder are dealt with as anywhere else.
    deleted = "<w:r><w:delText>[PERSON_1], person_1 and [PERSON_9]</w:delText></w:r>"
    path = make_docx(f"<w:p>{run('person_1 met ')}{tracked('del', deleted)}</w:p>")
    out, rep = restore_docx(path, CASE, confirm_altered)
    assert rep.unknown == ["[PERSON_9]"]
    if confirm_altered:
        assert text_of(out, "rejected") == "John Smith met John Smith, John Smith and [PERSON_9]"
        assert (rep.restored, rep.altered_restored, rep.needs_check) == (3, 2, [])
    else:
        assert text_of(out, "rejected") == "person_1 met John Smith, person_1 and [PERSON_9]"
        assert [item.match.raw for item in rep.needs_check] == ["person_1", "person_1"]
        assert (rep.restored, rep.altered_restored) == (1, 0)


def test_a_banner_the_ai_deleted_goes_and_is_not_restored(make_docx: MakeDocx) -> None:
    # The AI took the banner out as a tracked change: rejecting that must not bring it back
    # with a real value in it, so it is cut out of the deletion too.
    banner = f"<w:r><w:delText>{BANNER_TEXT}</w:delText></w:r>"
    path = make_docx(f"<w:p>{tracked('del', banner)}</w:p>{p('Hello [PERSON_1]')}")
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert text_of(out, "rejected") == "\nHello John Smith"
    assert rep.banner_removed and (rep.restored, rep.unknown) == (1, [])


def test_restoring_what_the_ai_took_out_never_changes_the_text_both_views_share(
    make_docx: MakeDocx,
) -> None:
    # The AI changed only the banner's example, as a tracked change. Read with the change
    # rejected, the line is the banner again; it is not cut there, as most of it is text the
    # file shows either way, and nothing in it is restored.
    before, after = BANNER_TEXT.split("[COMPANY_1]")
    path = make_docx(
        f"<w:p>{run(before)}{tracked('del', '<w:r><w:delText>[COMPANY_1]</w:delText></w:r>')}"
        f"{tracked('ins', '<w:r><w:t>[COMPANY_2]</w:t></w:r>')}{run(after)}</w:p>"
    )
    out, rep = restore_docx(path, CASE, confirm_altered=True)
    assert text_of(out, "accepted") == f"{before}[COMPANY_2]{after}"
    assert text_of(out, "rejected") == BANNER_TEXT
    assert not rep.banner_removed and (rep.restored, rep.unknown) == (0, ["[COMPANY_2]"])


def test_a_line_break_in_a_value_the_ai_deleted_is_written_as_word_writes_it(
    make_docx: MakeDocx,
) -> None:
    case = Case(
        "BRK", NOW, [], [], [KeyEntry("[ADDRESS_1]", PlaceholderType.ADDRESS, "Line 1\nLine 2", [])]
    )
    deleted = tracked("del", "<w:r><w:delText>[ADDRESS_1]</w:delText></w:r>")
    out, rep = restore_docx(make_docx(f"<w:p>{run('To ')}{deleted}</w:p>"), case, False)
    assert text_of(out, "rejected") == "To Line 1\nLine 2" and rep.restored == 1
    (gone,) = DocxPackage.open(out).xml("word/document.xml").findall(".//w:del/w:r", NS)
    assert [etree.QName(child).localname for child in gone] == ["delText", "br", "delText"]


def test_a_number_the_ai_changed_inside_a_placeholder_is_one_change_of_values(
    make_docx: MakeDocx,
) -> None:
    # R90: the AI made [COMPANY_1] into [COMPANY_2] by changing its digit alone. Each reading
    # gets its own value, in a deletion and an insertion with the AI's author and date.
    path = make_docx(
        f"<w:p>{run('Paid by [COMPANY_')}{deleted('1')}{inserted('2')}{run('].')}</w:p>"
    )
    out, rep = restore_docx(path, PARTIES, confirm_altered=False)
    assert text_of(out, "accepted") == "Paid by Brightwater BV."
    assert text_of(out, "rejected") == "Paid by Acme Supplies Ltd."
    assert changes(out) == [("del", "Acme Supplies Ltd"), ("ins", "Brightwater BV")]
    root = DocxPackage.open(out).xml("word/document.xml")
    made = list(root.iter(f"{W}ins", f"{W}del"))
    assert {(c.get(f"{W}author"), c.get(f"{W}date")) for c in made} == {
        ("AI tool", "2026-10-17T09:00:00Z")
    }
    assert len({c.get(f"{W}id") for c in made}) == 2
    assert rep.summary() == "1 placeholders restored, 0 need your check."


def test_a_swap_of_parties_inside_shared_brackets_shows_as_a_swap_of_values(
    make_docx: MakeDocx,
) -> None:
    path = make_docx(
        f"<w:p>{run('[')}{deleted('COMPANY_1')}{inserted('COMPANY_2')}{run('] shall indemnify [')}"
        f"{deleted('COMPANY_2')}{inserted('COMPANY_1')}{run('].')}</w:p>"
    )
    out, rep = restore_docx(path, PARTIES, confirm_altered=False)
    assert text_of(out, "accepted") == "Brightwater BV shall indemnify Acme Supplies Ltd."
    assert text_of(out, "rejected") == "Acme Supplies Ltd shall indemnify Brightwater BV."
    assert changes(out) == [
        ("del", "Acme Supplies Ltd"),
        ("ins", "Brightwater BV"),
        ("del", "Brightwater BV"),
        ("ins", "Acme Supplies Ltd"),
    ]
    assert rep.summary() == "2 placeholders restored, 0 need your check."


def test_a_type_the_ai_changed_inside_a_placeholder(make_docx: MakeDocx) -> None:
    path = make_docx(
        f"<w:p>{run('[')}{deleted('PERSON')}{inserted('COMPANY')}{run('_1] signs.')}</w:p>"
    )
    out, rep = restore_docx(path, PARTIES, confirm_altered=False)
    assert text_of(out, "accepted") == "Acme Supplies Ltd signs."
    assert text_of(out, "rejected") == "John Smith signs."
    assert rep.summary() == "1 placeholders restored, 0 need your check."


@pytest.mark.parametrize("confirm_altered", [False, True])
def test_a_bracket_the_ai_inserted_into_a_placeholder(
    make_docx: MakeDocx, confirm_altered: bool
) -> None:
    # With the change rejected the placeholder reads "PERSON_1]", a changed form, so the whole
    # placeholder waits for the owner's confirmation; confirmed, both readings show the value.
    path = make_docx(f"<w:p>{run('Signed by ')}{inserted('[')}{run('PERSON_1].')}</w:p>")
    out, rep = restore_docx(path, PARTIES, confirm_altered)
    if confirm_altered:
        assert text_of(out, "accepted") == text_of(out, "rejected") == "Signed by John Smith."
        assert changes(out) == []  # both readings agree: no change is left to accept or reject
        assert (rep.restored, rep.altered_restored, rep.needs_check) == (1, 1, [])
    else:
        assert text_of(out, "accepted") == "Signed by [PERSON_1]."
        assert text_of(out, "rejected") == "Signed by PERSON_1]."
        (item,) = rep.needs_check
        assert (item.match.raw, item.status, item.reason) == (
            "[PERSON_1]",
            "altered",
            TRACKED_CHANGE,
        )
        assert rep.restored == 0


@pytest.mark.parametrize(
    ("inside", "status"),
    [(("PERSON", "person"), "altered"), (("1", "9"), "unknown")],
    ids=["changed-form", "unknown"],
)
def test_a_placeholder_a_change_runs_through_is_left_and_listed_when_not_sure(
    make_docx: MakeDocx, inside: tuple[str, str], status: str
) -> None:
    # Read with the change accepted, the placeholder is "[person_1]", a changed form not
    # confirmed, or "[PERSON_9]", which the key does not hold: nothing of it is touched.
    old, new = inside
    before, after = ("[", "_1]") if old == "PERSON" else ("[PERSON_", "]")
    path = make_docx(
        f"<w:p>{run(before)}{deleted(old)}{inserted(new)}{run(after + ' signs.')}</w:p>"
    )
    out, rep = restore_docx(path, PARTIES, confirm_altered=False)
    assert text_of(out, "accepted") == f"{before}{new}{after} signs."
    assert text_of(out, "rejected") == f"{before}{old}{after} signs."
    (item,) = rep.needs_check
    assert (item.status, item.reason) == (status, TRACKED_CHANGE)
    assert (rep.restored, rep.unknown) == (0, [])
    if status == "altered":
        # Confirmed by its number, it becomes one change of values like any other.
        (planned,) = plan_docx(path, PARTIES)
        out, rep = restore_docx(path, PARTIES, {planned.ordinal}, out_dir=out.parent / "confirmed")
        assert text_of(out, "accepted") == text_of(out, "rejected") == "John Smith signs."
        assert rep.summary() == "1 placeholders restored, 0 need your check."


def test_half_a_placeholder_the_ai_inserted_keeps_the_other_reading_as_it_was(
    make_docx: MakeDocx,
) -> None:
    # Rejected, the change leaves "2]", no placeholder: that reading keeps its text.
    path = make_docx(f"<w:p>{run('Due to ')}{inserted('[COMPANY_')}{run('2] now.')}</w:p>")
    out, rep = restore_docx(path, PARTIES, confirm_altered=False)
    assert text_of(out, "accepted") == "Due to Brightwater BV now."
    assert text_of(out, "rejected") == "Due to 2] now."
    assert changes(out) == [("del", "2]"), ("ins", "Brightwater BV")]
    assert rep.summary() == "1 placeholders restored, 0 need your check."


def test_a_placeholder_one_reading_alone_sees_keeps_the_other_reading_as_it_was(
    make_docx: MakeDocx,
) -> None:
    # The AI deleted an "X" glued to "PERSON_1": accepted, the text reads the changed form
    # "PERSON_1"; rejected, "PERSON_1X", which is no placeholder, and stays so.
    path = make_docx(f"<w:p>{run('Rate: PERSON_1')}{deleted('X')}{run(' applies.')}</w:p>")
    out, rep = restore_docx(path, PARTIES, confirm_altered=True)
    assert text_of(out, "accepted") == "Rate: John Smith applies."
    assert text_of(out, "rejected") == "Rate: PERSON_1X applies."
    assert changes(out) == [("del", "PERSON_1"), ("ins", "John Smith"), ("del", "X")]
    assert (rep.restored, rep.altered_restored) == (1, 1)


def test_a_deletion_across_two_placeholders_is_left_and_listed(make_docx: MakeDocx) -> None:
    # Deleting "1] and [COMPANY_" makes one placeholder of two: nothing here is guessed.
    path = make_docx(f"<w:p>{run('X [PERSON_')}{deleted('1] and [COMPANY_')}{run('1] Y')}</w:p>")
    out, rep = restore_docx(path, PARTIES, confirm_altered=True)
    assert text_of(out, "accepted") == "X [PERSON_1] Y"
    assert text_of(out, "rejected") == "X [PERSON_1] and [COMPANY_1] Y"
    (item,) = rep.needs_check
    assert item.reason == TRACKED_CHANGE and rep.restored == 0


def test_a_confirmation_by_number_never_confirms_a_fallback_copy_by_chance(
    make_docx: MakeDocx,
) -> None:
    # The fallback copy is not in the plan; with numbers confirmed, its changed placeholders
    # stay as written rather than follow a number that names another placeholder.
    box = TEXT_BOX.format(inside=p("person_1 signs"))
    path = make_docx(f"{p('Dear [PERSON 1],')}<w:p>{box}</w:p>")
    plan = plan_docx(path, CASE)
    assert [(item.match.raw, item.ordinal) for item in plan] == [("[PERSON 1]", 0), ("person_1", 1)]
    out, rep = restore_docx(path, CASE, {0})
    texts = [t.text for t in DocxPackage.open(out).xml("word/document.xml").iter(f"{W}t")]
    assert texts == ["Dear John Smith,", "person_1 signs", "person_1 signs"]
    assert [item.ordinal for item in rep.needs_check] == [1]


def test_plan_docx_numbers_every_placeholder_and_the_owner_confirms_by_number(
    make_docx: MakeDocx,
) -> None:
    # R91: the plan holds what the restore deals with, comments and deletions too, numbered in
    # the order the restore numbers them; a set of numbers confirms exactly those changes.
    path = make_docx(
        f"<w:p>{run('Dear [PERSON 1] and ')}{deleted('[COMPANY_1]')}</w:p>",
        parts={"word/comments.xml": f'<w:comment w:id="0">{p("Ask person_1.")}</w:comment>'},
    )
    plan = plan_docx(path, CASE)
    assert [(item.part, item.match.raw, item.status, item.ordinal) for item in plan] == [
        ("word/document.xml", "[PERSON 1]", "altered", 0),
        ("word/document.xml", "[COMPANY_1]", "exact", 1),
        ("word/comments.xml", "person_1", "altered", 2),
    ]
    out, rep = restore_docx(path, CASE, {2})
    assert text_of(out, "accepted") == "Dear [PERSON 1] and "
    assert text_of(out, "rejected") == "Dear [PERSON 1] and Acme Supplies Ltd"
    comments = DocxPackage.open(out).xml("word/comments.xml")
    assert "".join(comments.itertext()) == "Ask John Smith."
    assert [(item.part, item.match.raw, item.ordinal) for item in rep.needs_check] == [
        ("word/document.xml", "[PERSON 1]", 0)
    ]
    assert (rep.restored, rep.altered_restored) == (2, 1)
    assert plan_docx(path, CASE) == plan  # the same numbers every time


@pytest.mark.parametrize(
    "paragraph",
    [
        p("[COMPANY_1] pays [AMOUNT_1] to [PERSON_1]."),
        p("[AMOUNT_1] and [AMOUNT_1] by [COMPANY_1] for [PERSON_1]."),
        (
            '<w:p><w:r><w:tab/><w:t xml:space="preserve">[COMPANY_1] owes [AMOUNT_1]</w:t><w:br/>'
            "<w:t>to [PERSON_1].</w:t></w:r></w:p>"
        ),
    ],
    ids=["company-and-amount", "amount-twice", "tab-and-break"],
)
def test_simulate_ai_copes_with_placeholders_that_share_a_run(
    make_docx: MakeDocx, tmp_path: Path, paragraph: str
) -> None:
    # Review finding M4: Task 24 runs simulate_ai over every corpus file.
    masked = make_docx(f"{italic(BANNER_TEXT)}<w:p/>{paragraph}")
    ai = simulate_ai(masked, tmp_path / "ai.docx")
    root = DocxPackage.open(ai).xml("word/document.xml")
    amounts = root.xpath(".//w:r[w:t='[AMOUNT_1]']", namespaces=NS)
    assert amounts and all(r.find("w:rPr/w:b", NS) is not None for r in amounts)
    (half,) = root.xpath(f".//w:r[@w:rsidR='{SPLIT_RSID}']", namespaces=NS)
    assert half.findtext("w:t", namespaces=NS) == "[COMP"
    out, rep = restore_docx(ai, CASE, confirm_altered=True)
    text = text_of(out)
    assert all(e.value in text for e in CASE.entries) and rep.unknown == ["[PERSON_9]"]
    assert {m.placeholder for m in find_placeholders(text)} == {"[PERSON_9]"}
