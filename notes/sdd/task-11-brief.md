### Task 11: Accept and reject all tracked changes

**Files:**
- Create: `src/themask/docx/revisions.py`
- Test: `tests/docx/test_revisions.py` (+ fixture builder `tests/docx/fixtures/revisions.py` making a docx with: `w:ins` run, `w:del` run, `w:moveFrom`/`w:moveTo`, `w:rPrChange` (old plain → new bold), `w:pPrChange`, an inserted paragraph mark (`w:pPr/w:rPr/w:ins`), a deleted paragraph mark (`w:pPr/w:rPr/w:del`), `w:cellIns`/`w:cellDel`, `w:numberingChange`, `w:sectPrChange`)

**Interfaces:**
- Produces: `accept_all(pkg: DocxPackage) -> int` (number of revisions resolved) and `reject_all(pkg: DocxPackage) -> int`, over `TEXT_PARTS`. Accept: unwrap `w:ins`/`w:moveTo`; delete `w:del`/`w:moveFrom`; delete `*Change` records; inserted paragraph mark → remove marker; deleted paragraph mark → merge paragraph with the following one; `w:cellDel` → remove cell, `w:cellIns` → keep. Reject: delete `w:ins`/`w:moveTo`; unwrap `w:del` turning `w:delText` into `w:t`; unwrap `w:moveFrom`; `*Change` → replace the current property element with the old one stored inside the change record; inserted paragraph mark → merge; deleted paragraph mark → keep; `w:cellIns` → remove cell. Afterwards `has_revisions(pkg)` is False.

- [ ] **Step 1: Write the failing tests**

```python
def test_accept_text(rev_pkg): accept_all(rev_pkg); assert extract_text(rev_pkg).text.splitlines()[0] == "The Buyer shall pay EUR 2,000 within 45 days."
def test_reject_text(rev_pkg): reject_all(rev_pkg); assert extract_text(rev_pkg).text.splitlines()[0] == "The Buyer shall pay EUR 1,000 within 30 days."
def test_no_revisions_left(rev_pkg): accept_all(rev_pkg); assert not has_revisions(rev_pkg)
def test_reject_restores_old_formatting(rev_pkg):
    reject_all(rev_pkg); r = rev_pkg.xml("word/document.xml").find(".//w:r[w:t='bold']", NS); assert r.find("w:rPr/w:b", NS) is None
def test_paragraph_marks(rev_pkg_marks):
    a = rev_pkg_marks.copy(); accept_all(a); assert extract_text(a).text.count("\n") == 1
    r = rev_pkg_marks.copy(); reject_all(r); assert extract_text(r).text.count("\n") == 2
def test_corpus_tracked_docs_resolve(corpus):
    for doc in (d for d in json.loads((corpus/"manifest.json").read_text()) if "tracked_changes" in d["features"]):
        pkg = DocxPackage.open(corpus / doc["file"]); accept_all(pkg); assert not has_revisions(pkg)
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: accept-all and reject-all for tracked changes"`

---

