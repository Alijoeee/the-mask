# The MASK — Mac Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build The MASK for macOS: a desktop app that finds personal data and business secrets in Word/PDF contracts, replaces them with `[TYPE_N]` placeholders behind a mandatory review, writes a leak-checked masked Word copy, keeps the key encrypted on the Mac, and restores the real values into the Word file an AI tool gives back.

**Architecture:** A pure-Python core (`themask`) does everything testable without a screen: detection (Presidio + spaCy + contract rules), Word XML surgery (accept/reject revisions, clean, mask, restore), PDF-to-Word extraction, the leak check, and the encrypted case store. A thin PySide6 layer (`themask.ui`) renders four screens over that core and runs detection in a worker thread. Briefcase wraps the whole thing into `The MASK.app`, ad-hoc signed, no installer.

**Tech Stack:** Python 3.12 · uv · PySide6-Essentials 6.12 (LGPL) · presidio-analyzer 2.2.364 · spaCy 3.8 + en_core_web_md 3.8.0 · python-docx 1.2 + lxml 6 · pdfplumber 0.11 · cryptography 50 · keyring 25 · schwifty · python-stdnum · rapidfuzz · platformdirs · pytest + pytest-qt · Faker + reportlab + Pillow (test corpus only) · Briefcase 0.4.6 (BSD).

**Spec:** `docs/superpowers/specs/2026-10-17-the-mask-design.md` (moved into the repo in Task 1). The spec's Windows phase (8.10 Windows, 8.11 IT pack, 8.12 step 2) is **not** in this plan; it gets its own plan once Bunzl IT has answered section 14.

## Global Constraints

- **Repository location:** `~/Developer/the-mask`, not the iCloud-synced Desktop (Briefcase cannot build inside iCloud folders, and a 1 GB virtualenv must not sync). Task 1 moves the spec there and leaves a pointer in `~/Desktop/Claude Projects/the-mask/README.md`.
- **Python 3.12.x** (`.python-version` = `3.12`), managed with `uv`. All commands below run as `uv run …` from the repo root.
- **No network, ever.** No code path may open a socket; Task 19 installs a socket guard at startup, and no dependency may need the network at runtime (spaCy model bundled as a pinned wheel; `tldextract` forced to its bundled snapshot).
- **Licences:** permissive (MIT/BSD/Apache-2.0/MPL for dev tools) or LGPL used as a library. No GPL/AGPL anywhere in the installed environment (so: no PyInstaller, no Nuitka, no PyMuPDF; Qt modules limited to QtCore/QtGui/QtWidgets). Task 1 adds a test that fails on any GPL/AGPL distribution.
- **Placeholder format:** `[TYPE_N]`, types exactly `PERSON, COMPANY, AMOUNT, PERCENT, QUANTITY, EMAIL, PHONE, ADDRESS, IBAN, ID, URL, CUSTOM`; numbering per type, in order of first appearance.
- **Visible by default:** defined terms (Buyer, Supplier, Party, Agreement, Schedule…), clause numbers and headings, dates, durations and notice periods, governing-law jurisdictions.
- **Exact copy, verbatim from the spec:**
  - Banner (top of every masked file): `Confidential values in this document are replaced by placeholders such as [COMPANY_1]. Keep them unchanged.`
  - Image note: `[image removed]`; embedded object note: `[embedded object removed]` (designer's call).
  - AI instruction (8.8): `This document uses placeholders such as [PERSON_1] and [AMOUNT_2] instead of confidential values. Keep every placeholder exactly as written, including the square brackets, in your answer and in any file you create. Do not guess the real values. Please give your result as a Word (.docx) file.`
  - Restore report: `{n} placeholders restored, {m} need your check.`
  - Masked file name: `MASKED-<CODE>.docx`, `<CODE>` = 4 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`; multi-file `MASKED-<CODE>-1.docx`, `-2`…; redline `MASKED-<CODE>-before.docx` / `-after.docx`. Restored file: `<original stem> – restored.docx`, never overwriting (append ` (2)`, ` (3)`…).
- **Originals are never modified.** Every writer works on a copy in memory or a new path.
- **The log never contains document content**: counts, types, durations and file sizes only.
- **Key storage:** AES-256-GCM; master key in macOS Keychain (service `The MASK`, account `master-key`); default retention 30 days.
- **Pass marks (spec §9)** are enforced by `tests/test_passmarks.py` (Task 24) and must pass before Task 25.
- **Commits:** Conventional Commits, one per task step that says "Commit"; each message ends with the attribution trailer this session requires (`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`).
- **Progress reporting (owner's request):** the implementer updates the session scratchpad file `ilerleme/the-mask-build.json` (`{"ad":"The MASK build","yuzde":<task_no/26*100>,"adim":"Task N: <name>"}`) when starting each task, and every subagent writes its own `ilerleme/<its description>.json`. See memory note `progress-mod-isler`.
- **Test data:** made-up documents only (Task 4/5 corpus). Never a real contract.

## Review Focus

Inputs the spec implies but names no test for, most likely to bite first. Each gets a test in the task named.

1. **A ".docx" that is really an old binary .doc, an encrypted file, or a corrupt zip** → a clear message naming the problem ("save it as .docx" / "provide an unprotected copy"), never a stack trace. → Task 10.
2. **Numbers as Word types them: non-breaking or thin spaces as separators (`EUR 1 250 000,00`, `1 250 000`)** → detected as AMOUNT, and the leak check treats `1,250,000`, `1.250.000` and `1 250 000` as the same value. → Tasks 3 and 6.
3. **Two different people sharing a surname (`John Smith`, `Jane Smith`, then `Mr Smith`)** → `Mr Smith` is never silently merged into either group; it becomes its own group flagged "check". → Task 8.
4. **Overlapping finds (an e-mail inside a URL, an IBAN inside an "Account:" line, a company name containing a person's surname)** → one replacement, longest span wins, never nested brackets like `[COMPANY_1[PERSON_2]]`. → Task 8, re-checked by the leak check in Task 14.
5. **Input that already contains placeholder-like tokens (`[PERSON_1]` from an earlier masked copy, template fields like `[Name]`)** → numbering continues after the highest existing number, the review shows a warning, and restore leaves tokens that are not in the key untouched. → Tasks 8 and 18.

---

## File Structure

```
~/Developer/the-mask/
  pyproject.toml            project, deps (pinned), dependency-groups.dev, ruff, mypy, pytest, [tool.briefcase]
  .python-version           3.12
  .gitignore                .venv/ build/ dist/ tests/corpus/generated/ *.log
  README.md                 what it is, how to run from source, how to install the .app
  docs/superpowers/specs/   the design (moved from Desktop)
  docs/superpowers/plans/   this plan
  packaging/icon/           themask.icns (+ 1024px PNG source)
  src/themask/
    __init__.py             __version__
    __main__.py             entry: install_network_guard() → setup_logging() → ui.app.main()
    about.py                APP_NAME = "The MASK", OWNER_NAME (owner fills in), VERSION
    model.py                PlaceholderType, Finding, Group, Analysis, Replacement, MaskPlan, KeyEntry, MaskedFile, Case (+ JSON (de)serialisation)
    placeholders.py         format_placeholder, PLACEHOLDER_RE, PlaceholderMatch, find_placeholders (exact + altered), next_free_number
    textnorm.py             normalize, variants_of, flexible_pattern
    instruction.py          AI_INSTRUCTION, BANNER_TEXT, IMAGE_NOTE, OBJECT_NOTE
    paths.py                data_dir, cases_dir, log_dir, lists_path
    logging_setup.py        rotating file log, content-free
    netguard.py             install_network_guard, NetworkBlockedError
    errors.py               MaskError, UnsupportedFileError, ProtectedFileError, ScannedPdfError, CaseCorruptError, LeakBlockedError
    detect/
      engine.py             Engine: Presidio AnalyzerEngine over spaCy en_core_web_md + our recognizers → list[Finding]
      patterns.py           AMOUNT, PERCENT, QUANTITY, VAT/registration/ID, account/BIC, bare-number recognizers (Presidio PatternRecognizer subclasses)
      contract_rules.py     parties clause, legal-form suffixes, signature blocks, Attention/Address lines, registered-office phrases, defined terms
      lists.py              DEFAULT_NEVER_HIDE, UserLists (global JSON), CaseLists
      grouping.py           group_findings: variants → Group, canonical form, ambiguity flag
      sweep.py              sweep: every other occurrence of each group's variants
      pipeline.py           analyze(texts…) → Analysis (overlap resolution, numbering, warnings)
    review.py               ReviewState: enable/disable, hide_text, merge/split, lists, mask_plan, key_entries
    docx/
      package.py            DocxPackage: zip in memory, lxml parts, rels, content types, remove_part, save
      reader.py             TextNode map per paragraph, extract_text(view) → DocText, has_revisions, has_comments
      revisions.py          accept_all, reject_all
      cleaner.py            clean → CleanReport
      masker.py             apply_mask, insert_banner, neutral_name, new_case_code
      restorer.py           replace_placeholders (shared by restore)
    pdf/
      extractor.py          extract_blocks → list[Block], PdfReport (image-only pages, repeated lines)
      to_docx.py            pdf_to_docx
    leakcheck.py            scan_package, rescan_detection, LeakHit
    export.py               CombinedText, load_sources, export_case → ExportResult
    keystore/
      crypto.py             encrypt/decrypt (AES-256-GCM)
      secrets.py            KeyStore protocol, KeychainKeyStore, MemoryKeyStore
      cases.py              CaseStore: save/load/list/delete/delete_all/purge_expired
    restore/
      matcher.py            plan_restore, suggest_cases
      text.py               restore_text
      docx_restore.py       restore_docx
      report.py             RestoreReport
    ui/
      app.py                main(), QApplication, theme
      main_window.py        QStackedWidget: Home, Review, Export, Restore, Cases, Settings
      drop_zone.py          drag-and-drop + file picker
      workers.py            AnalysisWorker(QThread) with progress
      review_screen.py      highlighted text + grouped list + actions
      export_dialog.py      redline offer, leak result, outputs, Copy instruction
      restore_screen.py     drop AI .docx / paste box, case picker, confirm altered, report
      cases_screen.py       list, delete, delete all
      settings_screen.py    always/never lists, retention days, About (OWNER_NAME)
  tools/
    make_corpus.py          deterministic made-up contracts: .docx, .pdf, truth JSON, manifest
    evaluate.py             recall/precision per class against truth, prints the §9 table
  tests/                    mirrors src; conftest.py (engine, corpus, keystore, data_dir, offscreen Qt)
```

---

### Task 1: Repository, toolchain, licence gate

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`, `src/themask/__init__.py`, `src/themask/about.py`, `src/themask/errors.py`, `tests/conftest.py`, `tests/test_licences.py`, `tests/test_about.py`
- Move: `~/Desktop/Claude Projects/the-mask/docs/` → `~/Developer/the-mask/docs/`; create pointer `~/Desktop/Claude Projects/the-mask/README.md` ("The code lives in ~/Developer/the-mask")

**Interfaces:**
- Produces: `about.APP_NAME = "The MASK"`, `about.OWNER_NAME: str` (placeholder `"<owner name — set in about.py>"`), `about.VERSION = "0.1.0"`; `errors.MaskError(Exception)` base with `user_message: str`, subclasses `UnsupportedFileError`, `ProtectedFileError`, `ScannedPdfError`, `CaseCorruptError`, `LeakBlockedError`.
- Produces: `conftest.py` fixtures `data_dir` (tmp path) and the env `QT_QPA_PLATFORM=offscreen` set at import.

- [ ] **Step 1: Create the repo and move the docs**

```bash
mkdir -p ~/Developer/the-mask && mv "$HOME/Desktop/Claude Projects/the-mask/docs" ~/Developer/the-mask/ && printf '# The MASK\n\nThe code lives in `~/Developer/the-mask` (outside iCloud).\n' > "$HOME/Desktop/Claude Projects/the-mask/README.md" && cd ~/Developer/the-mask && git init -b main
```

- [ ] **Step 2: Write `pyproject.toml`**

`[project]` name `the-mask`, package `themask` (src layout; `[build-system] requires = ["hatchling"]`, `[tool.hatch.build.targets.wheel] packages = ["src/themask"]`), `requires-python = ">=3.12,<3.13"`. Dependencies pinned exactly: `PySide6-Essentials==6.12.0`, `presidio-analyzer==2.2.364`, `spacy==3.8.16`, `en_core_web_md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl`, `python-docx==1.2.0`, `lxml==6.1.3`, `pdfplumber==0.11.10`, `cryptography==50.0.2`, `keyring==25.7.0`, `schwifty==2026.7.3`, `python-stdnum==2.2`, `phonenumbers==9.0.41`, `rapidfuzz==3.14.6`, `platformdirs==4.13.4`, `tldextract==5.4.0`. Dev group: `pytest==9.1.1`, `pytest-qt==4.5.0`, `Faker==40.43.0`, `reportlab==5.0.1`, `pillow==13.0.0`, `ruff==0.17.1`, `mypy==2.4.0`, `briefcase==0.4.6`. `[tool.pytest.ini_options] testpaths=["tests"]`, markers `slow`; `[tool.ruff] line-length=100`; `[tool.mypy] ignore_missing_imports=true, strict=true` on `src`. Leave `[tool.briefcase]` for Task 25.

- [ ] **Step 3: Write the failing licence test**

```python
# tests/test_licences.py
from importlib.metadata import distributions
ACCEPT = ("MIT", "BSD", "Apache", "LGPL", "MPL", "PSF", "Python Software Foundation", "ISC", "Unlicense", "Zlib", "HPND", "MIT-CMU", "CNRI")
def licence_of(dist) -> str:
    md = dist.metadata
    expr = md.get("License-Expression") or md.get("License") or ""
    cls = "; ".join(c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::"))
    return f"{expr}; {cls}"
def acceptable(text: str) -> bool:
    alternatives = [a.strip() for a in text.replace(";", " OR ").split(" OR ")]
    return any(any(ok.lower() in a.lower() for ok in ACCEPT) and "AGPL" not in a for a in alternatives)
def test_no_gpl_or_agpl_in_environment():
    bad = [f"{d.metadata['Name']}: {licence_of(d)}" for d in distributions()
           if ("GPL" in licence_of(d).upper() and not acceptable(licence_of(d)))]
    assert bad == []
```
Also `tests/test_about.py`: `APP_NAME == "The MASK"`, `VERSION == "0.1.0"`, `issubclass(LeakBlockedError, MaskError)`.

- [ ] **Step 4: Install and run; expect failure**

Run: `cd ~/Developer/the-mask && uv sync && uv run pytest -q`
Expected: FAIL (`ModuleNotFoundError: themask`) — and note the printout of `uv sync` shows the spaCy model wheel downloaded once.

- [ ] **Step 5: Create `src/themask/__init__.py`, `about.py`, `errors.py`, `tests/conftest.py`**

`conftest.py`: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at top; fixture `data_dir(tmp_path) -> Path`.

- [ ] **Step 6: Run tests, lint, types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all pass; the licence test passes (PySide6's `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` is accepted through its LGPL alternative).

- [ ] **Step 7: Write `README.md` (run from source: `uv run python -m themask`) and commit**

```bash
git add -A && git commit -m "chore: scaffold The MASK repo with pinned toolchain and licence gate"
```

---

### Task 2: Data model and placeholder grammar

**Files:**
- Create: `src/themask/model.py`, `src/themask/placeholders.py`, `src/themask/instruction.py`
- Test: `tests/test_model.py`, `tests/test_placeholders.py`

**Interfaces:**
- Produces (`model.py`): `class PlaceholderType(StrEnum)` with the 12 types; `@dataclass(frozen=True) Finding(type, start, end, text, score: float, source: Literal["pattern","model","rule","list","sweep","user"])`; `@dataclass Group(id: str, type, canonical: str, variants: set[str], findings: list[Finding], placeholder: str, enabled: bool = True, needs_check: bool = False, disabled: set[int] = field(default_factory=set))` with `active_findings() -> list[Finding]`; `@dataclass Analysis(text: str, groups: list[Group], warnings: list[str])`; `@dataclass(frozen=True) Replacement(start, end, placeholder)`; `@dataclass MaskPlan(replacements: list[Replacement])` sorted, non-overlapping (validated in `__post_init__`, raises `ValueError`); `@dataclass KeyEntry(placeholder, type, value, variants: list[str])`; `@dataclass MaskedFile(name, sha256)`; `@dataclass Case(id, created_at: datetime, source_files: list[str], masked_files: list[MaskedFile], entries: list[KeyEntry], retention_days: int = 30)` with `expires_at`, `to_json() -> str`, `Case.from_json(s)`.
- Produces (`placeholders.py`): `format_placeholder(t: PlaceholderType, n: int) -> str`; `PLACEHOLDER_RE: re.Pattern[str]` (exact form); `@dataclass(frozen=True) PlaceholderMatch(start, end, raw: str, placeholder: str, exact: bool)`; `find_placeholders(text: str) -> list[PlaceholderMatch]`; `next_free_number(text: str, t: PlaceholderType) -> int`.
- Produces (`instruction.py`): `AI_INSTRUCTION`, `BANNER_TEXT`, `IMAGE_NOTE`, `OBJECT_NOTE` — the exact strings from Global Constraints.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_placeholders.py
def test_format(): assert format_placeholder(PlaceholderType.PERSON, 1) == "[PERSON_1]"
@pytest.mark.parametrize("raw", ["[PERSON_1]"])
def test_exact(raw):
    m, = find_placeholders(f"Dear {raw},"); assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", True, raw)
@pytest.mark.parametrize("raw", ["PERSON_1", "[PERSON 1]", "[person_1]", r"\[PERSON_1\]", "**[PERSON_1]**", "__[PERSON_1]__", "`[PERSON_1]`", "[PERSON-1]", "[PERSON_01]", "[ PERSON_1 ]", "［PERSON_1］"])
def test_altered(raw):
    m, = find_placeholders(f"Dear {raw},"); assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", False, raw)
def test_not_a_placeholder(): assert find_placeholders("[Name] and [Date] and PERSONAL_1 and [TOTAL_3]") == []
def test_next_free(): assert next_free_number("[PERSON_2] [PERSON_7] [COMPANY_1]", PlaceholderType.PERSON) == 8
def test_next_free_empty(): assert next_free_number("nothing", PlaceholderType.PERSON) == 1
```
```python
# tests/test_model.py
def test_maskplan_rejects_overlap():
    with pytest.raises(ValueError): MaskPlan([Replacement(0, 5, "[A_1]"), Replacement(3, 8, "[B_1]")])
def test_case_json_roundtrip():
    c = Case("K4F7", datetime(2026, 10, 17, tzinfo=UTC), ["a.docx"], [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
             [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"])])
    assert Case.from_json(c.to_json()) == c and c.expires_at == c.created_at + timedelta(days=30)
def test_instruction_text_exact():
    assert AI_INSTRUCTION.startswith("This document uses placeholders such as [PERSON_1] and [AMOUNT_2]") and AI_INSTRUCTION.endswith("Word (.docx) file.")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_placeholders.py tests/test_model.py -q` → FAIL (import errors).

- [ ] **Step 3: Implement `model.py`, `placeholders.py`, `instruction.py`**

`find_placeholders`: one compiled regex over an optional marker prefix (`\*\*|__|`|\\`), optional `[`/`［`, optional spaces, type name (case-insensitive, from the enum), separator `[_ -]`, digits, optional spaces, optional `]`/`］`/`\]`, matching marker suffix; `exact` is true only for `[TYPE_N]` with upper-case type, underscore, no leading zero, no markers. Whole-word check (`(?<![A-Za-z0-9])` … `(?![A-Za-z0-9])`) so `PERSONAL_1` is not matched.

- [ ] **Step 4: Run to verify pass** — same command → PASS; `uv run ruff check src tests && uv run mypy src` clean.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: data model, placeholder grammar and fixed copy"`

---

### Task 3: Text normalisation and variants

**Files:**
- Create: `src/themask/textnorm.py`
- Test: `tests/test_textnorm.py`

**Interfaces:**
- Produces: `normalize(s: str) -> str` (NFKC → casefold → drop every Unicode whitespace incl. `     ` → drop punctuation `.,;:'"’‘“”()[]{}/\-_–—` → keep letters and digits); `variants_of(value: str, t: PlaceholderType) -> set[str]` (always includes `value`); `flexible_pattern(value: str) -> re.Pattern[str]` (case-insensitive; any run of whitespace in `value` matches `\s+`; word boundaries at alphanumeric ends).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("a,b", [("1,250,000", "1.250.000"), ("EUR 1 250 000,00", "eur 1.250.000,00"), ("NL91 ABNA 0417 1643 00", "NL91ABNA0417164300"), ("John  Smith", "john smith"), ("Acme Supplies Ltd.", "ACME SUPPLIES LTD")])
def test_normalize_equal(a, b): assert normalize(a) == normalize(b)
def test_normalize_keeps_digits_and_letters(): assert normalize("K4-F7 x") == "k4f7x"
def test_person_variants():
    v = variants_of("Mr John Smith", PlaceholderType.PERSON); assert {"Mr John Smith", "John Smith", "J. Smith"} <= v and "Smith" not in v
def test_company_variants():
    v = variants_of("Northwind Trading B.V.", PlaceholderType.COMPANY); assert {"Northwind Trading", "Northwind"} <= v
def test_company_first_word_not_common():
    assert "General" not in variants_of("General Supplies Ltd", PlaceholderType.COMPANY)
def test_amount_variants(): assert "1,250,000" in variants_of("EUR 1,250,000.00", PlaceholderType.AMOUNT)
def test_phone_variants(): assert "020 123 4567" in variants_of("+31 20 123 4567", PlaceholderType.PHONE)
def test_url_variants(): assert {"northwind.example", "www.northwind.example"} <= variants_of("https://www.northwind.example", PlaceholderType.URL)
def test_flexible_pattern(): assert flexible_pattern("John Smith").search("JOHN\n  smith") and not flexible_pattern("Smith").search("Smithson")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_textnorm.py -q` → FAIL.

- [ ] **Step 3: Implement `textnorm.py`**

Variant rules: PERSON — strip honorifics (`Mr Mrs Ms Mx Dr Prof Sir Dame Mevr Dhr Herr Frau`), add `F. Last` initial form, never surname alone. COMPANY — strip one trailing legal-form token (list shared with Task 7 via a module constant `LEGAL_FORMS`), add first token alone only if ≥ 4 letters and not in a small `COMMON_WORDS` stoplist (General, International, Global, European, National, United, Services, Group, Holdings, Trading, Supplies…). AMOUNT — the bare number, number without decimals, with/without currency. PHONE — national format via `phonenumbers` when parseable. URL — without scheme, without `www.`. Others — the value only (normalise handles spacing/case).

- [ ] **Step 4: Run to verify pass**, lint, types. **Step 5: Commit** — `git commit -am "feat: text normalisation and value variants"` (after `git add`).

---

### Task 4: Made-up contract corpus (Word) with ground truth

**Files:**
- Create: `tools/make_corpus.py`, `tests/corpus/__init__.py`, `tests/corpus/README.md`, `tests/test_corpus.py`
- Modify: `tests/conftest.py` (add `corpus` fixture), `.gitignore` (`tests/corpus/generated/`)

**Interfaces:**
- Produces (`tools/make_corpus.py`, importable as `tools.make_corpus`): `@dataclass TruthItem(type: PlaceholderType, value: str, variants: list[str])`; `@dataclass ContractSpec(kind: Literal["supply","services","nda","dpa"], seed: int, features: frozenset[str], truth: list[TruthItem], defined_terms: list[str], …)`; `build_spec(seed: int, kind: str, features: frozenset[str]) -> ContractSpec`; `write_docx(spec, path: Path) -> None`; `write_truth(spec, path: Path) -> None` (JSON list of TruthItem); `generate(out_dir: Path) -> list[dict]` writing 20 `.docx` + 20 `.truth.json` + `manifest.json`; CLI `python -m tools.make_corpus <out_dir>`.
- Features (each used by ≥ 3 documents, all 20 have `header_footer` and `table`): `comments`, `tracked_changes`, `secret_only_in_deletion`, `image`, `footnotes`, `hidden_text`, `textbox`, `properties`, `hyperlinks`, `shared_surname`, `existing_placeholders`, `nbsp_numbers`, `annex` (a second file in the same case), `thirty_pages`. In every document the party names in the parties clause are **bold and split across three runs** (as Word often saves them).
- Fixed assignments later tasks rely on: `supply-01` baseline; `supply-02` comments; `supply-03` tracked_changes + secret_only_in_deletion (truth item carries `"only_in_deletion": true`); `supply-04` properties (+ custom.xml); `supply-05` image (logo); `supply-06` footnotes + "Acme" in header and footer; `supply-07` + `supply-07-annex.docx` (annex); `supply-08` shared_surname + the phrase "Project Falcon" twice; `supply-09` existing_placeholders; `supply-10` thirty_pages; `services-01` hyperlinks (a `mailto:` link); `services-02` hidden_text (truth item carries `"hidden": true`); `services-03` textbox containing "Text box note"; `services-04` nbsp_numbers. The remaining documents (`services-05`, `nda-01…05`, `dpa-01…05`) mix the features freely.
- Produces fixture `corpus(tmp_path_factory) -> Path` (session scope, generated once per run).

- [ ] **Step 1: Write the failing tests**

```python
def test_corpus_counts(corpus):
    assert len(list(corpus.glob("*.docx"))) >= 20 and len(list(corpus.glob("*.truth.json"))) >= 20
def test_truth_covers_every_type(corpus):
    types = {t["type"] for p in corpus.glob("*.truth.json") for t in json.loads(p.read_text())}
    assert {"PERSON","COMPANY","AMOUNT","PERCENT","QUANTITY","EMAIL","PHONE","ADDRESS","IBAN","ID","URL"} <= types
def test_features_are_real(corpus):
    man = json.loads((corpus / "manifest.json").read_text())
    for doc in man:
        names = set(zipfile.ZipFile(corpus / doc["file"]).namelist()); xml = zipfile.ZipFile(corpus / doc["file"]).read("word/document.xml").decode()
        if "comments" in doc["features"]: assert "word/comments.xml" in names
        if "tracked_changes" in doc["features"]: assert "<w:ins " in xml and "<w:del " in xml
        if "image" in doc["features"]: assert any(n.startswith("word/media/") for n in names)
        if "properties" in doc["features"]: assert "<dc:creator>" in zipfile.ZipFile(corpus / doc["file"]).read("docProps/core.xml").decode()
def test_every_truth_value_is_in_the_file(corpus):
    for p in corpus.glob("*.truth.json"):
        blob = normalize("".join(zipfile.ZipFile(p.with_suffix("").with_suffix(".docx")).read(n).decode("utf-8","ignore") for n in zipfile.ZipFile(p.with_suffix("").with_suffix(".docx")).namelist() if n.endswith(".xml")))
        for t in json.loads(p.read_text()): assert normalize(t["value"]) in blob, (p.name, t["value"])
def test_deterministic(tmp_path):
    a = generate(tmp_path / "a"); b = generate(tmp_path / "b"); assert a == b and (tmp_path/"a"/"supply-01.truth.json").read_bytes() == (tmp_path/"b"/"supply-01.truth.json").read_bytes()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_corpus.py -q` → FAIL.

- [ ] **Step 3: Implement `tools/make_corpus.py`**

`Faker("en_GB")` and `random.Random(seed)`, seeded per document. Each contract: title, parties clause (`BETWEEN: (1) <Company A>, a company registered in <country> under number <reg>, whose registered office is at <address> (the "Supplier"); and (2) <Company B> … (the "Buyer")`), 8–12 numbered clauses using the defined terms, a pricing table (amounts, percentages, quantities with units), payment clause with IBAN/BIC (valid, from `schwifty` generation) and VAT numbers (valid via `stdnum`), notices clause (`Attention: <Mr X>`, address, e-mail, phone, URL), signature blocks (`By: … Name: … Title: …`), header with short party names and footer with page number. Variants used deliberately in the text (`Acme`, `Mr Smith`, `J. Smith`) and listed in `TruthItem.variants`. Dates, durations (`30 days`), governing law (`England and Wales`) appear and are **not** in truth. Tracked changes and comments are written as raw XML with lxml (python-docx 1.2 can add comments; `w:ins`/`w:del` by hand). `thirty_pages` repeats clause blocks until ≥ 30 pages of text (~12,000 words). `existing_placeholders` contains the literal `[PERSON_1]` and `[Name]`. `shared_surname` has two signatories with the same surname and a later `Mr <Surname>`.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_corpus.py -q` → PASS. Open one generated file in Word by hand once to confirm it looks like a contract (`open tests/corpus/generated/supply-01.docx`).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "test: deterministic made-up contract corpus with ground truth"`

---

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

### Task 6: Detection engine and pattern recognizers

**Files:**
- Create: `src/themask/detect/__init__.py`, `src/themask/detect/engine.py`, `src/themask/detect/patterns.py`, `src/themask/detect/nlp_config.yaml`
- Modify: `tests/conftest.py` (session fixture `engine`)
- Test: `tests/detect/test_patterns.py`

**Interfaces:**
- Produces: `class Engine: def __init__(self, model_name: str = "en_core_web_md") ...; def analyze(self, text: str) -> list[Finding]` (Presidio `AnalyzerEngine` with `NlpEngineProvider(conf_file=nlp_config.yaml)`, our recognizers registered, Presidio entities mapped: `EMAIL_ADDRESS→EMAIL, PHONE_NUMBER→PHONE, IBAN_CODE→IBAN, CREDIT_CARD→ID, URL→URL, PERSON→PERSON, ORGANIZATION→COMPANY, LOCATION→ADDRESS (kept only when Task 7 confirms an address context), US_SSN/US_PASSPORT/UK_NHS/UK_NINO→ID`; `low_score_entity_names: []`; `labels_to_ignore` keeps Presidio's defaults so MONEY/PERCENT/QUANTITY come from our regexes). Phone regions `GB NL DE FR BE IE TR US ES IT CH AT DK SE NO PL`.
- Produces (`patterns.py`, all `presidio_analyzer.PatternRecognizer` subclasses, `supported_entity` = our type names): `AmountRecognizer`, `PercentRecognizer`, `QuantityRecognizer`, `VatRecognizer` (validates with `stdnum.eu.vat`; valid → 0.9, format-only → 0.6), `RegistrationNumberRecognizer` (context: registered/company/registration/KvK/Chamber of Commerce/Companies House/HRB + number), `BicRecognizer` (validated with `schwifty.BIC`), `AccountNumberRecognizer` (context account/sort code), `NationalIdRecognizer` (NL BSN via `stdnum.nl.bsn`, TR TCKN via `stdnum.tr.tckimlik`, passport-number context), `BareNumberRecognizer` (≥ 1,000 with separators or decimals, base 0.4, context price/fee/amount/total/value/charge → 0.75; excludes years 1900–2099, clause numbers `\d+\.\d+` at line start, numbers followed by day/days/month/months/year/years/hours).
- `Engine.analyze` returns `Finding(score=…, source="pattern" | "model")`; findings with score < 0.3 are dropped.

- [ ] **Step 1: Write the failing tests** (positive and negative per type; `engine` fixture is session-scoped)

```python
def types_at(engine, text, needle):
    return {f.type for f in engine.analyze(text) if text[f.start:f.end].strip() == needle}
@pytest.mark.parametrize("text,needle", [("The Price is EUR 1,250,000.00 per year.", "EUR 1,250,000.00"), ("a fee of €1.25m", "€1.25m"), ("pay 1.250.000,00 EUR", "1.250.000,00 EUR"), ("the sum of one million euros", "one million euros"), ("EUR 1 250 000,00", "EUR 1 250 000,00"), ("GBP 48,000", "GBP 48,000")])
def test_amounts(engine, text, needle): assert PlaceholderType.AMOUNT in types_at(engine, text, needle)
@pytest.mark.parametrize("text", ["within 30 days", "in 2026", "clause 10.2 applies", "a term of 5 years", "Schedule 3"])
def test_not_amount_or_quantity(engine, text): assert not {PlaceholderType.AMOUNT, PlaceholderType.QUANTITY} & {f.type for f in engine.analyze(text)}
@pytest.mark.parametrize("text,needle", [("a discount of 12.5%", "12.5%"), ("interest at 8 per cent", "8 per cent")])
def test_percent(engine, text, needle): assert PlaceholderType.PERCENT in types_at(engine, text, needle)
@pytest.mark.parametrize("text,needle", [("minimum order of 10,000 units", "10,000 units"), ("deliver 48 pallets", "48 pallets"), ("capacity of 2.5 tonnes", "2.5 tonnes")])
def test_quantity(engine, text, needle): assert PlaceholderType.QUANTITY in types_at(engine, text, needle)
def test_iban_valid_only(engine):
    assert PlaceholderType.IBAN in types_at(engine, "IBAN NL91 ABNA 0417 1643 00", "NL91 ABNA 0417 1643 00")
    assert PlaceholderType.IBAN not in {f.type for f in engine.analyze("IBAN NL91 ABNA 0417 1643 01")}
def test_bic(engine): assert PlaceholderType.ID in types_at(engine, "BIC: ABNANL2A", "ABNANL2A")
def test_vat(engine): assert PlaceholderType.ID in types_at(engine, "VAT number NL123456782B01", "NL123456782B01")
def test_registration(engine): assert PlaceholderType.ID in types_at(engine, "registered in England and Wales under number 01234567", "01234567")
def test_email_phone_url(engine):
    t = "Contact j.smith@northwind.example, +31 20 123 4567 or https://www.northwind.example/legal"
    found = {f.type for f in engine.analyze(t)}; assert {PlaceholderType.EMAIL, PlaceholderType.PHONE, PlaceholderType.URL} <= found
def test_bare_number_in_price_context_is_low_confidence_amount(engine):
    f, = [f for f in engine.analyze("Total price: 48,000") if f.type == PlaceholderType.AMOUNT]; assert 0.3 <= f.score < 0.85
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/detect/test_patterns.py -q` → FAIL.
- [ ] **Step 3: Implement `nlp_config.yaml`, `engine.py`, `patterns.py`** (regexes for amounts: currency symbol/code before or after; digits with `[.,\s   ]` separators; optional decimals; optional `k|m|bn|million|billion|thousand`; number words one…ninety-nine + hundred/thousand/million + currency word).
- [ ] **Step 4: Run to verify pass**, lint, types. **Step 5: Commit** — `git add -A && git commit -m "feat: Presidio engine with contract pattern recognizers"`

---

### Task 7: Names, companies, addresses: model + contract rules

**Files:**
- Create: `src/themask/detect/contract_rules.py`
- Modify: `src/themask/detect/engine.py` (call rules; address confirmation for LOCATION), `src/themask/textnorm.py` (`LEGAL_FORMS` constant shared)
- Test: `tests/detect/test_contract_rules.py`

**Interfaces:**
- Produces: `LEGAL_FORMS: tuple[str, ...]` (`B.V., N.V., GmbH, AG, S.A., S.A.S., S.r.l., S.p.A., Ltd, Limited, LLP, LLC, Inc., Incorporated, plc, Corp., Corporation, Co., KG, OHG, A.Ş., Ltd. Şti., Oy, AB, ApS, A/S, SE` with optional dots); `find_parties(text) -> list[Finding]` (BETWEEN clause within the first 4,000 chars); `find_legal_form_companies(text) -> list[Finding]` (1–6 capitalised tokens + legal form, score 0.95); `find_signature_blocks(text) -> list[Finding]` (`Name:`/`By:`/`Signed by:` → PERSON unless legal form → COMPANY; `Attention:`/`Attn:`/`For the attention of` → PERSON); `find_addresses(text) -> list[Finding]` (`Address:`/`Registered office:` lines; `registered office is at …`/`principal place of business at …` up to `(`, `;`, ` and `, newline; street-pattern with number + street word incl. `straat weg laan plein Straße Platz Caddesi Sokak`; postcodes UK/NL/DE/FR/TR extend the span); `find_defined_terms(text) -> set[str]` (`(the "Supplier")`, `("Buyer")`, `hereinafter "X"`); `apply_rules(text) -> tuple[list[Finding], set[str]]`.
- Changes `Engine.analyze`: merges rule findings (`source="rule"`); model LOCATION kept only if overlapping/adjacent to an address finding (else dropped); COMPANY from the model without a legal form and without rule confirmation gets `score = min(score, 0.6)` (becomes "check" in Task 8).

- [ ] **Step 1: Write the failing tests**

```python
PARTIES = 'THIS AGREEMENT is made on 1 March 2026\nBETWEEN:\n(1) Northwind Trading B.V., a company registered in the Netherlands under number 12345678, whose registered office is at Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands (the "Supplier"); and\n(2) Acme Supplies Ltd, registered in England and Wales under number 01234567, whose registered office is at 10 Downing Street, London SW1A 2AA (the "Buyer").'
def texts(fs, t): return {t[f.start:f.end] for f in fs}
def test_parties_found():
    fs, terms = apply_rules(PARTIES)
    assert {"Northwind Trading B.V.", "Acme Supplies Ltd"} <= texts([f for f in fs if f.type == PlaceholderType.COMPANY], PARTIES)
    assert terms == {"Supplier", "Buyer"}
def test_addresses_found():
    fs, _ = apply_rules(PARTIES); addr = texts([f for f in fs if f.type == PlaceholderType.ADDRESS], PARTIES)
    assert any(a.startswith("Keizersgracht 123") and a.endswith("Netherlands") for a in addr) and any("SW1A 2AA" in a for a in addr)
def test_signature_block():
    t = "SIGNED for and on behalf of the Supplier\nBy: ____\nName: Dr Jane Smith\nTitle: Managing Director\nAttention: Mr Tom Brown"
    fs, _ = apply_rules(t); assert {"Dr Jane Smith", "Mr Tom Brown"} <= texts([f for f in fs if f.type == PlaceholderType.PERSON], t)
    assert "Managing Director" not in texts(fs, t)
def test_jurisdiction_stays_visible(engine):
    fs = engine.analyze("This Agreement is governed by the laws of the Netherlands and the courts of Amsterdam.")
    assert not [f for f in fs if f.type == PlaceholderType.ADDRESS]
def test_model_person_in_prose(engine):
    fs = engine.analyze("The notice was sent by Jane Smith to the Buyer on Monday."); assert "Jane Smith" in texts([f for f in fs if f.type == PlaceholderType.PERSON], "The notice was sent by Jane Smith to the Buyer on Monday.")
def test_legal_form_company_in_prose(engine):
    t = "Supplies are sourced from Baltic Fasteners GmbH and its affiliates."; assert "Baltic Fasteners GmbH" in texts([f for f in engine.analyze(t) if f.type == PlaceholderType.COMPANY], t)
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass**, lint, types.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: contract-aware rules for parties, signatures, addresses"`

---

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

### Task 9: Review state (the logic behind the review screen)

**Files:**
- Create: `src/themask/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `Analysis`, `Group`, `UserLists`, `sweep`, `flexible_pattern`.
- Produces: `class ReviewState` with `from_analysis(analysis: Analysis, user_lists: UserLists, case_lists: CaseLists) -> ReviewState`; `text: str`; `groups: list[Group]`; `set_group_enabled(group_id: str, enabled: bool)`; `set_occurrence_enabled(group_id: str, finding_index: int, enabled: bool)`; `hide_text(value: str, type: PlaceholderType) -> Group` (new group, numbered next for its type, swept across the text; if the text equals an existing group's variant, the occurrence joins that group instead); `merge(group_ids: list[str]) -> Group` (same type only, else `ValueError`; keeps the lowest placeholder number, union of variants, canonical = longest); `split(group_id: str, finding_indexes: list[int]) -> Group`; `add_always_hide(value: str)` (persists to `UserLists` and calls `hide_text`), `add_never_hide(value: str)` (persists, disables matching groups); `mask_plan() -> MaskPlan` (enabled groups' active findings only); `key_entries() -> list[KeyEntry]` (enabled groups; `value` = canonical; `variants` = all variants seen); `counts() -> ReviewCounts(groups: int, enabled: int, needs_check: int, replacements: int)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_disable_group_removes_replacements(review):           # fixture: ReviewState over analyze() of "Acme Supplies Ltd and Northwind Trading B.V. appoint John Smith. Project Falcon starts now; Project Falcon ends later. Acme signs." → groups in order [COMPANY_1] Acme, [COMPANY_2] Northwind, [PERSON_1] John Smith
    n = len(review.mask_plan().replacements); gid = review.groups[0].id
    review.set_group_enabled(gid, False); assert len(review.mask_plan().replacements) == n - len(review.groups[0].findings)
def test_disable_single_occurrence(review):
    gid = review.groups[0].id; review.set_occurrence_enabled(gid, 0, False); assert review.groups[0].findings[0].start not in {r.start for r in review.mask_plan().replacements}
def test_hide_text_sweeps(review):
    g = review.hide_text("Project Falcon", PlaceholderType.CUSTOM); assert len(g.findings) == review.text.count("Project Falcon") and g.placeholder == "[CUSTOM_1]"
def test_merge_keeps_lowest_number(review):
    a, b = review.groups[0], review.groups[1]; m = review.merge([a.id, b.id]); assert m.placeholder == min(a.placeholder, b.placeholder, key=lambda p: int(p.split("_")[1].rstrip("]"))) and len(review.groups) == 2
def test_split(review):
    g = review.groups[0]; new = review.split(g.id, [0]); assert len(new.findings) == 1 and new.placeholder != g.placeholder
def test_never_hide_disables(review, lists):
    v = review.groups[0].canonical; review.add_never_hide(v); assert not review.groups[0].enabled and v in lists.never_hide
def test_key_entries_match_plan(review):
    assert {r.placeholder for r in review.mask_plan().replacements} == {e.placeholder for e in review.key_entries()}
```

- [ ] **Step 2–5:** verify failure → implement → verify pass (+ lint/types) → `git commit -m "feat: review state with enable, hide, merge, split and lists"`

---

### Task 10: Word package and text map

**Files:**
- Create: `src/themask/docx/__init__.py`, `src/themask/docx/package.py`, `src/themask/docx/reader.py`
- Test: `tests/docx/test_package.py`, `tests/docx/test_reader.py`, fixtures `tests/docx/fixtures/` (`not-a-docx.doc` = 512 bytes starting `D0 CF 11 E0`, `corrupt.docx` = random bytes, `encrypted.docx` = OLE container bytes with the `EncryptionInfo` stream name)

**Interfaces:**
- Produces (`package.py`): `class DocxPackage` with `open(path: Path) -> DocxPackage` (raises `UnsupportedFileError("This is not a Word .docx file. If it is an old .doc, open it in Word and save as .docx.")` for non-zip / missing `word/document.xml`, `ProtectedFileError("This file is protected or encrypted. Please provide an unprotected copy.")` for OLE/`EncryptionInfo`), `copy() -> DocxPackage` (deep), `names() -> list[str]`, `xml(name) -> lxml.etree._Element` (parsed once, cached, written back on save), `raw(name) -> bytes`, `set_raw(name, data)`, `rels_of(part_name) -> lxml element` (`word/_rels/document.xml.rels` etc.), `remove_part(name)` (deletes the entry, every relationship pointing to it, and its `[Content_Types].xml` Override), `save(path: Path)`, `TEXT_PARTS` property: `word/document.xml`, `word/header*.xml`, `word/footer*.xml`, `word/footnotes.xml`, `word/endnotes.xml` (comments excluded), `NS` dict (`w`, `r`, `wp`, `a`, `pic`, `wps`, `v`, `c`, `dgm`, `cp`, `dc`, `dcterms`, `ep`, `w14`).
- Produces (`reader.py`): `@dataclass TextNode(elem, start: int, end: int, kind: Literal["t","instr"])`; `paragraph_nodes(p, view: Literal["accepted","rejected"]) -> tuple[str, list[TextNode]]` (walks `w:r`, `w:hyperlink`, `w:sdt/w:sdtContent`, `w:smartTag`, `w:fldSimple`, `w:ins` (accepted only), `w:del/w:delText` (rejected only), `w:instrText`); `@dataclass Segment(part: str, para: lxml element, start: int, end: int)`; `@dataclass DocText(text: str, segments: list[Segment])`; `extract_text(pkg, view="accepted") -> DocText` (paragraph texts joined with `\n`, over `TEXT_PARTS` in order document → headers → footers → footnotes → endnotes; text-box paragraphs included); `has_revisions(pkg) -> bool` (`w:ins|w:del|w:moveFrom|w:moveTo|w:rPrChange|w:pPrChange` anywhere in TEXT_PARTS); `has_comments(pkg) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_open_doc_renamed(fixtures):
    with pytest.raises(UnsupportedFileError) as e: DocxPackage.open(fixtures / "not-a-docx.doc")
    assert "save as .docx" in e.value.user_message
def test_open_corrupt(fixtures):
    with pytest.raises(UnsupportedFileError): DocxPackage.open(fixtures / "corrupt.docx")
def test_open_encrypted(fixtures):
    with pytest.raises(ProtectedFileError): DocxPackage.open(fixtures / "encrypted.docx")
def test_remove_part_cleans_rels_and_types(corpus):
    pkg = DocxPackage.open(corpus / "supply-02.docx"); assert "word/comments.xml" in pkg.names()
    pkg.remove_part("word/comments.xml"); assert "word/comments.xml" not in pkg.names()
    assert b"comments.xml" not in pkg.raw("word/_rels/document.xml.rels") and b"comments+xml" not in pkg.raw("[Content_Types].xml")
def test_extract_text_covers_all_parts(corpus):
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg)
    assert {s.part for s in dt.segments} >= {"word/document.xml", "word/header1.xml", "word/footer1.xml"} and "Confidential" in dt.text
def test_views(corpus):                       # supply-03 has tracked changes with a secret only in deleted text
    pkg = DocxPackage.open(corpus / "supply-03.docx"); truth = json.loads((corpus / "supply-03.truth.json").read_text())
    deleted = next(t["value"] for t in truth if t.get("only_in_deletion"))
    assert deleted not in extract_text(pkg, "accepted").text and deleted in extract_text(pkg, "rejected").text and has_revisions(pkg)
def test_split_runs_map_back(corpus):         # supply-01 writes "Northwind Trading B.V." across three runs
    pkg = DocxPackage.open(corpus / "supply-01.docx"); dt = extract_text(pkg); i = dt.text.index("Northwind Trading B.V.")
    seg = next(s for s in dt.segments if s.start <= i < s.end); text, nodes = paragraph_nodes(seg.para, "accepted")
    lo, hi = i - seg.start, i - seg.start + len("Northwind Trading B.V."); covering = [n for n in nodes if n.start < hi and n.end > lo]
    assert text[lo:hi] == "Northwind Trading B.V." and len(covering) >= 3
def test_original_untouched(corpus, tmp_path):
    src = corpus / "supply-01.docx"; before = src.read_bytes(); pkg = DocxPackage.open(src); pkg.remove_part("word/header1.xml"); pkg.save(tmp_path / "out.docx")
    assert src.read_bytes() == before
```

- [ ] **Step 2–5:** verify failure → implement → verify pass (+ lint/types) → `git commit -m "feat: docx package wrapper and text map with accepted/rejected views"`

---

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

### Task 17: Encrypted case store

**Files:**
- Create: `src/themask/keystore/__init__.py`, `src/themask/keystore/crypto.py`, `src/themask/keystore/secrets.py`, `src/themask/keystore/cases.py`
- Modify: `tests/conftest.py` (fixtures `keystore` = `MemoryKeyStore()`, `case_store`)
- Test: `tests/keystore/test_crypto.py`, `tests/keystore/test_cases.py`

**Interfaces:**
- Produces (`crypto.py`): `encrypt(key: bytes, plaintext: bytes) -> bytes` (12-byte random nonce ‖ AES-256-GCM ciphertext+tag), `decrypt(key: bytes, blob: bytes) -> bytes` (raises `CaseCorruptError` on tag failure).
- Produces (`secrets.py`): `class KeyStore(Protocol): def get_or_create_master_key(self) -> bytes`; `class KeychainKeyStore` (`keyring.get_password("The MASK", "master-key")`, creating 32 random bytes base64 on first use); `class MemoryKeyStore`.
- Produces (`cases.py`): `@dataclass CaseSummary(id, created_at, expires_at, source_files, n_entries)`; `class CaseStore(dir: Path, keystore: KeyStore)` with `save(case: Case) -> Path` (`<dir>/<id>.mask`, mode 0o600), `load(case_id) -> Case`, `list() -> list[CaseSummary]` (newest first; summaries need decryption, so the listing decrypts headers only — store `id, created_at, retention_days, source_files, n_entries` as a separate unencrypted-but-content-free JSON header line before the blob), `delete(case_id)`, `delete_all()`, `purge_expired(now: datetime | None = None) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_roundtrip_and_tamper():
    k = os.urandom(32); blob = encrypt(k, b"secret"); assert decrypt(k, blob) == b"secret"
    with pytest.raises(CaseCorruptError): decrypt(k, blob[:-1] + bytes([blob[-1] ^ 1]))
def test_memory_keystore_stable(): ks = MemoryKeyStore(); assert ks.get_or_create_master_key() == ks.get_or_create_master_key() and len(ks.get_or_create_master_key()) == 32
def test_save_load_list_delete(case_store, sample_case):
    p = case_store.save(sample_case); assert case_store.load(sample_case.id) == sample_case and oct(p.stat().st_mode)[-3:] == "600"
    assert [s.id for s in case_store.list()] == [sample_case.id]; case_store.delete(sample_case.id); assert case_store.list() == []
def test_values_not_on_disk(case_store, sample_case):
    p = case_store.save(sample_case); raw = p.read_bytes(); assert b"John Smith" not in raw and b"NL91" not in raw and sample_case.source_files[0].encode() in raw
def test_purge_expired(case_store, sample_case):
    case_store.save(sample_case); assert case_store.purge_expired(sample_case.created_at + timedelta(days=31)) == [sample_case.id] and case_store.list() == []
    case_store.save(sample_case); assert case_store.purge_expired(sample_case.created_at + timedelta(days=29)) == []
def test_wrong_key_is_corrupt(case_store, sample_case, tmp_path):
    case_store.save(sample_case); other = CaseStore(case_store.dir, MemoryKeyStore())
    with pytest.raises(CaseCorruptError): other.load(sample_case.id)
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: AES-GCM case store with Keychain-backed master key and retention purge"`

---

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

### Task 19: Paths, content-free logging, network guard

**Files:**
- Create: `src/themask/logging_setup.py`, `src/themask/netguard.py`, `src/themask/__main__.py` (temporary: guard → logging → print version)
- Modify: `src/themask/paths.py` (`log_dir`), `src/themask/detect/engine.py` (log counts only)
- Test: `tests/test_netguard.py`, `tests/test_logging.py`

**Interfaces:**
- Produces: `class NetworkBlockedError(OSError)`; `install_network_guard() -> None` (replaces `socket.socket.connect`, `connect_ex`, `sendto`, `bind`, `listen`, `socket.create_connection`, `socket.getaddrinfo` with functions raising `NetworkBlockedError("The MASK never uses the network.")`; sets `tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)` before Presidio imports; idempotent); `setup_logging(level="INFO") -> Path` (RotatingFileHandler 1 MB × 3 in `log_dir()`, format with timestamp, module, message).
- Rule enforced by test: log lines carry counts/types/durations only.
- `tests/conftest.py` calls `install_network_guard()` at import from this task on, so the whole suite proves the app needs no network.

- [ ] **Step 1: Write the failing tests**

```python
def test_guard_blocks_connect():
    install_network_guard()
    with pytest.raises(NetworkBlockedError): socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(NetworkBlockedError): socket.getaddrinfo("example.com", 443)
def test_url_recognizer_works_offline(engine, caplog):
    install_network_guard(); fs = engine.analyze("see https://www.northwind.example/terms"); assert any(f.type == PlaceholderType.URL for f in fs) and "Public Suffix List" not in caplog.text
def test_log_has_no_document_content(corpus, engine, lists, tmp_path, monkeypatch):
    monkeypatch.setenv("THEMASK_DATA_DIR", str(tmp_path)); log = setup_logging("DEBUG")
    srcs = load_sources([corpus / "supply-01.docx"], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set())); export_case(srcs, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None)
    text = normalize(log.read_text()); assert text
    for t in json.loads((corpus / "supply-01.truth.json").read_text()): assert normalize(t["value"]) not in text, t["value"]
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: network guard, offline tldextract and content-free logging"`

---

### Task 20: App shell, home screen, analysis worker

**Files:**
- Create: `src/themask/ui/__init__.py`, `src/themask/ui/app.py`, `src/themask/ui/main_window.py`, `src/themask/ui/drop_zone.py`, `src/themask/ui/workers.py`, `src/themask/ui/theme.py`
- Modify: `src/themask/__main__.py` (→ `ui.app.main()`)
- Test: `tests/ui/test_home.py` (pytest-qt, offscreen)

**Interfaces:**
- Produces: `class AppContext(engine: Engine, user_lists: UserLists, case_store: CaseStore, settings: Settings)` built lazily in `app.main()` (`Settings` = dataclass `retention_days: int = 30`, `out_dir: Path = ~/Documents/The MASK`, loaded/saved as JSON in `data_dir()`); `class MainWindow(QMainWindow)` with `show_home()`, `show_review(sources, analysis)`, `show_restore()`, `show_cases()`, `show_settings()`, `open_files(paths: list[Path], redline_split: bool | None, case_id: str | None = None)` (asks "This file contains tracked changes. Make a before-and-after pair?" when `None` and any source `has_revisions`; with `case_id` the analysis is seeded with that case's entries and the export updates that case); signals `analysisProgress(int, str)`, `analysisFinished()`, `analysisFailed(str)`; `current_screen_name() -> str`; `review_screen: ReviewScreen`; module-level `show_error(parent, message: str)` (a `QMessageBox`, monkeypatched in tests); `class DropZone(QFrame)` emitting `filesDropped(list)` for `.docx`/`.pdf`, with a "Choose files…" button; `class AnalysisWorker(QThread)` with signals `progress(int, str)` (0–100 and a step name: loading → reading → finding → grouping → done), `finished(object)` (`tuple[list[SourceDoc], Analysis]`), `failed(str)` (user_message); the engine is created once in a background thread at startup with a "Loading…" status in the home screen.

- [ ] **Step 1: Write the failing tests**

```python
def test_home_to_review(qtbot, app_ctx, corpus):
    w = MainWindow(app_ctx); qtbot.addWidget(w); w.show()
    with qtbot.waitSignal(w.analysisFinished, timeout=60000): w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert w.current_screen_name() == "review" and w.review_screen.group_count() > 0
def test_unsupported_file_shows_message(qtbot, app_ctx, fixtures, monkeypatch):
    shown = []; monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg)); w = MainWindow(app_ctx); qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000): w.open_files([fixtures / "not-a-docx.doc"], redline_split=False)
    assert shown and "save as .docx" in shown[0]
def test_scanned_pdf_message(qtbot, app_ctx, corpus, monkeypatch):
    shown = []; monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg)); w = MainWindow(app_ctx); qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000): w.open_files([corpus / "scanned-01.pdf"], redline_split=False)
    assert "scan" in shown[0]
def test_progress_reaches_100(qtbot, app_ctx, corpus):
    w = MainWindow(app_ctx); qtbot.addWidget(w); seen = []; w.analysisProgress.connect(lambda p, s: seen.append(p))
    with qtbot.waitSignal(w.analysisFinished, timeout=60000): w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert seen[-1] == 100 and seen == sorted(seen)
```
(`app_ctx` fixture: session `engine`, `lists`, `CaseStore(tmp, MemoryKeyStore())`, default `Settings`.)

- [ ] **Step 2–5:** verify failure → implement → verify pass (`uv run pytest tests/ui -q`) → `git commit -m "feat: app shell with drop zone and threaded analysis"`

---

### Task 21: Review screen

**Files:**
- Create: `src/themask/ui/review_screen.py`
- Test: `tests/ui/test_review_screen.py`

**Interfaces:**
- Consumes: `ReviewState`, `Analysis`, `CombinedText`.
- Produces: `class ReviewScreen(QWidget)` with `load(review: ReviewState, combined: CombinedText)`, `group_count() -> int`, `review: ReviewState`, `text: QTextEdit`, `tree: QTreeWidget`, `tree_item_for(group_id) -> QTreeWidgetItem` (column 1 shows `check` when flagged), `highlight_count() -> int`, `hide_selection(type: PlaceholderType)`, `export_button: QPushButton`, signal `exportRequested()`; layout: left a read-only `QTextEdit` showing the combined text with each active finding highlighted (background colour per type from `theme.TYPE_COLOURS`, a dotted underline + "check" tooltip for `needs_check`, file headers for each part), right a `QTreeWidget` of groups ("canonical — N times — [PLACEHOLDER]", checkbox per group and per occurrence, "check" badge), a warnings strip (from `Analysis.warnings`), and actions: **Hide selection** (type menu; enabled when text is selected), **Merge** (≥ 2 groups selected), **Split** (occurrences selected), **Always hide**, **Never hide**, **Continue to export** (disabled while zero groups are enabled? No: allowed — the owner may export a document with nothing to hide; the dialog then says so). Clicking a highlight selects its group; selecting a group scrolls to its first occurrence.

- [ ] **Step 1: Write the failing tests**

```python
def test_tree_matches_state(review_screen):
    s, st = review_screen; assert s.tree.topLevelItemCount() == len(st.groups) and s.tree.topLevelItem(0).text(0).endswith(st.groups[0].placeholder)
def test_untick_group_updates_plan_and_highlight(qtbot, review_screen):
    s, st = review_screen; n = len(st.mask_plan().replacements); item = s.tree.topLevelItem(0); item.setCheckState(0, Qt.CheckState.Unchecked)
    assert len(st.mask_plan().replacements) < n and s.highlight_count() == len(st.mask_plan().replacements)
def test_hide_selection(qtbot, review_screen):
    s, st = review_screen; i = s.text.toPlainText().index("Project Falcon"); c = s.text.textCursor(); c.setPosition(i); c.setPosition(i + len("Project Falcon"), c.MoveMode.KeepAnchor); s.text.setTextCursor(c)
    s.hide_selection(PlaceholderType.CUSTOM); assert any(g.canonical == "Project Falcon" for g in st.groups) and s.tree.topLevelItemCount() == len(st.groups)
def test_needs_check_marked(review_screen):
    s, st = review_screen; flagged = [g for g in st.groups if g.needs_check]; assert flagged and all(s.tree_item_for(g.id).text(1) == "check" for g in flagged)
def test_export_signal(qtbot, review_screen):
    s, _ = review_screen
    with qtbot.waitSignal(s.exportRequested): qtbot.mouseClick(s.export_button, Qt.MouseButton.LeftButton)
```
(`review_screen` fixture: analysis of `supply-08.docx` — the `shared_surname` document that also contains "Project Falcon" twice.)

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: review screen with highlights, grouped list and actions"`

---

### Task 22: Export dialog

**Files:**
- Create: `src/themask/ui/export_dialog.py`
- Modify: `src/themask/ui/main_window.py` (wire `exportRequested` → dialog)
- Test: `tests/ui/test_export_dialog.py`

**Interfaces:**
- Consumes: `export_case`, `ExportResult`, `AI_INSTRUCTION`, `Settings.out_dir`.
- Produces: `class ExportDialog(QDialog)` with `run(sources, review, options, ctx)` (runs `export_case` in a worker with a progress bar; `ctx.case_store.save` is the `save_case` callback), signal `finishedExport()`, `result: ExportResult`, `copy_button: QPushButton`, `summary_text() -> str`; `analysed(ctx, paths) -> tuple[list[SourceDoc], ReviewState]` helper in `tests/helpers.py`; on success shows the output file names, the `unmarked` list under "Also found in the masked copy — not marked by you:", a **Copy instruction** button (puts `AI_INSTRUCTION` on the clipboard) and **Show in Finder**; on `blocked` shows "Saving blocked: a marked value is still present" with each `LeakHit.part` and `context`, and only a **Back to review** button. `summary_text()` for tests.

- [ ] **Step 1: Write the failing tests**

```python
def test_success_shows_outputs_and_instruction(qtbot, app_ctx, corpus, tmp_path):
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"]); d = ExportDialog(); qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=60000): d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert "MASKED-" in d.summary_text() and not d.result.blocked
    qtbot.mouseClick(d.copy_button, Qt.MouseButton.LeftButton); assert QApplication.clipboard().text() == AI_INSTRUCTION
def test_blocked_shows_hits(qtbot, app_ctx, corpus, tmp_path, monkeypatch):
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"])
    monkeypatch.setattr(export_dialog, "export_case", lambda *a, **k: ExportResult(None, [], [LeakHit("word/header1.xml", "[COMPANY_1]", "… [COMPANY_1] …")], [], AI_INSTRUCTION, True))
    d = ExportDialog(); qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=10000): d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert "blocked" in d.summary_text().lower() and "word/header1.xml" in d.summary_text() and not d.copy_button.isEnabled()
def test_case_saved(qtbot, app_ctx, corpus, tmp_path):
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"]); d = ExportDialog(); qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=60000): d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert [s.id for s in app_ctx.case_store.list()] == [d.result.case.id]
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: export dialog with leak block, outputs and instruction copy"`

---

### Task 23: Restore, Cases and Settings screens

**Files:**
- Create: `src/themask/ui/restore_screen.py`, `src/themask/ui/cases_screen.py`, `src/themask/ui/settings_screen.py`
- Modify: `src/themask/ui/main_window.py` (navigation; `purge_expired` on startup), `src/themask/ui/app.py` (About with `OWNER_NAME`, `VERSION`)
- Test: `tests/ui/test_restore_screen.py`, `tests/ui/test_cases_settings.py`

**Interfaces:**
- Produces `class RestoreScreen(QWidget)` (`load_file(path)`, `case_combo` with the case id as item data, `altered_list: QListWidget` with check boxes, `restore_button`, `restore_text_button`, `paste_box`, `result_box`, `report_label`, signal `restoreFinished()`): a `DropZone` for the AI's `.docx` and a paste box (`QPlainTextEdit`) with **Restore text**; a case combo (`suggest_cases` order over all stored cases, most recent preselected when no placeholders match); when `plan_restore` has altered items, a list with checkboxes "These placeholders were changed by the AI — restore them?" and **Restore** applies `confirm_altered` to the ticked set (implementation: build a `Case` view containing only ticked altered entries); result panel with `RestoreReport.summary()`, the unknown list, and **Show in Finder**; restored text appears in a read-only box with **Copy**.
- Produces `class CasesScreen(QWidget)` (`table: QTableWidget`, `delete_button`, module-level `confirm(parent, message) -> bool`): table of `CaseSummary` (id, created, expires, files, entries), **Delete**, **Delete all** (both confirm), **Restore from this case**, **Add file to this case** (→ `MainWindow.open_files(paths, None, case_id)`).
- Produces `class SettingsScreen(QWidget)` (`always_edit`, `never_edit: QPlainTextEdit`, `retention_spin`, `save_button`, `about_label`): editable always-hide and never-hide lists (`UserLists`, one entry per line), retention days spin box (1–365, default 30), output folder picker, About box (`APP_NAME`, `VERSION`, `OWNER_NAME`, "Runs fully offline. Restored text you copy is on the clipboard in clear.").

- [ ] **Step 1: Write the failing tests**

```python
def test_restore_docx_flow(qtbot, app_ctx, exported):                      # exported fixture: (masked_path, case) saved in app_ctx.case_store
    masked, case = exported; ai = simulate_ai(masked, masked.parent / "ai.docx"); s = RestoreScreen(app_ctx); qtbot.addWidget(s)
    s.load_file(ai); assert s.case_combo.currentData() == case.id and s.altered_list.count() == 1
    s.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(s.restoreFinished, timeout=30000): qtbot.mouseClick(s.restore_button, Qt.MouseButton.LeftButton)
    assert s.report_label.text().endswith("need your check.") and (masked.parent / "ai – restored.docx").exists()
def test_restore_text_flow(qtbot, app_ctx, exported):
    _, case = exported; s = RestoreScreen(app_ctx); qtbot.addWidget(s); s.paste_box.setPlainText(f"Dear {case.entries[0].placeholder},"); s.case_combo.setCurrentIndex(s.case_combo.findData(case.id))
    qtbot.mouseClick(s.restore_text_button, Qt.MouseButton.LeftButton); assert case.entries[0].value in s.result_box.toPlainText()
def test_cases_screen_delete(qtbot, app_ctx, exported, monkeypatch):
    monkeypatch.setattr(cases_screen, "confirm", lambda *a: True); c = CasesScreen(app_ctx); qtbot.addWidget(c); assert c.table.rowCount() == 1
    c.table.selectRow(0); qtbot.mouseClick(c.delete_button, Qt.MouseButton.LeftButton); assert c.table.rowCount() == 0 and app_ctx.case_store.list() == []
def test_settings_lists_and_retention(qtbot, app_ctx):
    s = SettingsScreen(app_ctx); qtbot.addWidget(s); s.always_edit.setPlainText("Project Falcon\nSite 7"); s.retention_spin.setValue(14); qtbot.mouseClick(s.save_button, Qt.MouseButton.LeftButton)
    assert UserLists.load(lists_path()).always_hide == ["Project Falcon", "Site 7"] and app_ctx.settings.retention_days == 14
def test_about_shows_owner(qtbot, app_ctx): s = SettingsScreen(app_ctx); qtbot.addWidget(s); assert OWNER_NAME in s.about_label.text() and VERSION in s.about_label.text()
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: restore, cases and settings screens"`

---

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

### Task 25: The MASK.app for the owner's Mac

**Files:**
- Create: `packaging/icon/themask.icns`, `packaging/icon/themask-1024.png`, `packaging/make_icon.py` (Pillow draws a simple mask glyph; `iconutil` builds the `.icns`), `packaging/build_mac.sh`
- Modify: `pyproject.toml` (`[tool.briefcase]`), `README.md` ("Install on your Mac")

**Interfaces:**
- `[tool.briefcase]`: `project_name = "The MASK"`, `bundle = "com.<owner-domain-or-name>.themask"` (owner's call; default `local.themask`), `version = "0.1.0"`, `[tool.briefcase.app.themask]` `formal_name = "The MASK"`, `sources = ["src/themask"]`, `requires` = the runtime dependencies from Task 1 (same pins, including the model wheel URL), `icon = "packaging/icon/themask"`; `[tool.briefcase.app.themask.macOS]` `universal_build = false`, `min_os_version = "13.0"`, `requires = []`.
- `packaging/build_mac.sh`: `uv run briefcase create macOS app && uv run briefcase build macOS app && uv run briefcase package macOS app -p zip --adhoc-sign`, then prints the path of `dist/The MASK-0.1.0.zip`.

- [ ] **Step 1: Make the icon** — `uv run python packaging/make_icon.py` → `packaging/icon/themask.icns` exists (`file` reports "Mac OS X icon").
- [ ] **Step 2: Add the Briefcase configuration** to `pyproject.toml`.
- [ ] **Step 3: Build** — `bash packaging/build_mac.sh` (the build itself downloads Briefcase's Python support package and the wheels once; the finished app never touches the network). Expected: ends with `dist/The MASK-0.1.0.zip`; `build/themask/macos/app/The MASK.app` exists.
- [ ] **Step 4: Verify size and signature** — `du -sh "build/themask/macos/app/The MASK.app"` → under 600M; `codesign -dv --verbose=2 "build/themask/macos/app/The MASK.app" 2>&1 | grep -E 'Signature=adhoc|Identifier'` → shows `Signature=adhoc`.
- [ ] **Step 5: Install and launch** — `ditto "build/themask/macos/app/The MASK.app" "/Applications/The MASK.app" && open "/Applications/The MASK.app"`. Expected: the window opens, no security dialog, the home screen says the engine is loaded within ~10 s.
- [ ] **Step 6: Offline smoke test (owner at the keyboard)** — turn Wi-Fi off; drop `tests/corpus/generated/supply-01.docx`; review; export to `~/Documents/The MASK`; open the masked file in Word (banner first, placeholders, no logo, no comments; File → Properties shows no author); run `lsof -i -a -p $(pgrep -f "The MASK.app")` → prints nothing (no sockets); turn Wi-Fi back on. Record the result in `docs/acceptance/2026-10-xx-mac-smoke.md`.
- [ ] **Step 7: Write "Install on your Mac" in README** (copy the `.app` to Applications; on another Mac: right-click → Open, or System Settings → Privacy & Security → Open Anyway) and commit — `git add -A && git commit -m "build: Briefcase packaging for macOS, ad-hoc signed"`

---

### Task 26: Owner acceptance: the real round trip

**Files:**
- Create: `docs/acceptance/2026-10-xx-round-trip.md`

- [ ] **Step 1:** In The MASK.app, mask `tests/corpus/generated/supply-01.docx` (made-up data only). Copy the instruction.
- [ ] **Step 2:** For each of **Copilot**, **Claude** and **ChatGPT**: upload the masked file with the instruction and the prompt "Review this agreement for risks to the Buyer and return a revised version as a Word file." Download the Word file.
- [ ] **Step 3:** Restore each file in The MASK.app with the case preselected. Expected: every placeholder restored or listed under "need your check"; no invented values; banner gone.
- [ ] **Step 4:** Record per tool: placeholders survived (yes/no, which changed), restore report line, anything odd. Expected: all three "placeholders survive and restore" (spec §9).
- [ ] **Step 5:** `git add -A && git commit -m "docs: Mac acceptance round trip with three AI tools"`. Then the Windows-phase plan can start once Bunzl IT has answered spec §14.

---

## Self-review notes (filled in by the plan author)

- Spec coverage: §4 round trip → Tasks 15, 18, 22, 23, 26; §8.1 → 2, 8; §8.2 → 6, 7, 8, 24; §8.3 → 9, 21; §8.4 Word → 10–13, 15; §8.4 PDF → 16; §8.5 → 14, 15; §8.6 → 17; §8.7 → 18, 23; §8.8 → 2, 22; §8.9 (several files, add a file to an existing case) → 8, 15, 20, 23; §8.10 Mac → 1, 19, 25; §9 → 24, 25, 26; §10 clipboard note → Settings About copy (Task 23). Windows items deferred by design.
- Names used across tasks: `DocText/Segment/TextNode` (10 → 13, 18), `replace_in_paragraph` (13 → 18), `Group/KeyEntry/MaskPlan` (2 → 8, 9, 13, 14, 15, 18), `CombinedText` (8 → 15, 21), `ExportResult/LeakHit` (14, 15 → 22), `CaseStore/CaseSummary` (17 → 20, 23), `simulate_ai` helper defined once in `tests/helpers.py` (Task 18) and reused (23, 24).

## Results

**Detection pass marks (spec §9), 19 October 2026** (Task 24). Measured with `uv run python tools/evaluate.py` on the corpus generated afresh, on an Apple M3 Mac with 16 GB (the 8 GB office-laptop timing is Task 25's to confirm). Every Word file and every PDF is analysed on its own, annexes too, as the app does before the owner's review; a secret counts as found when every place of it, in every form its truth file lists, lies inside one replacement of the review's plan.

| Check (spec §9) | Word (28 files) | PDF (7 of 8 files) | All | Pass mark |
|---|---|---|---|---|
| Pattern-type items found before review (e-mail, phone, IBAN, ID, amount, percent, quantity, URL) | 100.0 % (719/719) | 100.0 % (194/194) | 100.0 % (913/913) | ≥ 99 % |
| Names, companies and addresses found before review | 100.0 % (255/255) | 100.0 % (65/65) | 100.0 % (320/320) | ≥ 95 % |
| Never-hide terms hidden by mistake | 0 | 0 | 0 | 0 |
| Thirty-page contract read and analysed (slowest file) | 2.2 s | 3.4 s | 3.4 s | < 60 s |
| Found secrets hidden as their own type (informational) | 99.9 % | 100.0 % | 99.9 % | — |

- Not counted: `scanned-01.pdf` (no text; v1 refuses scanned PDFs), and seven secrets the analysed text does not hold (six only in tracked-deleted or hidden text, which the prepared copy drops; the IBAN on the picture page of `mixed-01.pdf`).
- Before the tuning the same run gave 99.3 % (907/913: the six "N records" data volumes) and 100 %, with 96.3 % of found secrets typed right and 39 groups that hid no secret (29 of them running headers read whole). After it, 2 such groups are left: "Project Falcon" (kept on purpose, see the corpus README) and "Kraft" in "Kraft carrier bags" (a model guess, marked to check).
- Enforced by `tests/test_passmarks.py` (`test_pass_marks`, `test_thirty_pages_under_sixty_seconds`); the round-trip pass marks follow with `test_full_round_trip_every_docx` once Task 18's Word restore is in.
