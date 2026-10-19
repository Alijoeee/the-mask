"""The export: the files loaded and prepared, masked with the review's plan, checked and saved.

The brief's tests run the whole pipeline on corpus files: one file, a contract with its annex, a
redline in two versions, nothing marked, a file added to a case. The leak gate decides on a twin of
each file in which every place of every value of the key is replaced (ruling R84): it is tested on
supply-01 with one occurrence switched off, with and without a value planted where no review can
see it, with a form never hidden, and over two small files. Small made-up files reviewed by hand
cover the rest: values too short to check, what nobody marked, case codes in use, files never
overwritten, files of the same name, the key, the numbering and the retention of a case a file is
added to, a key that could not be saved, and what an export refuses.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import tempfile
import uuid
import zipfile
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import pytest

from tests.fixtures.docx import PACKAGE_RELS
from tests.helpers import plant, reviewed
from themask import export
from themask.detect.lists import CaseLists
from themask.docx.masker import new_case_code
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text, has_revisions
from themask.errors import UnsupportedFileError
from themask.export import (
    ExportOptions,
    ExportResult,
    SourceDoc,
    combined_text,
    export_case,
    load_sources,
)
from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.leakcheck import MEDIA_LEFT, MEDIA_PLACEHOLDER, LeakHit
from themask.model import Case, Finding, Group, KeyEntry, MaskedFile, PlaceholderType
from themask.review import ReviewState
from themask.textnorm import normalize

if TYPE_CHECKING:
    from tests.fixtures.docx import MakeDocx
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists

COMPANY = PlaceholderType.COMPANY
EMAIL = PlaceholderType.EMAIL
PERCENT = PlaceholderType.PERCENT
PERSON = PlaceholderType.PERSON

SUPPLY = "Northwind Trading B.V. supplies the goods to Thamesgate Catering plc."
# A run set in a font named after the company: a leftover no review sees (ruling R66).
FONT_RUN = (
    '<w:p><w:r><w:rPr><w:rFonts w:ascii="Northwind Trading B.V."/></w:rPr>'
    "<w:t>Delivery is free.</w:t></w:r></w:p>"
)


def para(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def link_to(target: str) -> bytes:
    """A document.xml.rels relating rId1 to ``target`` as an external hyperlink."""
    kind = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    row = f'<Relationship Id="rId1" Type="{kind}" Target="{target}" TargetMode="External"/>'
    xml = f'<Relationships xmlns="{PACKAGE_RELS}">{row}</Relationships>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml).encode()


def body_text(path: Path) -> str:
    """The text of a masked file without the banner on top, which names [COMPANY_1] itself."""
    text = extract_text(DocxPackage.open(path)).text
    assert text.startswith(BANNER_TEXT)
    return text.removeprefix(BANNER_TEXT)


def by_hand(
    source: SourceDoc,
    user_lists: UserLists,
    *hidden: tuple[str, PlaceholderType],
    reserved: Collection[str] = (),
) -> ReviewState:
    """A review of ``source`` in which nothing was found and the owner hid ``hidden`` by hand;
    ``reserved`` are the placeholders of the case the file is added to (ruling R61).
    """
    text = combined_text([source]).text
    review = ReviewState(text, [], [], user_lists, CaseLists([], [], set()), reserved)
    for value, kind in hidden:
        review.hide_text(value, kind)
    return review


def group_of(text: str, placeholder: str, kind: PlaceholderType, value: str) -> Group:
    """A group of every place ``value`` stands in ``text``, numbered ``placeholder``."""
    findings = [
        Finding(kind, m.start(), m.end(), value, 1.0, "user")
        for m in re.finditer(re.escape(value), text)
    ]
    return Group(uuid.uuid4().hex, kind, value, {value}, findings, placeholder)


def group_with(review: ReviewState, placeholder: str) -> Group:
    """The group of ``review`` numbered ``placeholder``."""
    return next(g for g in review.groups if g.placeholder == placeholder)


def private_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty folder where ``tempfile`` makes its folders for the rest of the test."""
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


# ---- the brief ----------------------------------------------------------------------------------


def test_export_single(corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path) -> None:
    srcs, review = reviewed([corpus / "supply-01.docx"], engine, lists)
    saved: list[Case] = []
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, saved.append)
    assert not res.blocked and res.leak_hits == [] and len(res.outputs) == 1
    assert re.fullmatch(r"MASKED-[A-Z2-9]{4}\.docx", res.outputs[0].name)
    assert saved[0].entries == review.key_entries()
    # The case saved is the one returned: its code names the file, which it fingerprints.
    (case,) = saved
    assert res.case is case and res.instruction == AI_INSTRUCTION
    assert res.outputs == [tmp_path / f"MASKED-{case.id}.docx"]
    assert case.source_files == ["supply-01.docx"] and case.retention_days == 30
    digest = hashlib.sha256(res.outputs[0].read_bytes()).hexdigest()
    assert case.masked_files == [MaskedFile(res.outputs[0].name, digest)]
    assert extract_text(DocxPackage.open(res.outputs[0])).text.startswith(BANNER_TEXT)


def test_truth_values_absent_everywhere(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs, review = reviewed([corpus / "supply-01.docx"], engine, lists)
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None)
    with zipfile.ZipFile(res.outputs[0]) as archive:
        parts = [archive.read(name).decode("utf-8", "ignore") for name in archive.namelist()]
    blob = normalize("".join(parts))
    for t in json.loads((corpus / "supply-01.truth.json").read_text()):
        assert normalize(t["value"]) not in blob, t


def test_annex_shares_placeholders(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    paths = [corpus / "supply-07.docx", corpus / "supply-07-annex.docx"]
    srcs, review = reviewed(paths, engine, lists)
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None)
    texts = [body_text(p) for p in res.outputs]
    assert [p.name[-7:] for p in res.outputs] == ["-1.docx", "-2.docx"]
    assert "[COMPANY_1]" in texts[0] and "[COMPANY_1]" in texts[1]
    assert res.case is not None and {p.name[:-7] for p in res.outputs} == {f"MASKED-{res.case.id}"}


def test_redline_split(corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path) -> None:
    srcs, review = reviewed([corpus / "supply-03.docx"], engine, lists, redline_split=True)
    options = ExportOptions(tmp_path, redline_split=True)
    res = export_case(srcs, review, options, engine, lists, lambda c: None)
    assert {p.name.rsplit("-", 1)[1] for p in res.outputs} == {"before.docx", "after.docx"}
    truth = json.loads((corpus / "supply-03.truth.json").read_text())
    deleted = next(t["value"] for t in truth if t.get("only_in_deletion"))
    assert all(
        normalize(deleted) not in normalize(extract_text(DocxPackage.open(p)).text)
        for p in res.outputs
    )


def test_nothing_marked_still_exports_and_reports_unmarked(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs, review = reviewed([corpus / "supply-01.docx"], engine, lists)
    for g in review.groups:
        review.set_group_enabled(g.id, False)
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None)
    # Nothing marked, so nothing to leak; the rescan reports what the owner skipped.
    assert not res.blocked and res.outputs and res.unmarked
    assert res.case is not None and res.case.entries == []


def test_original_unchanged(corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path) -> None:
    src = corpus / "supply-01.docx"
    before = src.read_bytes()
    srcs, review = reviewed([src], engine, lists)
    export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None)
    assert src.read_bytes() == before


def test_add_file_to_existing_case(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    first, r1 = reviewed([corpus / "supply-07.docx"], engine, lists)
    saved: list[Case] = []
    export_case(first, r1, ExportOptions(tmp_path), engine, lists, saved.append)
    case = saved[0]
    annex, r2 = reviewed([corpus / "supply-07-annex.docx"], engine, lists, case=case)
    options = ExportOptions(tmp_path, existing_case=case)
    res2 = export_case(annex, r2, options, engine, lists, saved.append)
    assert saved[1].id == case.id and len(saved[1].entries) >= len(case.entries)
    assert res2.outputs[0].name == f"MASKED-{case.id}-2.docx"
    assert "[COMPANY_1]" in body_text(res2.outputs[0])
    # The case keeps its date, its files and its key; the annex's file and values are added.
    added = saved[1]
    assert added.created_at == case.created_at
    assert added.source_files == ["supply-07.docx", "supply-07-annex.docx"]
    assert [f.name for f in added.masked_files] == [
        f"MASKED-{case.id}.docx",
        f"MASKED-{case.id}-2.docx",
    ]
    assert {e.placeholder for e in case.entries} <= {e.placeholder for e in added.entries}


# ---- loading ------------------------------------------------------------------------------------


def test_load_sources_pdf(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    temp = private_temp_dir(tmp_path, monkeypatch)
    (s,) = load_sources([corpus / "supply-01.pdf"], False)
    assert s.kind == "pdf" and s.pdf_report is not None and "Confidential" in s.text_after.text
    assert not s.has_revisions and s.pkg_before is None and s.text_before is None
    assert list(temp.iterdir()) == []  # the Word file made from the PDF is gone


def test_load_sources_prepares_each_version(corpus: Path) -> None:
    (plain,) = load_sources([corpus / "supply-03.docx"], False)
    assert plain.has_revisions and plain.pkg_before is None and plain.text_before is None
    (split,) = load_sources([corpus / "supply-03.docx"], True)
    assert split.pkg_before is not None and split.text_before is not None
    # The original as it was opened: its changes still tracked, its custom XML still there.
    assert split.kind == "docx" and split.has_revisions and has_revisions(split.pkg)
    assert "customXml/item1.xml" in split.pkg.names()
    # Each version resolved and cleaned, and its text read from that very package.
    for pkg, doc_text in (
        (split.pkg_after, split.text_after),
        (split.pkg_before, split.text_before),
    ):
        assert not has_revisions(pkg) and "customXml/item1.xml" not in pkg.names()
        assert doc_text.text == extract_text(pkg).text
        assert all(s.para.getroottree().getroot() is pkg.xml(s.part) for s in doc_text.segments)
    assert "within 10 days of accepting" in split.text_after.text
    assert "within 14 days of accepting" not in split.text_after.text
    assert "within 14 days of accepting" in split.text_before.text
    assert "English language only" not in split.text_before.text


def test_combined_text_names_each_version(corpus: Path) -> None:
    srcs = load_sources([corpus / "supply-03.docx", corpus / "supply-01.docx"], True)
    combined = combined_text(srcs)
    redline, plain = srcs
    assert redline.text_before is not None and plain.text_before is None
    views = [
        ("supply-03.docx (after)", redline.text_after.text),
        ("supply-01.docx (after)", plain.text_after.text),
        ("supply-03.docx (before)", redline.text_before.text),
    ]
    assert [name for name, _, _ in combined.parts] == [name for name, _ in views]
    for (_, start, end), (_, text) in zip(combined.parts, views, strict=True):
        assert combined.text[start:end] == text


def test_files_of_the_same_name_are_told_apart(make_docx: MakeDocx, tmp_path: Path) -> None:
    # Three files from three folders whose names Finder shows alike: each version of the
    # combined text has a name of its own, so a place can be traced back to its file.
    files = [
        ("a", "contract.docx", "Northwind Trading B.V. supplies the goods."),
        ("b", "Contract.docx", "Thamesgate Catering plc buys them."),
        ("c", "contract (2).docx", "Burren Logistics Limited carries them."),
    ]
    paths = []
    for folder, name, text in files:
        (tmp_path / folder).mkdir()
        paths.append(tmp_path / folder / name)
        paths[-1].write_bytes(make_docx(para(text)).read_bytes())
    combined = combined_text(load_sources(paths, False))
    assert [name for name, _, _ in combined.parts] == [
        "contract.docx (after)",
        "Contract (2).docx (after)",
        "contract (2) (2).docx (after)",
    ]
    assert combined.locate(combined.text.index("Thamesgate"))[0] == "Contract (2).docx (after)"


def test_only_word_and_pdf_files_are_read(corpus: Path, tmp_path: Path) -> None:
    other = tmp_path / "Supply Agreement.txt"
    other.write_text(SUPPLY, encoding="utf-8")
    with pytest.raises(UnsupportedFileError) as refused:
        load_sources([other], False)
    assert refused.value.user_message == "The MASK reads Word (.docx) and PDF files."
    capitals = tmp_path / "SUPPLY.DOCX"
    capitals.write_bytes((corpus / "supply-01.docx").read_bytes())
    assert [s.kind for s in load_sources([capitals], False)] == ["docx"]


def test_an_old_doc_file_is_told_to_be_saved_as_docx(fixtures: Path) -> None:
    # The interface shows this message as it is: a .doc file gets the advice the owner can act on.
    with pytest.raises(UnsupportedFileError) as refused:
        load_sources([fixtures / "not-a-docx.doc"], False)
    assert "open it in Word and save as .docx" in refused.value.user_message


# ---- what is masked -----------------------------------------------------------------------------


def test_the_redline_versions_are_the_prepared_ones(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs, review = reviewed([corpus / "supply-03.docx"], engine, lists, redline_split=True)
    options = ExportOptions(tmp_path, redline_split=True)
    res = export_case(srcs, review, options, engine, lists, lambda c: None)
    assert res.case is not None
    code = res.case.id
    assert [p.name for p in res.outputs] == [
        f"MASKED-{code}-before.docx",
        f"MASKED-{code}-after.docx",
    ]
    before, after = (body_text(p) for p in res.outputs)
    assert "within 14 days of accepting" in before and "within 14 days of accepting" not in after
    assert "within 10 days of accepting" in after and "within 10 days of accepting" not in before
    assert "English language only" in after and "English language only" not in before
    assert not any(has_revisions(DocxPackage.open(p)) for p in res.outputs)
    # Both versions share the placeholders.
    assert "[COMPANY_1]" in before and "[COMPANY_1]" in after


def test_several_files_with_a_redline_are_numbered(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs = load_sources([corpus / "supply-03.docx", corpus / "supply-01.docx"], True)
    review = ReviewState(combined_text(srcs).text, [], [], lists, CaseLists([], [], set()))
    options = ExportOptions(tmp_path, redline_split=True)
    res = export_case(srcs, review, options, engine, lists, lambda c: None)
    assert res.case is not None
    code = res.case.id
    assert [p.name for p in res.outputs] == [
        f"MASKED-{code}-1-before.docx",
        f"MASKED-{code}-1-after.docx",
        f"MASKED-{code}-2.docx",
    ]
    assert res.case.source_files == ["supply-03.docx", "supply-01.docx"]


def test_a_value_marked_in_one_file_leaves_the_names_and_links_of_the_others(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # The annex never names the company where it is read, but a bookmark is named after it and
    # a link leads to its sales address (ruling R82): the key's values leave every file's names
    # and links, not only the file they were in. (Since ruling R112 the cleaner takes every
    # link to the outside out anyway; the bookmark is the masker's to rename.)
    contract = make_docx(para(SUPPLY) + para("Orders go to sales@northwind.example."))
    link = (
        '<w:p><w:bookmarkStart w:id="0" w:name="Northwind_Trading_BV_orders"/>'
        '<w:hyperlink r:id="rId1"><w:r><w:t>Write to the sales desk.</w:t></w:r>'
        '</w:hyperlink><w:bookmarkEnd w:id="0"/></w:p>'
    )
    rels = {"word/_rels/document.xml.rels": link_to("mailto:sales@northwind.example")}
    annex = make_docx(para("Annex 1: the price list.") + link, raw=rels)
    sources = load_sources([contract, annex], False)
    review = ReviewState(combined_text(sources).text, [], [], lists, CaseLists([], [], set()))
    review.hide_text("Northwind Trading B.V.", COMPANY)
    review.hide_text("sales@northwind.example", PlaceholderType.EMAIL)
    res = export_case(
        sources, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    assert not res.blocked and res.leak_hits == [] and len(res.outputs) == 2
    masked = DocxPackage.open(res.outputs[1])
    assert b"northwind" not in masked.raw("word/document.xml").lower()
    assert "word/_rels/document.xml.rels" not in masked.names()  # the link went with its target
    assert "Write to the sales desk." in body_text(res.outputs[1])


@pytest.mark.parametrize("name", ["services-01", "nda-01", "dpa-01"])
def test_the_corpus_files_with_links_export_without_their_links(
    name: str, corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R112: the masked copy keeps the link text and loses every address behind it.
    srcs, review = reviewed([corpus / f"{name}.docx"], engine, lists)
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None)
    assert not res.blocked and res.leak_hits == [], res.leak_hits
    with zipfile.ZipFile(res.outputs[0]) as archive:
        everything = b"\n".join(archive.read(entry) for entry in archive.namelist())
    assert b"mailto:" not in everything and b"relationships/hyperlink" not in everything


def test_a_pdf_is_masked_like_a_word_file(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs, review = reviewed([corpus / "supply-01.pdf"], engine, lists)
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None)
    assert not res.blocked and len(res.outputs) == 1 and res.case is not None
    text = body_text(res.outputs[0])
    company = next(e for e in res.case.entries if e.placeholder == "[COMPANY_1]")
    assert "[COMPANY_1]" in text and normalize(company.value) not in normalize(text)
    assert res.case.source_files == ["supply-01.pdf"]


# ---- the leak gate ------------------------------------------------------------------------------


def test_an_occurrence_left_visible_on_purpose_is_allowed(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs, review = reviewed([corpus / "supply-01.docx"], engine, lists)
    company = group_with(review, "[COMPANY_1]")
    review.set_occurrence_enabled(company.id, 0, False)
    saved: list[Case] = []
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, saved.append)
    # The one place the owner switched off is still there, listed as left visible on purpose; the
    # twin with that place replaced too is clean, so nothing blocks (ruling R84).
    assert not res.blocked and res.outputs and saved and res.leak_hits == []
    assert {hit.placeholder for hit in res.allowed_hits} == {"[COMPANY_1]"}
    assert sum(hit.count for hit in res.allowed_hits) == 1
    assert normalize(company.canonical) in normalize(body_text(res.outputs[0]))


def test_a_leftover_blocks_and_saves_nothing(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A font named after the company: no review sees it, the leak check does (ruling R66). The
    # place the owner switched off is replaced in the twin, so only the font is found there.
    font = b'<w:font w:name="Northwind Trading"><w:family w:val="swiss"/></w:font>'
    src = plant(corpus / "supply-01.docx", "word/fontTable.xml", font, tmp_path / "planted.docx")
    srcs, review = reviewed([src], engine, lists)
    review.set_occurrence_enabled(group_with(review, "[COMPANY_1]").id, 0, False)
    temp = private_temp_dir(tmp_path, monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    saved: list[Case] = []
    res = export_case(srcs, review, ExportOptions(out), engine, lists, saved.append)
    # The font blocks, and nothing is saved anywhere; the place switched off is listed apart.
    assert res.blocked and res.case is None and res.outputs == [] and saved == []
    leftovers = [(hit.part, hit.placeholder, hit.count) for hit in res.leak_hits]
    assert leftovers == [("word/fontTable.xml", "[COMPANY_1]", 1)]
    assert [(hit.part, hit.count) for hit in res.allowed_hits] == [("word/document.xml", 1)]
    assert res.unmarked == [] and res.instruction == AI_INSTRUCTION
    assert list(out.iterdir()) == [] and list(temp.iterdir()) == []


def test_a_leftover_in_another_file_blocks(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    paths = [make_docx(para(SUPPLY) + para(SUPPLY)), make_docx(para(SUPPLY) + FONT_RUN)]
    sources = load_sources(paths, False)
    review = ReviewState(combined_text(sources).text, [], [], lists, CaseLists([], [], set()))
    company = review.hide_text("Northwind Trading B.V.", COMPANY)
    review.set_occurrence_enabled(company.id, 0, False)
    res = export_case(
        sources, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    # One place left visible in the first file, a leftover in the second: blocked.
    assert res.blocked and res.outputs == []
    (leftover,) = res.leak_hits
    assert re.fullmatch(r"MASKED-[A-Z2-9]{4}-2\.docx: word/document\.xml", leftover.part)
    (visible,) = res.allowed_hits
    assert re.fullmatch(r"MASKED-[A-Z2-9]{4}-1\.docx: word/document\.xml", visible.part)


def test_a_form_never_hidden_leaves_no_room_for_a_leftover(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Never hiding "Northwind" switches its places off and takes the form out of the key, so no
    # scan of the masked file sees those places. The twin has them replaced, and the font named
    # after the company is found (ruling R84).
    font = b'<w:font w:name="Northwind Trading B.V."><w:family w:val="swiss"/></w:font>'
    src = plant(corpus / "supply-01.docx", "word/fontTable.xml", font, tmp_path / "planted.docx")
    srcs, review = reviewed([src], engine, lists)
    review.add_never_hide("Northwind")
    assert group_with(review, "[COMPANY_1]").disabled  # its places are switched off
    out = tmp_path / "out"
    res = export_case(srcs, review, ExportOptions(out), engine, lists, lambda c: None)
    assert res.blocked and res.outputs == [] and not out.exists()
    leftovers = [(hit.part, hit.placeholder) for hit in res.leak_hits]
    assert leftovers == [("word/fontTable.xml", "[COMPANY_1]")]


def test_a_group_switched_off_in_a_file_added_leaves_no_room_for_a_leftover(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # The annex names the case's company only as "Northwind", a form its stored entry does not
    # list, and the owner switches the seeded group off whole. The twin has its places replaced,
    # and the font named after the company is found (ruling R84).
    case = Case(
        "TEST",
        datetime(2026, 10, 1, tzinfo=UTC),
        ["a.docx"],
        [MaskedFile("MASKED-TEST.docx", "0" * 64)],
        [KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", [])],
    )
    body = para("Northwind delivers the goods to every site.") + para("Northwind invoices monthly.")
    srcs, review = reviewed([make_docx(body + FONT_RUN)], engine, lists, case=case)
    seeded = group_with(review, "[COMPANY_1]")
    assert [f.text for f in seeded.findings] == ["Northwind", "Northwind"]
    review.set_group_enabled(seeded.id, False)
    options = ExportOptions(tmp_path / "out", existing_case=case)
    res = export_case(srcs, review, options, engine, lists, lambda c: None)
    assert res.blocked
    leftovers = [(hit.part, hit.placeholder, hit.count) for hit in res.leak_hits]
    assert leftovers == [("word/document.xml", "[COMPANY_1]", 1)]


def test_places_split_off_and_switched_off_whole_are_left_visible_not_leftovers(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R114: the owner moves two "Acme" places into a group of their own and switches it
    # off: "show Acme there". The twin replaces the places of every group, keyed or not, so the
    # gate sees no leftover and the two places are listed as left visible on purpose.
    (source,) = load_sources(
        [make_docx(para("Acme Supplies Ltd sells. Acme buys. Acme delivers. Acme ships."))], False
    )
    text = combined_text([source]).text
    full = Finding(COMPANY, 0, 17, "Acme Supplies Ltd", 1.0, "user")
    shorts = [
        Finding(COMPANY, m.start(), m.end(), "Acme", 1.0, "sweep")
        for m in re.finditer(r"Acme(?! Supplies)", text)
    ]
    acme = Group(
        uuid.uuid4().hex, COMPANY, "Acme Supplies Ltd", {"Acme Supplies Ltd", "Acme"}, [full, *shorts], "[COMPANY_1]"
    )
    review = ReviewState(text, [acme], [], lists, CaseLists([], [], set()))
    shown = review.split(acme.id, [2, 3])
    review.set_group_enabled(shown.id, False)
    res = export_case(
        [source], review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    assert not res.blocked and res.leak_hits == [] and len(res.outputs) == 1
    assert {hit.placeholder for hit in res.allowed_hits} == {"[COMPANY_1]"}
    assert sum(hit.count for hit in res.allowed_hits) == 2
    assert body_text(res.outputs[0]).strip() == (
        "[COMPANY_1] sells. [COMPANY_1] buys. Acme delivers. Acme ships."
    )


def test_a_place_switched_off_in_an_instruction_leaves_no_room_for_a_leftover(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # The masker takes the value out of every field instruction whatever the switches say, so no
    # scan sees the place switched off there. The twin is checked instead (ruling R84).
    field = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> QUOTE "Northwind Trading B.V." </w:instrText>'
        '</w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>the seller</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    path = make_docx(para("Northwind Trading B.V. sells.") + field + FONT_RUN)
    (source,) = load_sources([path], False)
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY))
    group = group_with(review, "[COMPANY_1]")
    quoted = next(
        i for i, f in enumerate(group.findings) if review.text[f.start - 7 : f.start] == 'QUOTE "'
    )
    review.set_occurrence_enabled(group.id, quoted, False)
    res = export_case(
        [source], review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    assert res.blocked
    leftovers = [(hit.part, hit.placeholder, hit.count) for hit in res.leak_hits]
    assert leftovers == [("word/document.xml", "[COMPANY_1]", 1)]


def test_a_picture_the_cleaner_could_not_remove_blocks_the_export(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R101: the leak check cannot read pixels, so a media part or an image relationship
    # still in a masked file is a leftover, whatever points at it. Planted after the cleaning.
    (source,) = load_sources([make_docx(para(SUPPLY))], False)
    source.pkg_after.set_raw("word/media/planted.png", b"PNG of a signature")
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY))
    out = tmp_path / "out"
    res = export_case([source], review, ExportOptions(out), engine, lists, lambda c: None)
    assert res.blocked and res.outputs == [] and not out.exists()
    assert [(hit.part, hit.placeholder, hit.context) for hit in res.leak_hits] == [
        ("word/media/planted.png", MEDIA_PLACEHOLDER, MEDIA_LEFT)
    ]
    assert res.allowed_hits == []


def test_an_image_relationship_left_behind_blocks_the_export(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    (source,) = load_sources([make_docx(para(SUPPLY))], False)
    image = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    row = f'<Relationship Id="rId9" Type="{image}" Target="media/gone.png"/>'
    rels = f'<Relationships xmlns="{PACKAGE_RELS}">{row}</Relationships>'
    source.pkg_after.set_raw("word/_rels/document.xml.rels", rels.encode())
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY))
    res = export_case(
        [source], review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    assert res.blocked
    assert [(hit.part, hit.placeholder) for hit in res.leak_hits] == [
        ("word/_rels/document.xml.rels", MEDIA_PLACEHOLDER)
    ]


def test_what_nobody_marked_is_listed_once(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    text = "Burren Logistics Limited carries the goods for Mathew Bennett."
    sources = load_sources([make_docx(para(text)), make_docx(para(text))], False)
    review = ReviewState(combined_text(sources).text, [], [], lists, CaseLists([], [], set()))
    res = export_case(
        sources, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    assert not res.blocked and len(res.outputs) == 2
    canonicals = [normalize(group.canonical) for group in res.unmarked]
    assert normalize("Burren Logistics Limited") in canonicals
    assert len(set(canonicals)) == len(canonicals)


def test_with_several_files_a_hit_names_its_file(
    corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R81: the annex of the pair carries a font named after a party of the case.
    font = b'<w:font w:name="Isarthal Hygiene Systems GmbH"><w:family w:val="swiss"/></w:font>'
    planted = tmp_path / "supply-07-annex.docx"
    plant(corpus / "supply-07-annex.docx", "word/fontTable.xml", font, planted)
    srcs, review = reviewed([corpus / "supply-07.docx", planted], engine, lists)
    res = export_case(srcs, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None)
    assert res.blocked and res.leak_hits
    assert all(re.fullmatch(r"MASKED-[A-Z2-9]{4}-[12]\.docx: .+", h.part) for h in res.leak_hits)
    (hit,) = [h for h in res.leak_hits if h.part.endswith(": word/fontTable.xml")]
    assert re.fullmatch(r"MASKED-[A-Z2-9]{4}-2\.docx: word/fontTable\.xml", hit.part)


def test_a_hit_names_its_file_as_it_was_written(
    make_docx: MakeDocx,
    engine: Engine,
    lists: UserLists,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(export, "new_case_code", lambda rng=None, existing=(): "TEST")
    out = tmp_path / "out"
    out.mkdir()
    (out / "MASKED-TEST-2.docx").write_bytes(b"another file")
    sources = load_sources([make_docx(para(SUPPLY)), make_docx(para(SUPPLY))], False)
    review = ReviewState(combined_text(sources).text, [], [], lists, CaseLists([], [], set()))
    company = review.hide_text("Northwind Trading B.V.", COMPANY)
    review.set_occurrence_enabled(company.id, 1, False)  # the one in the second file
    res = export_case(sources, review, ExportOptions(out), engine, lists, lambda c: None)
    assert not res.blocked
    assert [p.name for p in res.outputs] == ["MASKED-TEST-1.docx", "MASKED-TEST-2 (2).docx"]
    assert [h.part for h in res.allowed_hits] == ["MASKED-TEST-2 (2).docx: word/document.xml"]
    assert res.leak_hits == []
    assert (out / "MASKED-TEST-2.docx").read_bytes() == b"another file"


def test_values_too_short_to_check_are_reported(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    path = make_docx(para("Northwind Trading B.V. charges a fee of 7.5% on every order."))
    (source,) = load_sources([path], False)
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY), ("7.5%", PERCENT))
    res = export_case(
        [source], review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None
    )
    assert not res.blocked and res.unverifiable == ["[PERCENT_1]"]
    assert "a fee of [PERCENT_1] on" in body_text(res.outputs[0])  # replaced all the same


def test_a_result_keeps_the_brief_s_order_of_fields() -> None:
    # As the export dialog's tests make one (Task 22): the fields added since come last.
    hit = LeakHit("word/header1.xml", "[COMPANY_1]", "\N{HORIZONTAL ELLIPSIS} [COMPANY_1]")
    result = ExportResult(None, [], [hit], [], AI_INSTRUCTION, True)
    assert result.blocked and result.leak_hits == [hit]
    assert result.allowed_hits == [] and result.unverifiable == []


# ---- names and codes ----------------------------------------------------------------------------


def test_a_new_case_never_takes_a_code_in_use(
    make_docx: MakeDocx,
    engine: Engine,
    lists: UserLists,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def seeded(rng: random.Random | None = None, existing: Collection[str] = ()) -> str:
        return new_case_code(random.Random(15), existing)

    monkeypatch.setattr(export, "new_case_code", seeded)
    in_use = seeded()  # the first code the seeded source gives
    (source,) = load_sources([make_docx(para(SUPPLY))], False)
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY))
    options = ExportOptions(tmp_path / "out", existing_codes=[in_use.lower()])
    res = export_case([source], review, options, engine, lists, lambda c: None)
    assert res.case is not None and res.case.id != in_use
    assert res.case.id == seeded(existing=(in_use,))
    assert res.outputs[0].name == f"MASKED-{res.case.id}.docx"


def test_an_export_never_overwrites_a_file(
    make_docx: MakeDocx,
    engine: Engine,
    lists: UserLists,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(export, "new_case_code", lambda rng=None, existing=(): "TEST")
    (source,) = load_sources([make_docx(para(SUPPLY))], False)
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY))
    out = tmp_path / "out"
    first = export_case([source], review, ExportOptions(out), engine, lists, lambda c: None)
    kept = first.outputs[0].read_bytes()
    # The same files and review again, into the same folder.
    second = export_case([source], review, ExportOptions(out), engine, lists, lambda c: None)
    assert first.outputs == [out / "MASKED-TEST.docx"]
    assert second.outputs == [out / "MASKED-TEST (2).docx"]
    assert first.outputs[0].read_bytes() == kept
    assert second.case is not None
    digest = hashlib.sha256(second.outputs[0].read_bytes()).hexdigest()
    assert second.case.masked_files == [MaskedFile("MASKED-TEST (2).docx", digest)]
    assert "[COMPANY_1]" in body_text(second.outputs[0])


# ---- a file added to a case ---------------------------------------------------------------------


def test_a_file_added_to_a_case_merges_the_key(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    case = Case(
        "TEST",
        datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        ["Supply Agreement.docx"],
        [MaskedFile("MASKED-TEST.docx", "0" * 64)],
        [
            KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", ["Northwind"]),
            KeyEntry("[PERSON_1]", PERSON, "Mathew Bennett", []),
            KeyEntry("[COMPANY_2]", COMPANY, "Thamesgate Catering plc", []),
        ],
    )
    path = make_docx(
        para("Northwind Trading B.V. sells to Thamesgate Catering Ltd.")
        + para("Burren Logistics Limited carries the goods.")
    )
    (source,) = load_sources([path], False)
    text = combined_text([source]).text
    groups = [
        group_of(text, "[COMPANY_1]", COMPANY, "Northwind Trading B.V."),  # the same value
        group_of(text, "[COMPANY_2]", COMPANY, "Thamesgate Catering Ltd"),  # another form
        group_of(text, "[COMPANY_3]", COMPANY, "Burren Logistics Limited"),  # a new one
    ]
    reserved = [e.placeholder for e in case.entries]
    review = ReviewState(text, groups, [], lists, CaseLists([], [], set()), reserved)
    saved: list[Case] = []
    options = ExportOptions(tmp_path / "out", existing_case=case)
    res = export_case([source], review, options, engine, lists, saved.append)
    (merged,) = saved
    # A stored value is never rewritten: the case's first file still restores to it, and the
    # form the new file shows joins its variants (ruling R86).
    assert [(e.placeholder, e.value) for e in merged.entries] == [
        ("[COMPANY_1]", "Northwind Trading B.V."),
        ("[PERSON_1]", "Mathew Bennett"),
        ("[COMPANY_2]", "Thamesgate Catering plc"),
        ("[COMPANY_3]", "Burren Logistics Limited"),
    ]
    assert merged.entries[0].variants == ["Northwind", "Northwind Trading B.V."]
    assert merged.entries[2].variants == ["Thamesgate Catering Ltd"]
    assert (merged.id, merged.created_at) == (case.id, case.created_at)
    assert merged.source_files == ["Supply Agreement.docx", path.name]
    assert [f.name for f in merged.masked_files] == ["MASKED-TEST.docx", "MASKED-TEST-2.docx"]
    assert res.outputs == [tmp_path / "out" / "MASKED-TEST-2.docx"]
    # The case given is left as it was.
    assert len(case.entries) == 3 and case.entries[2].value == "Thamesgate Catering plc"
    assert len(case.masked_files) == 1 and case.source_files == ["Supply Agreement.docx"]


@pytest.mark.parametrize(
    ("masked", "redline", "expected"),
    [
        (["MASKED-TEST.docx"], False, ["MASKED-TEST-2.docx"]),
        (["MASKED-TEST-before.docx", "MASKED-TEST-after.docx"], False, ["MASKED-TEST-2.docx"]),
        (["MASKED-TEST-1.docx", "MASKED-TEST-2 (2).docx"], False, ["MASKED-TEST-3.docx"]),
        (
            ["MASKED-TEST-1-before.docx", "MASKED-TEST-1-after.docx", "MASKED-TEST-2.docx"],
            True,
            ["MASKED-TEST-3-before.docx", "MASKED-TEST-3-after.docx"],
        ),
    ],
)
def test_a_file_added_to_a_case_continues_its_numbering(
    masked: list[str],
    redline: bool,
    expected: list[str],
    corpus: Path,
    make_docx: MakeDocx,
    engine: Engine,
    lists: UserLists,
    tmp_path: Path,
) -> None:
    files = [MaskedFile(name, "0" * 64) for name in masked]
    case = Case("TEST", datetime(2026, 10, 1, tzinfo=UTC), ["a.docx"], files, [])
    path = corpus / "supply-03.docx" if redline else make_docx(para(SUPPLY))
    (source,) = load_sources([path], redline)
    options = ExportOptions(tmp_path / "out", redline_split=redline, existing_case=case)
    res = export_case([source], by_hand(source, lists), options, engine, lists, lambda c: None)
    assert [p.name for p in res.outputs] == expected


def test_a_case_a_file_is_added_to_keeps_its_retention(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R85: the option is for new cases. A case 45 days old and kept for 90 must not expire
    # at once because a file was added to it.
    created = datetime.now(UTC) - timedelta(days=45)
    case = Case(
        "TEST",
        created,
        ["a.docx"],
        [MaskedFile("MASKED-TEST.docx", "0" * 64)],
        [KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", [])],
        retention_days=90,
    )
    annex = make_docx(para("Northwind Trading B.V. delivers."))
    srcs, review = reviewed([annex], engine, lists, case=case)
    saved: list[Case] = []
    options = ExportOptions(tmp_path / "out", retention_days=30, existing_case=case)
    export_case(srcs, review, options, engine, lists, saved.append)
    (kept,) = saved
    assert kept.retention_days == 90 and kept.created_at == created
    assert kept.expires_at > datetime.now(UTC)


def test_a_merge_in_a_file_added_never_rewrites_a_value_of_the_case(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R86: in the added file's review the owner merges the case's company with another
    # name. The case's first file still restores to the stored value; the new form joins the
    # entry's variants. (Ruling R107: the stored group keeps its canonical form in the review
    # too, so the review shows the value the key will keep.)
    case = Case(
        "TEST",
        datetime(2026, 10, 1, tzinfo=UTC),
        ["a.docx"],
        [MaskedFile("MASKED-TEST.docx", "0" * 64)],
        [KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", [])],
    )
    annex = make_docx(
        para("Northwind Trading B.V. and Northwind Holdings International Limited sign.")
    )
    (source,) = load_sources([annex], False)
    text = combined_text([source]).text
    seeded = group_of(text, "[COMPANY_1]", COMPANY, "Northwind Trading B.V.")
    reserved = [entry.placeholder for entry in case.entries]
    review = ReviewState(text, [seeded], [], lists, CaseLists([], [], set()), reserved)
    other = review.hide_text("Northwind Holdings International Limited", COMPANY)
    merged = review.merge([seeded.id, other.id])
    assert (merged.placeholder, merged.canonical) == ("[COMPANY_1]", "Northwind Trading B.V.")
    assert "Northwind Holdings International Limited" in merged.variants
    saved: list[Case] = []
    options = ExportOptions(tmp_path / "out", existing_case=case)
    export_case([source], review, options, engine, lists, saved.append)
    (entry,) = [e for e in saved[0].entries if e.placeholder == "[COMPANY_1]"]
    assert entry.value == "Northwind Trading B.V."
    assert "Northwind Holdings International Limited" in entry.variants


def northwind_case() -> Case:
    """A case of one file, whose key holds the company and its sales address."""
    return Case(
        "TEST",
        datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        ["Supply Agreement.docx"],
        [MaskedFile("MASKED-TEST.docx", "0" * 64)],
        [
            KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", ["Northwind Trading B.V."]),
            KeyEntry("[EMAIL_1]", EMAIL, "sales@northwind.example", []),
        ],
    )


def test_a_value_of_the_case_leaves_a_file_added_that_never_shows_it(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R83: the annex shows neither value of the case, so its review finds neither, but a
    # bookmark is named after the case's sales address and a link leads to it. (Since ruling
    # R112 the cleaner takes the link out anyway; the bookmark is the masker's to rename.)
    case = northwind_case()
    link = (
        '<w:p><w:bookmarkStart w:id="0" w:name="sales_northwind_example"/>'
        '<w:hyperlink r:id="rId1"><w:r><w:t>Write to the sales desk.</w:t></w:r>'
        '</w:hyperlink><w:bookmarkEnd w:id="0"/></w:p>'
    )
    rels = {"word/_rels/document.xml.rels": link_to("mailto:sales@northwind.example")}
    annex = make_docx(para("Burren Logistics Limited carries the goods.") + link, raw=rels)
    (source,) = load_sources([annex], False)
    reserved = [entry.placeholder for entry in case.entries]
    review = by_hand(source, lists, ("Burren Logistics Limited", COMPANY), reserved=reserved)
    saved: list[Case] = []
    options = ExportOptions(tmp_path / "out", existing_case=case)
    res = export_case([source], review, options, engine, lists, saved.append)
    assert not res.blocked and res.leak_hits == []
    assert res.outputs == [tmp_path / "out" / "MASKED-TEST-2.docx"]
    masked = DocxPackage.open(res.outputs[0])
    assert b"northwind" not in masked.raw("word/document.xml").lower()
    assert "word/_rels/document.xml.rels" not in masked.names()
    assert "Write to the sales desk." in body_text(res.outputs[0])
    assert [e.placeholder for e in saved[0].entries] == ["[COMPANY_1]", "[EMAIL_1]", "[COMPANY_2]"]


def test_a_leftover_of_a_value_of_the_case_in_a_file_added_blocks(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Ruling R83: a run of the annex is set in a font named after the case's company, which the
    # annex's text never names.
    case = northwind_case()
    annex = make_docx(para("Burren Logistics Limited carries the goods.") + FONT_RUN)
    (source,) = load_sources([annex], False)
    reserved = [entry.placeholder for entry in case.entries]
    review = by_hand(source, lists, ("Burren Logistics Limited", COMPANY), reserved=reserved)
    saved: list[Case] = []
    out = tmp_path / "out"
    res = export_case(
        [source], review, ExportOptions(out, existing_case=case), engine, lists, saved.append
    )
    assert res.blocked and res.outputs == [] and saved == [] and not out.exists()
    assert [(hit.placeholder, hit.count) for hit in res.leak_hits] == [("[COMPANY_1]", 1)]
    assert res.allowed_hits == []


def test_a_value_of_the_case_left_visible_in_a_file_added_is_allowed(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # The owner switched off the whole group of a value of the case: each place it stands in the
    # file added is left visible on purpose (ruling R60), now that the case's key is checked there.
    case = northwind_case()
    annex = make_docx(para(SUPPLY) + para("Northwind Trading B.V. delivers to every site."))
    (source,) = load_sources([annex], False)
    text = combined_text([source]).text
    seeded = group_of(text, "[COMPANY_1]", COMPANY, "Northwind Trading B.V.")
    seeded.enabled = False
    reserved = [entry.placeholder for entry in case.entries]
    review = ReviewState(text, [seeded], [], lists, CaseLists([], [], set()), reserved)
    options = ExportOptions(tmp_path / "out", existing_case=case)
    res = export_case([source], review, options, engine, lists, lambda c: None)
    assert not res.blocked and res.outputs and res.leak_hits == []
    assert sum(hit.count for hit in res.allowed_hits) == 2


# ---- what an export refuses ---------------------------------------------------------------------


def test_an_export_refuses_what_does_not_fit(
    corpus: Path, make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    saved: list[Case] = []
    out = ExportOptions(tmp_path / "out")
    (source,) = load_sources([make_docx(para(SUPPLY))], False)
    # A review of other text: its plan would hide the wrong characters.
    other = ReviewState("Another text.", [], [], lists, CaseLists([], [], set()))
    with pytest.raises(ValueError, match="not made on these files"):
        export_case([source], other, out, engine, lists, saved.append)
    # Files loaded for a redline, exported as plain files.
    (redline,) = load_sources([corpus / "supply-03.docx"], True)
    with pytest.raises(ValueError, match="redline"):
        export_case([redline], by_hand(redline, lists), out, engine, lists, saved.append)
    # Files with tracked changes loaded without their version before, exported as a redline.
    (unsplit,) = load_sources([corpus / "supply-03.docx"], False)
    redline_options = ExportOptions(tmp_path / "out", redline_split=True)
    with pytest.raises(ValueError, match="tracked changes"):
        export_case(
            [unsplit], by_hand(unsplit, lists), redline_options, engine, lists, saved.append
        )
    # A file added to a case, reviewed without the case's placeholders reserved (ruling R61).
    key = [KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", [])]
    case = Case("TEST", datetime(2026, 10, 1, tzinfo=UTC), ["a.docx"], [], key)
    added = ExportOptions(tmp_path / "out", existing_case=case)
    with pytest.raises(ValueError, match="reserve"):
        export_case([source], by_hand(source, lists), added, engine, lists, saved.append)
    # No file at all.
    nothing = ReviewState("", [], [], lists, CaseLists([], [], set()))
    with pytest.raises(ValueError, match="no file"):
        export_case([], nothing, out, engine, lists, saved.append)
    assert saved == [] and not (tmp_path / "out").exists()


def test_no_masked_file_is_left_without_its_key(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    (source,) = load_sources([make_docx(para(SUPPLY))], False)
    review = by_hand(source, lists, ("Northwind Trading B.V.", COMPANY))

    def refuse(case: Case) -> None:
        raise OSError("The disk is full.")

    out = tmp_path / "out"
    with pytest.raises(OSError, match="disk is full"):
        export_case([source], review, ExportOptions(out), engine, lists, refuse)
    assert not out.exists() or list(out.iterdir()) == []
