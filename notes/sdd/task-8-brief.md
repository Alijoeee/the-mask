### Task 8: Lists, grouping, sweep and the analysis pipeline

**Files:**
- Create: `src/themask/detect/lists.py`, `src/themask/detect/grouping.py`, `src/themask/detect/sweep.py`, `src/themask/detect/pipeline.py`, `src/themask/paths.py`
- Test: `tests/detect/test_lists.py`, `tests/detect/test_grouping.py`, `tests/detect/test_pipeline.py`

**Interfaces:**
- Produces (`paths.py`): `data_dir() -> Path` (`platformdirs.user_data_dir("The MASK", appauthor=False)`, overridable by env `THEMASK_DATA_DIR` for tests), `cases_dir()`, `log_dir()`, `lists_path()`.
- Produces (`lists.py`): `DEFAULT_NEVER_HIDE: frozenset[str]` (roles, document words, legal vocabulary, months, weekdays, currency names/codes, countries and `England and Wales`, `European Union`); `class UserLists(always_hide: list[str], never_hide: list[str])` with `load(path) -> UserLists`, `save(path)`, `add_always(v)`, `add_never(v)`, `remove_*`; `@dataclass CaseLists(always_hide: list[str], never_hide: list[str], defined_terms: set[str])`; `is_never_hide(text: str, user: UserLists, case: CaseLists) -> bool` (case-insensitive equality, singular/plural, with/without leading `the`).
- Produces (`grouping.py`): `group_findings(findings: list[Finding], text: str) -> list[Group]`: key by `normalize(canonical)` per type; PERSON merge honorific-stripped equal names and `F. Last` ↔ `First Last` when exactly one full name has that surname+initial; a surname-only or honorific+surname mention (`Mr Smith`) merges only when exactly one full name has that surname, else becomes its own group with `needs_check=True`; COMPANY merge legal-form-stripped equal names and the first-token variant when unique; `needs_check=True` also when `max(score) < 0.7`. Canonical = longest variant (PERSON: longest containing a space). `placeholder` left empty.
- Produces (`sweep.py`): `sweep(text: str, groups: list[Group]) -> None` adds `Finding(source="sweep", score=1.0)` for every occurrence of any variant (`flexible_pattern`) not already covered by a finding of any group.
- Produces (`pipeline.py`): `@dataclass CombinedText(text: str, parts: list[tuple[str, int, int]])` with `CombinedText.join(named_texts: list[tuple[str, str]], separator="\n\f\n")` and `locate(offset) -> tuple[str, int]`; `analyze(combined: CombinedText, engine: Engine, user_lists: UserLists, case_lists: CaseLists | None = None) -> Analysis`: engine + `always_hide` matches (`source="list"`, type CUSTOM unless the list entry carries a type) → drop never-hide-equal findings (never when the finding is longer than the term) → resolve overlaps (longest span wins; equal length → precedence `IBAN EMAIL URL PHONE ID AMOUNT PERCENT QUANTITY PERSON COMPANY ADDRESS CUSTOM`) → group → number placeholders per type by first appearance starting at `next_free_number(text, type)` → sweep → `warnings`. Optional `seed_entries: list[KeyEntry] | None` (adding a file to an existing case, spec 8.9): each entry becomes a group with its placeholder fixed, its variants swept, and new groups are numbered after the highest seeded number per type (`"The document already contains placeholders such as [PERSON_1]; numbering continues after them."` when `next_free_number > 1` for any type).

- [ ] **Step 1: Write the failing tests**

```python
# test_grouping.py
P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY
def F(t, needle, txt, last=False, score=0.9):
    s = txt.rindex(needle) if last else txt.index(needle); return Finding(t, s, s + len(needle), needle, score, "model")
def test_variants_merge():
    txt = "John Smith … Mr Smith … J. Smith"; fs = [F(P, "John Smith", txt), F(P, "Mr Smith", txt), F(P, "J. Smith", txt)]
    g, = group_findings(fs, txt); assert g.canonical == "John Smith" and len(g.findings) == 3 and not g.needs_check
def test_shared_surname_not_merged():
    txt = "John Smith and Jane Smith … Mr Smith"; fs = [F(P, "John Smith", txt), F(P, "Jane Smith", txt), F(P, "Mr Smith", txt)]
    gs = group_findings(fs, txt); assert len(gs) == 3 and [g for g in gs if g.canonical == "Mr Smith"][0].needs_check
def test_company_suffix_merge():
    txt = "Acme Supplies Ltd … Acme Supplies … ACME"; fs = [F(C, "Acme Supplies Ltd", txt), F(C, "Acme Supplies", txt, last=True), F(C, "ACME", txt)]
    g, = group_findings(fs, txt); assert g.canonical == "Acme Supplies Ltd"
def test_low_score_needs_check():
    txt = "Riverside Partners"; g, = group_findings([F(C, "Riverside Partners", txt, score=0.6)], txt); assert g.needs_check
# test_pipeline.py (uses engine fixture)
def test_overlap_longest_wins(engine, lists):
    t = "Write to legal@northwind.example or https://northwind.example/contact?mail=legal@northwind.example"
    a = analyze(CombinedText.join([("x", t)]), engine, lists); spans = sorted((f.start, f.end) for g in a.groups for f in g.findings)
    assert all(b[0] >= a_[1] for a_, b in zip(spans, spans[1:]))
def test_never_hide_terms_stay(engine, lists):
    a = analyze(CombinedText.join([("x", "The Supplier shall deliver the Goods to the Buyer in March.")]), engine, lists); assert a.groups == []
def test_always_hide_list(engine, lists):
    lists.add_always("Project Falcon"); a = analyze(CombinedText.join([("x", "Project Falcon starts in May; PROJECT FALCON ends in June.")]), engine, lists)
    g, = a.groups; assert g.type == PlaceholderType.CUSTOM and len(g.findings) == 2 and g.placeholder == "[CUSTOM_1]"
def test_numbering_and_sweep(engine, lists):
    t = "Acme Supplies Ltd (the \"Buyer\")… Acme shall pay. Northwind Trading B.V. … Acme Supplies Ltd signs."
    a = analyze(CombinedText.join([("x", t)]), engine, lists); by = {g.canonical: g for g in a.groups}
    assert by["Acme Supplies Ltd"].placeholder == "[COMPANY_1]" and by["Northwind Trading B.V."].placeholder == "[COMPANY_2]" and len(by["Acme Supplies Ltd"].findings) == 3
def test_existing_placeholders_warning(engine, lists):
    a = analyze(CombinedText.join([("x", "[PERSON_1] met John Smith. [Name] signs.")]), engine, lists)
    g, = [g for g in a.groups if g.type == PlaceholderType.PERSON]; assert g.placeholder == "[PERSON_2]" and any("already contains placeholders" in w for w in a.warnings)
def test_combined_text_locate():
    c = CombinedText.join([("a.docx", "hello"), ("b.docx", "world")]); assert c.locate(0) == ("a.docx", 0) and c.locate(len("hello\n\f\n") + 2) == ("b.docx", 2)
def test_seed_entries_reuse_placeholders(engine, lists):
    seed = [KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme"]), KeyEntry("[COMPANY_2]", PlaceholderType.COMPANY, "Old Partner GmbH", [])]
    a = analyze(CombinedText.join([("annex", "Acme shall deliver to Baltic Fasteners GmbH.")]), engine, lists, seed_entries=seed); by = {g.canonical: g for g in a.groups}
    assert by["Acme Supplies Ltd"].placeholder == "[COMPANY_1]" and by["Baltic Fasteners GmbH"].placeholder == "[COMPANY_3]"
```
(`lists` fixture in `conftest.py`: `UserLists([], [])` saved under `data_dir`. From this task on an **autouse** fixture sets `THEMASK_DATA_DIR` to a fresh tmp dir for every test, so no test touches the real data folder or the Keychain.)

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement the five modules.** **Step 4: Run to verify pass**, lint, types.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: lists, variant grouping, sweep and analysis pipeline"`

---

