"""The Word package: what opens and what is refused, the parts, removing a part, and saving."""

from __future__ import annotations

import zipfile
from pathlib import Path

import docx
import pytest

from tests.fixtures.docx import XMLNS, MakeDocx
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import extract_text
from themask.errors import MaskError, ProtectedFileError, UnsupportedFileError

NOT_A_DOCX = (
    "This is not a Word .docx file. If it is an old .doc, open it in Word and save as .docx."
)
PROTECTED = "This file is protected or encrypted. Please provide an unprotected copy."
COMMENTS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"


# ---- opening ---------------------------------------------------------------------------------


def test_open_doc_renamed(fixtures: Path) -> None:
    with pytest.raises(UnsupportedFileError) as e:
        DocxPackage.open(fixtures / "not-a-docx.doc")
    assert "save as .docx" in e.value.user_message


def test_open_corrupt(fixtures: Path) -> None:
    with pytest.raises(UnsupportedFileError):
        DocxPackage.open(fixtures / "corrupt.docx")


def test_open_encrypted(fixtures: Path) -> None:
    with pytest.raises(ProtectedFileError):
        DocxPackage.open(fixtures / "encrypted.docx")


@pytest.mark.parametrize(
    ("name", "error", "message"),
    [
        ("not-a-docx.doc", UnsupportedFileError, NOT_A_DOCX),
        ("corrupt.docx", UnsupportedFileError, NOT_A_DOCX),
        ("encrypted.docx", ProtectedFileError, PROTECTED),
    ],
)
def test_the_owner_reads_what_is_wrong(
    fixtures: Path, name: str, error: type[MaskError], message: str
) -> None:
    with pytest.raises(error) as e:
        DocxPackage.open(fixtures / name)
    assert e.value.user_message == message


def test_the_encrypted_package_stream_counts_too(fixtures: Path, tmp_path: Path) -> None:
    # Word's encrypted file holds both streams; either name is enough to tell.
    path = tmp_path / "encrypted.docx"
    path.write_bytes(
        (fixtures / "not-a-docx.doc").read_bytes() + "EncryptedPackage".encode("utf-16-le")
    )
    with pytest.raises(ProtectedFileError):
        DocxPackage.open(path)


def test_a_zip_without_a_word_document(tmp_path: Path) -> None:
    path = tmp_path / "workbook.docx"  # an Excel file under the wrong name
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(UnsupportedFileError) as e:
        DocxPackage.open(path)
    assert e.value.user_message == NOT_A_DOCX


def test_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.docx"
    path.write_bytes(b"")
    with pytest.raises(UnsupportedFileError):
        DocxPackage.open(path)


def test_a_damaged_part(make_docx: MakeDocx, tmp_path: Path) -> None:
    # The zip's directory is fine but the bytes of the document no longer match their checksum.
    made = make_docx("<w:p><w:r><w:t>Damaged here</w:t></w:r></w:p>")
    stored = tmp_path / "stored.docx"
    with zipfile.ZipFile(made) as source, zipfile.ZipFile(stored, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))  # stored, not compressed
    stored.write_bytes(stored.read_bytes().replace(b"Damaged here", b"Damaged HERE"))
    with pytest.raises(UnsupportedFileError):
        DocxPackage.open(stored)


def test_a_document_that_is_not_xml(make_docx: MakeDocx) -> None:
    with pytest.raises(UnsupportedFileError):
        DocxPackage.open(make_docx("", raw={"word/document.xml": b"\x00\x01 no XML here"}))


def test_strict_open_xml_is_refused(make_docx: MakeDocx) -> None:
    # Word can save "Strict Open XML", whose elements have other namespaces. The text map would
    # find no text in it at all, so it must not pass for a Word file it can read.
    strict = (
        b'<w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main">'
        b"<w:body><w:p><w:r><w:t>Northwind Trading B.V.</w:t></w:r></w:p></w:body></w:document>"
    )
    with pytest.raises(UnsupportedFileError) as e:
        DocxPackage.open(make_docx("", raw={"word/document.xml": strict}))
    assert e.value.user_message == NOT_A_DOCX


# ---- parts -----------------------------------------------------------------------------------


def test_names_raw_and_xml(corpus: Path) -> None:
    path = corpus / "supply-01.docx"
    pkg = DocxPackage.open(path)
    with zipfile.ZipFile(path) as package:
        assert pkg.names() == package.namelist()
        assert pkg.raw("word/styles.xml") == package.read("word/styles.xml")
    root = pkg.xml("word/document.xml")
    assert root is pkg.xml("word/document.xml")  # parsed once
    assert root.tag == f"{{{NS['w']}}}document"
    with pytest.raises(KeyError):
        pkg.raw("word/missing.xml")


def test_parts_are_parsed_only_when_asked(make_docx: MakeDocx) -> None:
    # A damaged part the text never needs does not stop the file from opening or being read,
    # and a damaged part that is asked for gives the owner's message, not a parser error.
    pkg = DocxPackage.open(
        make_docx("<w:p><w:r><w:t>Hello</w:t></w:r></w:p>", raw={"word/styles.xml": b"<w:styles"})
    )
    assert extract_text(pkg).text == "Hello"
    with pytest.raises(UnsupportedFileError):
        pkg.xml("word/styles.xml")


def test_changes_to_the_parsed_xml_are_what_raw_and_save_give(corpus: Path, tmp_path: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    title = pkg.xml("word/document.xml").find(".//w:t", NS)
    assert title is not None and title.text == "SUPPLY AGREEMENT"
    title.text = "CHANGED TITLE"
    assert b"CHANGED TITLE" in pkg.raw("word/document.xml")
    pkg.save(tmp_path / "out.docx")
    assert (
        DocxPackage.open(tmp_path / "out.docx")
        .xml("word/document.xml")
        .findtext(".//w:t", namespaces=NS)
        == "CHANGED TITLE"
    )


def test_set_raw_replaces_a_parsed_part_and_adds_new_ones(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    pkg.xml("word/header1.xml")  # parsed first: the new bytes must still win
    pkg.set_raw(
        "word/header1.xml", f"<w:hdr {XMLNS}><w:p><w:r><w:t>New</w:t></w:r></w:p></w:hdr>".encode()
    )
    assert pkg.xml("word/header1.xml").findtext(".//w:t", namespaces=NS) == "New"
    pkg.set_raw("word/extra.bin", b"\x00\x01")
    assert pkg.names()[-1] == "word/extra.bin" and pkg.raw("word/extra.bin") == b"\x00\x01"


def test_rels_of(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    rels = pkg.rels_of("word/document.xml")
    assert rels is pkg.xml("word/_rels/document.xml.rels")
    assert {"styles.xml", "header1.xml", "footer1.xml"} <= {r.get("Target") for r in rels}
    assert pkg.rels_of("") is pkg.xml("_rels/.rels")  # the package's own relationships
    with pytest.raises(KeyError):
        pkg.rels_of("word/header1.xml")  # this header has no relationships


def test_text_parts_in_order(make_docx: MakeDocx) -> None:
    empty = "<w:p/>"
    pkg = DocxPackage.open(
        make_docx(
            empty,
            parts={
                "word/footer2.xml": empty,
                "word/header10.xml": empty,
                "word/endnotes.xml": "",
                "word/header2.xml": empty,
                "word/comments.xml": "",
                "word/footnotes.xml": "",
                "word/header1.xml": empty,
                "word/footer1.xml": empty,
            },
        )
    )
    assert pkg.TEXT_PARTS == [
        "word/document.xml",
        "word/header1.xml",
        "word/header2.xml",
        "word/header10.xml",
        "word/footer1.xml",
        "word/footer2.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
    ]
    pkg.remove_part("word/header2.xml")
    assert "word/header2.xml" not in pkg.TEXT_PARTS


def test_namespaces() -> None:
    assert NS == {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
        "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
        "v": "urn:schemas-microsoft-com:vml",
        "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
        "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
        "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
        "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
        "dc": "http://purl.org/dc/elements/1.1/",
        "dcterms": "http://purl.org/dc/terms/",
        "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
        "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
        "xml": "http://www.w3.org/XML/1998/namespace",
    }


def test_namespaces_work_in_xpath(corpus: Path) -> None:
    root = DocxPackage.open(corpus / "supply-01.docx").xml("word/document.xml")
    preserved = root.xpath(".//w:t[@xml:space='preserve']", namespaces=NS)
    assert preserved and all(t.get(f"{{{NS['xml']}}}space") == "preserve" for t in preserved)


# ---- removing a part -------------------------------------------------------------------------


def test_remove_part_cleans_rels_and_types(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-02.docx")
    assert "word/comments.xml" in pkg.names()
    pkg.remove_part("word/comments.xml")
    assert "word/comments.xml" not in pkg.names()
    assert b"comments.xml" not in pkg.raw("word/_rels/document.xml.rels")
    assert b"comments+xml" not in pkg.raw("[Content_Types].xml")


def test_remove_part_follows_relative_targets_and_takes_its_own_relationships(
    corpus: Path,
) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    assert b'Target="../customXml/item1.xml"' in pkg.raw("word/_rels/document.xml.rels")
    pkg.remove_part("customXml/item1.xml")
    assert b"customXml/item1.xml" not in pkg.raw("word/_rels/document.xml.rels")
    # Its own relationships part goes with it; the part those pointed to stays.
    assert "customXml/_rels/item1.xml.rels" not in pkg.names()
    assert "customXml/itemProps1.xml" in pkg.names()
    assert b"styles.xml" in pkg.raw("word/_rels/document.xml.rels")  # the others are untouched


def test_remove_part_finds_absolute_and_escaped_targets_in_any_rels(make_docx: MakeDocx) -> None:
    rels = (
        f'<Relationships xmlns="{PACKAGE_RELS}">'
        f'<Relationship Id="rId1" Type="{REL}/comments" Target="/word/comments.xml"/>'
        f'<Relationship Id="rId2" Type="{REL}/image" Target="media/logo%201.png"/>'
        f'<Relationship Id="rId3" Type="{REL}/hyperlink" Target="comments.xml"'
        ' TargetMode="External"/>'
        "</Relationships>"
    )
    header_rels = (
        f'<Relationships xmlns="{PACKAGE_RELS}">'
        f'<Relationship Id="rId1" Type="{REL}/comments" Target="./comments.xml"/>'
        f'<Relationship Id="rId2" Type="{REL}/image" Target="media/logo%201.png"/>'
        "</Relationships>"
    )
    pkg = DocxPackage.open(
        make_docx(
            "<w:p/>",
            parts={"word/comments.xml": "", "word/header1.xml": "<w:p/>"},
            raw={
                "word/_rels/document.xml.rels": rels.encode(),
                "word/_rels/header1.xml.rels": header_rels.encode(),
                "word/media/logo 1.png": b"\x89PNG",
            },
        )
    )
    pkg.remove_part("word/comments.xml")
    pkg.remove_part("word/media/logo 1.png")
    document_ids = [r.get("Id") for r in pkg.rels_of("word/document.xml")]
    assert document_ids == ["rId3"]  # an external link is not a part, whatever its target says
    assert len(pkg.rels_of("word/header1.xml")) == 0
    assert "word/media/logo 1.png" not in pkg.names()
    assert COMMENTS_TYPE.encode() not in pkg.raw("[Content_Types].xml")


def test_removing_a_part_that_is_not_there_changes_nothing(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    names, types = pkg.names(), pkg.raw("[Content_Types].xml")
    pkg.remove_part("word/comments.xml")  # supply-01 has no comments
    assert pkg.names() == names and pkg.raw("[Content_Types].xml") == types


# ---- copying and saving ----------------------------------------------------------------------


def test_copy_is_deep(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    pkg.xml("word/document.xml")  # parsed before the copy is made
    twin = pkg.copy()
    title = twin.xml("word/document.xml").find(".//w:t", NS)
    assert title is not None
    title.text = "CHANGED"
    twin.set_raw("word/header1.xml", b"<x/>")
    twin.remove_part("word/footer1.xml")
    assert pkg.xml("word/document.xml").findtext(".//w:t", namespaces=NS) == "SUPPLY AGREEMENT"
    assert pkg.raw("word/header1.xml") != b"<x/>"
    assert "word/footer1.xml" in pkg.names() and "word/footer1.xml" not in twin.names()
    assert b"footer1.xml" in pkg.raw("word/_rels/document.xml.rels")


def test_original_untouched(corpus: Path, tmp_path: Path) -> None:
    src = corpus / "supply-01.docx"
    before = src.read_bytes()
    pkg = DocxPackage.open(src)
    pkg.remove_part("word/header1.xml")
    pkg.save(tmp_path / "out.docx")
    assert src.read_bytes() == before


def test_save_refuses_to_write_over_the_original(corpus: Path, tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    src.write_bytes((corpus / "supply-01.docx").read_bytes())
    before = src.read_bytes()
    pkg = DocxPackage.open(src)
    pkg.remove_part("word/header1.xml")
    with pytest.raises(ValueError):
        pkg.save(src)
    with pytest.raises(ValueError):
        pkg.copy().save(tmp_path / "." / "contract.docx")
    assert src.read_bytes() == before


def test_save_writes_content_types_first_and_compresses(
    make_docx: MakeDocx, tmp_path: Path
) -> None:
    made = make_docx("<w:p><w:r><w:t>Hello</w:t></w:r></w:p>")
    shuffled = tmp_path / "shuffled.docx"
    with zipfile.ZipFile(made) as source, zipfile.ZipFile(shuffled, "w") as target:
        for name in reversed(source.namelist()):  # [Content_Types].xml comes last here
            target.writestr(name, source.read(name))
    pkg = DocxPackage.open(shuffled)
    pkg.save(tmp_path / "out.docx")
    with zipfile.ZipFile(tmp_path / "out.docx") as package:
        infos = package.infolist()
        assert infos[0].filename == "[Content_Types].xml"
        assert sorted(i.filename for i in infos) == sorted(pkg.names())
        assert {i.compress_type for i in infos} == {zipfile.ZIP_DEFLATED}
        assert package.testzip() is None


def test_saved_file_opens_with_python_docx(corpus: Path, tmp_path: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-02.docx")
    pkg.remove_part("word/comments.xml")
    pkg.xml("word/document.xml")  # parsed, so it is written back from the tree
    pkg.save(tmp_path / "out.docx")
    document = docx.Document(str(tmp_path / "out.docx"))
    assert document.paragraphs[0].text == "SUPPLY AGREEMENT"
    assert extract_text(DocxPackage.open(tmp_path / "out.docx")).text == extract_text(pkg).text
