### Task 24: Pass marks and tuning

**Files:**
- Create: `tools/evaluate.py`, `tests/test_passmarks.py` (`@pytest.mark.slow`)
- Modify: detection modules as tuning requires (patterns, contract rules, grouping, never-hide list)

**Interfaces:**
- Produces: `evaluate(corpus_dir: Path, engine, user_lists) -> Evaluation` with `recall_pattern: float` (EMAIL, PHONE, IBAN, ID, AMOUNT, PERCENT, QUANTITY, URL truth items found before review — a truth item counts as found when every one of its occurrences, value and listed variants, lies inside an enabled group of any type), `recall_names: float` (PERSON, COMPANY, ADDRESS), `type_accuracy: float` (informational: share of found items whose group has the truth type), `never_hide_false_positives: list[str]` (enabled groups whose canonical is a never-hide term), `misses: list[tuple[str, str, str]]` (file, type, value), `seconds_thirty_pages: float`; CLI prints the §9 table.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.slow
def test_pass_marks(corpus, engine, lists):
    ev = evaluate(corpus, engine, lists); print(ev.misses)
    assert ev.recall_pattern >= 0.99 and ev.recall_names >= 0.95 and ev.never_hide_false_positives == []
@pytest.mark.slow
def test_thirty_pages_under_sixty_seconds(corpus, engine, lists):
    t0 = time.perf_counter(); srcs = load_sources([corpus / "supply-10.docx"], False); analyze(combined_text(srcs), engine, lists); assert time.perf_counter() - t0 < 60
@pytest.mark.slow
def test_full_round_trip_every_docx(corpus, engine, lists, tmp_path):   # mask → simulate AI → restore: 100 % exact restored, altered caught, 0 wrong substitutions
    for doc in (d for d in json.loads((corpus/"manifest.json").read_text()) if d["format"] == "docx"):
        srcs = load_sources([corpus / doc["file"]], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))
        res = export_case(srcs, review, ExportOptions(tmp_path / doc["file"]), engine, lists, lambda c: None); assert not res.blocked
        ai = simulate_ai(res.outputs[0], tmp_path / f"ai-{doc['file']}"); out, rep = restore_docx(ai, res.case, True); text = extract_text(DocxPackage.open(out)).text
        for e in res.case.entries: assert e.value in text, (doc["file"], e.placeholder)
        if "existing_placeholders" not in doc["features"]: assert {m.placeholder for m in find_placeholders(text)} == {"[PERSON_9]"}
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_passmarks.py -q -m slow -s` → expect FAIL on recall first time; the printed `misses` drive the tuning loop.
- [ ] **Step 3: Tune** — iterate on `patterns.py`, `contract_rules.py`, `grouping.py` and `DEFAULT_NEVER_HIDE` until Step 2 passes; every tuning change keeps the earlier unit tests green (`uv run pytest -q`).
- [ ] **Step 4: Run everything** — `uv run pytest -q -m "slow or not slow" && uv run ruff check src tests tools && uv run mypy src`. Expected: all pass; record the evaluation table in `docs/superpowers/plans/2026-10-17-the-mask-mac-v1.md` under a "Results" heading.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "test: enforce spec pass marks; tune detection"`

---

