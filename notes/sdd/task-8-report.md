# Task 8 report: lists, variant grouping, sweep and the analysis pipeline

**Status:** DONE_WITH_CONCERNS (the concerns are listed at the end; none blocks the merge)
**Branch / worktree:** `task-8` in `/Users/alijoeee/Developer/the-mask-worktrees/task-8`, from `mac-v1` at 109cbf8
**Commit:** `d0f28ca feat: lists, variant grouping, sweep and analysis pipeline` (trailer: `Co-Authored-By: Claude Opus 5.5`, my own model, as the session's attribution reminder asks; the boilerplate names the controller's Fable 5.1, and the handover says implementers' own model trailers are accepted)

## What I implemented

### `src/themask/paths.py`
- `data_dir()`: `Path(THEMASK_DATA_DIR)` when the variable is set **and not blank**, else `platformdirs.user_data_dir("The MASK", appauthor=False)` (name from `about.APP_NAME`). A blank value is treated as unset, so it never becomes `Path("")`, the current directory.
- `cases_dir()` = `data_dir()/cases`, `log_dir()` = `data_dir()/logs`, `lists_path()` = `data_dir()/lists.json`. Each folder function creates its folder on first use (`parents=True, exist_ok=True`) with mode 0o700. That is an addition: the folders hold keys, logs and the always-hide list. `DATA_DIR_VARIABLE` is the variable's name as a constant.

### `src/themask/detect/lists.py`
- `DEFAULT_NEVER_HIDE: frozenset[str]` holds:
  - roles, document words and legal vocabulary;
  - **public bodies** a contract cites (European Commission, European Central Bank, Bank of England, ICO …);
  - months, weekdays, currency names and codes;
  - countries, including "England and Wales", "European Union" and "EEA". Jordan, Chad and Georgia are left out on purpose because they are common first names;
  - every word in controller decision 5, plus words the corpus showed the model taking for companies: Sub (from "SUB-PROCESSORS"), Time, Assistance, Operations, and department words.
- `term_key()` and the matching: a match ignores case, spacing and punctuation. It also ignores the singular/plural difference, a leading "the", a possessive "'s" and quotes at the ends.
- Beyond plain equality, these also count as never-hide:
  - a document word with its reference: "SCHEDULE 1", "Clause 4.2", "Annex II", "Article 28(3)", and a number before the word ("1.2 Clause");
  - a date in words: "June 2026", "25 June 2026", "Monday, 1 June 2026".
- `is_never_hide(text, user, case)`, as in the brief.
- `never_hide_check(user, case, names=())` returns the same test as a reusable predicate. Its `names` argument puts "names beat terms" into effect: a **defined term** that equals a name found in the document does not count as a term. The owner's never-hide lists and the defaults always count.
- `CaseLists(always_hide, never_hide, defined_terms)`, as in the brief.
- `UserLists(always_hide, never_hide)`:
  - `load` returns empty lists when the file is missing. For a damaged file it raises `MaskError` and never treats it as empty, because the always-hide values would silently stop being hidden.
  - `save` writes a temp file in the same folder with `mkstemp` (mode 0o600), fsyncs it, then calls `os.replace`; the temp file is removed on failure.
  - `add_always`, `add_never`, `remove_always`, `remove_never`. A value is kept on one list at a time: adding it to one list takes it off the other. Duplicates are ignored. A blank value raises `ValueError`.
- `always_hide_entry(entry)`: `TYPE:value` with TYPE one of the twelve placeholder types (any case) gives that type. Anything else is CUSTOM with the whole text as the value. The syntax is documented in the module docstring.

### `src/themask/detect/sweep.py`
- `sweep(text, groups)` adds `Finding(source="sweep", score=1.0)` for every occurrence of every variant that `flexible_pattern` finds. It runs longest variant first across all groups.
- An occurrence is never taken when it:
  - overlaps a finding of any group;
  - overlaps a placeholder already in the text (`find_placeholders`);
  - contains a line or paragraph break. `apply_mask` refuses a replacement across paragraphs, and the part separator is `\n\f\n`.
- After a refused match, the search continues from the next character, so a valid match that starts inside the refused one is still found.
- Blank variants, and variants under 2 normalised characters, are never searched (decision 6).
- New findings are **appended**, so indexes Task 9 keeps in `Group.disabled` stay valid. Running the sweep again adds nothing.
- `Spans`, `occurrences`, `is_searchable` and `LINE_BREAKS` are shared with grouping and the pipeline.

### `src/themask/detect/grouping.py`
`group_findings(findings, text, *, seeds=(), keep=None)`. The brief's signature still works; the two keyword arguments are used by the pipeline.

**People (PERSON)**
- Honorific-free names are equal in any case.
- "F. Last" joins the one full name with that initial and surname.
- A surname-only or honorific+surname mention ("Mr Smith") joins only when exactly one full name fits. Otherwise it becomes its own group with `needs_check`.
- The surname is everything after the first word; particles such as "van der Berg" are handled. The last word alone also counts, but only when the union of fits is a single full name (decision 7).
- `variants_of`'s "J. Berg" form is not relied on. "J. van der Berg" is added as a variant for names of three or more words.

**Companies (COMPANY)**
- Names are merged by their legal-form-free stem. "Ltd" equals "Limited", "Inc." equals "Incorporated", "Corp." equals "Corporation".
- **Two different legal forms on one stem are two companies** ("Northwind Trading B.V." and "Northwind Trading GmbH"), and the bare stem is then a group to check. This is an addition: it avoids a silent merge of sister companies.
- A single word joins the company whose stem or first-word short form it is, when that company is unique.

**Other types** are grouped by their normalised value.

**Additions, driven by the corpus run:**
- Corrections where the model mixes up people and companies:
  - a "company" without a legal form that has an honorific or an initial is a person ("Mr Edwards", "S. Davies");
  - a "person" with a legal form is a company;
  - a one-word "person" that is nobody's surname or first name joins the company it fits ("Acme signs.").
- A "strong" group wins a short form: a seed, or a group whose best score is at least 0.7 and that is not flagged. So the party "Westerkade Insurance N.V." keeps "Westerkade" against the model's 0.6 running header "Westerkade / Liffey — Data Processing Agreement".

**Variants**
- A group's variants are the forms it was seen in plus the forms `variants_of` derives, filtered by `keep`.
- Each variant belongs to one group only:
  - a form a group was seen in, or that is its name, is that group's own;
  - a form that only a seed owns stays with the seed;
  - a derived form that several groups claim, with no single strong winner, belongs to none of them. Where that form stands in the text outside every finding, it becomes its **own `needs_check` group**.
- This is how "Mr Smith" and "J. Smith" with John and Jane Smith are never silently merged by the sweep, while still being hidden.

**needs_check**: true when the best score that is not from the sweep is below 0.7, or the group is an ambiguous mention or shared form. Sweep findings never clear it. Seeds keep their own flag.

**Canonical**: the longest form seen (for PERSON, the longest with a space; for COMPANY, without a leading "the"). Runs of spaces count as one character. On equal length the form not in capitals wins, then the first one.

**Other details**: `placeholder` is left empty. Group ids are `uuid4().hex`. Groups are returned in order of first appearance, with their findings sorted.

### `src/themask/detect/pipeline.py`
- `CombinedText(text, parts)` with `join(named_texts, separator="\n\f\n")` and `locate(offset)`. The end offset of a part belongs to that part. An offset inside a separator or outside the text raises `ValueError`.
- `analyze(combined, engine, user_lists, case_lists=None, seed_entries=None)` runs these steps:
  1. `Engine.analyze` and `find_defined_terms` on **each part separately**, with offsets shifted into the combined text (decision 3). The terms are added to `case_lists.defined_terms`; a `CaseLists` is created when None is passed.
  2. Always-hide matches (`source="list"`, score 1.0, `flexible_pattern`) from the owner's and the case's lists.
  3. Each finding's edges are trimmed: spaces, quotes, an ellipsis, list marks and unmatched brackets. A full stop is kept, as in "B.V.". Findings are then cut at line breaks; for example, the model's `"Northwind Trading B.V. …"` becomes `"Northwind Trading B.V."`.
  4. Findings that overlap an existing placeholder are dropped (decision 8).
  5. Never-hide filter. "Names beat terms" uses a protected set built from PERSON and COMPANY findings (their texts, `variants_of` and legal-form-stripped forms), the always-hide matches and the seeds. Findings that are themselves never-hide terms are excluded from that set. Also dropped are model findings made only of the contract's own words (`contract_rules.is_contract_wording`: "GOVERNING LAW", "the Recipient for the Purpose"). That last rule only covers what the model finds; the ledger asked Task 8 to handle single-line model headings.
  6. Seeds: one `Group` per `KeyEntry`. Its variants are {value} ∪ entry.variants ∪ `variants_of(value)`, filtered the same way. A variant two seeds share is removed from both. Seed occurrences are matched **before** overlaps are settled (decision 9).
  7. Overlap resolution across all findings, keeping one finding per place:
     - the longest wins, counted in letters and digits, so a trailing full stop or a quote adds nothing;
     - on equal length, the **owner's own values (always-hide and seed matches) come first**, then the brief's type order (IBAN … CUSTOM), then the higher score.
  8. `group_findings` with the seeds and `keep`. `keep` excludes never-hide terms and **single** words of the contract's own ("Quality" of Quality Foods Ltd) from the sweep. Multi-word forms are still swept ("General Services" of General Services Ltd).
  9. `sweep`, then empty groups are dropped (a seed without an occurrence disappears), then findings and groups are sorted.
  10. Numbering per type in order of first appearance, from `max(next_free_number(text, type), highest seeded number + 1)`.
  11. The warning `"The document already contains placeholders such as [X]; numbering continues after them."` is added when `next_free_number > 1` for any type. X is the first placeholder actually found in the text.

### Tests and fixtures
- `tests/fixtures/lists.py`:
  - the autouse `private_data_dir` points THEMASK_DATA_DIR at the test's `data_dir`;
  - `lists` is `UserLists([], [])` saved at `lists_path()`.
  - Its imports of the code under test are inside the fixtures, so a broken module cannot stop the whole suite from being collected (the R15 lesson).
- `tests/conftest.py`: `data_dir` now returns `tmp_path_factory.mktemp("data")`. That is a fresh folder **beside** `tmp_path` and the same folder THEMASK_DATA_DIR points at (decision 1 allowed this change). It cannot live inside `tmp_path`, because existing case-store tests assert that `tmp_path` is empty.
- New test files, 195 collected tests in all:
  - `tests/test_paths.py`: 6.
  - `tests/detect/test_lists.py`: 114, counting each parametrised case.
  - `tests/detect/test_sweep.py`: 9.
  - `tests/detect/test_grouping.py`: 25, including the brief's 4.
  - `tests/detect/test_pipeline.py`: 41, including the brief's 8.
- The brief's tests keep the same texts, values and assertions. They are only split into separate lines, and `zip(spans, spans[1:])` and `[...][0]` were rewritten as `itertools.pairwise` and `next(...)`, because the repo's ruff 0.17 rule set (E7, RUF, ISC) rejects the one-line forms.

## Review focus items (controller decision 15)
- **Two people sharing a surname:** `test_shared_surname_not_merged`, `test_two_people_sharing_a_surname` (real engine), `test_initial_and_surname_merge_only_when_one_full_name_fits` and `test_a_shared_short_form_in_the_text_gets_a_group_of_its_own`. "Mr Smith" is its own `needs_check` group, numbered [PERSON_3]. Neither full name keeps "J. Smith" as a variant.
- **Overlapping finds:** `test_overlap_longest_wins` and `test_overlapping_finds_become_one_replacement` cover an IBAN inside an "Account:" line, a company that contains a person's surname, and an e-mail inside a URL. A `MaskPlan` built from every finding is valid (no overlaps), and every finding lies inside one line.
- **Existing placeholders:** `test_existing_placeholders_warning`, `test_altered_placeholders_count_too` (`company_2` counts, so the next number is [COMPANY_3]), `test_nothing_is_found_inside_an_existing_placeholder` and the sweep test `test_sweep_never_touches_an_existing_placeholder`.

## TDD evidence

**RED 1, before any module existed:**
`uv run pytest -q -p no:cacheprovider tests/test_paths.py tests/detect/test_lists.py tests/detect/test_sweep.py tests/detect/test_grouping.py tests/detect/test_pipeline.py`
```
E   ImportError: cannot import name 'paths' from 'themask' (.../src/themask/__init__.py)
E   ModuleNotFoundError: No module named 'themask.detect.lists'
E   ModuleNotFoundError: No module named 'themask.detect.sweep'
E   ModuleNotFoundError: No module named 'themask.detect.grouping'
E   ModuleNotFoundError: No module named 'themask.detect.lists'
!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!
```
This was expected: none of the five modules existed yet. The first run also showed that a fixture plugin importing the code under test at load time breaks the entire suite, so the imports were moved into the fixtures.

**Failures on the way to GREEN, and their fixes:**
- Two save tests and eight existing case-store tests failed because the data folder sat inside `tmp_path`. Fixed by creating it beside `tmp_path` (see the conftest note above).
- One pipeline test got canonical `"blue  harbour"` (two spaces) over "Blue Harbour". Fixed: runs of spaces now count as one character.

**RED 2, regression tests found by the corpus run.** These tests were written after the fixes. To show they test the fixes, I ran them in one process with each fix switched off: no date rule, no number-first reference, no new defaults, no person/company correction, no strong-claimant choice, no contract-wording filter.
`uv run python scratchpad/t8/red_regressions.py`
```
FAILED tests/detect/test_lists.py::test_never_hide_in_every_spelling[1.2 Clause]
FAILED tests/detect/test_lists.py::test_never_hide_in_every_spelling[June 2026]  (+ 3 other date forms)
FAILED tests/detect/test_lists.py::test_never_hide_in_every_spelling[the European Commission]
FAILED tests/detect/test_lists.py::test_never_hide_in_every_spelling[the Bank of England]
FAILED tests/detect/test_lists.py::test_never_hide_in_every_spelling[Time] / [SUB] / [Operations]
FAILED tests/detect/test_grouping.py::test_a_person_the_model_took_for_a_company
FAILED tests/detect/test_grouping.py::test_a_strong_name_wins_its_short_form_over_a_running_header
FAILED tests/detect/test_pipeline.py::test_what_the_model_finds_in_the_contracts_own_words_stays
FAILED tests/detect/test_pipeline.py::test_a_date_the_model_took_for_a_person_stays
14 failed, 18 passed in 0.41s
```

**GREEN:**
- `uv run pytest -q -p no:cacheprovider`: `2137 passed in 24.32s`. The baseline before this task was 1942 passed in 26.16s, so the new tests add no measurable time.
- The new tests alone: `195 passed in 5.39s`, with no warnings.
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

## Whole-corpus evaluation
I ran this over all 28 generated Word files, with scratch scripts outside the repo. A truth occurrence counts as covered when it lies inside some finding.

**Coverage: 1905 of 1915 truth occurrences (99.5%).** ADDRESS, AMOUNT, COMPANY, EMAIL, IBAN, ID, PERCENT, PERSON, PHONE and URL are all at 100%. The sweep brings COMPANY up to 703/703. The 10 misses are all QUANTITY "N records" in the DPAs, which the engine never detects; this is for Task 24.

**Never-hide terms hidden by mistake: 0.** No finding equals a term its own document defines.

**Groups that match no truth value: 5**, down from 82 before the corpus-driven fixes. All 5 are plausible hides: an extra phone number, a person named in a note, an amount in hidden text, the code name "Project Falcon" and the brand "Kraft". Before the fixes, the 82 included:
- "Time" swept 108 times, hiding every "time", as in "from time to time";
- "1.2 Clause" in 25 documents;
- "SUB-PROCESSORS" hidden as "[COMPANY]-processors";
- the European Central Bank, the European Commission and the Bank of England;
- "June 2026" hidden as a PERSON;
- party short names split off into their own `needs_check` groups by the running header line.

**Lower-case sweep hits** (an ordinary word hidden by the sweep): 0.

**Speed:**
- An 80,000-character contract takes about 2.1 s in the engine plus 0.2–0.26 s of pipeline overhead (rules for defined terms, grouping and sweep).
- A case of three files (88,000 characters) takes 2.8 s.

## Files changed
- New: `src/themask/paths.py`, `src/themask/detect/lists.py`, `src/themask/detect/sweep.py`, `src/themask/detect/grouping.py`, `src/themask/detect/pipeline.py`, `tests/fixtures/lists.py`, `tests/test_paths.py`, `tests/detect/test_lists.py`, `tests/detect/test_sweep.py`, `tests/detect/test_grouping.py`, `tests/detect/test_pipeline.py`
- Modified: `tests/conftest.py` (the `data_dir` fixture only)

## Self-review findings, fixed before the commit
- The "number before the word" reference rule first accepted any reference, so "A Schedule" would have been never-hide. It is now restricted to a leading digit, as in "1.2 Clause".
- Excluding every `is_contract_wording` form from the sweep would have stopped "General Services" (of General Services Ltd) from being swept, which is a leak. It is now narrowed to **single** words. Covered by `test_a_name_of_the_contracts_own_words_is_still_swept`.
- A COMPANY canonical with a leading "the" would restore as "the Northwind Group". The "the" is now dropped, the canonical is always among the variants, and `test_a_company_is_named_without_a_leading_the` covers it.
- Seed findings are appended to the seed `Group` objects passed in, so `group_findings` must be called once per set of seeds. The pipeline does that and the docstring says so.
- Size: `grouping.py` is 586 lines (about 140 of them docstring and comments) and `lists.py` 440 lines (about 150 of them term data). Neither looked worth splitting against the plan's one-responsibility-per-file intent.

## Issues and concerns
1. **Numbering happens after the sweep.** The brief's order is group → number → sweep. I number after the sweep so that "first appearance" includes swept occurrences and `[COMPANY_1]` really is the first company in the masked text. Example: "Acme pays … Northwind B.V. … Acme Supplies Ltd" gives Acme `[COMPANY_1]`. `test_a_swept_occurrence_counts_as_the_first_appearance` pins this. If the controller prefers the brief's literal order, the change is to move `_number` above `sweep` and drop that test.
2. **The warning names the first placeholder actually found.** The text matches the brief exactly when that placeholder is `[PERSON_1]`; for a document holding only `[COMPANY_1]` it says `[COMPANY_1]` (`test_altered_placeholders_count_too`).
3. **Task 9's fixture text produces 5 groups, not 3, with the real engine.** For "Acme Supplies Ltd and Northwind Trading B.V. appoint John Smith. Project Falcon starts now; Project Falcon ends later. Acme signs." the groups are:
   - [COMPANY_1] Acme, including the final "Acme", which the model labels PERSON and the person/company correction joins to the company;
   - [COMPANY_2] Northwind;
   - [PERSON_1] John Smith;
   - [COMPANY_3] "Falcon" and [COMPANY_4] "Project Falcon": model ORG findings at 0.6, flagged `needs_check`, hidden by design ("when unsure, hide").

   Task 9's tests assume exactly three groups: `len(review.groups) == 2` after a merge, and `hide_text("Project Falcon")` returning [CUSTOM_1]. The Task 9 dispatch needs a fixture text the model leaves alone, or a ruling.
4. **Behaviours added beyond the brief, all judgement calls and all tested:**
   - the owner's always-hide matches and the case's key win at equal length; the brief's own `test_always_hide_list` needs this, because the model reports COMPANY "Project Falcon" on exactly the list's span;
   - always-hide beats an automatically collected defined term;
   - two legal forms are two companies;
   - the person/company corrections;
   - the strong-claimant choice;
   - a shared form becomes its own `needs_check` group;
   - model findings made of contract words are dropped;
   - single contract words are not swept;
   - dates in words and number-first references are never-hide;
   - the extra default words;
   - a blank THEMASK_DATA_DIR counts as unset; folders are private and the lists file is 0o600;
   - a value lives on one list at a time, and blank values are refused.
5. **Engine and rules observations for Task 24 (not fixed here):**
   - QUANTITY "N records" is never detected (the only corpus misses).
   - The contract rules returned one PERSON span across a sentence end, "Jane van der Berg. Mrs van der Berg", for "Signed by Jane van der Berg. Mrs van der Berg and …". It is hidden whole, so nothing leaks, but the canonical form is odd.
   - The model takes a running header ("Westerkade / Liffey — Data Processing Agreement") for one COMPANY. It is hidden whole and flagged.
   - The model reports "June 2026" as PERSON. The pipeline now keeps dates visible, but the engine could also drop names that fall inside a DATE_TIME span.
6. **`tests/conftest.py` is a shared file.** The change is limited to the `data_dir` fixture's body and docstring, so a merge conflict with a parallel task (Task 16) is unlikely.

---

# Fix round 1: controller rulings R34 and R35 (pre-review)

**Commit:** `68d5d97 fix: the sweep takes over a shorter find it holds (R35)`, on top of d0f28ca.

## R34: numbering after the sweep, and the warning text (accepted as built)
No code change. The test that pins the rule is renamed and made explicit: `test_a_short_form_swept_near_the_top_makes_that_value_number_1`.
- In "Acme pays Jane Doe. Northwind B.V. and Acme Supplies Ltd sign." the engine finds Northwind B.V. first.
- The sweep finds "Acme" at offset 0, so Acme Supplies Ltd is `[COMPANY_1]`. The test asserts that the group's first finding is `("Acme", 0)` with source "sweep".

## R35: a swept occurrence takes over shorter findings it strictly contains
**`src/themask/detect/sweep.py`**
- `sweep(text, groups, fixed=())` takes a new optional `fixed` argument: groups whose findings are never taken over.
- An occurrence whose span strictly contains every finding it overlaps (contains it, and is longer) takes them over:
  - each such finding leaves its group;
  - the whole occurrence joins the sweeping group as one sweep finding. This also works when the shorter finding belongs to the sweeping group itself ("Acme" becomes "Acme Supplies Ltd").
- Never taken over; the occurrence is skipped instead, and the search goes on from the next character:
  - findings with source "list" (always-hide) or "user". I added "user", the owner's own selection in review (Task 9), under the same reasoning that owner authority beats a model guess;
  - findings of a `fixed` group;
  - an occurrence the owner switched off (its index is in `Group.disabled`), and the findings of a group the owner switched off (`enabled=False`). These are owner decisions too; it matters once Task 9 sweeps after a review.
- Unchanged: an equal or partial overlap keeps the finding in place, as do placeholders and line breaks.
- A finding taken out of a group shifts that group's `disabled` indexes, so Task 9's occurrence switches stay right.
- A group whose findings are all taken over is left empty, for the caller to drop. It still sweeps its own variants, so a standalone "Falcon" elsewhere stays hidden.
- Findings in place are now indexed with their groups (`_Places`, bisect by start, bounded by the longest finding), so a takeover can find and remove them.

**`src/themask/detect/pipeline.py`**
- Calls `sweep(text, groups, fixed=seeds)`, so the case's key is never taken over.
- Empty groups are dropped after the sweep and before numbering, as before.
- The module docstring's step 5 describes the takeover.

## Tests added
**`tests/detect/test_sweep.py`: 8 tests**
- a longer occurrence takes over a shorter find, and the group left empty has no findings;
- a group takes over its own shorter find;
- every find inside an occurrence is taken over at once ("Carter" PERSON and "Logistics Ltd" inside "Carter Logistics Ltd");
- the always-hide list is never taken over;
- a `fixed` group is never taken over;
- a switched-off occurrence and a switched-off group are never taken over;
- equal and partial overlaps keep the find in place;
- the `disabled` indexes are right after a takeover.

**`tests/detect/test_pipeline.py`: 4 tests**
- `test_one_code_name_found_two_ways_is_one_group`, the controller's test (a): one COMPANY group "Project Falcon" `[COMPANY_1]` with both occurrences and no "Falcon" group. The engine stub reports exactly the model's two finds.
- `test_the_falcon_text_with_the_real_engine`, test (a) on Task 9's text with the real engine: one Falcon group with both "Project Falcon" occurrences, and no "Falcon" finding anywhere.
- `test_the_owners_always_hide_find_is_never_taken_over`, test (b): always-hide "Falcon" plus the model's "Project Falcon" elsewhere. The "Falcon" occurrence stays `[CUSTOM_1]` (source "list"), and "Project Falcon" `[COMPANY_1]` keeps only its own occurrence.
- `test_a_case_entry_is_never_taken_over`: a seed `[CUSTOM_4]` "Falcon" keeps its occurrence and its placeholder.

**Test (c)**: the existing "longest wins / never nested" tests (`test_overlap_longest_wins`, `test_overlapping_finds_become_one_replacement`, and every test that builds a `MaskPlan` from all findings) still pass.

## TDD evidence
**RED** (the new tests against the d0f28ca sweep):
`uv run pytest -q -p no:cacheprovider tests/detect/test_sweep.py tests/detect/test_pipeline.py`
```
FAILED tests/detect/test_sweep.py::test_a_longer_occurrence_takes_over_a_shorter_find
FAILED tests/detect/test_sweep.py::test_a_group_takes_over_its_own_shorter_find
FAILED tests/detect/test_sweep.py::test_every_find_inside_is_taken_over_at_once
FAILED tests/detect/test_sweep.py::test_a_fixed_group_is_never_taken_over - T...   (no `fixed` argument yet)
FAILED tests/detect/test_sweep.py::test_taking_over_keeps_the_switched_off_indexes_right
FAILED tests/detect/test_pipeline.py::test_one_code_name_found_two_ways_is_one_group
FAILED tests/detect/test_pipeline.py::test_the_falcon_text_with_the_real_engine
7 failed, 55 passed in 5.64s
```
This was expected: the old sweep never takes a span over. The tests for what must stay in place (the list, a seed, switched-off finds, equal and partial overlaps) already passed and still pass. One new fixture had overlapping findings by mistake; I fixed it before implementing.

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect/test_sweep.py tests/detect/test_pipeline.py tests/detect/test_grouping.py` gives `87 passed in 5.75s`.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2149 passed in 24.35s` (12 new). All of this task's tests: `207 passed in 5.53s`, no warnings.
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

**Corpus re-run (28 Word files):**
- 1905 of 1915 truth occurrences covered, the same as before.
- The same 5 groups match no truth value, and the per-document group counts are identical.
- No document hides a term it defines.

**Task 9's fixture text now gives 4 groups**: Acme `[COMPANY_1]`, Northwind `[COMPANY_2]`, John Smith `[PERSON_1]`, and Project Falcon `[COMPANY_3]` with both occurrences (model 0.6, `needs_check`). Before this fix it gave 5.

## Concerns
None new. One note for Task 9: its `hide_text` will call `sweep` after a review. A swept occurrence can then take a finding out of another enabled, unreviewed group and leave that group empty, so Task 9 should drop or ignore empty groups as the pipeline does. Owner decisions are never moved: switched-off finds, the always-hide list, the owner's own selections and `fixed` groups.

---

# Fix round 2: review fix round 1 (Important 1–4, rulings R42–R46, raised minors R43)

**Commit:** `b25f8cc fix: surname forms beat terms, shared initials checked, exact placeholders only`, on top of 68d5d97. 10 files changed, +583 −91.

## What changed, item by item

**Important 1: a person's defined short name no longer leaks**
- **Protected names** (`pipeline._names`): every full PERSON name found, and every PERSON seed, now adds its surname forms through `grouping.PersonName.short_forms()`. These are the surname and its last word, each on its own, after any honorific, and after the first initial: "van der Berg", "Berg", "Ms van der Berg", "Mr Berg", "J. van der Berg", "J. Berg". A defined term equal to one of them no longer suppresses a finding.
- **Defined terms as variants** (`group_findings(..., aliases=...)`; the pipeline passes `case.defined_terms`). A term that is a surname form of a full name found becomes that person's derived variant, so the sweep hides it.
  - This part is needed for `John Smith ("Smith")`: the engine finds no "Smith" at all there, so protecting the term alone hides nothing.
  - A term several people fit ("Smith" with John and Jane Smith) belongs to none of them. Where it occurs, it becomes its own `needs_check` group.
- **Real engine, the reviewer's three probes:**
  - `[COMPANY_1] appoints [PERSON_1] (the "Consultant", or "[PERSON_1]"). [PERSON_1] shall report weekly.`
  - `[PERSON_1] ("[PERSON_1]"). [PERSON_1] shall provide the Services.`
  - `[PERSON_1] ("[PERSON_1]"). [PERSON_1] shall attend every meeting.`
- **Known side effect:** a defined term that equals a found person's surname but means something else would now be hidden. Example: Laura Mill and `the "Mill"`. Over-hiding, never a leak. A default term such as "Price" is still protected by the defaults.

**Important 2: a shared initial is never given to the stronger name**
- New `_form_owner`: the "only strong claimant" choice (`_chosen`) now applies to companies only.
- A form that two people fit is always shared. Where it stands in the text, it becomes its own `needs_check` group.
- With a stub engine (John Smith 0.85, the model's company "Ms Jane Smith" 0.6) the reviewer's text masks to `[PERSON_1] and [PERSON_2] sign. [PERSON_3] attends every meeting.`, and [PERSON_3] is flagged.

**Important 3: one legal form in two spellings is one company**
- New `_legal_form_key`: the form is normalised (no case, dots or spaces), decomposed with NFKD, and stripped of its combining marks, then the Ltd/Limited, Inc/Incorporated and Corp/Corporation synonyms are applied.
- "Ltd. Şti." equals "Ltd. Sti.", "A.Ş." equals "A.S.", "B.V." equals "BV".
- Both probe texts give one company group with both occurrences, with the real engine.
- Accepted side effect: Danish "A/S" and Turkish "A.Ş." now compare equal. Two companies with one stem in those two countries would merge, which is very unlikely.

**Important 4 / R42**
`_surnames_kept` covers a PERSON finding of one capitalised word, with or without an honorific, that is a default never-hide word. It is kept, and its group flagged `needs_check`, when all of these hold:
- exactly one full PERSON name found ends with that word;
- the word before it on its line is not a determiner (the, such, this, that, any, each, no);
- the word is not on the owner's or the case's own never-hide list.

The kept word is then removed from every group's variants before the sweep. It stays hidden at that one place but is never swept through the document, so "the Price" elsewhere stays visible, and the leak check won't look for it.

**R44: only exact placeholders count in a source**
- New `sweep.existing_placeholders(text)` returns the exact `[TYPE_N]` matches only. It feeds:
  - the drop rule (`analyze`);
  - the sweep's guard;
  - the shared-form search in grouping;
  - numbering (`_number` now counts from the exact placeholders and the case's key);
  - the warning.
- `next_free_number` is no longer used here, because it also counts altered forms.
- Real engine on "Customer ID-55821 shall be quoted on every invoice.": "55821" is hidden as [AMOUNT_1] (flagged) and there is no warning. With a stub ID finding the group is [ID_1], not [ID_55822].

**R45**: `_without_overruns` drops a model finding when a rule finding of the same type, starting at the same offset, with a legal form and score ≥ 0.9, ends before it. With the real engine, "Name: Jane Doe, for Acme Supplies Ltd. Passport number: 534412786." now gives the canonical "Acme Supplies Ltd" (it was "Acme Supplies Ltd. Passport"). A rule name without a legal form ("Jane Doe") still loses to the model's longer span ("Jane Doe Smith"); that case is tested too.

**R46**: findings on one span are settled first (`_span_winner`):
1. the owner's own values (always-hide and seed matches);
2. then candidates whose score is within 0.1 of the best, using a 1e-9 tolerance because 0.85 − 0.75 is 0.0999… in floating point;
3. then the brief's type order;
4. then the higher score.

The greedy longest-first pass then runs over the per-span winners. With the real engine, the passport number is [ID_1] (ID 0.85 against PHONE 0.75). With a stub, ID 0.80 against PHONE 0.75 is [PHONE_1].

**R43: raised minors**
- **M1**: single-word company mentions are keyed by their name without "the", so "the Acme" joins Acme Supplies Ltd. The cross-type person check also uses the name without "the".
- **M3**: a group switched off sweeps nothing, and `may_take_over` refuses when the sweeping group is switched off.
- **M4**: `UserLists.load` reads bytes and decodes inside the `try`, so a non-UTF-8 file raises `MaskError`.
- **M5**: `flexible_pattern`'s word edges (Task 3's `textnorm.py`) now treat a letter or digit of any script as part of a word: "Gül" is not in "Gülşen", "Smith" not in "Smithé", "12" not after an Arabic-Indic digit.
  - The class is `[^\W_<numbers that are not decimal digits>]`. The excluded numbers (category No/Nl in the Basic Multilingual Plane, about 35 ranges) are computed at import in about 4 ms.
  - With that exclusion, a footnote mark such as "Smith¹" still ends a word, so Task 3's existing test stays green; `\w` alone would count "¹" as alphanumeric.
- **M10**: forms seen with fewer than 2 normalised characters ("5%") leave `Group.variants`, and the canonical is added only when it is searchable.

## Tests added or changed (34 new; every reviewer probe is a test text)
**`tests/detect/test_pipeline.py`** (61 tests):
- the three Important 1 probes, with exact masked output and the real engine;
- the Important 2 probe, with a stub;
- both Important 3 probes, with the real engine;
- R42: the Price and Banks texts hidden and flagged; "the Price shall be paid" stays visible; the owner's never-hide "Price" stays visible; "Ms Price" is hidden and flagged (real engine);
- R44: the ID-55821 probe with the real engine and with a stub;
- R45: the probe text with the real engine, plus the stub case where the rule has no legal form;
- R46: the two score cases;
- changed: `test_altered_placeholders_count_too` became `test_only_exact_placeholders_count` ("company_2" is text now, so Northwind is [COMPANY_2]).

**`tests/detect/test_grouping.py`** (34 tests):
- a weak claimant still makes a shared initial a check, both with Jane Smith 0.6 and with the model's company "Ms Jane Smith";
- a defined surname form becomes its person's variant, and is checked when two people share it;
- three legal-form spelling triples;
- "the Acme" (M1);
- tiny forms (M10).

**`tests/detect/test_sweep.py`** (19 tests):
- a group switched off (M3);
- words in any script (M5);
- changed: the placeholder test now expects "company_2" to be swept as text (R44).

**`tests/detect/test_lists.py`**: the non-UTF-8 file (M4).

**`tests/test_textnorm.py`**: 5 script-edge cases, plus a check that a word next to non-letters of any script is still found, superscript and fraction marks included.

## TDD evidence
**RED** (the new tests, before any implementation):
`uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py`
```
FAILED tests/detect/test_grouping.py::test_a_weak_name_still_makes_a_shared_initial_a_check[jane0] / [jane1]
FAILED tests/detect/test_grouping.py::test_a_defined_surname_form_is_its_persons_variant
FAILED tests/detect/test_grouping.py::test_a_defined_surname_two_people_share_is_checked
FAILED tests/detect/test_grouping.py::test_one_legal_form_spelt_two_ways_is_one_company[names0] / [names1]
FAILED tests/detect/test_grouping.py::test_a_company_with_a_leading_the_joins_its_name
FAILED tests/detect/test_grouping.py::test_a_form_too_short_to_search_is_no_variant
FAILED tests/detect/test_lists.py::test_load_refuses_a_file_that_is_not_utf8
FAILED tests/detect/test_pipeline.py::test_a_persons_defined_short_name_is_hidden (all 3 probes)
FAILED tests/detect/test_pipeline.py::test_a_shared_initial_is_never_given_to_the_stronger_name
FAILED tests/detect/test_pipeline.py::test_one_legal_form_spelt_two_ways_is_one_company (both probes)
FAILED tests/detect/test_pipeline.py::test_a_surname_that_is_a_default_term_stays_hidden (Price, Banks)
FAILED tests/detect/test_pipeline.py::test_a_default_term_with_an_honorific_is_flagged
FAILED tests/detect/test_pipeline.py::test_a_rule_name_with_its_legal_form_keeps_its_end
FAILED tests/detect/test_pipeline.py::test_a_rule_name_beats_a_longer_model_span_only_with_its_legal_form
FAILED tests/detect/test_pipeline.py::test_on_one_span_a_clearly_higher_score_wins[0.85-0.75-ID]
FAILED tests/detect/test_pipeline.py::test_only_exact_placeholders_count
FAILED tests/detect/test_pipeline.py::test_a_bare_reference_like_id_55821_is_a_value
FAILED tests/detect/test_sweep.py::test_sweep_never_touches_an_existing_placeholder
FAILED tests/detect/test_sweep.py::test_a_group_switched_off_neither_sweeps_nor_takes_over
FAILED tests/detect/test_sweep.py::test_a_word_is_whole_in_any_script
FAILED tests/test_textnorm.py::test_flexible_pattern_word_edges_hold_in_any_script (all 5 cases)
31 failed, 1268 passed in 8.02s
```
- These failures were expected: each one asks for behaviour this round adds.
- The new tests that already passed are the ones that pin unchanged behaviour: a determiner keeps "the Price" visible, the owner's never-hide list wins, closer scores go by the type order, and a word beside non-letters is still found.
- The `test_a_persons_defined_short_name_is_hidden["Mr John Smith"]` case first passed for the wrong reason: the model's inner "Smith" was hidden, but "Mr" showed. I tightened all three probes to exact masked strings before implementing.
- During implementation one new test had a stub offset that was off by one. The stub skips mismatched findings, so the test failed silently; I fixed the fixture to compute offsets from the text.

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py tests/test_paths.py` gives `1305 passed in 7.73s`.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2183 passed in 23.99s` (2149 + 34).
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: clean once `textnorm.py` was reformatted (a blank line).

**Corpus re-run (28 Word files):**
- 1905 of 1915 truth occurrences covered, unchanged.
- The same 5 groups match no truth value, and the per-document group counts are identical.
- No lower-case sweep hits, and no document hides a term it defines.
- The three existing-placeholder documents (dpa-04, nda-03, supply-09) still warn about [PERSON_1].

## Concerns
1. **R42 cannot act where the engine finds nothing.** The ruling works on findings, but the real engine reports no bare "Price" in "Katie Price signs for the Supplier. Price shall attend.", and no bare "Banks" in the Banks text. With the real engine those two probes still show the word. The R42 tests therefore use a stub engine that reports the bare word, as the ruling describes.
   - This is a detection gap for any surname, not only default words: "Katie Smith … Smith shall attend." gives no "Smith" finding either, and the brief keeps bare surnames out of the sweep's variants.
   - Candidates: Task 24 (engine tuning), or a ruling on attributing bare surnames when exactly one full name fits.
2. **Side effects I accepted:**
   - a defined term equal to a found person's surname is hidden as that person (the Laura Mill / `the "Mill"` case);
   - Danish "A/S" and Turkish "A.Ş." compare as one legal form;
   - `textnorm.py` (Task 3's file) changed as ruled; its tests stay green.

---

# Fix round 3: review fix round 2 (ruling R50)

**Commit:** `2c008e7 fix: sweep a person's bare surname where it stands as a name (R50)`, on top of b25f8cc. 7 files changed, +387 −61.

## What changed
**Bare surnames as variants** (`grouping.SurnamePolicy`; `group_findings(..., surnames=...)`; `PersonName.surnames()`)
- Every PERSON group with a full name, seeds included, gets its bare surname as a variant: the last word, and for a name with particles all that follows the first name ("Berg" and "van der Berg").
- The pipeline's policy:
  - `allowed`: the surname is not on the owner's or the case's own never-hide list, which always wins;
  - `only_one`: a default never-hide word ("Price", "Banks") is a variant only when exactly one person found ends with it (R42's attribution). With two people it belongs to no one and stays visible.
- Any other surname two people share becomes its own group, flagged `needs_check` (the existing shared-form rule).
- A surname a person and a company share (John Carter and Carter Logistics Ltd) gives a PERSON shared group, so the name guard applies.

**The name guard** (`sweep.is_bare_name`, `sweep.stands_as_a_name`, `sweep.after_a_determiner`)
- A PERSON variant of one word, or a surname with its particles, with no honorific, is matched only where it stands as a name:
  - capitalised (particles aside);
  - not after a determiner: the, such, this, that, any, each, no, a, an.
- A surname's own particles are skipped when looking for that determiner. Without this, "Berg" in "the van der Berg file" was swept as the last word after "der"; the first test run caught it.
- The guard applies everywhere a person's bare name is searched:
  - the sweep, including Task 9's re-sweeps;
  - the case key's seed matching;
  - the shared-form groups;
  - round 1's defined-term surname forms.
- The determiner list is shared with R42, which therefore now also counts "a" and "an".

**Flagging**: after the sweep, a group gets `needs_check` when the sweep hid one of its person's bare names that is also an ordinary word of the contract (`pipeline._ordinary`). That means a default never-hide word, a COMMON_WORDS word, a term the document defines, or a single word of the contract's own. "Smith" is not flagged.

**Laura Mill**: the model itself reports the "Mill" in "The Mill shall be maintained" as a person, and since names beat terms that finding would have been kept. Now a person's bare-name finding that is a defined term but does not stand as a name is dropped (`pipeline._term_not_a_name`): names beat terms only where the word stands as a name.

**Variants**:
- The R42 variant cleanup now keeps a person's bare names; the sweep guards them.
- A surname or initial form now derives no further variants. Task 3's `variants_of` turned the seen "van der Berg" into a junk "v. Berg".

**`textnorm.NAME_PARTICLES`** now holds the particle list that grouping and the sweep both use. Grouping's private copy is gone; contract_rules keeps its own, as the ledger notes.

## Tests (19 new; the real-engine ones are the evidence)
**`tests/detect/test_pipeline.py`, real engine, exact masked text and flag:**
- "Katie Price signs for the Supplier. Price shall attend." gives `[PERSON_1] signs for the Supplier. [PERSON_1] shall attend.`, flagged.
- "Jo Banks signs for the Buyer. Banks shall be notified." is hidden and flagged.
- "Katie Smith signs. Smith shall attend." is hidden and not flagged.
- "Katie Price signs for the Supplier. The Price shall be paid." keeps "The Price" visible, not flagged.
- The Laura Mill text (`Laura Mill manages the old factory (the "Mill"). The Mill shall be maintained by the Supplier. Mill shall attend every inspection.`) gives `[PERSON_1] manages the old factory (the "Mill"). The Mill shall be maintained by the Supplier. [PERSON_1] shall attend every inspection.`, flagged.
- "Jane van der Berg signs for the Supplier; van der Berg shall report monthly." is hidden. Here the model finds the bare "van der Berg" itself.
- Owner never-hide "Price": `[PERSON_1] signs for the Supplier. Price shall attend.`
- "John Smith and Jane Smith sign for the Buyer. Smith shall attend." gives `[PERSON_3]` for "Smith", flagged.
- "Katie Price and Tom Price sign for the Buyer. Price shall attend." keeps "Price" visible.

**`tests/detect/test_pipeline.py`, stubs:**
- the particle path through the sweep itself ("the van der Berg file" stays visible), because the model always finds a bare "van der Berg" on its own;
- a case-key entry's bare surname stays a name;
- the two R42 stub tests are kept, now asserting that the word is a (guarded) variant.

**`tests/detect/test_grouping.py`**:
- the bare surname as a variant, with particles;
- the policy refusing a surname;
- a default word two people end with belongs to no one;
- a shared surname checked only where it stands as a name.

**`tests/detect/test_sweep.py`**: the guard ("The Mill", "a Mill", "mill-race" refused; "MILL" taken), other types unguarded, `is_bare_name`, and `stands_as_a_name`.

## TDD evidence
**RED**: the new tests against the round-1 source. I extracted b25f8cc's `src` with `git archive` and put it first on `PYTHONPATH`:
`PYTHONPATH=<b25f8cc src> uv run pytest -q -p no:cacheprovider tests/detect/test_pipeline.py`
```
FAILED test_a_surname_that_is_a_default_term_stays_hidden[Katie Price … / Jo Banks …]   (both)
FAILED test_a_persons_bare_surname_is_hidden_where_it_names_them[Katie Price …]
FAILED test_a_persons_bare_surname_is_hidden_where_it_names_them[Jo Banks …]
FAILED test_a_persons_bare_surname_is_hidden_where_it_names_them[Katie Smith …]
FAILED test_a_persons_bare_surname_is_hidden_where_it_names_them[Laura Mill …]
FAILED test_a_surname_two_people_share_is_a_group_to_check
FAILED test_a_surname_with_particles_is_swept_as_a_name
FAILED test_a_case_entrys_bare_surname_stays_a_name
9 failed, 63 passed in 5.11s
```
- The grouping and sweep test files fail to import there (`cannot import name 'SurnamePolicy'`, `'is_bare_name'`).
- New cases that already pass on round 1 pin behaviour that must not change: "The Price" visible, the owner's list, two Prices visible, and van der Berg (found by the model).
- This round I wrote the code before the tests, so this RED run against the earlier commit is the evidence.

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py tests/test_paths.py` gives `1324 passed in 8.28s`.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2202 passed in 23.79s` (2183 + 19).
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

## Corpus numbers (28 Word files)
- **Coverage:** 1905 of 1915 truth occurrences (99.5%), unchanged. All 10 misses are "N records" quantities the engine never detects.
- **Non-secret groups:** 5, the same ones, with identical per-document group counts.
- **Defined terms hidden:** none, in any of the 28 documents. No lower-case sweep hits.
- **Bare surnames swept:** 0. The corpus always names people with an honorific or an initial ("Mr Bennett", "J. Parker", "Ms Lynda Stevens"), so R50 neither adds coverage nor over-hides there. The real-engine tests above are the evidence for R50.

## Concerns
1. **Task 14 must search bare surnames with the same guard.** A person's bare surname is now in `Group.variants`, as the ruling says, and so in Task 9's key entries. The leak check searches every variant everywhere, so it would block an export on the "the Price" or "The Mill" this ruling leaves visible on purpose; lower-case "price" and "mill" inside "sawmill" would block it too. Task 14 should search such a variant only where it stands as a name, with `sweep.is_bare_name(kind, variant)` and `sweep.stands_as_a_name(text, start, end)`, or skip it. The masker replaces the planned occurrences, so nothing marked is left behind.
2. **Over-hiding risk for surnames that are ordinary capitalised words.** "Tom English" with "English law", or "Rob French" with "French law", would hide the governing law. The R50 guard does not stop that, and English and French are not default never-hide words, so the group is not even flagged. Adding nationality adjectives to `DEFAULT_NEVER_HIDE` would at least flag it (R42 would still hide it for a single English). I have not added them; that is the controller's call.
3. The same over-hiding applies to an all-capitals heading ("PRICE AND PAYMENT") and to a compound term ("Total Price", "Price List" at a line start) when a person found is named Price. Those are flagged, since Price is a default word; the owner can switch them off.

---

# Fix round 4: rulings R52 and R53

**Commit:** `ccc93ab fix: nationality and language words are never hidden by default (R53)`, on top of 2c008e7. 4 files changed, +53 −4.

## R52 (concern 1 settled for Tasks 9 and 14)
No behaviour change. `sweep.stands_as_a_name(text, start, end)` is public and importable, and so are `sweep.is_bare_name(kind, variant)` and `sweep.after_a_determiner(text, start)`. The docstring now says how the leak check calls it:
- `text` is any raw text the occurrence was found in, a whole document's or one paragraph's;
- `start`-`end` is the occurrence's span in that text;
- it holds when every word but the surname's particles is capitalised, and the word before the occurrence on its line, particles aside, is not a determiner;
- the sweep applies it, so the leak check should too, and occurrences left visible on purpose then do not count as leaks.

## R53 (concern 2)
`lists._NATIONALITIES`, now part of `DEFAULT_NEVER_HIDE`, holds nationality and language adjectives:
- the ruling's list: English, Dutch, German, French, Turkish, British, European, American, Belgian, Spanish, Italian, Swiss, Irish, Scottish, Welsh, Danish, Swedish, Norwegian, Finnish, Polish, Austrian, Portuguese, Greek, Chinese, Japanese, Indian, Luxembourgish, Czech, Hungarian, Romanian;
- "and the like": Northern Irish, Flemish, Catalan, Basque, Icelandic, Slovak, Slovenian, Croatian, Serbian, Bulgarian, the Baltic nationalities, Maltese, Cypriot, Russian, Ukrainian, Canadian, Mexican, Brazilian, Argentinian, Chilean, Australian, Korean, Pakistani, Singaporean, Malaysian, Indonesian, Thai, Vietnamese, Arabic, Arab, Emirati, Saudi, Israeli, Hebrew, Egyptian, Moroccan, Nigerian, Kenyan, South African, Latin, Mandarin, Cantonese, Hindi, Persian.

Region words that start corpus company names ("Baltic", "Nordic", "Hanseatic") are left out on purpose, because a default word stops being a company's first-word short form; "Baltic" of Baltic Fasteners GmbH would then stay visible.

Effect on a person named by such a word ("Tom English"): through R42/R50 the word is hidden only where exactly one person found ends with it and no determiner stands before it, and the group is flagged `needs_check`.

## Tests (17 new, real engine where the ruling asks)
- `test_a_surname_that_is_a_nationality_is_checked`: "Tom English signs for the Supplier. This Agreement is governed by English law and the parties submit to the English courts." gives `[PERSON_1] signs for the Supplier. This Agreement is governed by [PERSON_1] law and the parties submit to the English courts.`, flagged `needs_check`. "the English courts" stays visible.
- `test_a_nationality_without_a_person_of_that_name_stays`: "This Agreement is governed by Dutch law." creates no group.
- `test_default_never_hide_holds`: 15 new cases, one for each of English, Dutch, German, French, Turkish, British, Luxembourgish, Swiss, Irish, Polish, Czech, Hungarian, Romanian, Greek and Chinese.

## TDD evidence
**RED** (before the change):
`uv run pytest -q -p no:cacheprovider tests/detect/test_lists.py tests/detect/test_pipeline.py -k "default_never_hide_holds or nationality"`
```
FAILED tests/detect/test_lists.py::test_default_never_hide_holds[English] … [Chinese]   (all 15)
FAILED tests/detect/test_pipeline.py::test_a_surname_that_is_a_nationality_is_checked
16 failed, 46 passed, 142 deselected in 1.85s
```
Before the change, "English law" was hidden without a flag. The "Dutch law" test passed already, because no group was ever created for it.

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py tests/test_paths.py` gives `1341 passed in 8.48s`.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2219 passed in 24.20s` (2202 + 17).
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

## Corpus numbers (28 Word files), unchanged
- 1905 of 1915 truth occurrences covered (99.5%).
- The same 5 non-secret groups, with identical per-document group counts.
- No defined term hidden in any of the 28 documents.
- The corpus surname "French" is unaffected, because its documents always write it with a first name or an honorific.

---

# Fix round 5: review fix round 3 (N1, N2, N4, N5, O1, O3; rulings R54, R55)

**Commit:** `f34338a fix: a bare surname only where it stands alone as a name (R54, R55)`, on top of ccc93ab. 7 files changed, +454 −57.

## What changed
**R54, `sweep.stands_as_a_name(text, start, end, is_term=is_default_term)`**
Still public and documented for Task 14. Besides capitals and the determiner guard, it now refuses an occurrence:
- **N1, capitalised neighbour**: a capitalised word right before or after it on its line, with nothing but spaces between, that is not an honorific, an initial or a particle. Refuses "Business Day", "Companies House", "Long Stop", "Performance Bond", "High Court"; a comma separates ("Price, Director" still passes).
- **N1, line of capitals**: the line's letters are all capitals ("2. GRANT OF LICENCE").
- **N5, month beside a number**: a month with a number as the adjacent token on its line ("dated 1 May 2026", "May 30, 2026"). A sentence end parts them: "… 1 June 2026. May shall attend" still passes.
- **N1, part of a longer term**: part of a term the caller's `is_term` knows. Phrases run over words joined only by spaces on its line, up to six words, longest first ("Terms of Use", "High Court of Justice", "Long Stop Date").

**`is_term` everywhere the name test runs**
- The pipeline builds it once: `never_hide_check(user_lists, case)`, which covers the defaults, the owner's and the case's lists, and the defined terms.
- It reaches `sweep(..., is_term=)`, `occurrences(..., is_term=)`, the seed matching, `SurnamePolicy.is_term` (the shared-form groups and grouping's attachment test) and R42's `_surnames_kept`, which now uses the full name test.
- **New default terms**: Terms of Use, Terms and Conditions, General Terms and Conditions, Long Stop Date, Bank Holiday, Public Holiday, Performance Bond, Parent Company Guarantee, Grant of Licence, Licence; and the courts (High Court, High Court of Justice, Court of Appeal, Supreme Court, County Court, Commercial Court, District Court). The model reported "the High Court of Justice" as a company, which is now dropped.

**N2, the attachment test**
- In grouping, a bare-name finding that joins a person as their surname must stand as a name, whatever type the model gave it. Findings that don't stand as a name are left out, so they stay visible. This covers:
  - same-type surname mentions with at least one claim, particle surnames included;
  - the model's one-word "company" that joins a person.
- Sam Lodge: the model's COMPANY "Lodge" in "The Lodge" stays visible. "Lodge shall attend" is hidden and flagged, since "Lodge" is a defined term.
- Round 2's pipeline-level `_term_not_a_name` is removed; this test covers it.

**N4, a surname that is another person's first name**
- In `_place_people`, a one-word mention that is the first name of a full name other than its claim becomes its own flagged group.
- In `_settle_variants`, that person is added as a second claimant for the surname form, so it becomes shared (a flagged group where it stands as a name) instead of one person's variant.
- Example: "James" with Sarah James and James Wilson.

**Flag**: a bare-name finding in a person's group that is an ordinary word (a default word, a COMMON_WORDS word, a defined term, a single contract word) now flags the group whether the sweep or the engine found it.

**R55 (O1)**: `pipeline._people_among_parties` retypes a rule party as PERSON before the names are built, when all of these hold:
- it is a COMPANY of two or three capitalised words, from source "rule";
- it has no legal form and no company word (COMMON_WORDS plus Foods, Ventures, Associates, Partnership, Bank, Insurance, Media, Properties, Engineering, Construction, Energy, Pharma, Healthcare, Retail);
- the bracket straight after it defines its last word (`("Smith")`, `(the "Smith")`).

I did this in the pipeline, not in `contract_rules.find_parties`, so Task 7's module and tests are untouched.

**R55 (O3)**: `grouping._companies_by_their_name` makes a PERSON finding of two or more words whose normalised text equals the stem of a COMPANY found with a legal form (seeds included) into a COMPANY, so it joins that company by its stem.

## Tests (31 new; real engine except where the ruling says stub)
**`tests/detect/test_pipeline.py`, real engine, exact masked text:**
- `TERMS_AND_HEADINGS`, eight N1 texts: Business Day (Doris Day), Companies House (Tom House), GRANT OF LICENCE (Hugh Grant), Long Stop Date (Tom Long), High Court of Justice (Ann Court), Terms of Use (Ann Terms), Performance Bond (Rob Bond), and "Price, Director" (comma). In each the phrase stays visible and the standalone "Day / House / Grant / Long / Court / Terms / Bond shall attend" is hidden.
- The Sam Lodge text: `[PERSON_1] manages the site (the "Lodge"). The Lodge shall be kept open daily. [PERSON_1] shall attend.`
- Sarah James and James Wilson: `[PERSON_1] and [PERSON_2] sign for the Buyer. [PERSON_3] shall attend.`, with [PERSON_3] flagged.
- O1: `This Agreement is made between [COMPANY_1] and [PERSON_1] ("[PERSON_1]"). [PERSON_1] shall provide the Services.`
- O3: `[COMPANY_1] signs the order. [COMPANY_1] invoices monthly.`

**`tests/detect/test_pipeline.py`, stub**: Theresa May (the model reads only "Theresa"). "dated 1 May 2026" stays visible; "May shall attend" is hidden and flagged.

**`tests/detect/test_grouping.py`**: a first name of another person; a word joining a person must stand as a name (the model's company "Lodge"); a person named like a company without its legal form.

**`tests/detect/test_sweep.py`**:
- `test_a_name_stands_alone`: 14 cases.
- the caller's term list ("Gate of Honour");
- changed: the M5 word-edge test now uses company groups. The new neighbour rule rightly refuses "Gül" right after "Gülşen" for a person, and that test is about word edges only.

## TDD evidence
**RED**: the new tests against ccc93ab's source (`git archive`, first on `PYTHONPATH`):
```
pipeline and grouping (-k on the new names): 15 failed, 1 passed
  FAILED test_a_surname_inside_a_term_or_heading_stays[Doris Day … / Tom House … / Hugh Grant … / Tom Long …
         / Ann Court … / Ann Terms … / Rob Bond …]
  FAILED test_a_surname_form_the_model_took_for_a_company_follows_the_guard_too
  FAILED test_a_surname_that_is_another_persons_first_name_is_checked
  FAILED test_a_month_surname_beside_a_number_is_a_date
  FAILED test_a_party_shortened_to_its_surname_is_a_person
  FAILED test_a_company_name_without_its_legal_form_joins_the_company
  FAILED test_grouping.py::test_a_surname_that_is_another_persons_first_name_fits_neither
  FAILED test_grouping.py::test_a_word_that_joins_a_person_as_their_surname_must_stand_as_a_name
  FAILED test_grouping.py::test_a_person_named_like_a_company_without_its_legal_form_joins_it
sweep (-k "stands_alone or callers_lists"): 10 failed, 5 passed
```
- What still passes on ccc93ab is the behaviour that must not change: "Price, Director", "Day shall attend", "May shall attend", "Mr Price", and a full stop after a date.
- During the work two of my own new tests were wrong and I fixed them: a person-group M5 test refused by the new neighbour rule, and a "Gate" between capitalised words in the caller's-list test.
- The month rule also needed the sentence-end exception: "2026." at the end of one sentence is not beside "May" at the start of the next.

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py tests/test_paths.py` gives `1372 passed in 8.65s`.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2250 passed in 23.82s` (2219 + 31).
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

## Corpus numbers (28 Word files)
- **Coverage:** 1905 of 1915 truth occurrences (99.5%), unchanged. The 10 misses are "N records" quantities the engine never detects.
- **Non-secret groups:** 5, the same ones, with identical per-document group counts.
- **Defined terms hidden:** none, in any of the 28 documents.
- **Bare surnames swept:** 0. The corpus writes names with an honorific or an initial.

## Concerns
None new.
- The R55 retyping lives in the pipeline (`_people_among_parties`), so the parties rule in `contract_rules` still reports such a party as a company to its own callers. The ruling allowed either place; the pipeline keeps Task 7's module untouched.
- Phrases are checked up to six words. A longer multi-word term containing a surname would not be recognised by that check, but the capitalised-neighbour rule usually catches such terms first.

---

# Fix round 6: review fix round 4 (NB1, NB2; ruling R56)

**Commit:** `44a5426 fix: where the engine saw a name, and what parts a name from its phrase (R56)`, on top of f34338a. 6 files changed, +340 −35.

The usage-limit interruption came after the probe and before any edit, so the worktree was still clean at f34338a. This round was written from there, tests first.

## What changed
**R56 (a): `stands_as_a_name(..., found_by_engine=True)`**
- Only the determiner guard applies, for bare surnames the engine itself reported.
- Grouping uses it when the engine's own one-word finding joins a person: same-type surname mentions, and a "company" that joins a person (`grouping._a_name_there`).
- R42's `_surnames_kept` uses it too.
- The owner's own entries (sources "list" and "user") are never tested.
- The capitalised-neighbour, capitals-line, longer-term and month guards stay for the sweep's finds (source "sweep").

**R56 (b)**: a line that holds nothing but the name (punctuation and underscores aside) is a name, not a capitals heading ("SMITH" under "Signed: ____").

**R56 (c), separators.** These part a name from its neighbours, as a comma does:
- a salutation right before it: Dear, Attn, Attention, To, From, cc;
- a job title right after it, read over up to four words that must start with a capital (`contract_rules.is_job_title`): "Smith Director", "Smith Finance Director". The capital rule matters because `is_job_title` accepts "of Attorney";
- a label's colon after the neighbour ("Smith Title: Director");
- a tab. Phrase words are joined only by spaces now, so "Name:\tSmith\tTitle:\tDirector" counts as separate fields.

**R56 (d), phrases over a connective.**
- The phrase test now also looks across a lowercase connective (of, and, for, to, in, on, the) and across "&", on both sides: "Grant of Rights", "Power of Attorney", "Field of Use", "Rights of Grant", "Smith & Co".
- The exception is a word beyond the connective that is a found name. `stands_as_a_name` takes `is_name`; `sweep.name_test(groups)` builds it from the people's and companies' variants and seen forms, and the seed matching and the shared-form groups build the same.
- So "Price and Smith sign" hides both names.

**Every guard is still in `stands_as_a_name`**, public and documented. Its keyword parameters are `is_name` and `found_by_engine`, so Task 14's leak check inherits all of them.

## Tests (32 new)
**`tests/detect/test_pipeline.py`, real engine, exact masked text and flag** (`SEEN_AND_SEPARATED`):
- "Smith Director" is hidden.
- "SMITH" on its own line under "Signed: ____" is hidden.
- "Dear Price," is hidden and flagged, as R42/R50 already flag a default word.
- Must stay hidden: "Price, Director"; "Price" and "Director" on two lines; "Yours, Smith".
- NB2: "2. Grant of Rights" and "Power of Attorney dated 1 March 2026." stay visible, with "Grant/Power shall attend" hidden.
- "Price and Smith sign the annex.": both hidden.

**`tests/detect/test_pipeline.py`, stubs** (the engine reports only the full name, so these are the sweep's spots):
- "Approved by Smith Finance Director.";
- "Name:\tSmith\tTitle:\tDirector";
- "Smith/Jones";
- "Field of Use: Europe." stays visible while "Field shall attend" is hidden (the real engine finds nothing in that text);
- R56 (a) directly: the engine's own "Smith" in "Smith Holdings" is hidden, and its "Smith" in "the Smith file" stays visible.

**`tests/detect/test_sweep.py`**: 15 cases of `test_a_swept_name_stands_alone`, the `is_name` exception, and `found_by_engine` (capitals, months and neighbours don't count; a determiner does). The caller's-term test now uses "Gate area" as the term, because R56 (d) rightly treats "Gate of Honour" as a phrase.

**`tests/detect/test_grouping.py`**: the engine's "Smith" beside a capital still joins John Smith.

## TDD evidence
**RED** (the new tests against the unchanged f34338a code):
`uv run pytest -q -p no:cacheprovider tests/detect`
```
FAILED test_grouping.py::test_a_surname_the_engine_found_beside_a_capital_still_joins_its_person
FAILED test_pipeline.py::test_a_surname_by_a_separator_is_hidden_and_a_phrase_stays[Smith Director / SMITH line /
       Dear Price / Grant of Rights / Power of Attorney]   (5)
FAILED test_pipeline.py::test_the_sweep_by_a_separator_where_the_engine_found_only_the_person[Smith Finance Director /
       Name-Title tabs / Field of Use]   (3)
FAILED test_pipeline.py::test_a_surname_the_engine_found_needs_only_no_determiner
FAILED test_sweep.py::test_a_swept_name_stands_alone[…]   (12)
FAILED test_sweep.py::test_a_name_found_beyond_a_connective_is_no_phrase
FAILED test_sweep.py::test_where_the_engine_saw_a_name_only_a_determiner_counts
24 failed, 854 passed in 7.96s
```
The new cases that already passed are the ones that must not change: the four "must stay hidden" texts, the two-names text, "Smith/Jones" (no neighbour after a slash), and "Signed: ____ SMITH" on one line.

While implementing, two fixes to my own first version were needed:
- **Title after a connective**: "of Attorney" passed as a job title, so a title must now start with a capital.
- **Colon beyond a connective**: I had let a colon after the word beyond a connective part the phrase, but "Field of Use:" is one label.

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py tests/test_paths.py` gives `1404 passed in 9.25s`. Every earlier R50, R54 and R55 test is still green.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2282 passed in 26.46s` (2250 + 32).
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

## Corpus numbers (28 Word files)
- **Coverage:** 1905 of 1915 truth occurrences (99.5%), unchanged. The 10 misses are "N records" quantities.
- **Non-secret groups:** 5, the same ones, with identical per-document group counts.
- **Defined terms hidden:** none, in any of the 28 documents.
- **Bare surnames swept:** 0.

## Observations (no leak; for the reviewer and Task 24)
With the real engine, two of the stub-only texts take a different path, because the model itself reports a company span:
- "Approved by Smith Finance Director." gives COMPANY "Smith Finance" (0.6, flagged), masked "Approved by [COMPANY_1] Director." Smith is hidden, but as a separate company group.
- "Name:\tSmith\tTitle:\tDirector" gives COMPANY "Smith\tTitle" (0.85) across the tab, masked "Name:\t[COMPANY_1]:\tDirector". The label "Title" is hidden with it.
- A possible engine-side fix: cut model findings at a tab as they are cut at a line break. Then the rule's PERSON "Smith" would win (R46) and "Title" would drop as a label word. I did not add it; it is outside R56.

---

# Fix round 7: ruling R58 (model findings cut at tabs)

**Commit:** `b3daf3a fix: cut the model's findings at tabs as at line breaks (R58)`, on top of 44a5426. 3 files changed.

## What changed
- **`src/themask/detect/engine.py` (Task 6/7's module, as the ruling allows):**
  - `_lines_of` already held the model-specific newline cut. It now cuts a model finding at a tab too, using `_PART_BREAK = [\n\t]`, and keeps each part with at least two visible characters that names somebody (`_names_nobody`, unchanged).
  - The module docstring says so.
  - For "Name:\tSmith\tTitle:\tDirector", the model's COMPANY "Smith\tTitle:\t" becomes the parts "Smith" and "Title:" (the empty part after the last tab is dropped). "Title:" is a label word, so it names nobody and is dropped. The model's "Smith" has the same span as the signature rule's own PERSON "Smith", so the engine keeps the rule's finding, and it joins John Smith.
- Engine output on that text, probed with the old `src` (44a5426, via `git archive` + PYTHONPATH) and with the new one:
  ```
  old: model PERSON 'John Smith' 0 10 | rule PERSON 'Smith' 41 46 | model COMPANY 'Smith\tTitle:\t' 41 54
  new: model PERSON 'John Smith' 0 10 | rule PERSON 'Smith' 41 46
  ```
- **Pipeline unchanged**: `_cleaned` still cuts every finding at line breaks only. As ruled, only model findings are cut at tabs. Rule, pattern and list findings keep their spans.

## Tests (2 new, real engine)
- `tests/detect/test_contract_rules.py::test_model_findings_never_cross_a_tab`: on "John Smith signs for the Supplier.\nName:\tSmith\tTitle:\tDirector", no engine finding holds a tab, "Smith" is found, and "Title" is not.
- `tests/detect/test_pipeline.py::test_a_tab_separated_signature_line_keeps_its_labels`: the same text masks to `[PERSON_1] signs for the Supplier.\nName:\t[PERSON_1]\tTitle:\tDirector`, unflagged.

## TDD evidence
**RED** (before the change):
`uv run pytest -q -p no:cacheprovider tests/detect -k "never_cross_a_tab or tab_separated_signature"`
```
FAILED tests/detect/test_contract_rules.py::test_model_findings_never_cross_a_tab
FAILED tests/detect/test_pipeline.py::test_a_tab_separated_signature_line_keeps_its_labels
2 failed, 878 deselected in 2.50s
```

**GREEN:**
- Focused: `uv run pytest -q -p no:cacheprovider tests/detect tests/test_textnorm.py tests/test_paths.py` gives `1406 passed in 10.62s`, including every Task 6/7 engine and rules test.
- Full: `uv run pytest -q -p no:cacheprovider` gives `2284 passed in 33.22s` (2282 + 2).
- `uv run ruff check src tests tools`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 27 source files`
- `uv run ruff format --check src tests tools`: `77 files already formatted`

## Corpus numbers (28 Word files), unchanged
- 1905 of 1915 truth occurrences covered (99.5%).
- The same 5 non-secret groups, with identical per-document group counts.
- No defined term hidden in any of the 28 documents.
- The corpus text holds no tabs, so the cut cannot change it.
