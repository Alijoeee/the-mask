### Task 13: Masker

**Files:**
- Create: `src/themask/docx/masker.py`, `src/themask/docx/restorer.py` (shared replace routine)
- Test: `tests/docx/test_masker.py`

**Interfaces:**
- Consumes: `DocText`, `TextNode`, `paragraph_nodes`, `MaskPlan`, `BANNER_TEXT`.
- Produces (`restorer.py`): `replace_in_paragraph(p, view, replacements: list[tuple[int, int, str]]) -> int` — generic cross-run replacement: positions are paragraph-relative; the replacement text goes into the first covered `w:t`/`w:instrText` (keeping that run's `w:rPr`), covered characters are removed from the following nodes, empty nodes deleted; `xml:space="preserve"` kept.
- Produces (`masker.py`): `@dataclass MaskReport(replaced: int, hyperlinks_unwrapped: int, instr_fields_masked: int)`; `apply_mask(pkg: DocxPackage, doc_text: DocText, plan: MaskPlan) -> MaskReport` (maps each `Replacement` through `doc_text.segments` into paragraph-relative positions, calls `replace_in_paragraph`; `w:fldSimple/@w:instr` attribute values masked with `flexible_pattern` of each replaced value; hyperlink relationships whose `Target` contains a replaced value (normalised) → `w:hyperlink` unwrapped to plain runs and the relationship removed); `insert_banner(pkg, text: str = BANNER_TEXT) -> None` (first body paragraph, italic, followed by an empty paragraph); `new_case_code(rng: random.Random | None = None) -> str`; `neutral_name(code: str, suffix: str | None = None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def plan_for(dt, value, ph): return MaskPlan([Replacement(m.start(), m.end(), ph) for m in re.finditer(re.escape(value), dt.text)])
def test_cross_run_replacement(corpus):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg); rep = apply_mask(pkg, dt, plan_for(dt, "Northwind Trading B.V.", "[COMPANY_1]"))
    t = extract_text(pkg).text; assert "Northwind Trading B.V." not in t and t.count("[COMPANY_1]") == rep.replaced >= 3
def test_formatting_of_first_run_kept(corpus):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg); apply_mask(pkg, dt, plan_for(dt, "Northwind Trading B.V.", "[COMPANY_1]"))
    r = pkg.xml("word/document.xml").xpath(".//w:r[w:t[contains(text(),'[COMPANY_1]')]]", namespaces=NS)[0]; assert r.find("w:rPr/w:b", NS) is not None   # the party name is bold in the parties clause
def test_header_footer_footnote(corpus):
    pkg = DocxPackage.open(corpus / "supply-06.docx"); dt = extract_text(pkg); apply_mask(pkg, dt, plan_for(dt, "Acme", "[COMPANY_2]"))
    for part in ("word/header1.xml", "word/footer1.xml", "word/footnotes.xml"): assert b"Acme" not in etree.tostring(pkg.xml(part))
def test_mailto_hyperlink_unwrapped(corpus):
    pkg = DocxPackage.open(corpus / "services-01.docx"); dt = extract_text(pkg); email = next(t["value"] for t in json.loads((corpus/"services-01.truth.json").read_text()) if t["type"] == "EMAIL")
    rep = apply_mask(pkg, dt, plan_for(dt, email, "[EMAIL_1]")); assert rep.hyperlinks_unwrapped >= 1 and email.encode() not in pkg.raw("word/_rels/document.xml.rels")
def test_banner_first(corpus):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); insert_banner(pkg); assert extract_text(pkg).text.startswith(BANNER_TEXT)
def test_names():
    code = new_case_code(random.Random(1)); assert len(code) == 4 and set(code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    assert neutral_name("K4F7") == "MASKED-K4F7.docx" and neutral_name("K4F7", "before") == "MASKED-K4F7-before.docx" and neutral_name("K4F7", "2") == "MASKED-K4F7-2.docx"
def test_numbering_intact(corpus, tmp_path):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg); apply_mask(pkg, dt, plan_for(dt, "Northwind Trading B.V.", "[COMPANY_1]")); pkg.save(tmp_path/"m.docx")
    import docx; d = docx.Document(str(tmp_path/"m.docx")); assert any(p.style.name.startswith("List") or p._p.pPr is not None and p._p.pPr.numPr is not None for p in d.paragraphs)
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: masker with cross-run replacement, hyperlink unwrapping and banner"`

---

