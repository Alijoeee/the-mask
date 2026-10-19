"""The cleaner: everything it takes out of a Word file, and what it must leave alone.

The corpus files give the cases the plan names (comments, properties, pictures, hidden text, a
text box, the settings). The other constructs are small Word files built here in memory, one
construct to a test, so each test shows which part of the file it looks at: ``package`` builds
one, ``assert_consistent`` is the check every cleaned file has to pass (each relationship leads
to a part, each reference in the XML to a relationship, each Override to a part), and
``everywhere`` is every byte of the package, for "this text is nowhere in the file".
"""

from __future__ import annotations

import copy
import json
import posixpath
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import docx
import pytest
from lxml import etree

from tests.fixtures.docx import MAIN, PACKAGE_RELS, REL, TYPES, WML, XMLNS, content_types
from themask.docx.cleaner import ALTCHUNK_NOTE, EQUATION_NOTE, CleanReport, clean
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import View, extract_text, has_comments
from themask.instruction import IMAGE_NOTE, OBJECT_NOTE

NOW = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
STAMP = "2030-01-02T03:04:05Z"

# The namespaces the small files here use besides the ones tests/fixtures/docx.py declares.
_MORE = {
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "o": "urn:schemas-microsoft-com:office:office",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "cx": "http://schemas.microsoft.com/office/drawing/2014/chartex",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
}
DECLARATIONS = XMLNS + "".join(f' xmlns:{prefix}="{uri}"' for prefix, uri in _MORE.items())

# Relationship types (the first group are all under REL) and the content types used below.
IMAGE, CHART, OLE = f"{REL}/image", f"{REL}/chart", f"{REL}/oleObject"
HYPERLINK, SETTINGS_REL = f"{REL}/hyperlink", f"{REL}/settings"
CUSTOM_XML, CUSTOM_XML_PROPS = f"{REL}/customXml", f"{REL}/customXmlProps"
TEMPLATE, MAIL_MERGE, AFCHUNK = (
    f"{REL}/{k}" for k in ("attachedTemplate", "mailMergeSource", "aFChunk")
)
HEADER, FOOTER = f"{REL}/header", f"{REL}/footer"
THUMBNAIL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"
CORE_REL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
APP_REL, CUSTOM_REL = f"{REL}/extended-properties", f"{REL}/custom-properties"
SIGNATURES = "http://schemas.openxmlformats.org/package/2006/relationships/digital-signature"
HEADER_TYPE, FOOTER_TYPE = f"{WML}.header+xml", f"{WML}.footer+xml"
SETTINGS_TYPE = f"{WML}.settings+xml"
CUSTOM_XML_PROPS_TYPE = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
DEFAULT_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "bin": "application/octet-stream",
    "html": "text/html",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

VIEWS: tuple[View, ...] = ("accepted", "rejected")
Row = tuple[str, str] | tuple[str, str, str]  # (type, target) or (type, target, "External")


# ---- building small files and checking big ones --------------------------------------------------


def part(root: str, content: str = "") -> bytes:
    """A part of the package: element ``root`` ("w:hdr") holding ``content``, namespaces declared."""
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f"<{root} {DECLARATIONS}>{content}</{root}>"
    ).encode()


def rels_xml(rows: Sequence[Row]) -> bytes:
    """A .rels part with the ids rId1, rId2, ... in the order of ``rows``."""
    items = []
    for number, (kind, target, *mode) in enumerate(rows, start=1):
        external = f' TargetMode="{mode[0]}"' if mode else ""
        items.append(f'<Relationship Id="rId{number}" Type="{kind}" Target="{target}"{external}/>')
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{PACKAGE_RELS}">{"".join(items)}</Relationships>'
    ).encode()


def package(
    body: str = "<w:p/>",
    *,
    rels: Sequence[Row] = (),
    parts: Mapping[str, bytes] | None = None,
    types: Mapping[str, str] | None = None,
    package_rels: Sequence[Row] = (),
) -> DocxPackage:
    """A small Word file in memory: ``body`` is the content of w:body.

    ``rels`` are the document's relationships (rId1, rId2, ... in order), ``package_rels`` those
    the package adds to its officeDocument one, ``parts`` more parts byte for byte and ``types``
    the content type of each part that has an Override.
    """
    entries = {
        "[Content_Types].xml": content_types(
            {"word/document.xml": MAIN, **(types or {})}, DEFAULT_TYPES
        ),
        "_rels/.rels": rels_xml([(f"{REL}/officeDocument", "word/document.xml"), *package_rels]),
        "word/document.xml": part("w:document", f"<w:body>{body}</w:body>"),
    }
    if rels:
        entries["word/_rels/document.xml.rels"] = rels_xml(rels)
    entries.update(parts or {})
    return DocxPackage(entries)


def everywhere(pkg: DocxPackage) -> bytes:
    """Every byte of every part."""
    return b"\n".join(pkg.raw(name) for name in pkg.names())


def saved_bytes(pkg: DocxPackage, tmp_path: Path) -> bytes:
    """Every byte of the file ``pkg`` saves to: what an AI tool would be given."""
    path = tmp_path / "saved.docx"
    pkg.save(path)
    with zipfile.ZipFile(path) as archive:
        return b"\n".join(archive.read(name) for name in archive.namelist())


def document(pkg: DocxPackage, name: str = "word/document.xml") -> bytes:
    return etree.tostring(pkg.xml(name))


def content(pkg: DocxPackage, name: str = "word/document.xml") -> bytes:
    """The part as it is, but for the namespace declarations nothing in it uses, which the
    cleaner drops (ruling R102), and the package's own prefixes, which it keeps."""
    root = copy.deepcopy(pkg.xml(name))
    etree.cleanup_namespaces(root, keep_ns_prefixes=list(NS))
    return etree.tostring(root)


def text_of(pkg: DocxPackage) -> str:
    return extract_text(pkg).text


def assert_consistent(pkg: DocxPackage) -> None:
    """The package still holds together after parts and relationships were taken out of it."""
    names = pkg.names()
    for override in pkg.xml("[Content_Types].xml").iterchildren(f"{{{TYPES}}}Override"):
        assert override.get("PartName", "").lstrip("/") in names, override.get("PartName")
    with_rels = set()
    for name in (n for n in names if n.endswith(".rels")):
        folder = posixpath.dirname(posixpath.dirname(name))  # word/_rels/x.rels belongs in word/
        source = posixpath.join(folder, posixpath.basename(name)[: -len(".rels")])
        with_rels.add(source)
        assert source == "" or source in names, f"{name} belongs to a part that is gone"
        rows = list(pkg.xml(name).iterchildren(f"{{{PACKAGE_RELS}}}Relationship"))
        assert rows, f"{name} is left empty"
        for row in rows:
            if row.get("TargetMode") != "External":
                target = row.get("Target", "")
                path = target[1:] if target.startswith("/") else posixpath.join(folder, target)
                assert posixpath.normpath(path) in names, f"{name}: {target} is not a part"
    for name in (n for n in names if n.endswith(".xml") and n != "[Content_Types].xml"):
        root = pkg.xml(name)
        assert not root.xpath("//w:r/w:r", namespaces=NS), f"{name}: a run inside a run"
        used = {
            value
            for value in root.xpath("//@*[namespace-uri()=$r]", r=NS["r"])
            if isinstance(value, str)
        }
        if not used:
            continue
        assert name in with_rels, f"{name} refers to relationships but has none"
        known = {row.get("Id") for row in pkg.rels_of(name)}
        assert used <= known, f"{name} refers to {used - known}, which are not relationships"


def para(*content: str) -> str:
    return "<w:p>" + "".join(content) + "</w:p>"


def run(text: str, props: str = "") -> str:
    properties = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{properties}<w:t xml:space="preserve">{text}</w:t></w:r>'


def picture(rid: str, *, descr: str = "", kind: str = "embed", link: str = "") -> str:
    """A w:drawing holding a picture; its image is the relationship ``rid``."""
    alt = f' descr="{descr}"' if descr else ""
    return (
        '<w:drawing><wp:inline><wp:extent cx="100" cy="100"/>'
        f'<wp:docPr id="1" name="Picture 1"{alt}>{link}</wp:docPr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:blipFill><a:blip r:{kind}="{rid}"/></pic:blipFill></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing>"
    )


def text_box(content: str, *, name: str = "Text Box 1", alt: str = "") -> str:
    """A w:drawing holding a text box: DrawingML text, no picture. ``content`` is its paragraphs."""
    return (
        f'<w:drawing><wp:anchor><wp:docPr id="2" name="{name}"{alt}/>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        f"<wps:wsp><wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx></wps:wsp>"
        "</a:graphicData></a:graphic></wp:anchor></w:drawing>"
    )


def field(instruction: str | Sequence[str], result: str) -> str:
    """The runs of a complex field as Word writes them; ``result`` is its already-made runs."""
    pieces = [instruction] if isinstance(instruction, str) else instruction
    codes = "".join(
        f'<w:r><w:instrText xml:space="preserve">{p}</w:instrText></w:r>' for p in pieces
    )
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'{codes}<w:r><w:fldChar w:fldCharType="separate"/></w:r>{result}'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def in_header(content: str) -> dict[str, bytes]:
    return {"word/header1.xml": part("w:hdr", content)}


def with_header(body: str, header: str) -> DocxPackage:
    """A small file whose only header holds the paragraphs ``header``."""
    return package(
        body,
        rels=[(HEADER, "header1.xml")],
        parts=in_header(header),
        types={"word/header1.xml": HEADER_TYPE},
    )


HIDDEN = "<w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden</w:t></w:r>"


# ---- the plan's tests, on the corpus -------------------------------------------------------------


def test_comments_gone(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-02.docx")
    said = [t.text or "" for t in pkg.xml("word/comments.xml").iter(f"{{{NS['w']}}}t")]
    assert len(said) == 2 and "Volumes confirmed" in said[0]
    rep = clean(pkg)
    names = set(pkg.names())
    xml = document(pkg)
    assert rep.comments == 2
    assert not {n for n in names if "comments" in n or n.endswith("people.xml")}
    assert b"commentReference" not in xml and b"commentRangeStart" not in xml
    assert b"commentRangeEnd" not in xml and not has_comments(pkg)
    assert not any(text.encode() in everywhere(pkg) for text in said)  # the comments are nowhere
    assert_consistent(pkg)


def test_properties_cleared(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-04.docx")
    clean(pkg)
    core = etree.fromstring(pkg.raw("docProps/core.xml"))
    app = pkg.raw("docProps/app.xml").decode()
    for tag in ("dc:creator", "cp:lastModifiedBy", "dc:title", "cp:keywords"):
        el = core.find(tag, NS)
        assert el is None or not (el.text or "").strip(), tag
    assert "TitlesOfParts" not in app and "HeadingPairs" not in app
    assert "<Company></Company>" in app.replace("<Company/>", "<Company></Company>")
    assert "docProps/custom.xml" not in pkg.names()
    assert_consistent(pkg)


def test_images_replaced(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-05.docx")
    n_media = len([n for n in pkg.names() if n.startswith("word/media/")])
    rep = clean(pkg)
    assert n_media == 2 and rep.images == n_media and rep.objects == 0
    assert not [n for n in pkg.names() if n.startswith("word/media/")]
    assert text_of(pkg).count(IMAGE_NOTE) == n_media
    assert_consistent(pkg)


def test_hidden_text_removed(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "services-02.docx")
    truth = json.loads((corpus / "services-02.truth.json").read_text())
    hidden = next(t["value"] for t in truth if t.get("hidden"))
    assert hidden in text_of(pkg)
    rep = clean(pkg)
    assert hidden not in text_of(pkg) and b"w:vanish" not in document(pkg)
    assert rep.hidden_runs == 1
    assert hidden.encode() not in everywhere(pkg)  # not hidden somewhere else in the file either


def test_textbox_kept(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "services-03.docx")
    clean(pkg)
    assert "Text box note" in text_of(pkg)


def test_settings_scrubbed(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    clean(pkg)
    s = pkg.raw("word/settings.xml")
    assert b"w:rsids" not in s and b"attachedTemplate" not in s and b"docVars" not in s
    assert b"w:rsidR=" not in pkg.raw("word/document.xml")


def test_file_still_opens_with_python_docx(corpus: Path, tmp_path: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-05.docx")
    clean(pkg)
    pkg.save(tmp_path / "c.docx")
    assert docx.Document(str(tmp_path / "c.docx")).paragraphs
    assert DocxPackage.open(tmp_path / "c.docx").TEXT_PARTS


# ---- more on the corpus: where else the values were ----------------------------------------------


def test_the_template_path_goes_with_its_relationship(corpus: Path) -> None:
    # w:attachedTemplate points at a relationship whose target is a path on the author's disk.
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    assert b"file:///" in everywhere(pkg)
    rep = clean(pkg)
    assert b"file:///" not in everywhere(pkg) and b".dotx" not in everywhere(pkg)
    assert "word/_rels/settings.xml.rels" in rep.parts_removed  # nothing else was in it
    assert_consistent(pkg)


def test_picture_alt_text_goes_with_the_picture(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-05.docx")
    assert b"Signature of Bryan Stone" in everywhere(pkg)
    clean(pkg)
    assert b"Signature of Bryan Stone" not in everywhere(pkg)
    assert b"Kronberg logo" not in everywhere(pkg)


def test_the_text_box_is_in_the_file_once(corpus: Path) -> None:
    # Ruling R16: Word stores a text box twice, in mc:Choice and in the VML mc:Fallback.
    pkg = DocxPackage.open(corpus / "services-03.docx")
    assert document(pkg).count(b"Text box note") == 2
    rep = clean(pkg)
    after = document(pkg)
    assert after.count(b"Text box note") == 1 and text_of(pkg).count("Text box note") == 1
    assert rep.fallbacks_removed == 1
    assert b"AlternateContent" not in after and b"Fallback" not in after and b"w:pict" not in after
    assert pkg.xml("word/document.xml").find(".//wps:txbx", NS) is not None  # the DrawingML copy
    assert_consistent(pkg)


def test_a_kept_shape_loses_its_name(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "services-03.docx")
    clean(pkg)
    doc_pr = pkg.xml("word/document.xml").find(".//wp:docPr", NS)
    assert doc_pr is not None and doc_pr.get("name") == "Shape1"
    assert b"Text Box 1" not in everywhere(pkg)


def test_the_footer_field_that_is_not_personal_stays(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    rep = clean(pkg)
    footer = pkg.xml("word/footer1.xml")
    assert footer.find(".//w:fldSimple", NS).get(f"{{{NS['w']}}}instr") == "PAGE"
    assert rep.fields_flattened == 0


def test_a_cleaned_file_is_clean_a_second_time(corpus: Path) -> None:
    for name in ("supply-02", "supply-04", "supply-05", "services-03", "dpa-01"):
        pkg = DocxPackage.open(corpus / f"{name}.docx")
        first = clean(pkg, now=NOW)
        assert first != CleanReport(), name
        parts = {n: pkg.raw(n) for n in pkg.names()}
        assert clean(pkg, now=NOW) == CleanReport(), name
        assert {n: pkg.raw(n) for n in pkg.names()} == parts, name


def test_every_corpus_file_is_cleaned_and_keeps_its_visible_text(
    corpus: Path, tmp_path: Path
) -> None:
    gone = ("word/media/", "comments", "customxml/", "word/glossary/", "word/embeddings/")
    gone += ("word/charts/", "word/diagrams/", "people.xml", "docprops/custom.xml")
    manifest = json.loads((corpus / "manifest.json").read_text())
    files = [d["file"] for d in manifest if d["format"] == "docx"]
    assert len(files) >= 25  # the contracts and their annexes
    for file in files:
        pkg = DocxPackage.open(corpus / file)
        expected = {view: visible_text(pkg, view) for view in VIEWS}
        layout, text_parts = structure(pkg), pkg.TEXT_PARTS
        clean(pkg, now=NOW)
        assert structure(pkg) == layout, file  # the layout of the contract is not touched
        assert not [n for n in pkg.names() if any(g in n.casefold() for g in gone)], file
        assert not rsid_traces(pkg), file
        assert b"docVar" not in everywhere(pkg) and b"attachedTemplate" not in everywhere(pkg), file
        for view in VIEWS:
            # What was visible is still there, word for word; the only new text is the notes.
            assert extract_text(pkg, view).text.replace(IMAGE_NOTE, "") == expected[view], file
        assert_consistent(pkg)
        pkg.save(tmp_path / file)
        assert docx.Document(str(tmp_path / file)).paragraphs, file
        assert DocxPackage.open(tmp_path / file).TEXT_PARTS == text_parts, file


# (Not w:hyperlink: the links to the outside go since ruling R112, their text stays.)
STRUCTURE = ("w:p", "w:tbl", "w:tr", "w:tc", "w:numPr", "w:sectPr")
STRUCTURE += ("w:footnoteReference", "w:bookmarkStart", "w:tblGrid")


def structure(pkg: DocxPackage) -> dict[str, int]:
    """How many paragraphs, tables, numbered items ... the text parts hold, apart from fallbacks."""
    return {
        tag: sum(
            len(pkg.xml(name).xpath(f"//{tag}[not(ancestor::mc:Fallback)]", namespaces=NS))
            for name in pkg.TEXT_PARTS
        )
        for tag in STRUCTURE
    }


def rsid_traces(pkg: DocxPackage) -> list[object]:
    """The attributes and elements named rsid* in the XML parts: not the letters, which a name has."""
    found: list[object] = []
    for name in pkg.names():
        if name.endswith(".xml") and name != "[Content_Types].xml":
            found += pkg.xml(name).xpath(
                "//@*[starts-with(local-name(), 'rsid')] | //*[starts-with(local-name(), 'rsid')]"
            )
    return found


def visible_text(pkg: DocxPackage, view: View) -> str:
    """The text of the file without its hidden runs, found without the cleaner."""
    twin = pkg.copy()
    for name in twin.TEXT_PARTS:
        for hidden in twin.xml(name).xpath(".//w:r[w:rPr/w:vanish]", namespaces=NS):
            hidden.getparent().remove(hidden)
    return extract_text(twin, view).text


# ---- the report ----------------------------------------------------------------------------------


def test_the_report_of_a_file_with_nothing_to_clean() -> None:
    assert clean(package("<w:p/>")) == CleanReport()
    assert CleanReport(1, 2, 3, 4, ["x"], ["y"]).fields_flattened == 0  # the six first, in order


def test_parts_removed_are_the_names_gone_in_the_order_of_the_zip(corpus: Path) -> None:
    pkg = DocxPackage.open(corpus / "supply-05.docx")
    before = pkg.names()
    rep = clean(pkg)
    assert rep.parts_removed == [n for n in before if n not in pkg.names()]
    assert {"word/media/image1.png", "word/media/image2.png", "customXml/item1.xml"} <= set(
        rep.parts_removed
    )
    assert "customXml/_rels/item1.xml.rels" in rep.parts_removed  # its relationships go with it


# ---- comments ------------------------------------------------------------------------------------

_W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
_W16CID = "http://schemas.microsoft.com/office/word/2016/wordml/cid"
_W16CEX = "http://schemas.microsoft.com/office/word/2018/wordml/cex"
_COMMENTS_XML = (
    f'<w:comments xmlns:w="{NS["w"]}">'
    '<w:comment w:id="7" w:author="Jane Doe" w:initials="JD">'
    "<w:p><w:r><w:t>Ask Acme</w:t></w:r></w:p></w:comment></w:comments>"
)
_EXTENDED_XML = (
    f'<w15:commentsEx xmlns:w15="{_W15}">'
    '<w15:commentEx w15:paraId="1A2B3C4D" w15:done="0"/></w15:commentsEx>'
)
_IDS_XML = (
    f'<w16cid:commentsIds xmlns:w16cid="{_W16CID}">'
    '<w16cid:commentId w16cid:paraId="1A2B3C4D" w16cid:durableId="12345678"/></w16cid:commentsIds>'
)
_EXTENSIBLE_XML = (
    f'<w16cex:commentsExtensible xmlns:w16cex="{_W16CEX}">'
    '<w16cex:commentExtensible w16cex:durableId="12345678" w16cex:dateUtc="2026-04-16T10:00:00Z"/>'
    "</w16cex:commentsExtensible>"
)
_PEOPLE_XML = (
    f'<w15:people xmlns:w15="{_W15}"><w15:person w15:author="Jane Doe">'
    '<w15:presenceInfo w15:providerId="AD" w15:userId="S::jane.doe@acme.example::1"/>'
    "</w15:person></w15:people>"
)
_MS_RELS = "http://schemas.microsoft.com/office"
_COMMENT_PARTS = {  # kind: (content, standard name, content type, relationship type)
    "comments": (_COMMENTS_XML, "word/comments.xml", f"{WML}.comments+xml", f"{REL}/comments"),
    "commentsExtended": (
        _EXTENDED_XML,
        "word/commentsExtended.xml",
        f"{WML}.commentsExtended+xml",
        f"{_MS_RELS}/2011/relationships/commentsExtended",
    ),
    "commentsIds": (
        _IDS_XML,
        "word/commentsIds.xml",
        f"{WML}.commentsIds+xml",
        f"{_MS_RELS}/2016/09/relationships/commentsIds",
    ),
    "commentsExtensible": (
        _EXTENSIBLE_XML,
        "word/commentsExtensible.xml",
        f"{WML}.commentsExtensible+xml",
        f"{_MS_RELS}/2018/08/relationships/commentsExtensible",
    ),
    "people": (
        _PEOPLE_XML,
        "word/people.xml",
        f"{WML}.people+xml",
        f"{_MS_RELS}/2011/relationships/people",
    ),
}
_COMMENTED = para(
    '<w:commentRangeStart w:id="7"/>',
    run("Price"),
    '<w:commentRangeEnd w:id="7"/>',
    '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="7"/></w:r>',
    run(" in total"),
)


def commented(how: str) -> DocxPackage:
    """A file with a comment and the four parts Word adds to it, found in the way ``how`` says."""
    parts, types, rels = {}, {}, []
    for number, (xml, standard, content_type, relationship) in enumerate(_COMMENT_PARTS.values()):
        name = standard if how == "by name" else f"word/remark{number}.xml"
        parts[name] = f'<?xml version="1.0"?>{xml}'.encode()
        if how == "by content type":
            types[name] = content_type
        if how == "by relationship":
            rels.append((relationship, posixpath.basename(name)))
    return package(_COMMENTED, rels=rels, parts=parts, types=types)


@pytest.mark.parametrize("how", ["by name", "by content type", "by relationship"])
def test_every_comment_part_goes_however_it_is_found(how: str) -> None:
    pkg = commented(how)
    assert has_comments(pkg) is True and "Ask Acme" in everywhere(pkg).decode()
    rep = clean(pkg)
    assert rep.comments == 1
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert text_of(pkg) == "Price in total" and not has_comments(pkg)
    for stale in (b"comment", b"Comment", b"people", b"Jane", b"Ask Acme"):
        assert stale not in everywhere(pkg)
    assert_consistent(pkg)


def test_a_run_with_a_comment_reference_and_text_keeps_the_text() -> None:
    pkg = package(para('<w:r><w:t>keep</w:t><w:commentReference w:id="3"/></w:r>'))
    clean(pkg)
    assert text_of(pkg) == "keep" and b"commentReference" not in document(pkg)


def test_comments_in_footnotes_are_stripped_too() -> None:
    note = para('<w:commentRangeStart w:id="1"/>', run("Note"), '<w:commentRangeEnd w:id="1"/>')
    note += para('<w:r><w:commentReference w:id="1"/></w:r>')
    pkg = package(
        parts={
            "word/footnotes.xml": part("w:footnotes", f'<w:footnote w:id="1">{note}</w:footnote>')
        },
        types={"word/footnotes.xml": f"{WML}.footnotes+xml"},
        rels=[(f"{REL}/footnotes", "footnotes.xml")],
    )
    assert clean(pkg).comments == 1
    assert b"comment" not in document(pkg, "word/footnotes.xml")


# ---- revision traces and settings ----------------------------------------------------------------


def test_rsids_are_stripped_from_every_part() -> None:
    attributes = " ".join(
        f'w:{name}="00AB12CD"'
        for name in ("rsidR", "rsidRPr", "rsidRDefault", "rsidP", "rsidDel", "rsidSect", "rsidTr")
    )
    styles = part(
        "w:styles", '<w:style w:type="paragraph" w:styleId="A"><w:rsid w:val="00AB12CD"/></w:style>'
    )
    pkg = package(
        f'<w:p {attributes} w:other="keep"><w:r {attributes}><w:t>Text</w:t></w:r></w:p>',
        parts={
            "word/styles.xml": styles,
            "word/footnotes.xml": part(
                "w:footnotes", f"<w:footnote><w:p {attributes}/></w:footnote>"
            ),
        },
        types={"word/footnotes.xml": f"{WML}.footnotes+xml"},
        rels=[(f"{REL}/footnotes", "footnotes.xml")],
    )
    clean(pkg)
    assert not rsid_traces(pkg)
    for name in ("word/document.xml", "word/styles.xml", "word/footnotes.xml"):
        assert b"rsid" not in pkg.raw(name), name  # none of these has the letters elsewhere
    assert pkg.xml("word/document.xml").find(".//w:p", NS).get(f"{{{NS['w']}}}other") == "keep"
    assert text_of(pkg) == "Text\n"  # and the footnote's paragraph, which is empty
    assert pkg.xml("word/styles.xml").find(".//w:style", NS).get(f"{{{NS['w']}}}styleId") == "A"


# ---- namespace declarations (ruling R102) --------------------------------------------------------


def test_a_declaration_nothing_uses_goes_and_one_in_use_stays(tmp_path: Path) -> None:
    document = (
        f"<w:document {DECLARATIONS}"
        ' xmlns:ns0="urn:northwind-trading-bv:contract-schema"'
        ' xmlns:nw="http://northwind-trading.example/2026/templates"><w:body>'
        "<w:p><w:r><w:t>Signed for the Supplier.</w:t><nw:NorthwindTradingBV/></w:r></w:p>"
        "</w:body></w:document>"
    )
    header = (
        f'<w:hdr {DECLARATIONS} xmlns:acme="http://acme-supplies.example/letterhead" '
        'mc:Ignorable="w14 wp14" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing">'
        "<w:p><w:r><w:t>Page</w:t></w:r></w:p></w:hdr>"
    )
    pkg = package(
        rels=[(HEADER, "header1.xml")],
        parts={
            "word/document.xml": ('<?xml version="1.0" encoding="UTF-8"?>\n' + document).encode(),
            "word/header1.xml": ('<?xml version="1.0" encoding="UTF-8"?>\n' + header).encode(),
        },
        types={"word/header1.xml": HEADER_TYPE},
    )
    clean(pkg)
    saved = saved_bytes(pkg, tmp_path)
    assert b"northwind-trading-bv" not in saved and b"acme-supplies" not in saved
    # The one in use stays, for the leak check to find.
    assert b'xmlns:nw="http://northwind-trading.example/2026/templates"' in saved
    assert b"<nw:NorthwindTradingBV/>" in saved
    # The prefixes mc:Ignorable names stay declared, used or not: Word refuses the file otherwise.
    header_part = pkg.raw("word/header1.xml")
    assert b'xmlns:w14="' in header_part and b'xmlns:wp14="' in header_part
    assert b'mc:Ignorable="w14 wp14"' in header_part and b'xmlns:mc="' in header_part
    opened = docx.Document(str(tmp_path / "saved.docx"))
    assert opened.paragraphs[0].text == "Signed for the Supplier."


def test_every_corpus_file_keeps_its_ignorable_prefixes(corpus: Path, tmp_path: Path) -> None:
    # The corpus files declare mc:Ignorable="w14 wp14" on w:document, as Word and python-docx do.
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    assert b'mc:Ignorable="w14 wp14"' in pkg.raw("word/document.xml")
    clean(pkg)
    document = pkg.raw("word/document.xml")
    assert b'xmlns:w14="' in document and b'xmlns:wp14="' in document
    saved = tmp_path / "supply-01-cleaned.docx"
    pkg.save(saved)
    assert docx.Document(str(saved)).paragraphs


def test_the_main_document_is_cleaned_wherever_the_package_keeps_it() -> None:
    # The package may name another part as its main document; its text and rsids are cleaned too.
    body = f'<w:body><w:p w:rsidR="00AB12CD">{HIDDEN}{run("kept")}</w:p></w:body>'
    pkg = DocxPackage(
        {
            "[Content_Types].xml": content_types({"doc/main.xml": MAIN}, DEFAULT_TYPES),
            "_rels/.rels": rels_xml([(f"{REL}/officeDocument", "/doc/main.xml")]),
            "doc/main.xml": part("w:document", body),
        }
    )
    assert pkg.TEXT_PARTS == ["doc/main.xml"]
    rep = clean(pkg)
    assert rep.hidden_runs == 1 and text_of(pkg) == "kept"
    assert not rsid_traces(pkg)


def settings_package() -> DocxPackage:
    settings = part(
        "w:settings",
        '<w:zoom w:percent="100"/><w:trackRevisions/><w:attachedTemplate r:id="rId1"/>'
        '<w:defaultTabStop w:val="720"/>'
        '<w:mailMerge><w:mainDocumentType w:val="formLetters"/><w:dataSource r:id="rId2"/>'
        '<w:query w:val="SELECT * FROM Clients"/></w:mailMerge>'
        '<w:docVars><w:docVar w:name="Client" w:val="Acme"/></w:docVars>'
        '<w:rsids><w:rsidRoot w:val="00B47730"/><w:rsid w:val="00034616"/></w:rsids>'
        '<w:saveThroughXslt r:id="rId3"/>',
    )
    settings_rels = rels_xml(
        [
            (TEMPLATE, "file:///C:/Templates/Acme%20Deals.dotx", "External"),
            (MAIL_MERGE, "file:///C:/Clients/Acme.xlsx", "External"),
            (OLE, "file:///C:/Stylesheets/keep.xsl", "External"),
        ]
    )
    return package(
        rels=[(SETTINGS_REL, "settings.xml")],
        parts={"word/settings.xml": settings, "word/_rels/settings.xml.rels": settings_rels},
        types={"word/settings.xml": SETTINGS_TYPE},
    )


def test_settings_lose_their_traces_and_keep_the_rest() -> None:
    pkg = settings_package()
    clean(pkg)
    settings = pkg.raw("word/settings.xml")
    for gone in (b"docVar", b"attachedTemplate", b"rsid", b"trackRevisions", b"mailMerge", b"Acme"):
        assert gone not in settings, gone
    assert (
        b"w:zoom" in settings and b"w:defaultTabStop" in settings and b"saveThroughXslt" in settings
    )


def test_the_links_of_removed_settings_go_and_the_ones_still_used_stay() -> None:
    pkg = settings_package()
    clean(pkg)
    rows = list(pkg.rels_of("word/settings.xml"))
    assert [r.get("Target") for r in rows] == ["file:///C:/Stylesheets/keep.xsl"]  # used by rId3
    assert b"Acme" not in everywhere(pkg) and b".dotx" not in everywhere(pkg)
    assert_consistent(pkg)


def test_settings_without_relationships_or_without_settings_are_fine() -> None:
    bare = package(
        rels=[(SETTINGS_REL, "settings.xml")],
        parts={"word/settings.xml": part("w:settings", "<w:trackRevisions/>")},
        types={"word/settings.xml": SETTINGS_TYPE},
    )
    clean(bare)
    assert b"trackRevisions" not in bare.raw("word/settings.xml")
    assert clean(package()) == CleanReport()  # no settings part at all


# ---- hidden text ---------------------------------------------------------------------------------


def test_hidden_runs_are_removed_wherever_they_are() -> None:
    body = (
        para(run("Open "), HIDDEN)
        + f"<w:tbl><w:tr><w:tc>{para(HIDDEN, run('cell'))}</w:tc></w:tr></w:tbl>"
        + para("<w:r><w:rPr><w:specVanish/></w:rPr><w:t>special</w:t></w:r>", run("tail"))
    )
    pkg = with_header(body, para(HIDDEN, run("Header")))
    rep = clean(pkg)
    assert rep.hidden_runs == 4
    assert text_of(pkg) == "Open \ncell\ntail\nHeader"
    assert b"vanish" not in everywhere(pkg) and b"Vanish" not in everywhere(pkg)
    assert b"hidden" not in everywhere(pkg)


def test_hidden_text_in_a_text_box_is_removed() -> None:
    pkg = package(para(f"<w:r>{text_box(para(HIDDEN, run('Shown')))}</w:r>"))
    assert clean(pkg).hidden_runs == 1
    assert text_of(pkg).splitlines()[-1] == "Shown" and b"hidden" not in everywhere(pkg)


def test_a_hidden_toggle_that_is_off_hides_nothing() -> None:
    body = para(
        run("a", '<w:vanish w:val="0"/>'),
        run("b", '<w:vanish w:val="false"/>'),
        run("c", '<w:vanish w:val="off"/>'),
        run("d", '<w:vanish w:val="1"/>'),
        run("e", '<w:vanish w:val="true"/>'),
        run("f", '<w:vanish w:val="on"/>'),
        run("g", '<w:specVanish w:val="0"/>'),
        run("h", "<w:webHidden/>"),  # hidden on the web only: the contents page uses it
    )
    pkg = package(body)
    assert clean(pkg).hidden_runs == 3
    assert text_of(pkg) == "abcgh"


def test_a_paragraph_that_was_only_hidden_text_stays_as_an_empty_paragraph() -> None:
    pkg = package(para(HIDDEN) + para(run("next")))
    clean(pkg)
    assert text_of(pkg) == "\nnext" and len(extract_text(pkg).segments) == 2


def test_a_hidden_picture_leaves_no_note_and_no_file() -> None:
    pkg = package(
        para(f"<w:r><w:rPr><w:vanish/></w:rPr>{picture('rId1')}</w:r>"),
        rels=[(IMAGE, "media/logo.png")],
        parts={"word/media/logo.png": b"PNG"},
    )
    rep = clean(pkg)
    assert rep.hidden_runs == 1 and rep.images == 0 and text_of(pkg) == ""
    assert "word/media/logo.png" in rep.parts_removed
    assert_consistent(pkg)


ADDRESS = "zeta.counsel@zeta-holdings.example"


def test_hidden_text_in_a_link_takes_the_link_with_it(tmp_path: Path) -> None:
    # Word turns a typed e-mail address into a link, so a hidden drafting note can be one. The runs
    # go; the link around them goes too, or its target stays in the relationships.
    link = (
        '<w:hyperlink r:id="rId1" w:history="1"><w:r><w:rPr><w:vanish/></w:rPr>'
        f"<w:t>{ADDRESS}</w:t></w:r></w:hyperlink>"
    )
    pkg = package(para(run("Contact "), link), rels=[(HYPERLINK, f"mailto:{ADDRESS}", "External")])
    rep = clean(pkg)
    assert rep.hidden_runs == 1 and text_of(pkg) == "Contact "
    assert ADDRESS.encode() not in saved_bytes(pkg, tmp_path)
    assert b"hyperlink" not in document(pkg) and "word/_rels/document.xml.rels" not in pkg.names()
    assert_consistent(pkg)


def test_hidden_text_in_a_simple_field_takes_the_field_with_it(tmp_path: Path) -> None:
    hidden = (
        f'<w:fldSimple w:instr=" HYPERLINK &quot;mailto:{ADDRESS}&quot; ">'
        f"<w:r><w:rPr><w:vanish/></w:rPr><w:t>{ADDRESS}</w:t></w:r></w:fldSimple>"
    )
    pkg = package(para(run("Contact "), hidden))
    rep = clean(pkg)
    assert rep.hidden_runs == 1 and text_of(pkg) == "Contact "
    assert ADDRESS.encode() not in saved_bytes(pkg, tmp_path)
    assert b"fldSimple" not in document(pkg)


def test_a_link_in_a_field_goes_when_nothing_visible_is_left_in_either() -> None:
    nested = (
        '<w:hyperlink r:id="rId1"><w:bookmarkStart w:id="4" w:name="note"/><w:fldSimple w:instr=" PAGE ">'
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t>7</w:t></w:r></w:fldSimple></w:hyperlink>"
    )
    pkg = package(
        para(run("Page "), nested), rels=[(HYPERLINK, "https://secret.example/", "External")]
    )
    clean(pkg)
    assert text_of(pkg) == "Page "
    assert b"secret.example" not in everywhere(pkg) and b"hyperlink" not in document(pkg)
    assert b"bookmarkStart" in document(pkg)  # what else was in the link stays where it was


def test_a_link_that_also_holds_visible_text_keeps_the_text_and_loses_its_target() -> None:
    # Ruling R112: every link to the outside goes, with or without hidden text in it.
    mixed = (
        '<w:hyperlink r:id="rId1"><w:r><w:rPr><w:vanish/></w:rPr><w:t>note</w:t></w:r>'
        f"{run('portal')}</w:hyperlink>"
    )
    pkg = package(para(mixed), rels=[(HYPERLINK, "https://portal.example/", "External")])
    rep = clean(pkg)
    assert rep.hidden_runs == 1 and rep.links_removed == 1
    assert text_of(pkg) == "portal" and b"portal.example" not in everywhere(pkg)
    assert_consistent(pkg)


# ---- links to the outside, permissions and field data (ruling R112) ------------------------------

LINKED = "pieter.de.vries@pdv-advocaten.example"
FIELD_ADDRESS = "legal.desk@lexpoint.example"
EDITOR = "jane.doe@brightwater-foods.example"


def contact_in_links() -> DocxPackage:
    """The reviewer's file: an address behind "click here", one in a HYPERLINK simple field, one
    as the editor of a permission range, and a name in the text."""
    body = (
        para(
            run("Notices to the Supplier: "),
            '<w:hyperlink r:id="rId1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            "<w:t>click here</w:t></w:r></w:hyperlink>",
            run(" or "),
            f'<w:fldSimple w:instr=" HYPERLINK &quot;mailto:{FIELD_ADDRESS}&quot; ">'
            "<w:r><w:t>this address</w:t></w:r></w:fldSimple>",
            run("."),
        )
        + para(
            f'<w:permStart w:id="100" w:edGrp="everyone" w:ed="{EDITOR}"/>',
            run("The Buyer may edit this clause."),
            '<w:permEnd w:id="100"/>',
        )
        + para(run("Signed by John Carter for the Buyer."))
    )
    return package(body, rels=[(HYPERLINK, f"mailto:{LINKED}", "External")])


def test_contact_data_that_stands_only_in_links_and_marks_goes(tmp_path: Path) -> None:
    pkg = contact_in_links()
    rep = clean(pkg)
    saved = saved_bytes(pkg, tmp_path)
    for address in (LINKED, FIELD_ADDRESS, EDITOR):
        assert address.encode() not in saved, address
    assert b"relationships/hyperlink" not in saved and b"permStart" not in saved
    assert b"permEnd" not in saved and b"w:ed=" not in saved and b"edGrp" not in saved
    assert text_of(pkg) == (
        "Notices to the Supplier: click here or this address.\nThe Buyer may edit this clause.\n"
        "Signed by John Carter for the Buyer."
    )
    assert rep.links_removed == 1 and rep.fields_flattened == 1
    assert "word/_rels/document.xml.rels" not in pkg.names()
    assert_consistent(pkg)


def test_an_internal_link_stays_and_a_hyperlink_field_becomes_its_text() -> None:
    body = para(
        '<w:hyperlink w:anchor="_Toc1" w:history="1">',
        run("Definitions"),
        "</w:hyperlink>",
        run(" and "),
        field(' HYPERLINK "https://portal.example/login" ', run("the portal")),
    )
    pkg = package(body)
    rep = clean(pkg)
    assert b'w:anchor="_Toc1"' in document(pkg) and text_of(pkg) == "Definitions and the portal"
    assert b"portal.example" not in everywhere(pkg) and b"fldChar" not in document(pkg)
    assert rep.links_removed == 0 and rep.fields_flattened == 1


@pytest.mark.parametrize("name", ["INCLUDEPICTURE", "INCLUDETEXT", "INCLUDE", "IMPORT", "LINK"])
def test_a_field_that_reads_a_file_or_an_address_becomes_its_result(name: str) -> None:
    instruction = f' {name} "C:\\\\Clients\\\\Acme\\\\terms.docx" '
    pkg = package(para(field(instruction, run("the terms"))))
    rep = clean(pkg)
    assert text_of(pkg) == "the terms" and b"Acme" not in everywhere(pkg)
    assert rep.fields_flattened == 1


def test_links_on_shapes_go_and_the_shapes_stay() -> None:
    box = (
        '<w:drawing><wp:anchor><wp:docPr id="2" name="Text Box 2">'
        '<a:hlinkClick r:id="rId1" tooltip="Acme portal"/><a:hlinkHover r:id="rId1"/></wp:docPr>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        f"<wps:wsp><wps:txbx><w:txbxContent>{para(run('Boxed'))}</w:txbxContent></wps:txbx></wps:wsp>"
        "</a:graphicData></a:graphic></wp:anchor></w:drawing>"
    )
    vml = (
        '<w:pict><v:rect id="_x0000_s1026" href="https://acme.example/terms" '
        'o:href="https://acme.example/terms" o:hrlabel="Acme terms" style="width:100pt">'
        f"<v:textbox><w:txbxContent>{para(run('VML box'))}</w:txbxContent></v:textbox></v:rect>"
        "</w:pict>"
    )
    pkg = package(
        para(f"<w:r>{box}</w:r><w:r>{vml}</w:r>"),
        rels=[(HYPERLINK, "https://acme.example/portal", "External")],
    )
    rep = clean(pkg)
    assert b"acme.example" not in everywhere(pkg) and b"Acme" not in everywhere(pkg)
    assert b"hlink" not in document(pkg) and b"href" not in document(pkg)
    assert text_of(pkg).splitlines()[1:] == ["Boxed", "VML box"]
    assert rep.links_removed == 3  # two on the drawing, the VML shape's
    assert_consistent(pkg)


def test_field_data_and_editing_marks_go_and_the_rest_stays() -> None:
    page = (
        '<w:r><w:fldChar w:fldCharType="begin"><w:fldData>QWNtZSBTdXBwbGllcw==</w:fldData>'
        '</w:fldChar></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>{run("7")}'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    marked = (
        '<w:p w:author="Jane Doe"><w:r w:ed="jane.doe@brightwater-foods.example">'
        '<w:t>Reviewed</w:t></w:r><w:permStart w:id="1" w:edGrp="everyone"/><w:permEnd w:id="1"/>'
        "</w:p>"
    )
    pkg = package(para(page) + marked)
    rep = clean(pkg)
    assert b"fldData" not in document(pkg) and b"QWNt" not in everywhere(pkg)
    assert b"Jane Doe" not in everywhere(pkg) and b"jane.doe" not in everywhere(pkg)
    assert b"w:author" not in document(pkg) and b"w:ed" not in document(pkg)
    assert b" PAGE " in document(pkg) and text_of(pkg) == " PAGE 7\nReviewed"
    assert rep.links_removed == 0 and rep.attributes_cleared == 2
    assert_consistent(pkg)


# ---- runs outside any paragraph (ruling R24) -----------------------------------------------------


def test_runs_outside_any_paragraph_are_removed(corpus: Path, tmp_path: Path) -> None:
    # A block-level w:ins or w:del may hold runs straight in the body, a table, a row or a cell, and
    # once the change is accepted or rejected they stay there as bare runs. The text map reads
    # paragraphs only, so nothing would ever mask what such a run says, and nobody would see it.
    path = corpus / "supply-01.docx"
    visible = extract_text(DocxPackage.open(path)).text
    pkg = DocxPackage.open(path)
    w = f"{{{NS['w']}}}"
    body = pkg.xml("word/document.xml").find(f"{w}body")
    table = body.find(f"{w}tbl")
    row = table.find(f"{w}tr")
    cell = row.find(f"{w}tc")
    secret = "Side letter with Zeta Holdings"

    def bare_run(parent: etree._Element, text: str = "t") -> None:
        run_ = parent.makeelement(f"{w}r", {})
        etree.SubElement(run_, f"{w}{text}").text = secret
        parent.insert(0, run_)

    for parent in (body, table, row, cell):
        bare_run(parent)
    inserted = body.makeelement(f"{w}ins", {f"{w}id": "90", f"{w}author": "Jane Doe"})
    deleted = body.makeelement(f"{w}del", {f"{w}id": "91", f"{w}author": "Jane Doe"})
    bare_run(inserted)
    bare_run(deleted, "delText")
    body.insert(0, inserted)
    body.insert(0, deleted)
    for view in VIEWS:
        assert secret not in extract_text(pkg, view).text  # the reader never meets them
    assert pkg.raw("word/document.xml").count(secret.encode()) == 6  # but they are in the file

    rep = clean(pkg, now=NOW)
    assert rep.stray_runs_removed == 6 and rep.hidden_runs == 0 and rep.images == 0
    saved = tmp_path / "cleaned.docx"
    pkg.save(saved)
    with zipfile.ZipFile(saved) as archive:
        assert not [n for n in archive.namelist() if secret.encode() in archive.read(n)]
    assert extract_text(DocxPackage.open(saved)).text == visible
    assert docx.Document(str(saved)).paragraphs
    assert not pkg.xml("word/document.xml").xpath("//w:r[not(ancestor::w:p)]", namespaces=NS)
    assert clean(pkg, now=NOW) == CleanReport()  # and there is nothing left to find


def test_a_stray_run_takes_its_picture_with_it_and_is_not_a_picture() -> None:
    pkg = package(
        f"<w:r>{picture('rId1')}</w:r>" + para(run("kept")),
        rels=[(IMAGE, "media/a.png")],
        parts={"word/media/a.png": b"PNG"},
    )
    rep = clean(pkg)
    assert rep.stray_runs_removed == 1 and rep.images == 0
    assert text_of(pkg) == "kept" and not [n for n in pkg.names() if "media" in n]
    assert_consistent(pkg)


def test_runs_in_paragraphs_and_in_text_boxes_are_not_stray() -> None:
    boxed = f"<w:r>{text_box(para(run('Box')))}</w:r>"
    table = f"<w:tbl><w:tr><w:tc>{para(run('Cell'))}</w:tc></w:tr></w:tbl>"
    pkg = package(para(run("Body"), boxed) + table)

    def runs() -> int:
        return len(pkg.xml("word/document.xml").xpath("//w:r", namespaces=NS))

    assert runs() == 4  # the body's, the one holding the text box, the box's and the cell's
    rep = clean(pkg)
    assert rep.stray_runs_removed == 0 and runs() == 4
    assert text_of(pkg) == "Body\nBox\nCell"


# ---- fields (ruling R22) -------------------------------------------------------------------------


def test_personal_simple_fields_become_plain_text() -> None:
    body = para(
        run("By "),
        r'<w:fldSimple w:instr=" AUTHOR \* MERGEFORMAT "><w:r><w:rPr><w:noProof/></w:rPr>'
        "<w:t>Joel Stewart</w:t></w:r></w:fldSimple>",
        run(" of "),
        '<w:fldSimple w:instr="docproperty Company"><w:r><w:t>Acme Ltd</w:t></w:r></w:fldSimple>',
        run(" at "),
        r'<w:fldSimple w:instr="  FILENAME \p"><w:r><w:t>C:/Clients/Acme/deal.docx</w:t></w:r></w:fldSimple>',
    )
    pkg = package(body)
    rep = clean(pkg)
    assert rep.fields_flattened == 3
    assert text_of(pkg) == "By Joel Stewart of Acme Ltd at C:/Clients/Acme/deal.docx"
    assert b"fldSimple" not in document(pkg) and b"w:instr" not in document(pkg)
    assert document(pkg).count(b"noProof") == 1  # the result run is an ordinary run, as it was


@pytest.mark.parametrize(
    "instruction",
    [
        "AUTHOR",
        "USERNAME",
        "USERINITIALS",
        "LASTSAVEDBY",
        "FILENAME",
        "TEMPLATE",
        "DOCPROPERTY",
        "INFO",
    ],
)
def test_each_personal_field_is_flattened(instruction: str) -> None:
    simple = f'<w:fldSimple w:instr="{instruction} x"><w:r><w:t>A</w:t></w:r></w:fldSimple>'
    pkg = package(para(simple, field(f" {instruction} y ", run("B"))))
    assert clean(pkg).fields_flattened == 2 and text_of(pkg) == "AB"


@pytest.mark.parametrize(
    "instruction", ["DOCVARIABLE", "TITLE", "SUBJECT", "KEYWORDS", "COMMENTS", "USERADDRESS"]
)
def test_each_field_that_reads_what_the_cleaner_removes_is_flattened(instruction: str) -> None:
    # Ruling R22, extended: these read a document variable or a property the cleaner removes (or the
    # user's address), so updating one in the masked file would put an error or nothing where the
    # masked result stands.
    simple = f'<w:fldSimple w:instr="{instruction} x"><w:r><w:t>A</w:t></w:r></w:fldSimple>'
    pkg = package(para(simple, field(f" {instruction} y ", run("B"))))
    assert clean(pkg).fields_flattened == 2 and text_of(pkg) == "AB"
    assert b"fldSimple" not in document(pkg) and b"fldChar" not in document(pkg)


def test_a_field_that_reads_a_removed_document_variable_keeps_its_result_as_text() -> None:
    variables = '<w:docVars><w:docVar w:name="ClientName" w:val="Acme Ltd"/></w:docVars>'
    pkg = package(
        para(run("Client: "), field(r" DOCVARIABLE ClientName \* MERGEFORMAT ", run("Acme Ltd"))),
        rels=[(SETTINGS_REL, "settings.xml")],
        parts={"word/settings.xml": part("w:settings", variables)},
        types={"word/settings.xml": SETTINGS_TYPE},
    )
    rep = clean(pkg)
    assert rep.fields_flattened == 1 and text_of(pkg) == "Client: Acme Ltd"
    assert b"DOCVARIABLE" not in everywhere(pkg) and b"docVar" not in everywhere(pkg)


def test_personal_complex_fields_become_plain_text() -> None:
    joined = '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> TEMPLATE </w:instrText><w:fldChar w:fldCharType="separate"/></w:r>'
    body = para(
        run("Saved by "),
        field([" LASTSAVE", r"DBY \* Upper "], run("Joel ") + run("Stewart")),  # split mid-word
        run("."),
    ) + para(joined, run("Normal.dotm"), '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    pkg = package(body)
    rep = clean(pkg)
    assert rep.fields_flattened == 2
    assert text_of(pkg) == "Saved by Joel Stewart.\nNormal.dotm"
    assert b"fldChar" not in document(pkg) and b"instrText" not in document(pkg)


def test_a_contents_page_is_left_as_it_is() -> None:
    # Word hides the page numbers of a contents page on the web only (w:webHidden), and a contents
    # page is a field with fields in it: neither may be mistaken for hidden text or a personal field.
    web = "<w:rPr><w:noProof/><w:webHidden/></w:rPr>"
    entry = (
        '<w:hyperlink w:anchor="_Toc1" w:history="1">'
        '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/><w:noProof/></w:rPr><w:t>1. Definitions</w:t></w:r>'
        f"<w:r>{web}<w:tab/></w:r>"
        f'<w:r>{web}<w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r>{web}<w:instrText xml:space="preserve"> PAGEREF _Toc1 \\h </w:instrText></w:r>'
        f'<w:r>{web}<w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r>{web}<w:t>3</w:t></w:r>"
        f'<w:r>{web}<w:fldChar w:fldCharType="end"/></w:r></w:hyperlink>'
    )
    begin = '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    code = '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
    separate = '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    contents = para(begin, code, separate, entry) + para(
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    pkg = package(
        contents + para('<w:bookmarkStart w:id="1" w:name="_Toc1"/>', run("1. Definitions"))
    )
    before = content(pkg)
    rep = clean(pkg)
    assert rep == CleanReport() and content(pkg) == before


def test_a_field_that_starts_in_one_paragraph_and_ends_in_the_next() -> None:
    first = para(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>',
        "<w:r><w:instrText> INFO Title </w:instrText></w:r>",
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>',
        run("one"),
    )
    second = para(run("two"), '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    pkg = package(first + second)
    assert clean(pkg).fields_flattened == 1
    assert text_of(pkg) == "one\ntwo" and b"fldChar" not in document(pkg)


@pytest.mark.parametrize(
    "nested", [' QUOTE "Mary" ', " DOCVARIABLE ClientName "], ids=["a QUOTE field", "a DOCVARIABLE"]
)
def test_a_field_in_the_instruction_of_a_flattened_field_goes_with_it(nested: str) -> None:
    # Everything between begin and separate is the instruction. A field in it, with its result,
    # must not turn into body text when the field around it becomes plain text.
    outer = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        "<w:r><w:instrText> DOCPROPERTY </w:instrText></w:r>"
        + field(nested, run("Mary Major"))
        + '<w:r><w:instrText xml:space="preserve"> </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + run("Result")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    pkg = package(para(run("A "), outer, run(" B")))
    rep = clean(pkg)
    assert rep.fields_flattened == 1  # the nested one is part of the instruction, not of the text
    assert text_of(pkg) == "A Result B"
    assert b"Mary Major" not in everywhere(pkg) and b"fldChar" not in document(pkg)


def test_other_fields_are_left_alone() -> None:
    # (A HYPERLINK field is flattened since ruling R112: its address is a link to the outside.)
    body = para(
        run("Page "),
        '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>',
        field(r" REF _Ref1 \h ", run("clause 2")),
        field(" NUMPAGES ", run("9")),
    )
    pkg = package(body)
    before = content(pkg)
    rep = clean(pkg)
    assert rep.fields_flattened == 0 and content(pkg) == before


def test_a_personal_field_in_the_result_of_another_is_flattened() -> None:
    inner = field(" AUTHOR ", run("Joel"))
    pkg = package(para(field(" REF clause ", run("by ") + inner)))
    assert clean(pkg).fields_flattened == 1
    assert document(pkg).count(b"w:fldChar ") == 3  # the outer field's begin, separate and end
    assert text_of(pkg) == " REF clause by Joel"


def test_a_personal_field_in_the_instruction_of_another_is_left_alone() -> None:
    # Its result would become text in the middle of an instruction, which Word reads as code.
    outer = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> IF </w:instrText></w:r>'
        + field(" AUTHOR ", run("Joel"))
        + '<w:r><w:instrText> = "x" "yes" "no" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + run("no")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    pkg = package(para(outer))
    before = content(pkg)
    assert clean(pkg).fields_flattened == 0 and content(pkg) == before


def test_a_field_that_is_never_closed_does_no_harm() -> None:
    open_field = para(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>',
        "<w:r><w:instrText> AUTHOR </w:instrText></w:r>",
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>',
        run("Joel"),
    )
    stray_end = para('<w:r><w:fldChar w:fldCharType="end"/></w:r>', run("after"))
    pkg = package(stray_end + open_field)
    assert clean(pkg).fields_flattened == 0 and "Joel" in text_of(pkg)


# ---- text kept in attributes (ruling R19) --------------------------------------------------------

_WATERMARK = (
    '<w:r><w:rPr><w:noProof/></w:rPr><w:pict><v:shapetype id="_x0000_t136" coordsize="21600,21600">'
    '<v:path textpathok="t"/><v:textpath on="t" fitshape="t"/></v:shapetype>'
    '<v:shape id="PowerPlusWaterMarkObject1" type="#_x0000_t136" style="rotation:315">'
    '<v:textpath style="font-family:Calibri" string="CONFIDENTIAL ACME"/></v:shape></w:pict></w:r>'
)


def test_a_text_watermark_goes_without_a_note() -> None:
    pkg = with_header(para(run("Body")), para(_WATERMARK, run("Header")))
    rep = clean(pkg)
    assert text_of(pkg) == "Body\nHeader" and rep.images == 0
    assert b"textpath" not in everywhere(pkg) and b"CONFIDENTIAL" not in everywhere(pkg)
    assert b"w:pict" not in document(pkg, "word/header1.xml")
    assert rep.attributes_cleared == 1


def test_a_shape_definition_alone_is_not_a_watermark() -> None:
    definition = (
        '<w:r><w:pict><v:shapetype id="t"><v:textpath on="t"/></v:shapetype></w:pict></w:r>'
    )
    pkg = package(para(definition, run("x")))
    assert clean(pkg).attributes_cleared == 0 and text_of(pkg) == "x"


def test_a_smart_tag_is_unwrapped_and_its_attributes_dropped() -> None:
    tag = (
        '<w:smartTag w:uri="urn:schemas-microsoft-com:office:smarttags" w:element="PersonName">'
        '<w:smartTagPr><w:attr w:uri="" w:name="ProductID" w:val="Joel Stewart"/></w:smartTagPr>'
        f"{run('Joel')}</w:smartTag>"
    )
    pkg = package(para(run("Mr "), tag, run(" signs")))
    assert clean(pkg).attributes_cleared == 1
    assert text_of(pkg) == "Mr Joel signs"
    assert b"smartTag" not in everywhere(pkg) and b"Joel Stewart" not in everywhere(pkg)


def test_custom_xml_wrappers_in_the_text_are_unwrapped_too() -> None:
    wrapper = (
        '<w:customXml w:uri="urn:acme:clients" w:element="client"><w:customXmlPr>'
        '<w:attr w:name="id" w:val="Acme Holdings"/></w:customXmlPr>'
        + run("Acme")
        + "</w:customXml>"
    )
    block = f'<w:customXml w:uri="urn:x" w:element="clause">{para(run("Clause"))}</w:customXml>'
    pkg = package(para(wrapper) + block)
    assert clean(pkg).attributes_cleared == 2
    assert text_of(pkg) == "Acme\nClause"
    assert b"customXml" not in everywhere(pkg) and b"Acme Holdings" not in everywhere(pkg)


def test_the_items_of_a_list_content_control_go_and_its_text_stays() -> None:
    controls = (
        '<w:sdt><w:sdtPr><w:alias w:val="Client"/><w:dropDownList w:lastValue="acme">'
        '<w:listItem w:displayText="Acme Ltd" w:value="acme"/><w:listItem w:displayText="Globex" w:value="globex"/>'
        f"</w:dropDownList></w:sdtPr><w:sdtContent>{para(run('Acme Ltd'))}</w:sdtContent></w:sdt>"
        '<w:sdt><w:sdtPr><w:comboBox><w:listItem w:displayText="Initech" w:value="initech"/></w:comboBox></w:sdtPr>'
        f"<w:sdtContent>{para(run('Pick'))}</w:sdtContent></w:sdt>"
    )
    pkg = package(controls)
    assert clean(pkg).attributes_cleared == 3  # the two lists, and the title of the first control
    assert text_of(pkg) == "Acme Ltd\nPick"
    for gone in (b"listItem", b"Globex", b"Initech", b"lastValue", b"alias"):
        assert gone not in document(pkg)
    assert pkg.xml("word/document.xml").find(".//w:dropDownList", NS) is not None  # still a list
    assert pkg.xml("word/document.xml").find(".//w:comboBox", NS) is not None


def test_the_title_and_tag_of_a_content_control_go(corpus: Path, tmp_path: Path) -> None:
    # Ruling R19, extended (found by Task 13): w:alias and w:tag are free text, and a document
    # assembly system may fill them with a value. The control, its id and its text stay.
    pkg = DocxPackage.open(corpus / "supply-01.docx")
    w = f"{{{NS['w']}}}"
    body = pkg.xml("word/document.xml").find(f"{w}body")
    control = body.makeelement(f"{w}sdt", {})
    properties = etree.SubElement(control, f"{w}sdtPr")
    etree.SubElement(properties, f"{w}alias").set(f"{w}val", "Counterparty: Zeta Holdings")
    etree.SubElement(properties, f"{w}tag").set(f"{w}val", "zeta_holdings_2026")
    etree.SubElement(properties, f"{w}id").set(f"{w}val", "4711")
    paragraph = etree.SubElement(etree.SubElement(control, f"{w}sdtContent"), f"{w}p")
    etree.SubElement(etree.SubElement(paragraph, f"{w}r"), f"{w}t").text = "Zeta Holdings Ltd"
    body.insert(0, control)

    rep = clean(pkg, now=NOW)
    assert rep.attributes_cleared == 2  # the title and the tag; the contract has nothing else
    saved = tmp_path / "cleaned.docx"
    pkg.save(saved)
    with zipfile.ZipFile(saved) as archive:
        everything = b"".join(archive.read(name) for name in archive.namelist())
    assert b"Counterparty" not in everything and b"zeta_holdings_2026" not in everything
    reopened = DocxPackage.open(saved)
    kept = reopened.xml("word/document.xml").find(f".//{w}sdt/{w}sdtPr")
    assert kept.find(f"{w}alias") is None and kept.find(f"{w}tag") is None
    assert kept.find(f"{w}id").get(f"{w}val") == "4711"  # the control can still be told apart
    assert extract_text(reopened).text.startswith("Zeta Holdings Ltd")  # and keeps its text


def test_alt_text_and_names_of_grouped_shapes_go() -> None:
    def box(number: int, text: str, extra: str) -> str:
        return (
            f'<wps:wsp><wps:cNvPr id="{number}" name="Zeta box {number}"{extra}/>'
            '<wps:cNvSpPr txBox="1"/><wps:spPr/><wps:txbx><w:txbxContent>'
            f"{para(run(text))}</w:txbxContent></wps:txbx></wps:wsp>"
        )

    group = (
        '<w:drawing><wp:anchor><wp:docPr id="1" name="Group 1"/><a:graphic>'
        '<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
        '<wpg:wgp><wpg:cNvPr id="2" name="Zeta group"/>'
        + box(3, "One", ' descr="Prices for Zeta"')
        + box(4, "Two", ' title="Zeta tip"')
        + "</wpg:wgp></a:graphicData></a:graphic></wp:anchor></w:drawing>"
    )
    pkg = package(para(f"<w:r>{group}</w:r>"))
    rep = clean(pkg)
    properties = pkg.xml("word/document.xml").xpath(
        "//wp:docPr | //*[local-name()='cNvPr']", namespaces=NS
    )
    assert [p.get("name") for p in properties] == ["Shape1", "Shape2", "Shape3", "Shape4"]
    assert rep.attributes_cleared == 6  # four names, one description, one title
    assert b"Zeta" not in everywhere(pkg)
    assert text_of(pkg).splitlines()[1:] == ["One", "Two"]  # the boxes keep their text


def test_alt_text_of_a_vml_text_box_goes() -> None:
    box = (
        '<w:r><w:pict><v:shape id="Text Box 2" type="#_x0000_t202" alt="Pricing for Zeta" '
        'title="Zeta tip"><v:textbox><w:txbxContent>'
        f"{para(run('Box'))}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    pkg = package(para(box))
    rep = clean(pkg)
    assert rep.attributes_cleared == 2 and "Box" in text_of(pkg)
    assert b"Zeta" not in everywhere(pkg)
    assert pkg.xml("word/document.xml").find(".//v:shape", NS).get("id") == "Text Box 2"


def test_the_data_binding_of_a_word_2013_control_goes_like_the_older_one() -> None:
    store = "{11111111-2222-3333-4444-555555555555}"
    controls = (
        f'<w:sdt><w:sdtPr><w:dataBinding w:xpath="/c/n" w:storeItemID="{store}"/></w:sdtPr>'
        f"<w:sdtContent>{para(run('Old'))}</w:sdtContent></w:sdt>"
        f'<w:sdt><w:sdtPr><w15:dataBinding w15:xpath="/c/n" w15:storeItemID="{store}"/></w:sdtPr>'
        f"<w:sdtContent>{para(run('New'))}</w:sdtContent></w:sdt>"
    )
    pkg = package(controls)
    clean(pkg)
    assert b"dataBinding" not in everywhere(pkg) and b"storeItemID" not in everywhere(pkg)
    assert text_of(pkg) == "Old\nNew"  # the controls keep their text


def test_form_field_data_goes_and_the_field_stays() -> None:
    form = (
        '<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Text1"/><w:enabled/>'
        '<w:textInput><w:default w:val="Acme Holdings"/></w:textInput><w:helpText w:type="text" w:val="Ask Jane"/>'
        "</w:ffData></w:fldChar></w:r><w:r><w:instrText> FORMTEXT </w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + run("Acme Holdings")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    pkg = package(para(form))
    rep = clean(pkg)
    assert rep.attributes_cleared == 1 and rep.fields_flattened == 0
    assert b"ffData" not in document(pkg) and b"Ask Jane" not in document(pkg)
    assert document(pkg).count(b"w:fldChar ") == 3 and text_of(pkg) == " FORMTEXT Acme Holdings"


def test_a_link_loses_its_tooltip_and_its_target_and_keeps_its_text() -> None:
    # Ruling R112: the target goes with the tooltip; the AI reads text, not links.
    link = (
        '<w:hyperlink r:id="rId1" w:tooltip="Open the Acme portal" w:history="1">'
        f"{run('portal')}</w:hyperlink>"
    )
    pkg = package(para(link), rels=[(HYPERLINK, "https://portal.example/login", "External")])
    rep = clean(pkg)
    assert rep.attributes_cleared == 1 and rep.links_removed == 1
    assert b"tooltip" not in everywhere(pkg) and b"Acme portal" not in everywhere(pkg)
    assert text_of(pkg) == "portal" and b"portal.example" not in everywhere(pkg)
    assert_consistent(pkg)


def test_alt_text_and_names_of_kept_shapes_go() -> None:
    body = para(
        "<w:r>"
        + text_box(
            para(run("Body box")),
            name="Acme price box",
            alt=' descr="Prices for Acme" title="Secret"',
        )
        + "</w:r>"
    )
    header = para("<w:r>" + text_box(para(run("Header box")), name="Header Box") + "</w:r>")
    pkg = with_header(body, header)
    rep = clean(pkg)
    names = [
        d.get("name")
        for n in ("word/document.xml", "word/header1.xml")
        for d in pkg.xml(n).iter(f"{{{NS['wp']}}}docPr")
    ]
    assert names == ["Shape1", "Shape2"]  # numbered in the order the parts are read
    assert rep.attributes_cleared == 4  # two names, one description, one title
    for gone in (b"Acme price box", b"Prices for Acme", b"Secret", b"descr", b"title="):
        assert gone not in everywhere(pkg)


def test_table_alt_text_goes() -> None:
    table = (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblCaption w:val="Prices for Acme"/>'
        '<w:tblDescription w:val="Acme price list"/></w:tblPr><w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>'
        f"<w:tr><w:tc>{para(run('cell'))}</w:tc></w:tr></w:tbl>"
    )
    pkg = package(table)
    assert clean(pkg).attributes_cleared == 2
    assert b"Acme" not in everywhere(pkg) and text_of(pkg) == "cell"
    assert pkg.xml("word/document.xml").find(".//w:tblStyle", NS) is not None


def test_the_hidden_copy_of_a_vml_text_box_goes_with_its_text_kept() -> None:
    # Word 2007 keeps a base64 copy of a shape, text included, in o:gfxdata.
    shape = (
        '<w:r><w:pict><v:shape id="s1" type="#_x0000_t202" o:gfxdata="UEsDBBQABgAIAAAAIQ">'
        f"<v:textbox><w:txbxContent>{para(run('Box text'))}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    pkg = package(para(shape))
    assert clean(pkg).attributes_cleared == 1
    assert b"gfxdata" not in everywhere(pkg) and "Box text" in text_of(pkg)
    assert pkg.xml("word/document.xml").find(".//w:pict", NS) is not None  # a text box is kept


# ---- equations and embedded content (ruling R17) -------------------------------------------------


def test_equations_become_a_note() -> None:
    inline = "<m:oMath><m:r><m:t>x=5</m:t></m:r></m:oMath>"
    display = (
        '<m:oMathPara><m:oMathParaPr><m:jc m:val="center"/></m:oMathParaPr>'
        "<m:oMath><m:r><m:t>E=mc2</m:t></m:r></m:oMath></m:oMathPara>"
    )
    pkg = package(para(run("Where "), inline, run(" is five.")) + para(display))
    rep = clean(pkg)
    assert rep.equations_removed == 2  # a display equation is one, however many equations it holds
    assert text_of(pkg) == f"Where {EQUATION_NOTE} is five.\n{EQUATION_NOTE}"
    assert EQUATION_NOTE == "[equation removed]"
    assert b"oMath" not in everywhere(pkg) and b"E=mc2" not in everywhere(pkg)


@pytest.mark.parametrize(
    ("target", "content_type"),
    [("afchunk.html", "text/html"), ("embeddings/Microsoft_Word_Document1.docx", MAIN)],
    ids=["html", "a whole .docx"],
)
def test_embedded_content_becomes_a_note_and_its_part_goes(target: str, content_type: str) -> None:
    name = f"word/{target}"
    pkg = package(
        para(run("Before")) + '<w:altChunk r:id="rId1"/>' + para(run("After")),
        rels=[(AFCHUNK, target)],
        parts={name: b"<html><body>Secret clause</body></html>"},
        types={name: content_type},
    )
    rep = clean(pkg)
    assert rep.altchunks_removed == 1 and ALTCHUNK_NOTE == "[embedded content removed]"
    assert text_of(pkg) == f"Before\n{ALTCHUNK_NOTE}\nAfter"
    assert name in rep.parts_removed and b"Secret clause" not in everywhere(pkg)
    assert b"altChunk" not in everywhere(pkg)
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert_consistent(pkg)


# ---- pictures and embedded objects ---------------------------------------------------------------


def test_pictures_in_headers_and_footers_count_too() -> None:
    header = para("<w:r>" + picture("rId1", descr="Acme letterhead") + "</w:r>")
    footer = para(
        '<w:r><w:pict><v:shape><v:imagedata r:id="rId1" o:title="Draft mark"/></v:shape></w:pict></w:r>'
    )
    pkg = package(
        para(run("Body")),
        rels=[(HEADER, "header1.xml"), (FOOTER, "footer1.xml")],
        parts={
            **in_header(header),
            "word/footer1.xml": part("w:ftr", footer),
            "word/_rels/header1.xml.rels": rels_xml([(IMAGE, "media/letterhead.png")]),
            "word/_rels/footer1.xml.rels": rels_xml([(IMAGE, "media/mark.png")]),
            "word/media/letterhead.png": b"PNG",
            "word/media/mark.png": b"PNG",
        },
        types={"word/header1.xml": HEADER_TYPE, "word/footer1.xml": FOOTER_TYPE},
    )
    rep = clean(pkg)
    assert rep.images == 2
    assert text_of(pkg) == f"Body\n{IMAGE_NOTE}\n{IMAGE_NOTE}"
    assert not [
        n for n in pkg.names() if "media" in n or "_rels/header" in n or "_rels/footer" in n
    ]
    assert b"Acme" not in everywhere(pkg) and b"Draft mark" not in everywhere(pkg)
    assert b"ns0:" not in everywhere(pkg)  # the new runs are written with the file's own prefixes
    assert_consistent(pkg)


def test_a_picture_amid_text_leaves_the_text_around_it() -> None:
    pkg = package(
        para(f"<w:r><w:t>See </w:t>{picture('rId1')}<w:t> above</w:t></w:r>"),
        rels=[(IMAGE, "media/a.png")],
        parts={"word/media/a.png": b"PNG"},
    )
    clean(pkg)
    assert text_of(pkg) == f"See {IMAGE_NOTE} above"


def test_charts_and_diagrams_are_pictures_with_all_their_parts() -> None:
    chart = (
        '<w:drawing><wp:inline><wp:docPr id="3" name="Chart 3" descr="Revenue by client"/><a:graphic>'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart r:id="rId1"/>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing>"
    )
    diagram = (
        '<w:drawing><wp:inline><wp:docPr id="4" name="Diagram 4"/><a:graphic>'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
        '<dgm:relIds r:dm="rId2" r:lo="rId3" r:qs="rId4" r:cs="rId5"/></a:graphicData></a:graphic></wp:inline></w:drawing>'
    )
    drawing = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing"
    pkg = package(
        para(f"<w:r>{chart}</w:r>") + para(f"<w:r>{diagram}</w:r>"),
        rels=[
            (CHART, "charts/chart1.xml"),
            (f"{REL}/diagramData", "diagrams/data1.xml"),
            (f"{REL}/diagramLayout", "diagrams/layout1.xml"),
            (f"{REL}/diagramQuickStyle", "diagrams/quickStyle1.xml"),
            (f"{REL}/diagramColors", "diagrams/colors1.xml"),
            (drawing, "diagrams/drawing1.xml"),  # no element of the page names this one
        ],
        parts={
            "word/charts/chart1.xml": b"<c:chartSpace xmlns:c='urn:c'>Revenue</c:chartSpace>",
            "word/charts/_rels/chart1.xml.rels": rels_xml(
                [
                    (f"{REL}/package", "../embeddings/Microsoft_Excel_Sheet1.xlsx"),
                    (f"{REL}/chartStyle", "style1.xml"),
                ]
            ),
            "word/charts/style1.xml": b"<cs:chartStyle xmlns:cs='urn:cs'/>",
            "word/embeddings/Microsoft_Excel_Sheet1.xlsx": b"PK-workbook-with-client-data",
            "word/diagrams/data1.xml": b"<dgm:dataModel xmlns:dgm='urn:d'>Client names</dgm:dataModel>",
            "word/diagrams/layout1.xml": b"<l/>",
            "word/diagrams/quickStyle1.xml": b"<q/>",
            "word/diagrams/colors1.xml": b"<c/>",
            "word/diagrams/drawing1.xml": b"<dsp:drawing xmlns:dsp='urn:dsp'>Client names</dsp:drawing>",
        },
    )
    rep = clean(pkg)
    assert rep.images == 2 and rep.objects == 0
    assert text_of(pkg) == f"{IMAGE_NOTE}\n{IMAGE_NOTE}"
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert b"Revenue" not in everywhere(pkg) and b"Client" not in everywhere(pkg)
    assert_consistent(pkg)


def test_an_embedded_object_becomes_its_own_note_with_its_parts() -> None:
    obj = (
        '<w:object w:dxaOrig="4320" w:dyaOrig="1440"><v:shape id="_x0000_i1025" type="#_x0000_t75">'
        '<v:imagedata r:id="rId1" o:title=""/></v:shape>'
        '<o:OLEObject Type="Embed" ProgID="Excel.Sheet.12" ShapeID="_x0000_i1025" DrawAspect="Content" '
        'ObjectID="_1500000001" r:id="rId2"/></w:object>'
    )
    pkg = package(
        para(run("Table: "), f"<w:r>{obj}</w:r>"),
        rels=[(IMAGE, "media/preview.png"), (OLE, "embeddings/oleObject1.bin")],
        parts={
            "word/media/preview.png": b"PNG",
            "word/embeddings/oleObject1.bin": b"OLE price list",
        },
    )
    rep = clean(pkg)
    assert rep.objects == 1 and rep.images == 0 and OBJECT_NOTE == "[embedded object removed]"
    assert text_of(pkg) == f"Table: {OBJECT_NOTE}"
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert_consistent(pkg)


def test_an_old_style_picture_reference_is_followed_too() -> None:
    # Older VML names the relationship of an image in o:relid, not r:id.
    old = '<w:r><w:pict><v:shape><v:imagedata o:relid="rId1"/></v:shape></w:pict></w:r>'
    pkg = package(
        para(old),
        rels=[(IMAGE, "media/old.png")],
        parts={"word/media/old.png": b"PNG"},
    )
    assert clean(pkg).images == 1
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]


def test_a_linked_picture_leaves_no_path_behind() -> None:
    pkg = package(
        para(f"<w:r>{picture('rId1', kind='link')}</w:r>"),
        rels=[(IMAGE, "file:///C:/Clients/Acme/logo.png", "External")],
    )
    assert clean(pkg).images == 1
    assert b"Acme" not in everywhere(pkg) and "word/_rels/document.xml.rels" not in pkg.names()
    assert_consistent(pkg)


def test_a_link_on_a_picture_goes_with_it() -> None:
    link = '<a:hlinkClick r:id="rId2"/>'
    pkg = package(
        para(
            f"<w:r>{picture('rId1', link=link)}</w:r>"
            + f'<w:hyperlink r:id="rId3">{run("visible")}</w:hyperlink>'
        ),
        rels=[
            (IMAGE, "media/a.png"),
            (HYPERLINK, "https://secret.example/from-the-picture", "External"),
            (HYPERLINK, "https://kept.example/", "External"),
        ],
        parts={"word/media/a.png": b"PNG"},
    )
    rep = clean(pkg)
    # Ruling R112: the link on the text goes as well, its text stays.
    assert b"secret.example" not in everywhere(pkg) and b"kept.example" not in everywhere(pkg)
    assert text_of(pkg).endswith("visible") and rep.links_removed == 2  # the picture's, the text's
    assert_consistent(pkg)


def test_a_picture_used_twice_is_removed_when_its_last_use_is() -> None:
    pkg = package(
        para(f"<w:r>{picture('rId1')}</w:r>"),
        rels=[(IMAGE, "media/shared.png"), (HEADER, "header1.xml")],
        parts={
            "word/media/shared.png": b"PNG",
            "word/_rels/header1.xml.rels": rels_xml([(IMAGE, "media/shared.png")]),
            **in_header(para(f"<w:r>{picture('rId1')}</w:r>")),
        },
        types={"word/header1.xml": HEADER_TYPE},
    )
    assert clean(pkg).images == 2
    assert not [n for n in pkg.names() if "media" in n]
    assert_consistent(pkg)


def test_text_boxes_are_kept() -> None:
    vml = (
        '<w:r><w:pict><v:shape id="s2" type="#_x0000_t202"><v:textbox>'
        f"<w:txbxContent>{para(run('VML box'))}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    pkg = package(para(f"<w:r>{text_box(para(run('Drawing box')))}</w:r>") + para(vml))
    rep = clean(pkg)
    assert rep.images == 0 and rep.objects == 0
    assert text_of(pkg).splitlines() == ["", "Drawing box", "", "VML box"]  # each box in its place
    assert pkg.xml("word/document.xml").find(".//w:pict", NS) is not None


def test_a_picture_inside_a_text_box_goes_and_the_box_stays() -> None:
    inner = para(run("Caption "), f"<w:r>{picture('rId1')}</w:r>")
    pkg = package(
        para(f"<w:r>{text_box(inner)}</w:r>"),
        rels=[(IMAGE, "media/a.png")],
        parts={"word/media/a.png": b"PNG"},
    )
    rep = clean(pkg)
    assert rep.images == 1
    assert f"Caption {IMAGE_NOTE}" in text_of(pkg)
    assert pkg.xml("word/document.xml").find(".//wps:txbx", NS) is not None
    assert not [n for n in pkg.names() if "media" in n]


def test_a_picture_with_a_vml_fallback_is_one_picture() -> None:
    both = (
        '<w:r><mc:AlternateContent><mc:Choice Requires="wpg">' + picture("rId1") + "</mc:Choice>"
        '<mc:Fallback><w:pict><v:shape><v:imagedata r:id="rId2"/></v:shape></w:pict></mc:Fallback>'
        "</mc:AlternateContent></w:r>"
    )
    pkg = package(
        para(both),
        rels=[(IMAGE, "media/a.png"), (IMAGE, "media/b.png")],
        parts={"word/media/a.png": b"PNG", "word/media/b.png": b"PNG"},
    )
    rep = clean(pkg)
    assert rep.images == 1 and rep.fallbacks_removed == 1
    assert text_of(pkg) == IMAGE_NOTE
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert_consistent(pkg)


SIGNED = "Signed for Zeta Holdings by Mary Major"


def picture_group(rid: str = "rId1") -> str:
    """A w:drawing: a group of a text box and a picture."""
    return (
        '<w:drawing><wp:anchor><wp:docPr id="5" name="Group 5" descr="Signature block"/><a:graphic>'
        '<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
        '<wpg:wgp><wps:wsp><wps:cNvPr id="6" name="Text Box 6" descr="Signed by Mary"/>'
        f"<wps:txbx><w:txbxContent>{para(run(SIGNED))}</w:txbxContent></wps:txbx></wps:wsp>"
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="7" name="Picture 7" descr="Signature of Mary Major"/>'
        f'<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill>'
        "<pic:spPr/></pic:pic></wpg:wgp></a:graphicData></a:graphic></wp:anchor></w:drawing>"
    )


def vml_picture_group(rid: str = "rId1") -> str:
    """A w:pict: a VML group of a picture and a text box."""
    return (
        '<w:pict><v:group id="Group 1" coordsize="100,100"><v:shape id="Picture 2" '
        f'type="#_x0000_t75" alt="Signature of Mary Major"><v:imagedata r:id="{rid}" o:title=""/>'
        '</v:shape><v:shape id="Text Box 3" type="#_x0000_t202" alt="Signed by Mary"><v:textbox>'
        f"<w:txbxContent>{para(run(SIGNED))}</w:txbxContent></v:textbox></v:shape></v:group></w:pict>"
    )


def picture_filled_text_box(rid: str = "rId1", text: str = SIGNED) -> str:
    """A w:drawing: a text box whose fill is a picture."""
    inside = (
        f"<wps:txbx><w:txbxContent>{para(run(text))}</w:txbxContent></wps:txbx>" if text else ""
    )
    return (
        '<w:drawing><wp:anchor><wp:docPr id="8" name="Box 8"/><a:graphic>'
        '<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr><a:prstGeom prst="rect"/>'
        f'<a:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></a:blipFill>'
        f"</wps:spPr>{inside}<wps:bodyPr/></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>"
    )


def with_signature_picture(shape: str) -> DocxPackage:
    return package(
        para(f"<w:r>{shape}</w:r>"),
        rels=[(IMAGE, "media/sign.png")],
        parts={"word/media/sign.png": b"PNG of a signature"},
    )


def assert_only_the_picture_went(pkg: DocxPackage, rep: CleanReport) -> None:
    """What the three shapes below have in common: the text stays, the picture is a note beside it."""
    assert rep.images == 1 and rep.objects == 0
    assert text_of(pkg).splitlines() == [IMAGE_NOTE, SIGNED]  # the note, then the text box
    assert not [n for n in pkg.names() if "media" in n]
    assert b"Signature of Mary Major" not in everywhere(pkg) and b"r:embed" not in document(pkg)
    assert_consistent(pkg)
    assert clean(pkg) == CleanReport()  # and nothing is left that a second clean would find


def test_a_group_of_a_picture_and_a_text_box_loses_only_the_picture() -> None:
    pkg = with_signature_picture(picture_group())
    rep = clean(pkg)
    assert_only_the_picture_went(pkg, rep)
    root = pkg.xml("word/document.xml")
    assert root.find(".//pic:pic", NS) is None and root.find(".//wps:txbx", NS) is not None


def test_a_vml_group_of_a_picture_and_a_text_box_loses_only_the_picture() -> None:
    pkg = with_signature_picture(vml_picture_group())
    rep = clean(pkg)
    assert_only_the_picture_went(pkg, rep)
    root = pkg.xml("word/document.xml")
    assert root.find(".//v:imagedata", NS) is None and root.find(".//v:textbox", NS) is not None
    assert len(root.findall(".//v:shape", NS)) == 1  # the picture's shape is gone, the box's is not


def test_a_text_box_with_a_picture_fill_loses_only_the_fill() -> None:
    pkg = with_signature_picture(picture_filled_text_box())
    rep = clean(pkg)
    assert_only_the_picture_went(pkg, rep)
    root = pkg.xml("word/document.xml")
    assert (
        root.find(".//a:blipFill", NS) is None and root.find(".//wps:spPr/a:noFill", NS) is not None
    )


def test_a_shape_with_a_picture_fill_and_no_text_is_a_picture() -> None:
    pkg = with_signature_picture(picture_filled_text_box(text=""))
    rep = clean(pkg)
    assert rep.images == 1 and text_of(pkg) == IMAGE_NOTE
    assert not [n for n in pkg.names() if "media" in n]
    assert_consistent(pkg)


CHART_EX = "http://schemas.microsoft.com/office/2014/relationships/chartEx"


def test_a_word_2016_chart_is_a_picture_with_its_parts() -> None:
    chart = (
        '<mc:AlternateContent><mc:Choice Requires="cx1"><w:drawing><wp:inline>'
        '<wp:docPr id="9" name="Chart 9" descr="Waterfall of Zeta Holdings revenue"/><a:graphic>'
        '<a:graphicData uri="http://schemas.microsoft.com/office/drawing/2014/chartex">'
        '<cx:chart r:id="rId1"/></a:graphicData></a:graphic></wp:inline></w:drawing></mc:Choice>'
        "<mc:Fallback><w:pict><v:rect><v:textbox><w:txbxContent>"
        f"{para(run('This chart is not available in your version of Word.'))}"
        "</w:txbxContent></v:textbox></v:rect></w:pict></mc:Fallback></mc:AlternateContent>"
    )
    pkg = package(
        para(f"<w:r>{chart}</w:r>"),
        rels=[(CHART_EX, "charts/chartEx1.xml")],
        parts={
            "word/charts/chartEx1.xml": b"<cx:chartSpace xmlns:cx='urn:cx'>Zeta revenue</cx:chartSpace>",
            "word/charts/_rels/chartEx1.xml.rels": rels_xml(
                [(f"{REL}/package", "../embeddings/Microsoft_Excel_Sheet1.xlsx")]
            ),
            "word/embeddings/Microsoft_Excel_Sheet1.xlsx": b"PK-workbook",
        },
    )
    rep = clean(pkg)
    assert rep.images == 1 and rep.fallbacks_removed == 1
    assert text_of(pkg) == IMAGE_NOTE
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert b"Zeta" not in everywhere(pkg)
    assert_consistent(pkg)


def test_an_ink_drawing_is_a_picture_and_its_part_goes() -> None:
    # Word keeps the strokes in an InkML part that the document relates to as custom XML.
    ink = (
        '<w:drawing><wp:inline><wp:docPr id="1" name="Ink 1"/><a:graphic><a:graphicData '
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingInk">'
        '<w14:contentPart bwMode="auto" r:id="rId1"><w14:nvContentPartPr><w14:cNvContentPartPr/>'
        "</w14:nvContentPartPr></w14:contentPart></a:graphicData></a:graphic></wp:inline></w:drawing>"
    )
    pkg = package(
        para(run("Initialled "), f"<w:r>{ink}</w:r>"),
        rels=[(CUSTOM_XML, "ink/ink1.xml")],
        parts={"word/ink/ink1.xml": b"<inkml>strokes of Mary Major</inkml>"},
        types={"word/ink/ink1.xml": "application/inkml+xml"},
    )
    rep = clean(pkg)
    assert rep.images == 1 and text_of(pkg) == f"Initialled {IMAGE_NOTE}"
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert_consistent(pkg)


@pytest.mark.parametrize(
    ("relationship", "target"),
    [(f"{REL}/package", "embeddings/widget.bin"), (CUSTOM_XML, "ink/widget.xml")],
    ids=["a swept folder", "a custom XML relationship"],
)
def test_a_part_that_the_text_still_refers_to_is_never_removed(
    relationship: str, target: str
) -> None:
    # An element this cleaner does not know refers to a part that it removes otherwise (by its
    # folder, or by its relationship type): the part stays, so the reference still leads somewhere
    # and the file stays whole.
    unknown = '<w:r><ex:widget xmlns:ex="urn:example" r:id="rId1"/></w:r>'
    pkg = package(
        para(unknown),
        rels=[(relationship, target)],
        parts={f"word/{target}": b"<widget/>"},
    )
    clean(pkg)
    assert f"word/{target}" in pkg.names()
    assert_consistent(pkg)


# ---- the two copies of a text box (ruling R16) ---------------------------------------------------


def test_an_alternate_content_with_only_a_fallback_is_removed_whole() -> None:
    only = "<mc:AlternateContent><mc:Fallback><w:t>old</w:t></mc:Fallback></mc:AlternateContent>"
    pkg = package(para(f"<w:r><w:t>x</w:t>{only}</w:r>"))
    assert clean(pkg).fallbacks_removed == 1
    assert text_of(pkg) == "x" and b"AlternateContent" not in everywhere(pkg)


def test_of_several_choices_the_first_is_kept() -> None:
    choices = (
        '<mc:AlternateContent><mc:Choice Requires="a"><w:t>first</w:t></mc:Choice>'
        '<mc:Choice Requires="b"><w:t>second</w:t></mc:Choice><mc:Fallback><w:t>third</w:t></mc:Fallback>'
        "</mc:AlternateContent>"
    )
    pkg = package(para(f"<w:r>{choices}</w:r>"))
    assert clean(pkg).fallbacks_removed == 1
    assert text_of(pkg) == "first"


# ---- file properties -----------------------------------------------------------------------------

_CORE = (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "<dc:title>Supply Agreement - Acme / Beta</dc:title><dc:subject>Packaging</dc:subject>"
    "<dc:creator>Jane Doe</dc:creator><cp:keywords>acme; beta</cp:keywords>"
    "<dc:description>Agreed with John</dc:description><cp:lastModifiedBy>John Roe</cp:lastModifiedBy>"
    "<dc:identifier>DMS-4711</dc:identifier><cp:version>7.2</cp:version><cp:revision>18</cp:revision>"
    '<dcterms:created xsi:type="dcterms:W3CDTF">2026-03-01T10:01:00Z</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-04-16T13:54:00Z</dcterms:modified>'
    "<cp:category>Contracts</cp:category><cp:contentStatus>Final draft</cp:contentStatus>"
    "</cp:coreProperties>"
)
_APP = (
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    "<Template>Supply Agreement.dotx</Template><TotalTime>621</TotalTime><Pages>4</Pages>"
    "<Application>Microsoft Office Word</Application>"
    '<HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Title</vt:lpstr></vt:variant>'
    "<vt:variant><vt:i4>1</vt:i4></vt:variant></vt:vector></HeadingPairs>"
    '<TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>Supply Agreement - Acme / Beta</vt:lpstr>'
    "</vt:vector></TitlesOfParts><Manager>Jane Doe</Manager><Company>Acme Ltd</Company>"
    '<HLinks><vt:vector size="2" baseType="variant"><vt:variant><vt:i4>5</vt:i4></vt:variant><vt:variant>'
    "<vt:lpwstr>mailto:jane@acme.example</vt:lpwstr></vt:variant></vt:vector></HLinks>"
    "<HyperlinkBase>https://www.acme.example/contracts/</HyperlinkBase><AppVersion>16.0000</AppVersion>"
    "</Properties>"
)
_CUSTOM = (
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="Client"><vt:lpwstr>Acme Ltd</vt:lpwstr></property>'
    '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="3" name="Matter owner"><vt:lpwstr>Jane Doe</vt:lpwstr></property>'
    "</Properties>"
)


CORE_CLEARED = (  # in the order the plan lists them
    *("dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject"),
    *("cp:keywords", "dc:description", "cp:category", "cp:contentStatus"),
    *("dc:identifier", "cp:version"),
)


def with_properties() -> DocxPackage:
    return package(
        package_rels=[
            (CORE_REL, "docProps/core.xml"),
            (APP_REL, "docProps/app.xml"),
            (CUSTOM_REL, "docProps/custom.xml"),
        ],
        parts={
            "docProps/core.xml": _CORE.encode(),
            "docProps/app.xml": _APP.encode(),
            "docProps/custom.xml": _CUSTOM.encode(),
        },
        types={
            "docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
            "docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
            "docProps/custom.xml": "application/vnd.openxmlformats-officedocument.custom-properties+xml",
        },
    )


def test_core_properties_are_emptied_and_dated_now() -> None:
    pkg = with_properties()
    clean(pkg, now=NOW)
    core = pkg.xml("docProps/core.xml")
    for tag in CORE_CLEARED:
        el = core.find(tag, NS)
        assert el is not None and not (el.text or ""), tag  # emptied, not removed
    for tag in ("dcterms:created", "dcterms:modified"):
        el = core.find(tag, NS)
        assert el is not None and el.text == STAMP
        assert el.get("{http://www.w3.org/2001/XMLSchema-instance}type") == "dcterms:W3CDTF"
    assert core.findtext("cp:revision", namespaces=NS) == "18"  # not a person's, not a name
    for stale in (b"Jane", b"John", b"acme", b"Acme", b"2026-03-01", b"2026-04-16"):
        assert stale not in pkg.raw("docProps/core.xml")


def test_app_properties_are_emptied_and_the_lists_removed() -> None:
    pkg = with_properties()
    clean(pkg, now=NOW)
    app = pkg.xml("docProps/app.xml")
    ep = {"ep": NS["ep"]}
    for tag in ("Company", "Manager", "HyperlinkBase"):
        el = app.find(f"ep:{tag}", ep)
        assert el is not None and not (el.text or ""), tag
    assert app.findtext("ep:Template", namespaces=ep) == "Normal.dotm"
    assert app.findtext("ep:TotalTime", namespaces=ep) == "0"
    for tag in ("TitlesOfParts", "HeadingPairs", "HLinks"):
        assert app.find(f"ep:{tag}", ep) is None, tag
    assert app.findtext("ep:Pages", namespaces=ep) == "4"  # figures about the file are not names
    assert app.findtext("ep:Application", namespaces=ep) == "Microsoft Office Word"
    for stale in (b"Jane", b"acme", b"Acme", b"mailto", b"Supply"):
        assert stale not in pkg.raw("docProps/app.xml")


def test_the_report_names_the_properties_that_held_something() -> None:
    rep = clean(with_properties(), now=NOW)
    assert rep.properties_cleared == [
        *CORE_CLEARED,
        "dcterms:created",
        "dcterms:modified",
        *("Company", "Manager", "HyperlinkBase", "Template", "TotalTime"),
        *("TitlesOfParts", "HeadingPairs", "HLinks"),
        *("custom:Client", "custom:Matter owner"),
    ]
    assert rep.parts_removed == ["docProps/custom.xml"]


def test_the_custom_properties_part_goes_with_its_links() -> None:
    pkg = with_properties()
    clean(pkg, now=NOW)
    assert "docProps/custom.xml" not in pkg.names()
    for bookkeeping in ("_rels/.rels", "[Content_Types].xml"):
        assert b"custom" not in pkg.raw(bookkeeping), bookkeeping
    assert b"Matter owner" not in everywhere(pkg)
    assert_consistent(pkg)


def test_the_dates_are_now_in_utc_whatever_the_clock_given() -> None:
    plus_two = datetime(2030, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2)))
    for moment in (NOW, plus_two, datetime(2030, 1, 2, 3, 4, 5)):  # the last one has no zone
        pkg = with_properties()
        clean(pkg, now=moment)
        assert pkg.xml("docProps/core.xml").findtext("dcterms:modified", namespaces=NS) == STAMP


def test_without_a_clock_the_dates_are_the_time_of_cleaning() -> None:
    pkg = with_properties()
    clean(pkg)
    stamp = pkg.xml("docProps/core.xml").findtext("dcterms:created", namespaces=NS)
    moment = datetime.strptime(stamp or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs(datetime.now(UTC) - moment) < timedelta(minutes=1)


def test_properties_that_are_missing_or_already_empty_are_fine() -> None:
    sparse = (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title/><cp:keywords></cp:keywords></cp:coreProperties>'
    )
    pkg = package(
        package_rels=[(CORE_REL, "docProps/core.xml")], parts={"docProps/core.xml": sparse.encode()}
    )
    rep = clean(pkg, now=NOW)
    assert (
        rep.properties_cleared == []
        and pkg.xml("docProps/core.xml").find("dcterms:created", NS) is None
    )


def test_core_properties_are_blanked_whatever_they_hold() -> None:
    # A property can have child elements (keywords may hold cp:value) and a name can repeat.
    core = (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:creator>Jane Doe</dc:creator><dc:creator>Second Author</dc:creator>"
        "<cp:keywords>acme <cp:value>Zeta Holdings</cp:value> deal</cp:keywords>"
        "<dc:identifier>DMS-4711/Zeta</dc:identifier><cp:version>7.2 Zeta draft</cp:version>"
        "<cp:revision>3</cp:revision></cp:coreProperties>"
    )
    pkg = package(
        package_rels=[(CORE_REL, "docProps/core.xml")], parts={"docProps/core.xml": core.encode()}
    )
    rep = clean(pkg, now=NOW)
    for stale in (b"Zeta", b"Jane", b"Second", b"acme", b"deal", b"DMS", b"7.2"):
        assert stale not in pkg.raw("docProps/core.xml"), stale
    root = pkg.xml("docProps/core.xml")
    assert [e.text for e in root.findall("dc:creator", NS)] == [None, None]
    assert len(root.find("cp:keywords", NS)) == 0  # no child is left either
    assert root.findtext("cp:revision", namespaces=NS) == "3"
    assert rep.properties_cleared == ["dc:creator", "cp:keywords", "dc:identifier", "cp:version"]


def test_the_picture_of_the_first_page_goes() -> None:
    pkg = package(
        package_rels=[(THUMBNAIL, "docProps/thumbnail.jpeg")],
        parts={"docProps/thumbnail.jpeg": b"JPEG of page one"},
    )
    rep = clean(pkg)
    assert rep.parts_removed == ["docProps/thumbnail.jpeg"]
    assert b"thumbnail" not in everywhere(pkg) and b"JPEG" not in everywhere(pkg)
    assert_consistent(pkg)


def test_printer_settings_and_signatures_go() -> None:
    section = (
        '<w:sectPr><w:printerSettings r:id="rId1"/><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
    )
    pkg = package(
        f"<w:p/>{section}",
        rels=[(f"{REL}/printerSettings", "printerSettings/printerSettings1.bin")],
        package_rels=[(f"{SIGNATURES}/origin", "_xmlsignatures/origin.sigs")],
        parts={
            "word/printerSettings/printerSettings1.bin": b"HP-LaserJet-Legal-Dept",
            "_xmlsignatures/origin.sigs": b"",
            "_xmlsignatures/_rels/origin.sigs.rels": rels_xml(
                [(f"{SIGNATURES}/signature", "sig1.xml")]
            ),
            "_xmlsignatures/sig1.xml": b"<Signature><X509SubjectName>CN=Joel Stewart</X509SubjectName></Signature>",
        },
    )
    rep = clean(pkg)
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert len(rep.parts_removed) == 5
    assert b"printerSettings" not in everywhere(pkg)  # the element that named the part goes too
    assert pkg.xml("word/document.xml").find(".//w:pgSz", NS) is not None  # the section stays
    assert_consistent(pkg)


# ---- the theme's names (ruling R66) --------------------------------------------------------------

THEME_REL = f"{REL}/theme"
THEME_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def with_theme(name: str, scheme: str) -> DocxPackage:
    """A small file whose theme and its three schemes have these names, and a font of its own."""
    theme = (
        f'<a:theme xmlns:a="{THEME_NS}" name="{name}"><a:themeElements>'
        f'<a:clrScheme name="{scheme}"/><a:fontScheme name="{scheme}"><a:majorFont>'
        '<a:latin typeface="Northwind Sans"/></a:majorFont></a:fontScheme>'
        f'<a:fmtScheme name="{scheme}"/></a:themeElements></a:theme>'
    )
    parts = {"word/theme/theme1.xml": ('<?xml version="1.0"?>\n' + theme).encode()}
    return package(rels=[(THEME_REL, "theme/theme1.xml")], parts=parts)


def test_the_theme_takes_back_the_names_word_gives_its_own() -> None:
    pkg = with_theme("Northwind Trading", "Northwind")
    rep = clean(pkg)
    root = pkg.xml("word/theme/theme1.xml")
    schemes = root.iter(*(f"{{{THEME_NS}}}{k}" for k in ("clrScheme", "fontScheme", "fmtScheme")))
    assert root.get("name") == "Office Theme"
    assert [scheme.get("name") for scheme in schemes] == ["Office", "Office", "Office"]
    assert rep.attributes_cleared == 4
    # Its fonts are its own: the leak check finds a font named after the company.
    assert b'typeface="Northwind Sans"' in pkg.raw("word/theme/theme1.xml")
    assert clean(with_theme("Office Theme", "Office")).attributes_cleared == 0


# ---- custom XML, bindings, glossary --------------------------------------------------------------


def test_custom_xml_parts_and_data_bindings_go() -> None:
    bound = (
        '<w:sdt><w:sdtPr><w:alias w:val="Client"/><w:dataBinding w:prefixMappings="" '
        'w:xpath="/clients/client" w:storeItemID="{11111111-2222-3333-4444-555555555555}"/></w:sdtPr>'
        f"<w:sdtContent>{para(run('Acme Ltd'))}</w:sdtContent></w:sdt>"
    )
    pkg = package(
        bound,
        rels=[(CUSTOM_XML, "../customXml/item1.xml")],
        parts={
            "customXml/item1.xml": b"<clients><client>Acme Ltd</client></clients>",
            "customXml/itemProps1.xml": b"<ds:datastoreItem xmlns:ds='urn:ds' ds:itemID='{X}'/>",
            "customXml/_rels/item1.xml.rels": rels_xml([(CUSTOM_XML_PROPS, "itemProps1.xml")]),
        },
        types={"customXml/itemProps1.xml": CUSTOM_XML_PROPS_TYPE},
    )
    rep = clean(pkg)
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert rep.parts_removed == [
        "word/_rels/document.xml.rels",  # it held nothing but the link to the item
        "customXml/item1.xml",
        "customXml/itemProps1.xml",
        "customXml/_rels/item1.xml.rels",
    ]
    assert b"dataBinding" not in document(pkg)
    assert text_of(pkg) == "Acme Ltd"  # the control keeps its text
    assert b"customXml" not in everywhere(pkg)
    assert_consistent(pkg)


def test_the_glossary_goes_with_everything_only_it_used() -> None:
    glossary = part("w:glossaryDocument", "<w:docParts/>")
    pkg = package(
        rels=[(f"{REL}/glossaryDocument", "glossary/document.xml")],
        parts={
            "word/glossary/document.xml": glossary,
            "word/glossary/_rels/document.xml.rels": rels_xml([(IMAGE, "../media/stamp.png")]),
            "word/glossary/settings.xml": part("w:settings"),
            "word/media/stamp.png": b"PNG of a stamp",
        },
        types={"word/glossary/document.xml": f"{WML}.document.glossary+xml"},
    )
    clean(pkg)
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert_consistent(pkg)


# The kind of picture that is not one of those in the text: the bullet of a list.
BULLET = (
    '<w:numPicBullet w:numPicBulletId="0"><w:pict><v:shape><v:imagedata r:id="rId1"/></v:shape>'
    "</w:pict></w:numPicBullet>"
)


def test_the_image_of_a_picture_bullet_goes_with_the_bullet() -> None:
    # Ruling R101: every media part goes, the one a picture bullet uses and the one nobody uses
    # alike; the bullet itself goes with its image, so nothing is left dangling.
    pkg = package(
        para(f"<w:r>{picture('rId1')}</w:r>"),
        rels=[(IMAGE, "media/a.png"), (f"{REL}/numbering", "numbering.xml")],
        parts={
            "word/media/a.png": b"PNG",
            "word/media/bullet.png": b"PNG",
            "word/numbering.xml": part("w:numbering", BULLET),
            "word/_rels/numbering.xml.rels": rels_xml([(IMAGE, "media/bullet.png")]),
            "word/media/orphan.png": b"PNG nobody uses",
        },
    )
    rep = clean(pkg)
    assert [n for n in pkg.names() if "media" in n] == []
    assert b"numPicBullet" not in everywhere(pkg) and rep.images == 2
    assert "word/numbering.xml" in pkg.names()
    assert_consistent(pkg)


def test_a_picture_that_something_else_still_uses_goes_as_well() -> None:
    # Ruling R101: a picture bullet's image is a picture like any other.
    pkg = package(
        para(f"<w:r>{picture('rId1')}</w:r>"),
        rels=[(IMAGE, "media/shared.png"), (f"{REL}/numbering", "numbering.xml")],
        parts={
            "word/media/shared.png": b"PNG",
            "word/numbering.xml": part("w:numbering", BULLET),
            "word/_rels/numbering.xml.rels": rels_xml([(IMAGE, "media/shared.png")]),
        },
    )
    rep = clean(pkg)
    assert rep.images == 2 and "word/media/shared.png" not in pkg.names()
    assert "word/_rels/numbering.xml.rels" not in pkg.names()
    assert_consistent(pkg)


def test_a_part_takes_the_parts_only_it_used_and_leaves_the_shared_ones() -> None:
    chunk_rels = rels_xml([(IMAGE, "logo.png"), (IMAGE, "shared.png")])
    pkg = package(
        '<w:altChunk r:id="rId1"/>',
        rels=[(AFCHUNK, "chunk/afchunk.html"), (f"{REL}/numbering", "numbering.xml")],
        parts={
            "word/chunk/afchunk.html": b"<html><img src='logo.png'/><img src='shared.png'/></html>",
            "word/chunk/_rels/afchunk.html.rels": chunk_rels,
            "word/chunk/logo.png": b"PNG only the chunk uses",
            "word/chunk/shared.png": b"PNG the bullets use as well",
            "word/numbering.xml": part("w:numbering", BULLET),
            "word/_rels/numbering.xml.rels": rels_xml([(IMAGE, "chunk/shared.png")]),
        },
        types={"word/chunk/afchunk.html": "text/html"},
    )
    rep = clean(pkg)
    assert {"word/chunk/afchunk.html", "word/chunk/logo.png"} <= set(rep.parts_removed)
    # Ruling R101: the picture the bullets share is a picture, and goes with the bullet.
    assert "word/chunk/shared.png" not in pkg.names()
    assert_consistent(pkg)


# ---- pictures that are not in the text (ruling R101) ---------------------------------------------

THEME_WITH_IMAGE = (
    '<a:theme name="Acme Corporate"><a:themeElements><a:clrScheme name="Office"/>'
    '<a:fontScheme name="Office"/><a:fmtScheme name="Office"><a:fillStyleLst>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></a:blipFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
    '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:blipFill><a:blip r:embed="rId1"/></a:blipFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
    "</a:fmtScheme></a:themeElements></a:theme>"
)
PICTURE_BULLETS = (
    BULLET + '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
    '<w:numFmt w:val="bullet"/><w:lvlPicBulletId w:val="0"/><w:lvlText w:val=""/>'
    '<w:lvlJc w:val="left"/></w:lvl></w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
)
MODEL3D_NS = "http://schemas.microsoft.com/office/drawing/2017/model3d"
MODEL3D = (
    '<w:drawing><wp:inline><wp:docPr id="7" name="3D Model 7"/><a:graphic>'
    f'<a:graphicData uri="{MODEL3D_NS}"><am3d:model3d xmlns:am3d="{MODEL3D_NS}" r:embed="rId1">'
    "<am3d:spPr/></am3d:model3d></a:graphicData></a:graphic></wp:inline></w:drawing>"
)


def media_everywhere() -> DocxPackage:
    """The reviewer's file: a picture in the page background, a picture bullet, an image in the
    theme, a VML shape with a picture fill, an orphan image relationship and a header picture."""
    background = (
        '<w:background w:color="FFFFFF"><v:background id="_x0000_s1025" o:bwmode="white">'
        '<v:fill r:id="rId3" o:title="letterhead" recolor="t" type="frame"/></v:background>'
        "</w:background>"
    )
    body = (
        para(run("Acme Supplies Ltd (the Supplier) and Brightwater Foods Ltd (the Buyer) agree."))
        + '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        + run("A bulleted item with a picture bullet.")
        + "</w:p>"
        + para(
            '<w:r><w:pict><v:rect id="_x0000_s1026" style="width:100pt;height:50pt">'
            '<v:fill r:id="rId4" type="frame"/></v:rect></w:pict></w:r>',
            run("Contact: John Carter, Director."),
        )
        + '<w:sectPr><w:headerReference w:type="default" r:id="rId5"/></w:sectPr>'
    )
    header = para(
        run("Acme Supplies Ltd"),
        '<w:r><w:pict><v:shape style="width:60pt;height:20pt"><v:imagedata r:id="rId1" o:title="logo"/>'
        "</v:shape></w:pict></w:r>",
    )
    pkg = package(
        body,
        rels=[
            (f"{REL}/numbering", "numbering.xml"),
            (THEME_REL, "theme/theme1.xml"),
            (IMAGE, "media/background.png"),
            (IMAGE, "media/fill.png"),
            (HEADER, "header1.xml"),
            (IMAGE, "media/orphan.png"),
        ],
        parts={
            "word/numbering.xml": part("w:numbering", PICTURE_BULLETS),
            "word/_rels/numbering.xml.rels": rels_xml([(IMAGE, "media/bullet.png")]),
            "word/theme/theme1.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                + THEME_WITH_IMAGE.replace("<a:theme ", f"<a:theme {DECLARATIONS} ", 1)
            ).encode(),
            "word/theme/_rels/theme1.xml.rels": rels_xml([(IMAGE, "../media/themeimage.png")]),
            **in_header(header),
            "word/_rels/header1.xml.rels": rels_xml([(IMAGE, "media/logo.png")]),
            **{
                f"word/media/{name}.png": b"PNG " + name.encode()
                for name in ("bullet", "themeimage", "logo", "background", "fill", "orphan")
            },
        },
        types={
            "word/numbering.xml": f"{WML}.numbering+xml",
            "word/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
            "word/header1.xml": HEADER_TYPE,
        },
    )
    # The document's root holds the background before the body, as Word writes it.
    root = pkg.xml("word/document.xml")
    root.insert(0, etree.fromstring(f"<w:root {DECLARATIONS}>{background}</w:root>")[0])
    return pkg


def test_every_picture_goes_wherever_it_is_reached_from(tmp_path: Path) -> None:
    # Ruling R101: pixels are what is marked (a logo is the company, a signature the person).
    pkg = media_everywhere()
    rep = clean(pkg)
    assert not [n for n in pkg.names() if n.startswith("word/media/")]
    assert all(f"{IMAGE}" not in pkg.raw(n).decode() for n in pkg.names() if n.endswith(".rels"))
    document = pkg.raw("word/document.xml")
    assert b"background" not in document and b'r:id="rId4"' not in document
    assert b"<v:fill" in document  # a fill without its picture is a plain fill
    numbering = pkg.raw("word/numbering.xml")
    assert b"numPicBullet" not in numbering and b"lvlPicBulletId" not in numbering
    theme = pkg.xml("word/theme/theme1.xml")
    assert b"blip" not in pkg.raw("word/theme/theme1.xml")
    for fills in theme.iter(f"{{{THEME_NS}}}fillStyleLst", f"{{{THEME_NS}}}bgFillStyleLst"):
        assert len(fills) == 3 and all(f.tag == f"{{{THEME_NS}}}solidFill" for f in fills)
    header_text = text_of(pkg).splitlines()[-1]
    assert header_text.startswith("Acme Supplies Ltd") and header_text.endswith(IMAGE_NOTE)
    # The header picture, the background, the bullet, the theme's two images and the VML fill.
    assert rep.images == 6
    assert set(rep.parts_removed) >= {f"word/media/{n}.png" for n in ("bullet", "orphan", "logo")}
    assert_consistent(pkg)
    saved = tmp_path / "cleaned.docx"
    pkg.save(saved)
    assert docx.Document(str(saved)).paragraphs[0].text.startswith("Acme Supplies Ltd")


def test_a_3d_model_is_a_picture_with_its_part() -> None:
    pkg = package(
        para(run("See "), f"<w:r>{MODEL3D}</w:r>"),
        rels=[(f"{REL}/model3d", "media/model1.glb")],
        parts={"word/media/model1.glb": b"glTF"},
        types={"word/media/model1.glb": "model/gltf-binary"},
    )
    rep = clean(pkg)
    assert rep.images == 1 and text_of(pkg) == f"See {IMAGE_NOTE}"
    assert pkg.names() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
    assert_consistent(pkg)


def test_a_media_part_goes_by_its_content_type_wherever_it_is() -> None:
    # An audio clip the document plays, under a folder of its own and an Override type.
    pkg = package(
        parts={"word/clips/intro.wav": b"RIFF", "word/stills/frame.bin": b"PNG"},
        types={"word/clips/intro.wav": "audio/wav", "word/stills/frame.bin": "image/png"},
    )
    rep = clean(pkg)
    assert set(rep.parts_removed) == {"word/clips/intro.wav", "word/stills/frame.bin"}
    assert_consistent(pkg)


def test_the_steps_work_on_each_other_in_the_order_given() -> None:
    # Fields are flattened before hidden runs go, so a hidden result is removed with the rest;
    # a hidden run takes its picture with it; a comment inside a text box goes with its markers.
    hidden_result = field(" AUTHOR ", "<w:r><w:rPr><w:vanish/></w:rPr><w:t>Joel</w:t></w:r>")
    pictured = f"<w:r><w:rPr><w:vanish/></w:rPr>{picture('rId1')}</w:r>"
    marked = text_box(
        para('<w:commentRangeStart w:id="1"/>', run("Boxed"), '<w:commentRangeEnd w:id="1"/>')
    )
    pkg = package(
        para(run("a"), hidden_result, pictured, f"<w:r>{marked}</w:r>"),
        rels=[(IMAGE, "media/a.png")],
        parts={"word/media/a.png": b"PNG"},
    )
    rep = clean(pkg)
    assert (rep.fields_flattened, rep.hidden_runs, rep.images, rep.comments) == (1, 2, 0, 1)
    assert text_of(pkg).splitlines() == ["a", "Boxed"]
    assert b"fldChar" not in everywhere(pkg) and b"comment" not in everywhere(pkg)
    assert not [n for n in pkg.names() if "media" in n]
    assert_consistent(pkg)
