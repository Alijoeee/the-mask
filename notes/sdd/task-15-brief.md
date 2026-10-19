### Task 15: Export orchestration and case key

**Files:**
- Create: `src/themask/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: everything from Tasks 8–14, `CaseStore` (Task 17 — until then `export_case` takes a `save_case: Callable[[Case], None]`).
- Produces: `@dataclass SourceDoc(path: Path, kind: Literal["docx","pdf"], pkg: DocxPackage, text_after: DocText, text_before: DocText | None, has_revisions: bool, pdf_report: PdfReport | None)`; `load_sources(paths: list[Path], redline_split: bool) -> list[SourceDoc]` (PDFs go through Task 16 first; `text_before` only when `redline_split and has_revisions`); `combined_text(sources) -> CombinedText` (names `"<file> (after)"` / `"<file> (before)"`); `@dataclass ExportOptions(out_dir: Path, redline_split: bool = False, retention_days: int = 30, existing_case: Case | None = None)` (with `existing_case`: the review was built with `seed_entries=existing_case.entries`, the saved case keeps its id and code, entries are merged, outputs continue the numbering after the case's existing masked files); `@dataclass ExportResult(case: Case | None, outputs: list[Path], leak_hits: list[LeakHit], unmarked: list[Group], instruction: str, blocked: bool)`; `export_case(sources, review: ReviewState, options, engine, user_lists, save_case) -> ExportResult`: per source → copy pkg → (`reject_all` for before / `accept_all` for after) → `clean` → `apply_mask` with that document's slice of the plan → `insert_banner` → save to a temp file under a neutral name → `scan_package`; any hit → delete every temp output, `blocked=True`, nothing saved; else move outputs into `out_dir`, `rescan_detection` for the `unmarked` list, build `Case` (`entries = review.key_entries()`, `masked_files` with sha256), `save_case(case)`, `instruction = AI_INSTRUCTION`. Multi-file numbering: single file `MASKED-CODE.docx`; several → `-1`, `-2`…; redline → `-before`/`-after` (with `-1-before` when several).

- [ ] **Step 1: Write the failing tests**

```python
def test_export_single(corpus, engine, lists, tmp_path):
    srcs = load_sources([corpus / "supply-01.docx"], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
    saved = []; res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, saved.append)
    assert not res.blocked and res.leak_hits == [] and len(res.outputs) == 1 and re.fullmatch(r"MASKED-[A-Z2-9]{4}\.docx", res.outputs[0].name) and saved[0].entries == review.key_entries()
def test_truth_values_absent_everywhere(corpus, engine, lists, tmp_path):
    srcs = load_sources([corpus / "supply-01.docx"], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None); blob = normalize("".join(zipfile.ZipFile(res.outputs[0]).read(n).decode("utf-8","ignore") for n in zipfile.ZipFile(res.outputs[0]).namelist()))
    for t in json.loads((corpus/"supply-01.truth.json").read_text()): assert normalize(t["value"]) not in blob, t
def test_annex_shares_placeholders(corpus, engine, lists, tmp_path):
    srcs = load_sources([corpus / "supply-07.docx", corpus / "supply-07-annex.docx"], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None); texts = [extract_text(DocxPackage.open(p)).text for p in res.outputs]
    assert [p.name[-7:] for p in res.outputs] == ["-1.docx", "-2.docx"] and "[COMPANY_1]" in texts[0] and "[COMPANY_1]" in texts[1]
def test_redline_split(corpus, engine, lists, tmp_path):
    srcs = load_sources([corpus / "supply-03.docx"], True); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
    res = export_case(srcs, review, ExportOptions(tmp_path, redline_split=True), engine, lists, lambda c: None)
    assert {p.name.rsplit("-", 1)[1] for p in res.outputs} == {"before.docx", "after.docx"}
    deleted = next(t["value"] for t in json.loads((corpus/"supply-03.truth.json").read_text()) if t.get("only_in_deletion")); assert all(normalize(deleted) not in normalize(extract_text(DocxPackage.open(p)).text) for p in res.outputs)
def test_nothing_marked_still_exports_and_reports_unmarked(corpus, engine, lists, tmp_path):
    srcs = load_sources([corpus / "supply-01.docx"], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
    for g in review.groups: review.set_group_enabled(g.id, False)
    res = export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None); assert not res.blocked and res.outputs and res.unmarked   # nothing marked → nothing to leak; rescan reports what the owner skipped
def test_original_unchanged(corpus, engine, lists, tmp_path):
    src = corpus / "supply-01.docx"; before = src.read_bytes(); srcs = load_sources([src], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
    export_case(srcs, review, ExportOptions(tmp_path), engine, lists, lambda c: None); assert src.read_bytes() == before
def test_add_file_to_existing_case(corpus, engine, lists, tmp_path):
    first = load_sources([corpus / "supply-07.docx"], False); r1 = ReviewState.from_analysis(analyze(combined_text(first), engine, lists), lists, CaseLists([], [], set()))
    saved = []; res1 = export_case(first, r1, ExportOptions(tmp_path), engine, lists, saved.append); case = saved[0]
    annex = load_sources([corpus / "supply-07-annex.docx"], False); r2 = ReviewState.from_analysis(analyze(combined_text(annex), engine, lists, seed_entries=case.entries), lists, CaseLists([], [], set()))
    res2 = export_case(annex, r2, ExportOptions(tmp_path, existing_case=case), engine, lists, saved.append)
    assert saved[1].id == case.id and len(saved[1].entries) >= len(case.entries) and res2.outputs[0].name == f"MASKED-{case.id}-2.docx" and "[COMPANY_1]" in extract_text(DocxPackage.open(res2.outputs[0])).text
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: export pipeline with leak-check gate, multi-file and redline cases"`

---

