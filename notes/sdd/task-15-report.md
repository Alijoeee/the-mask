# Task 15 report: export orchestration

**Status:** DONE_WITH_CONCERNS
**Branch / worktree:** task-15 at /Users/alijoeee/Developer/the-mask-worktrees/task-15 (from mac-v1 7548a97)
**Commit:** 6a3dee2 feat: export pipeline with leak-check gate, multi-file and redline cases

## What I implemented

`src/themask/export.py` (512 lines, mostly docstrings):

- `SourceDoc(path, kind, pkg, pkg_after, text_after, pkg_before, text_before, has_revisions, pdf_report)`, in the R2 field order.
- `load_sources(paths, redline_split)` prepares the packages (R2). `pkg` is the opened original and nothing changes it. `pkg_after` is copy → `accept_all` → `clean`. `pkg_before` is copy → `reject_all` → `clean`, made only when `redline_split` is set and the file has revisions. `text_after` and `text_before` are `extract_text` of those prepared packages.
  - `.pdf` (R73): `pdf_to_docx` writes into a `tempfile.mkdtemp` folder, the result is opened, then the folder is deleted. Result: `kind="pdf"`, `pdf_report` set, `has_revisions=False`, and it is cleaned like any .docx.
  - Extensions are compared without case (`.DOCX` works). Any other extension raises `UnsupportedFileError("The MASK reads Word (.docx) and PDF files.")`.
  - OSError and MaskError subclasses are not caught.
- `combined_text(sources)` names the parts `"<file name> (after)"` and `"<file name> (before)"`. All before parts come after all after parts, in source order. One private `_views()` list drives both `combined_text` and `export_case`, so the two cannot disagree.
- `ExportOptions(out_dir, redline_split=False, retention_days=30, existing_case=None, existing_codes=())` (R74).
- `ExportResult(case, outputs, leak_hits, unmarked, instruction, blocked, allowed_hits=[], unverifiable=[])`. The brief's positional order still constructs.
- `export_case(sources, review, options, engine, user_lists, save_case)`:
  1. **Guards.** Raises ValueError before anything is written (see "Choices beyond the decisions").
  2. **Code.** `new_case_code(existing=options.existing_codes)`, or the case's id when `existing_case` is set.
  3. **Names.** One file of a new case is `MASKED-CODE.docx`. Several files are `-1`, `-2`… A redline adds `-before` / `-after`, and `-1-before` / `-1-after` when there are several files. With `existing_case`, numbering continues after the highest number among the case's masked file names; a file with no number counts as 1. So a case with one file, or with one redline pair, gives `-2`.
  4. **Plan slicing.** One `bisect` per replacement, shifted by its part's start. A replacement outside one part raises ValueError (an explicit check rather than `assert`, so it still runs under `-O`).
  5. **Masking.** For each version, in output order (by source, a redline's before first): copy the prepared package, read its text again, check it is identical to `text_after` / `text_before`, then `apply_mask`, `insert_banner`, and save under the neutral name into a `tempfile.mkdtemp` folder.
  6. **Leak gate (R60).** `scan_package` runs on every staged file with `entries = review.key_entries()`.
     - Allowance per placeholder = the occurrences switched off one by one in enabled groups.
     - `hits_by_placeholder` is summed over all the files. A placeholder blocks when its total is above its allowance.
     - `leak_hits` holds every hit. `allowed_hits` holds the hits of placeholders that do not block. `unverifiable = unverifiable(entries)`.
     - Blocked: `case=None`, `outputs=[]`, `unmarked=[]`, nothing written to `out_dir`, the staging folder is deleted.
  7. **After a clean scan:**
     - `rescan_detection` runs on each staged file; `unmarked` is deduplicated by `normalize(canonical)`.
     - `out_dir` is created with its parents. Each file is written by exclusive create (`open(..., "xb")`), so an existing file is never overwritten; a clash becomes `" (2)"`, `" (3)"`.
     - `Case` holds `MaskedFile(name, sha256 of the bytes written)` and `save_case(case)` is called. If writing or `save_case` fails, the files already written are deleted again and the error is re-raised.
     - `instruction = AI_INSTRUCTION`.
  8. **Existing case.** Its id and `created_at` are kept. `source_files` and `masked_files` are appended to. The key is merged by placeholder:
     - An existing entry the review does not touch is kept (copied).
     - The same placeholder with the same value is kept, with its variants unioned (sorted).
     - A changed value replaces the old entry in place.
     - New entries are appended in review order.
     - `retention_days` comes from the options (decision 7 keeps only the id and the date).
- No logging, and no values printed.

`tests/helpers.py`: added `reviewed(paths, engine, user_lists, redline_split=False, case=None) -> (sources, review)`. It loads, analyses and reviews the way the app should: the review gets the same `CaseLists` that `analyze` filled. For a file added to a case, it passes the case key as `seed_entries` and the key's placeholders as `reserved` (R61). Imports happen inside the function, so `plant` users are unaffected.

## Choices beyond the decisions (please confirm)

1. **Masking works on a copy of the prepared package.** The text is read again from that copy and compared with the prepared text. Masking the prepared packages in place would make a retried export (blocked → back to review → export again with the same sources, as Task 22's flow does) fail with "A paragraph has changed". Nothing is cleaned or accepted again. `test_an_export_never_overwrites_a_file` exports the same sources twice.
2. **Files are written into `out_dir`, not moved.** The bytes come from the staged file and go in by exclusive create, instead of `rename`. This works across volumes and never overwrites, even under a race. The sha256 is taken from exactly those bytes. The staging folder is deleted in all cases.
3. **Rollback when the key cannot be saved.** If `save_case` fails, the masked files are deleted. A masked file without its key could never be restored.
4. **Four guards in `export_case`** (ValueError, before anything is written):
   - no sources;
   - `review.text != combined_text(sources).text`: the plan would hide the wrong characters;
   - sources loaded with `redline_split=True` (they have before versions) but `options.redline_split=False`;
   - `existing_case` whose placeholders are not all in `review.reserved` (R61 enforced). Without reserved, a hand-hidden or split group could take a dropped seed's number, and the merge would then overwrite that entry's value for the case's other files. That is a silent restore error.
5. **Merge reading.** "Existing entries kept" also unions in the new review's variants when the value is unchanged; that is better for seeding later files.
6. **Brief test adaptations.**
   - The banner names `[COMPANY_1]`, so the brief's `"[COMPANY_1]" in texts[1]` was always true. The tests strip the banner first (`body_text`).
   - The brief's long-hand review building (a fresh `CaseLists`, no `reserved`) is replaced by `reviewed()`. The R61 guard would refuse the brief's `r2`.

## Tests

`tests/test_export.py`: 29 tests, all passing.

- **The brief's seven:**
  - single
  - truth values absent everywhere
  - annex shares placeholders (plus one code for both files)
  - redline split
  - nothing marked still exports and reports unmarked (plus an empty key)
  - original unchanged
  - add file to existing case (plus date, source files, masked file names and key placeholders kept)
- **Loading:**
  - `test_load_sources_pdf` (the brief's Task-16 test, plus no temp file left)
  - load prepares each version: the original still has its revisions and custom XML; after and before have them resolved and cleaned, and every text segment points into that very package
  - combined-text names and order
  - only Word and PDF are read (refused `.txt` with the exact message; `.DOCX` accepted)
- **What is masked:**
  - redline versions are the prepared ones: "within 14 days" only before, "within 10 days" and "English language only" only after, no revisions left, placeholders shared
  - several files with a redline are numbered `-1-before`, `-1-after`, `-2`
  - a PDF is masked like a Word file
- **Leak gate:**
  - R60: one occurrence switched off → not blocked, `leak_hits` non-empty and equal to `allowed_hits`, one place.
  - A font named after the company planted in fontTable.xml, plus one occurrence off → two places against an allowance of one → blocked. No case, no outputs, `save_case` not called, `out_dir` and the monkeypatched temp root left empty.
  - The allowance is summed over two files.
  - What nobody marked is listed once across two files.
  - A 7.5% value is reported as unverifiable and is still replaced.
  - The `ExportResult` positional order still constructs.
- **Names and codes:**
  - `existing_codes` respected: a seeded `new_case_code`, with the code in use passed in lower case.
  - Never overwrites: a second export into the same folder gives `MASKED-TEST (2).docx`, the first file is untouched, and the case records the actual name and sha256.
- **Case:**
  - key merge: kept, unioned, replaced, appended; the given case is not mutated
  - numbering continues: after one file, a redline pair, `-1` plus `-2 (2)`, and a redline added after `-2`
- **Refusals and rollback:**
  - the four guards
  - no masked file is left without its key when `save_case` raises

**Mutation checks** (scratch script, file restored after each). Every one of these mutations makes at least one test fail:
- no allowance
- no clean
- masking in place
- overwrite instead of exclusive create
- no rollback
- no R61 guard
- `text_after` read from the original
- keeping the old value on a change
- numbering by count of files
- no review-text guard
- allowance per file instead of summed
- no dedupe of unmarked

**Commands and results:**
- `uv run pytest -q`: **2492 passed in 64.9 s** (baseline 2463).
- `uv run pytest -q tests/test_export.py -W error`: 29 passed, no warnings.
- `uv run ruff check src tests tools`: clean.
- `uv run ruff format --check src tests tools`: 93 files formatted.
- `uv run mypy src`: no issues in 33 files.

## TDD evidence

- **RED:** `uv run pytest -q tests/test_export.py` failed at collection with `ImportError: cannot import name 'export' from 'themask'`. That is expected: the module did not exist yet.
- **GREEN:** after the implementation, 21 of 21 passed on the first run. More tests were added from the mutation checks, giving 29 of 29. One of them failed first: the planted font name was not a variant of the hand-hidden value, so the test was wrong, and I fixed the test.

## Performance (decision 10)

- **supply-10.docx (24 pages, 46 key entries):**
  - `load_sources` 0.03 s; analysis 2.3 s (excluded).
  - `export_case` 2.3 s in total, of which `rescan_detection` (a second analysis) takes about 2.0 s and `scan_package` about 0.2 s.
  - So masking, saving and the leak gate take about 0.25 s, well under 10 s.
- **supply-10.pdf:** load 1.3 s, export 2.3 s.

## Corpus sweep (scratch, not a test)

- Every readable manifest entry was exported through `reviewed()` + `export_case`: 28 Word files and 7 PDFs (scanned-01 refused, as expected), each tracked file also as a redline. **0 blocked.**
- The three contract–annex pairs, exported together (plain and split) and as an annex added to the main file's case: 0 blocked, 0 hits, no key value changed.
- No AMOUNT or PERCENT truth value is visible in any masked text, checked with a `flexible_pattern` search. A crude normalised-blob check flags only very short values ("4", "15"), which are substring coincidences.

## Files

- `src/themask/export.py` (new)
- `tests/test_export.py` (new)
- `tests/helpers.py` (`reviewed()` added; `plant` unchanged)

## Concerns

1. **Hits do not name their output file.** `LeakHit` has no output-file field, so with several outputs a blocked dialog cannot tell the owner which file a hit is in (Task 22). I kept the `LeakHit` contract unchanged.
2. **Values outside a file's text are only taken out of the file where they were marked.** `apply_mask` learns the values from that file's own slice of the plan. Suppose a value is marked in file 1 but appears in file 2 only outside its text (a link target, a field instruction, a bookmark name). The masker leaves it in file 2 and the gate then blocks, with nothing the owner can fix in the review. Not seen in the corpus. A later fix would let `apply_mask` take the whole case's values.
3. **Task 14 parked must-fix (3) is not done here.** It asks for the R60 comparison on the union of placeholders whose values fold alike. That needs a leak-check API that says which placeholders share a fold. The comparison here is per placeholder, as decision 6 says.
4. **The added-file check uses only this review's key.** With `existing_case`, the leak check uses `review.key_entries()` (decision 6). A value of the case that the added file holds only outside its text is not searched for in that file.
5. **The guards are a contract the UI must honour.** The UI (Tasks 21/23) must pass `reserved` for an added file and decide the redline split before analysing; otherwise `export_case` raises ValueError.
6. **Commit trailer.** It is `Co-Authored-By: Claude Opus 5.5`, following this session's attribution rule. The boilerplate names Fable 5.1, and earlier Opus implementers' trailers were accepted.

---

## Pre-review tweak: rulings R81 and R82

**Commit:** 89414f6 feat: case key masks every file's links, hits name their file (R81, R82)

### What changed

**R82** (`src/themask/docx/masker.py`):
- `apply_mask(pkg, doc_text, plan, *, entries: Sequence[KeyEntry] = ())`.
- `_values` adds each entry's value and variants, keeping the plan's own values first (`setdefault`) and mapping each to its entry's placeholder.
- That one `values` table already feeds every pass that runs where the text is not read:
  - `_ValueFinder` for link targets and bookmark/anchor names, and glued instruction words (R14 and R27 floors: at least four normalised characters, digit-only values with digit boundaries);
  - `_Instructions` patterns for `w:instrText` and `w:fldSimple/@w:instr`, including %-decoded matches (R26) and field words kept (R30).
- The visible-text edits still come only from the plan (`_paragraph_edits`), and `MaskReport.replaced` still counts plan replacements only.
- With `entries=()` the behaviour is the same as before; Task 13's tests are untouched and green.
- In `src/themask/export.py`, `_mask` passes `entries=review.key_entries()` for every output.

**R81** (`src/themask/export.py`):
- The scan results are kept per file. With several outputs each `LeakHit` is rebuilt with `dataclasses.replace` and its `part` becomes `"<file name>: <part>"`; a single output keeps the bare part.
- Blocking is computed from the hits before they are renamed, using `hits_by_placeholder` totals over all files, so the counts are unchanged.
- Which name goes in front:
  - blocked export: the staged neutral name;
  - successful export: the name the file was actually written under, so `MASKED-TEST-2 (2).docx` after a name clash.
- `allowed_hits` are taken from the renamed hits.

### Tests (new)

`tests/docx/test_masker.py`:
- `test_the_keys_values_leave_links_instructions_and_names_but_never_the_text`. An annex with no plan replacements, but with:
  - a mailto `w:hyperlink` (unwrapped, its relationship removed);
  - a %-escaped `fldSimple` HYPERLINK (gives `mailto:orders%40[COMPANY_1].example`);
  - a bookmark `Northwind_Terms`, renamed `bm1`, with its PAGEREF following;
  - a visible "Northwind …" paragraph, unchanged.

  Result: `MaskReport(0, 1, 2, 1)`.
- `test_the_keys_values_follow_the_rules_the_plans_values_follow`. A short value "AB1" neither unwraps a link nor renames `_AB1`, but is replaced in a QUOTE instruction. "Page" never touches `PAGE \* MERGEFORMAT`. The text is unchanged. Result: `MaskReport(0, 0, 1, 0)`.

`tests/test_export.py`:
- `test_a_value_marked_in_one_file_leaves_the_links_of_the_others` (R82, the ruling's test). The contract shows the company and `sales@northwind.example`; the annex shows neither but links to `mailto:sales@northwind.example`. After export: not blocked, no hits, no `northwind` left in the annex's `document.xml.rels`, and the link text still there.
- `test_with_several_files_a_hit_names_its_file` (R81, the ruling's test). supply-07 plus its annex, with a font named "Isarthal Hygiene Systems GmbH" planted in the annex's fontTable. Result: blocked; every hit's part matches `MASKED-XXXX-[12].docx: …`, and the planted one is `MASKED-XXXX-2.docx: word/fontTable.xml`.
- `test_a_hit_names_its_file_as_it_was_written` (R81). Two files, the occurrence in file 2 switched off, and `MASKED-TEST-2.docx` already in the output folder. Result: outputs `MASKED-TEST-1.docx` and `MASKED-TEST-2 (2).docx`, and the allowed hit's part is `MASKED-TEST-2 (2).docx: word/document.xml`.
- The existing single-output test still asserts the bare part `word/fontTable.xml`.

### TDD evidence

- **RED:** `uv run pytest -q tests/test_export.py tests/docx/test_masker.py` gave 5 failed, 83 passed:
  - the masker tests failed with `TypeError: apply_mask() got an unexpected keyword argument 'entries'`;
  - the R82 export test was blocked by a `word/_rels/document.xml.rels` hit for `[EMAIL_1]`;
  - the R81 tests failed with `'word/document.xml' != 'MASKED-TEST-2 (2).docx: word/document.xml'` and an unprefixed part.
- **GREEN:** after the change, 88 passed.

**Mutation checks** (file restored after each):
- dropping `entries=` in `_mask` fails the R82 export test;
- never prefixing fails both R81 tests;
- prefixing with the staged names fails the clash test;
- always prefixing fails the single-output test.

### Verification

- `uv run pytest -q`: **2497 passed** (2492 + 5).
- The touched files with `-W error`: 88 passed.
- `uv run ruff check src tests tools`: clean.
- `ruff format --check`: 93 files formatted.
- `uv run mypy src`: clean.

**Corpus sweep** (scratch, rerun):
- 0 of 35 readable files blocked, plain and redline.
- The three contract–annex pairs, exported together and as an added file: 0 blocked, 0 hits, no key value changed.

**Timing:**
- On supply-10, `apply_mask` takes 1–3 ms with the plan alone and 2–6 ms with the plan plus the 46-entry key.
- Whole-export times went up (export 3.5 s, rescan 3.1 s) only because the machine's load average was about 58 during the run; the analysis is unchanged.

### Notes

- R82 passes `review.key_entries()`, as ruled. For a file added to an existing case, passing the merged key (old entries included) would also take out of the new file's links the case values its own review dropped. Those values are still not leak-checked in that file (report concern 4). It is a one-line change if wanted.
- One over-long line in `tests/docx/test_masker.py` (line 659) predates this task and is untouched.
- Earlier concerns: 1 is resolved by R81 and 2 by R82; 3 stays parked; 4 (the UI contract) goes to Task 20.

---

## Pre-review tweak: ruling R83

**Commit:** 8612c29 feat: a file added to a case is masked and checked for the whole key (R83)

### What changed (`src/themask/export.py`)

- **The merged key.** `key = _merged(existing.entries, review.key_entries())` when `existing_case` is set, otherwise `review.key_entries()`. It is computed once and is exactly the list the saved case gets; `_case` now takes this final key instead of merging again.
- **Where the key is used:**
  - `apply_mask(..., entries=key)` for the passes the text is not read in;
  - `scan_package(path, key)`;
  - `rescan_detection(path, ..., key)`;
  - `unverifiable(key)`;
  - the saved `Case.entries`.
- **Allowances (R60) are still computed from the review's groups, with one change I made — please confirm.** A group the owner switched off whole now counts all its findings as left visible on purpose; before, only enabled groups' switched-off occurrences counted.
  - Reason: with the merged key, a seeded case value whose group the owner switched off in the added file's review is now scanned there. Without this change, every visible place would block, so the owner could no longer leave a case value visible in an added file.
  - For a new case nothing changes: a group switched off whole has no key entry, so its placeholder is never scanned.

### Tests (new, `tests/test_export.py`)

- `test_a_value_of_the_case_leaves_a_file_added_that_never_shows_it` (the ruling's first test).
  - Setup: the case key holds `[COMPANY_1]` and `[EMAIL_1]` (sales@northwind.example). The annex text names only Burren Logistics Limited, which the owner hides by hand as `[COMPANY_2]`, but it links to `mailto:sales@northwind.example`.
  - Result: not blocked, no hits, output `MASKED-TEST-2.docx`, no `northwind` in its `document.xml.rels`, the link text still there. The saved key is `[COMPANY_1]`, `[EMAIL_1]`, `[COMPANY_2]`.
- `test_a_leftover_of_a_value_of_the_case_in_a_file_added_blocks` (the ruling's second test). A run of the annex is set in a font named "Northwind Trading B.V.", which the annex text never names. Result: blocked, with one hit `[COMPANY_1]` ×1; nothing saved and no output folder created.
- `test_a_value_of_the_case_left_visible_in_a_file_added_is_allowed` (the allowance change). The seeded `[COMPANY_1]` group is switched off whole and the value is visible twice in the annex. Result: not blocked, 2 places, all of them allowed.

### TDD evidence

- **RED:** 3 failed, 32 passed. All three failures show what was wrong before:
  - the annex's mailto target still named the case's company (a silent leak);
  - the planted font was not blocked;
  - no case value was counted in the added file.
- **GREEN:** 35 of 35 export tests pass, and 91 including the masker tests.

**Mutation checks** (file restored after each):
- `key = entries` (no R83) fails 5 tests: the three new ones and the two key-merge tests, since the saved case now takes the key;
- enabled-only allowances fails the left-visible test;
- scanning with the review key only fails the leftover and left-visible tests.

### Verification

- `uv run pytest -q`: **2500 passed** in 62 s.
- `tests/test_export.py` and `tests/docx/test_masker.py` with `-W error`: 91 passed.
- `uv run ruff check src tests tools`: clean.
- `ruff format --check`: 93 files formatted.
- `uv run mypy src`: clean.

**Sweep:**
- The three contract–annex pairs, together (plain and redline) and with the annex added to the main file's case, now under the merged key: 0 blocked, 0 hits, no key value changed.
- All 35 readable corpus files: 0 blocked.

**Timing on supply-10** (24 pages, load average about 2): export 2.2 s, of which the second detection run takes about 1.95 s and the leak check about 0.2 s.

### Status of the concerns

- Report concern 4 (the added file was checked only for its own review's key) is resolved by R83.
- Concerns 1 and 2 were resolved by R81 and R82.
- Concern 3 stays parked for the final wave.
- The UI contract (reserved placeholders, redline decided before analysis) goes to Task 20.

---

## Fix round 1 (deep review: C1, I1, I2, M1, M5)

**Commit:** 0d004d5 fix: leak gate on a fully masked twin; case retention and values kept (R84-R86)

### What changed (`src/themask/export.py`)

**C1 / R84: the leak gate decides on a twin.** `_allowances` and `_blocking` are gone.

- **The twin plan.** `_whole_plan(review.groups, key)` holds every finding of each group whose placeholder the scanned key holds: the occurrences switched off one by one, and, for a file added to a case, a seeded group switched off whole. It is cut per version like the real plan.
  - For a new case this is exactly "the plan plus the enabled groups' disabled occurrences", since only groups with something to replace are in its key.
  - For an added file, R83's merged key also brings in seeded groups switched off whole. Without them, a case value the owner left visible on purpose would block, or (when the stored entry does not list the visible form) a leftover would pass, as `slack3` showed.
- **The check, per file (`_checked`).** The real file is masked and saved as before.
  - When the twin plan replaces nothing more for that file, the file is its own twin: one mask and one scan, as before.
  - Otherwise the twin is masked into `staging/twins/<same name>` and scanned with the same key.
- **The result:**
  - `leak_hits` = the twins' hits (leftovers); any one blocks, and nothing is saved.
  - `allowed_hits` = the real file's hits minus its twin's, compared by part, placeholder and context, with counts subtracted: the places left visible on purpose. They never gate.
  - Both are named per file by R81 (staged names when blocked, written names otherwise).
- **Contract change:** `leak_hits` used to hold every hit. Now it holds only what blocks; when an export is not blocked it is `[]` and `allowed_hits` lists what was left visible. That suits Task 22's blocked dialog, which shows `leak_hits` only.

**I1 / R85.** `_case` keeps `existing.retention_days` for an existing case; `options.retention_days` is for new cases only.

**I2 / R86.** `_merged` never rewrites a stored value. When the review has an entry for the same placeholder, its value and variants join the stored entry's variants (sorted); an untouched entry is copied as it was.

**M1.** `_check` raises ValueError when `options.redline_split` is on but a source with tracked changes was loaded without its before version.

**M5.** `_told_apart` gives each source its own name in the combined text. Names are compared without case, and a clash gets " (2)", " (3)" before the extension. The saved case's `source_files` keep the original names.

### Tests (`tests/test_export.py`: 41 tests)

**New:**
- **R84, the three routes:**
  - `test_a_form_never_hidden_leaves_no_room_for_a_leftover`: supply-01 with the font "Northwind Trading B.V." planted in fontTable, then `reviewed()` and `add_never_hide("Northwind")`. Blocked; the leftover is `word/fontTable.xml`.
  - `test_a_group_switched_off_in_a_file_added_leaves_no_room_for_a_leftover`: the `slack3` shape. Blocked; the font hit is the only leftover.
  - `test_a_place_switched_off_in_an_instruction_leaves_no_room_for_a_leftover`: the Q2 shape. Blocked.
- `test_a_case_a_file_is_added_to_keeps_its_retention` (R85, Q1 shape): retention 90 is kept and the case expires in the future.
- `test_a_merge_in_a_file_added_never_rewrites_a_value_of_the_case` (R86, Q5): a merge in the added file's review leaves `[COMPANY_1]` as "Northwind Trading B.V.", and the new name appears among its variants.
- `test_files_of_the_same_name_are_told_apart` (M5): `contract.docx`, `Contract.docx` and `contract (2).docx` give `contract.docx`, `Contract (2).docx` and `contract (2) (2).docx`; `locate()` finds the second file.
- The M1 refusal is added to `test_an_export_refuses_what_does_not_fit`.

**Changed to the new contract:**
- The brief's unticked-occurrence test now shows `leak_hits == []` and one place in `allowed_hits`; it still exports.
- The planted-font leftover test is renamed `test_a_leftover_blocks_and_saves_nothing`: the leftover is the font only, and the place switched off is listed apart.
- The cross-file test is renamed `test_a_leftover_in_another_file_blocks`: the leftover is in file 2, the visible place in file 1.
- The name-clash test now has `leak_hits == []`.
- The added-file left-visible test checks its 2 places via `allowed_hits`.
- `test_a_file_added_to_a_case_merges_the_key`: `[COMPANY_2]` stays "Thamesgate Catering plc" and gains the variant "Thamesgate Catering Ltd".

### TDD evidence

- **RED:** `uv run pytest -q tests/test_export.py` gave 13 failed, 28 passed:
  - the three routes were not blocked, and the full legal name was saved;
  - retention was 30 instead of 90;
  - the value was rewritten to "Northwind Holdings International Limited";
  - the names were not unique;
  - the symmetric guard did not raise;
  - the contract-changed tests failed on the old semantics.
- **GREEN:** 41 of 41 pass, and 97 with the masker tests.
- **Reviewer probes after the fix:**
  - `slack2.py` never / untick / never-full: all blocked; the full name is no longer saved.
  - `slack3.py`: blocked for both stored-variant shapes.
  - `edge.py` Q1–Q8: ALL PASS.

**Mutation checks** (file restored after each):

| Mutation | Tests that fail |
|---|---|
| no twin (every real hit blocks) | 5: the places left visible on purpose would block |
| every real hit counted as allowed | the leftover test |
| retention taken from the options | the retention test |
| value rewritten | both merge tests |
| no symmetric guard | the refusals test |
| no unique names | the same-name test |
| twin built from enabled groups only | the added-file left-visible test |

### Verification

- `uv run pytest -q`: **2506 passed** in 64.6 s.
- `tests/test_export.py` and `tests/docx/test_masker.py` with `-W error`: 97 passed.
- `uv run ruff check src tests tools`: clean.
- `ruff format --check`: 93 files formatted.
- `uv run mypy src`: clean.

**Sweep:**
- All 35 readable corpus files: 0 blocked.
- The three contract–annex pairs, together (plain and redline) and with the annex added to the case: 0 blocked, 0 hits, no stored value changed.

### Timing (supply-10, load average about 3)

| | Export | Masking and saving | Scans | Second detection run |
|---|---|---|---|---|
| Nothing switched off (no twin needed) | 2.2 s | 0.02 s | 0.2 s | 1.95 s |
| One occurrence switched off (twin made) | 2.4–2.5 s | 0.03–0.05 s | 0.4 s | 1.95 s |

With a twin, masking and scanning double, as expected; the export stays far under 10 s.

### Parked as instructed

Not touched: the empty out_dir left behind on failure, the shared list object, and the timing/no-logging tests.
