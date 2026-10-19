### Task 5: PDF corpus (text, scanned, mixed)

**Files:**
- Modify: `tools/make_corpus.py` (add `write_pdf`, `write_scanned_pdf`, `write_mixed_pdf`; `generate` also writes 6 text PDFs, 1 scanned, 1 mixed, listed in the manifest with `"format": "pdf"` and `"image_pages": [...]`)
- Test: `tests/test_corpus.py` (extend)

**Interfaces:**
- Produces: PDFs with a running header (`<Short A> / <Short B> — <Title>`) and footer (`Page N of M · Confidential`) on every page, a pricing table, the same truth JSON as the docx twin; scanned PDF = pages rendered to PNG with Pillow then placed by reportlab (no text layer); mixed PDF = page 1 text, page 2 image.

- [ ] **Step 1: Write the failing tests**

```python
def test_pdf_corpus(corpus):
    man = json.loads((corpus / "manifest.json").read_text()); pdfs = [d for d in man if d["format"] == "pdf"]
    assert len(pdfs) >= 8 and sum(1 for d in pdfs if d["image_pages"]) >= 2
def test_text_pdf_has_text_and_running_header(corpus):
    import pdfplumber
    with pdfplumber.open(corpus / "supply-01.pdf") as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    assert len(pages) >= 3 and all("Confidential" in t for t in pages)
def test_scanned_pdf_has_no_text(corpus):
    import pdfplumber
    with pdfplumber.open(corpus / "scanned-01.pdf") as pdf: assert all(not (p.extract_text() or "").strip() for p in pdf.pages)
```

- [ ] **Step 2: Run to verify failure**, **Step 3: implement** (reportlab `SimpleDocTemplate` with `onPage` callbacks for header/footer; tables via `Table`; `write_scanned_pdf` renders each page's text with `ImageDraw` at 150 dpi), **Step 4: run to verify pass**.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "test: PDF corpus incl. scanned and mixed pages"`

---

