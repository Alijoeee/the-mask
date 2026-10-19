### Task 16: PDF to Word

**Files:**
- Create: `src/themask/pdf/__init__.py`, `src/themask/pdf/extractor.py`, `src/themask/pdf/to_docx.py`
- Modify: `src/themask/export.py` (`load_sources` converts `.pdf` via `pdf_to_docx` into a temp `.docx`, keeps `pdf_report`)
- Test: `tests/pdf/test_extractor.py`, `tests/pdf/test_to_docx.py`

**Interfaces:**
- Produces (`extractor.py`): `@dataclass Block(kind: Literal["heading","paragraph","table"], text: str, rows: list[list[str]] | None, page: int)`; `@dataclass PdfReport(pages: int, image_only_pages: list[int], repeated_lines_removed: list[str])`; `extract_blocks(pdf: Path) -> tuple[list[Block], PdfReport]` using `pdfplumber`: a page is image-only when `extract_text()` is empty and `page.images` is non-empty; lines whose normalised text appears on ≥ 60 % of pages within the top or bottom 12 % of the page height are running headers/footers → kept once as the first block, removed elsewhere; `extract_tables()` rows become table blocks; remaining words grouped into lines (`extract_text_lines`) and paragraphs (gap > 1.5 × line height); a line in a larger font than the page median → heading. Raises `ScannedPdfError("This PDF is a scan without selectable text. The MASK cannot read it yet.")` when every page is image-only.
- Produces (`to_docx.py`): `pdf_to_docx(pdf: Path, out: Path) -> PdfReport` (python-docx: headings as `Heading 1/2`, paragraphs, tables with the first row bold; image-only pages → a paragraph `[page N is an image — not included]`).

- [ ] **Step 1: Write the failing tests**

```python
def test_blocks_and_report(corpus):
    blocks, rep = extract_blocks(corpus / "supply-01.pdf"); assert rep.image_only_pages == [] and any(b.kind == "table" for b in blocks) and rep.repeated_lines_removed
def test_running_header_once(corpus):
    blocks, _ = extract_blocks(corpus / "supply-01.pdf"); joined = "\n".join(b.text for b in blocks); assert joined.count("Confidential") == 1
def test_scanned_refused(corpus):
    with pytest.raises(ScannedPdfError): extract_blocks(corpus / "scanned-01.pdf")
def test_mixed_lists_image_pages(corpus):
    _, rep = extract_blocks(corpus / "mixed-01.pdf"); assert rep.image_only_pages == [2]
def test_to_docx_keeps_every_truth_value(corpus, tmp_path):
    out = tmp_path / "s.docx"; pdf_to_docx(corpus / "supply-01.pdf", out); text = normalize(extract_text(DocxPackage.open(out)).text)
    for t in json.loads((corpus / "supply-01.truth.json").read_text()): assert normalize(t["value"]) in text, t["value"]
def test_load_sources_pdf(corpus):
    s, = load_sources([corpus / "supply-01.pdf"], False); assert s.kind == "pdf" and s.pdf_report is not None and "Confidential" in s.text_after.text
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: PDF text extraction to Word with image-page reporting"`

---

