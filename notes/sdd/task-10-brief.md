### Task 10: Word package and text map

**Files:**
- Create: `src/themask/docx/__init__.py`, `src/themask/docx/package.py`, `src/themask/docx/reader.py`
- Test: `tests/docx/test_package.py`, `tests/docx/test_reader.py`, fixtures `tests/docx/fixtures/` (`not-a-docx.doc` = 512 bytes starting `D0 CF 11 E0`, `corrupt.docx` = random bytes, `encrypted.docx` = OLE container bytes with the `EncryptionInfo` stream name)

**Interfaces:**
- Produces (`package.py`): `class DocxPackage` with `open(path: Path) -> DocxPackage` (raises `UnsupportedFileError("This is not a Word .docx file. If it is an old .doc, open it in Word and save as .docx.")` for non-zip / missing `word/document.xml`, `ProtectedFileError("This file is protected or encrypted. Please provide an unprotected copy.")` for OLE/`EncryptionInfo`), `copy() -> DocxPackage` (deep), `names() -> list[str]`, `xml(name) -> lxml.etree._Element` (parsed once, cached, written back on save), `raw(name) -> bytes`, `set_raw(name, data)`, `rels_of(part_name) -> lxml element` (`word/_rels/document.xml.rels` etc.), `remove_part(name)` (deletes the entry, every relationship pointing to it, and its `[Content_Types].xml` Override), `save(path: Path)`, `TEXT_PARTS` property: `word/document.xml`, `word/header*.xml`, `word/footer*.xml`, `word/footnotes.xml`, `word/endnotes.xml` (comments excluded), `NS` dict (`w`, `r`, `wp`, `a`, `pic`, `wps`, `v`, `c`, `dgm`, `cp`, `dc`, `dcterms`, `ep`, `w14`).
- Produces (`reader.py`): `@dataclass TextNode(elem, start: int, end: int, kind: Literal["t","instr"])`; `paragraph_nodes(p, view: Literal["accepted","rejected"]) -> tuple[str, list[TextNode]]` (walks `w:r`, `w:hyperlink`, `w:sdt/w:sdtContent`, `w:smartTag`, `w:fldSimple`, `w:ins` (accepted only), `w:del/w:delText` (rejected only), `w:instrText`); `@dataclass Segment(part: str, para: lxml element, start: int, end: int)`; `@dataclass DocText(text: str, segments: list[Segment])`; `extract_text(pkg, view="accepted") -> DocText` (paragraph texts joined with `\n`, over `TEXT_PARTS` in order document → headers → footers → footnotes → endnotes; text-box paragraphs included); `has_revisions(pkg) -> bool` (`w:ins|w:del|w:moveFrom|w:moveTo|w:rPrChange|w:pPrChange` anywhere in TEXT_PARTS); `has_comments(pkg) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_open_doc_renamed(fixtures):
    with pytest.raises(UnsupportedFileError) as e: DocxPackage.open(fixtures / "not-a-docx.doc")
    assert "save as .docx" in e.value.user_message
def test_open_corrupt(fixtures):
    with pytest.raises(UnsupportedFileError): DocxPackage.open(fixtures / "corrupt.docx")
def test_open_encrypted(fixtures):
    with pytest.raises(ProtectedFileError): DocxPackage.open(fixtures / "encrypted.docx")
def test_remove_part_cleans_rels_and_types(corpus):
    pkg = DocxPackage.open(corpus / "supply-02.docx"); assert "word/comments.xml" in pkg.names()
    pkg.remove_part("word/comments.xml"); assert "word/comments.xml" not in pkg.names()
    assert b"comments.xml" not in pkg.raw("word/_rels/document.xml.rels") and b"comments+xml" not in pkg.raw("[Content_Types].xml")
def test_extract_text_covers_all_parts(corpus):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg)
    assert {s.part for s in dt.segments} >= {"word/document.xml", "word/header1.xml", "word/footer1.xml"} and "Confidential" in dt.text
def test_views(corpus):                       # supply-03 has tracked changes with a secret only in deleted text
    pkg = DocxPackage.open(corpus / "supply-03.docx"); truth = json.loads((corpus / "supply-03.truth.json").read_text())
    deleted = next(t["value"] for t in truth if t.get("only_in_deletion"))
    assert deleted not in extract_text(pkg, "accepted").text and deleted in extract_text(pkg, "rejected").text and has_revisions(pkg)
def test_split_runs_map_back(corpus):         # supply-01 writes "Northwind Trading B.V." across three runs
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg); i = dt.text.index("Northwind Trading B.V.")
    seg = next(s for s in dt.segments if s.start <= i < s.end); text, nodes = paragraph_nodes(seg.para, "accepted")
    lo, hi = i - seg.start, i - seg.start + len("Northwind Trading B.V."); covering = [n for n in nodes if n.start < hi and n.end > lo]
    assert text[lo:hi] == "Northwind Trading B.V." and len(covering) >= 3
def test_original_untouched(corpus, tmp_path):
    src = corpus / "supply-01.docx"; before = src.read_bytes(); pkg = DocxPackage.open(src); pkg.remove_part("word/header1.xml"); pkg.save(tmp_path / "out.docx")
    assert src.read_bytes() == before
```

- [ ] **Step 2–5:** verify failure → implement → verify pass (+ lint/types) → `git commit -m "feat: docx package wrapper and text map with accepted/rejected views"`

---

