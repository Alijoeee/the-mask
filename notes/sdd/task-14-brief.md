### Task 14: Leak check

**Files:**
- Create: `src/themask/leakcheck.py`
- Test: `tests/test_leakcheck.py`

**Interfaces:**
- Consumes: `KeyEntry`, `normalize`, `Engine`, `analyze`.
- Produces: `@dataclass LeakHit(part: str, placeholder: str, context: str)` (`context` never contains the value: the value is replaced by its placeholder in the ~40-char window); `scan_package(path: Path, entries: list[KeyEntry]) -> list[LeakHit]` — for every zip entry (decoded `utf-8` with `errors="ignore"`), the file name, and every entry name: normalised search for `normalize(value)` and each `normalize(variant)` (variants shorter than 4 normalised chars skipped); `rescan_detection(path: Path, engine, user_lists) -> list[Group]` — Task 10 text of the masked file through `analyze`, returning groups whose canonical is not a placeholder and not in the entries' variants (candidates the owner never marked).

- [ ] **Step 1: Write the failing tests**

```python
E = [KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Northwind Trading B.V.", ["Northwind Trading", "Northwind"]), KeyEntry("[IBAN_1]", PlaceholderType.IBAN, "NL91 ABNA 0417 1643 00", [])]
def test_clean_file_has_no_hits(masked_docx): assert scan_package(masked_docx, E) == []
def test_planted_in_header_rels_and_props(masked_docx, tmp_path):
    for part, payload in [("word/header1.xml", b"<w:t>northwind</w:t>"), ("word/_rels/document.xml.rels", b'Target="mailto:x@northwind.example"'), ("docProps/core.xml", b"<dc:creator>NL91ABNA0417164300</dc:creator>")]:
        p = plant(masked_docx, part, payload, tmp_path / f"{part.replace('/','_')}.docx"); hits = scan_package(p, E); assert hits and hits[0].part == part and "Northwind" not in hits[0].context and "NL91" not in hits[0].context
def test_spacing_case_punct_variants(masked_docx, tmp_path):
    p = plant(masked_docx, "word/document.xml", "<w:t>1.250.000</w:t>".encode(), tmp_path / "v.docx"); assert scan_package(p, [KeyEntry("[AMOUNT_1]", PlaceholderType.AMOUNT, "1,250,000", [])])
def test_file_name_is_checked(tmp_path, masked_docx):
    p = tmp_path / "Northwind-contract.docx"; p.write_bytes(masked_docx.read_bytes()); assert any(h.part == "<file name>" for h in scan_package(p, E))
def test_rescan_finds_unmarked(engine, lists, tmp_path, masked_docx):
    p = plant(masked_docx, "word/document.xml", b"<w:t>Signed: Dr Jane Smith</w:t>", tmp_path / "u.docx"); assert any(g.type == PlaceholderType.PERSON for g in rescan_detection(p, engine, lists))
```
(`masked_docx` fixture: `supply-01.docx` → `accept_all` → `clean` → `apply_mask` with the two entries → saved. `plant(src, part, payload, out)` lives in `tests/helpers.py`, created here: it copies the zip and appends `payload` just before the closing tag of that part.)

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: leak check over every package part, name and variant"`

---

