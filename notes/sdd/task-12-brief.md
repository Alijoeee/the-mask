### Task 12: Cleaner (hidden places)

**Files:**
- Create: `src/themask/docx/cleaner.py`
- Test: `tests/docx/test_cleaner.py`

**Interfaces:**
- Consumes: `DocxPackage`, `IMAGE_NOTE`, `OBJECT_NOTE`.
- Produces: `@dataclass CleanReport(comments: int, images: int, objects: int, hidden_runs: int, properties_cleared: list[str], parts_removed: list[str])`; `clean(pkg: DocxPackage) -> CleanReport`:
  - comments: remove `word/comments.xml`, `commentsExtended.xml`, `commentsIds.xml`, `commentsExtensible.xml`, `people.xml`; strip `w:commentRangeStart/End`, runs containing `w:commentReference`;
  - properties: `docProps/core.xml` → clear `dc:creator cp:lastModifiedBy dc:title dc:subject cp:keywords dc:description cp:category cp:contentStatus`, set `dcterms:created/modified` to now (UTC); `docProps/app.xml` → clear `Company Manager HyperlinkBase`, `Template`→`Normal.dotm`, `TotalTime`→`0`, remove `TitlesOfParts` and `HeadingPairs`; remove `docProps/custom.xml`;
  - `customXml/*` removed, every `w:dataBinding` removed; `w:docVars`, `w:attachedTemplate`, `w:rsids`, `w:trackRevisions` removed from `word/settings.xml`; all `w:rsid*` attributes stripped; `word/glossary/*` removed;
  - hidden text: remove every `w:r` whose `w:rPr` has `w:vanish` (and `w:specVanish`);
  - images/objects: every `w:drawing` whose content references `a:blip`, `c:chart` or `dgm:relIds`, every `w:pict` with `v:imagedata`, and every `w:object` → replaced by a run with `IMAGE_NOTE` (`OBJECT_NOTE` for `w:object`), the referenced parts (`word/media/*`, `word/charts/*`, `word/diagrams/*`, `word/embeddings/*`) removed; drawings/picts that only hold a text box (`wps:txbx`, `v:textbox`) are kept.

- [ ] **Step 1: Write the failing tests**

```python
def test_comments_gone(corpus):
    pkg = DocxPackage.open(corpus / "supply-02.docx"); rep = clean(pkg); names = set(pkg.names()); xml = etree.tostring(pkg.xml("word/document.xml"))
    assert rep.comments > 0 and not {n for n in names if "comments" in n or n.endswith("people.xml")} and b"commentReference" not in xml and b"commentRangeStart" not in xml
def test_properties_cleared(corpus):
    pkg = DocxPackage.open(corpus / "supply-04.docx"); clean(pkg); core = etree.fromstring(pkg.raw("docProps/core.xml")); app = pkg.raw("docProps/app.xml").decode()
    for tag in ("dc:creator", "cp:lastModifiedBy", "dc:title", "cp:keywords"): el = core.find(tag, NS); assert el is None or not (el.text or "").strip(), tag
    assert "TitlesOfParts" not in app and "HeadingPairs" not in app and "<Company></Company>" in app.replace("<Company/>", "<Company></Company>") and "docProps/custom.xml" not in pkg.names()
def test_images_replaced(corpus):
    pkg = DocxPackage.open(corpus / "supply-05.docx"); n_media = len([n for n in pkg.names() if n.startswith("word/media/")]); rep = clean(pkg)
    assert rep.images == n_media and not [n for n in pkg.names() if n.startswith("word/media/")] and extract_text(pkg).text.count(IMAGE_NOTE) == n_media
def test_hidden_text_removed(corpus):
    pkg = DocxPackage.open(corpus / "services-02.docx"); truth = json.loads((corpus / "services-02.truth.json").read_text()); hidden = next(t["value"] for t in truth if t.get("hidden"))
    clean(pkg); assert hidden not in extract_text(pkg).text and b"w:vanish" not in etree.tostring(pkg.xml("word/document.xml"))
def test_textbox_kept(corpus):
    pkg = DocxPackage.open(corpus / "services-03.docx"); clean(pkg); assert "Text box note" in extract_text(pkg).text
def test_settings_scrubbed(corpus):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); clean(pkg); s = pkg.raw("word/settings.xml"); assert b"w:rsids" not in s and b"attachedTemplate" not in s and b"docVars" not in s
    assert b"w:rsidR=" not in pkg.raw("word/document.xml")
def test_file_still_opens_with_python_docx(corpus, tmp_path):
    pkg = DocxPackage.open(corpus / "supply-05.docx"); clean(pkg); pkg.save(tmp_path / "c.docx"); import docx; assert docx.Document(str(tmp_path / "c.docx")).paragraphs
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: cleaner removes comments, properties, hidden text, images and settings traces"`

---

