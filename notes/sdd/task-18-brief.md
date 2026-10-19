### Task 18: Restore

**Files:**
- Create: `src/themask/restore/__init__.py`, `src/themask/restore/matcher.py`, `src/themask/restore/text.py`, `src/themask/restore/docx_restore.py`, `src/themask/restore/report.py`
- Test: `tests/restore/test_matcher.py`, `tests/restore/test_text.py`, `tests/restore/test_docx_restore.py`

**Interfaces:**
- Consumes: `find_placeholders`, `Case`, `KeyEntry`, `DocxPackage`, `extract_text`, `replace_in_paragraph`, `BANNER_TEXT`.
- Produces (`report.py`): `@dataclass RestoreItem(match: PlaceholderMatch, entry: KeyEntry | None, status: Literal["exact","altered","unknown"])`; `@dataclass RestoreReport(restored: int, altered_restored: int, needs_check: list[RestoreItem], unknown: list[str], banner_removed: bool)` (`restored` counts every replacement made, exact and altered; `altered_restored` is the altered subset) with `summary() -> str` = `f"{restored} placeholders restored, {len(needs_check)} need your check."`.
- Produces (`matcher.py`): `plan_restore(text: str, case: Case) -> list[RestoreItem]`; `suggest_cases(text: str, cases: list[Case]) -> list[Case]` (ranked by number of the text's placeholders present in the case's entries, then newest `created_at`).
- Produces (`text.py`): `restore_text(text: str, case: Case, confirm_altered: bool) -> tuple[str, RestoreReport]` (exact always replaced; altered replaced only when `confirm_altered`, otherwise listed in `needs_check`; unknown left; a line equal to `BANNER_TEXT` removed).
- Produces (`docx_restore.py`): `restore_docx(src: Path, case: Case, confirm_altered: bool, out_dir: Path | None = None) -> tuple[Path, RestoreReport]` over `TEXT_PARTS` + `word/comments.xml`, replacing through `replace_in_paragraph` so the AI's formatting survives; output `<stem> – restored.docx` (` (2)` … if taken), `src` untouched.

- [ ] **Step 1: Write the failing tests**

```python
CASE = Case("K4F7", NOW, ["c.docx"], [], [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"]), KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme"]), KeyEntry("[AMOUNT_1]", PlaceholderType.AMOUNT, "EUR 1,250,000", [])])
def test_text_exact_and_altered():
    out, rep = restore_text("Dear [PERSON_1], [COMPANY_1]'s fee is **[AMOUNT_1]**. See [PERSON_9].", CASE, confirm_altered=False)
    assert out == "Dear John Smith, Acme Supplies Ltd's fee is **[AMOUNT_1]**. See [PERSON_9]." and rep.restored == 2 and len(rep.needs_check) == 1 and rep.unknown == ["[PERSON_9]"]
    out2, rep2 = restore_text("fee **[AMOUNT_1]** and PERSON_1", CASE, confirm_altered=True); assert out2 == "fee EUR 1,250,000 and John Smith" and rep2.altered_restored == 2 and rep2.summary() == "2 placeholders restored, 0 need your check."
def test_banner_removed(): out, rep = restore_text(BANNER_TEXT + "\n\nHello [PERSON_1]", CASE, True); assert out == "Hello John Smith" and rep.banner_removed
def test_suggest_cases():
    a = Case("A", NOW, [], [], CASE.entries[:2]); b = Case("B", NOW, [], [], CASE.entries[:1])
    assert [c.id for c in suggest_cases("[PERSON_1] and [COMPANY_1]", [b, a])] == ["A", "B"]
def test_docx_roundtrip(masked_case, tmp_path):            # fixture: supply-01 exported via Task 15 → (masked_path, case)
    masked, case = masked_case; ai = simulate_ai(masked, tmp_path / "ai.docx")   # tests/helpers.py, created here: alters one [PERSON_1] to "[PERSON 1]", adds a comment containing [COMPANY_1], makes [AMOUNT_1] bold, inserts [PERSON_9], copies the banner, splits a placeholder across two runs
    out, rep = restore_docx(ai, case, confirm_altered=True); text = extract_text(DocxPackage.open(out)).text
    for e in case.entries: assert e.value in text
    assert "[PERSON_9]" in text and rep.unknown == ["[PERSON_9]"] and rep.banner_removed and BANNER_TEXT not in text and out.name == "ai – restored.docx"
    assert b"[COMPANY_1]" not in DocxPackage.open(out).raw("word/comments.xml")
def test_docx_formatting_kept(masked_case, tmp_path):
    masked, case = masked_case; ai = simulate_ai(masked, tmp_path / "ai.docx"); out, _ = restore_docx(ai, case, True); amount = next(e.value for e in case.entries if e.placeholder == "[AMOUNT_1]")
    r = DocxPackage.open(out).xml("word/document.xml").xpath(f".//w:r[w:t[contains(text(),'{amount}')]]", namespaces=NS)[0]; assert r.find("w:rPr/w:b", NS) is not None
def test_never_overwrites(masked_case, tmp_path):
    masked, case = masked_case; ai = simulate_ai(masked, tmp_path / "ai.docx"); a, _ = restore_docx(ai, case, True); b, _ = restore_docx(ai, case, True); assert a != b and b.name == "ai – restored (2).docx"
def test_template_brackets_untouched():
    out, rep = restore_text("[Name] signs for [COMPANY_1] on [Date]", CASE, True); assert out == "[Name] signs for Acme Supplies Ltd on [Date]" and rep.unknown == []
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: restore placeholders into text and Word files with altered-form confirmation"`

---

