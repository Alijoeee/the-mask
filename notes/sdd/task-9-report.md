# Task 9 report — Review state (`src/themask/review.py`)

**Status: DONE_WITH_CONCERNS** (nothing blocked; three small readings of the decisions and two hand-offs to later tasks are listed under "Concerns"). Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-9`, branch `task-9`, one commit on top of `d201148`:

- `857e89d feat: review state with enable, hide, merge, split and lists`

## What I implemented

`src/themask/review.py` (388 lines, one class plus small helpers, no Qt):

- `ReviewCounts(groups, enabled, needs_check, replacements)` (frozen dataclass).
- `ReviewState(text, groups, warnings, user_lists, case_lists)` with `from_analysis(analysis, user_lists, case_lists)`, `set_group_enabled`, `set_occurrence_enabled`, `hide_text(value, type) -> Group`, `merge(group_ids) -> Group`, `split(group_id, finding_indexes) -> Group`, `add_always_hide(value)`, `add_never_hide(value)`, `mask_plan() -> MaskPlan`, `key_entries() -> list[KeyEntry]`, `counts() -> ReviewCounts`.
- `tests/fixtures/review.py`: the `review` fixture, exactly as decision 1 writes it (real engine, `lists`, `CaseLists([], [], set())`), the brief's text as `REVIEW_TEXT`.
- `tests/test_review.py`: the brief's seven tests (group counts made relative, decision 1) plus 33 more: 40 tests.

## How each controller decision was applied

1. **Fixture / pinned order** — `test_the_fixture_groups_come_in_the_order_the_brief_expects` pins `[COMPANY_1] Acme Supplies Ltd (2)`, `[COMPANY_2] Northwind Trading B.V. (1)`, `[PERSON_1] John Smith (1)`, `[COMPANY_3] Project Falcon (2, needs_check)`. `test_merge_keeps_lowest_number` asserts `len(review.groups) == n - 1`.
2. **`hide_text`** — value stripped; fewer than two letters/digits → `ValueError`. The group that has the value (normalised) among its canonical/variants is looked up, one of the same type first. Same type: the occurrences join it. Another type: that whole group is re-typed (same id; new placeholder = next free number of the new type; `needs_check` cleared; its findings become `type=new, score=1.0, source="user"`). None: new group (uuid4 hex, canonical = value, variants = {value}, `needs_check=False`, next free number). In every case the group is switched on, then **every occurrence of the value that no finding or existing `[TYPE_N]` overlaps becomes a `"user"` finding** (via `sweep.occurrences`, which uses `flexible_pattern`; no bare-name test, see concern 5), then `sweep(text, groups, fixed=[group], is_term=never_hide_check(user, case))` runs so a longer occurrence takes over shorter non-owner findings (R35), and what that sweep adds to the group is also marked `"user"`. Never-hide lists are not consulted: the owner's call wins (`test_hide_text_beats_the_never_hide_lists`). `ValueError` when nothing could be hidden (not in the text, runs over a line break, already inside a longer finding); the state is untouched then.
3. **Empty groups** — `_tidy()` after every sweep: drops groups with no finding, puts each group's findings in text order (remapping `disabled`), keeps `groups` in order of first appearance, all in place (`groups` is the same list object). Nothing is renumbered (`test_a_group_a_sweep_leaves_empty_is_dropped`).
4. **`merge`** — distinct ids, at least two, same type else `ValueError`; the group with the lowest number survives (its id and placeholder), union of variants and canonicals, `needs_check = any`, findings in text order with `disabled` remapped, then `sweep` + `_tidy`. Canonical: see concern 2. Switches: see concern 4.
5. **`split`** — new group: uuid4 id, the moved findings, canonical = longest moved text, variants = the moved texts, next free number of the type; the original keeps the rest with `disabled` remapped; `ValueError` for an empty list, an index out of range, or a split that would empty the original. Beyond the decision: the new group copies `enabled`, `needs_check` and the moved occurrences' switches; the original loses variants only the moved texts showed and, if its canonical moved with them, takes the fullest text it still shows.
6. **Lists** — `add_always_hide`: `user_lists.add_always`, `save(lists_path())`, then `hide_text` with `always_hide_entry`'s type (`company:Falcon Freight` → COMPANY, plain → CUSTOM); a value this document lacks (or one too short to look for) is only saved, no error; blank → `ValueError` from `add_always`. `add_never_hide`: `add_never`, `save`, then every group whose canonical or any variant matches the value the way the lists match (`on_never_hide_list` against a list of just that value: case, singular/plural, leading "the") is switched off.
7. **`mask_plan()`** — `Replacement(f.start, f.end, group.placeholder)` for every `active_findings()`, wrapped in `MaskPlan`.
8. **`key_entries()`** — one entry per group that masks something, value = canonical, variants = all variants minus R52 (see concern 3) minus variants shorter than two normalised characters (`is_searchable`), sorted; entries ordered by type then number (concern 1).
9. **`counts()`** — `needs_check` counts enabled flagged groups; `replacements` counts active findings.
10. **Attributes** — `text`, `groups`, `warnings` (copy of the analysis's), `user_lists`, `case_lists` (the very objects given, so the caller's lists change). `from_analysis` works on copies of the groups, so the analysis is not changed by the review (`test_the_review_leaves_the_analysis_alone`). 388 lines.
11. **Tests beyond the brief** — all the ones decision 11 lists, plus a few more where behaviour needed pinning (list below).

## Tests

`uv run pytest tests/test_review.py -q` → `40 passed`. Full suite, ruff, ruff format, mypy: see "Final verification".

The 40: the brief's 7; fixture order; mask plan in text order; occurrence off/on; counts; unknown group/occurrence refused; analysis left alone; re-type on `hide_text`; new group numbering; emptied group dropped; never-hide beaten; bare name the sweep left visible (R54); group switched back on; refusals (blank, one letter, absent, inside a longer finding); line break; numbering after the exact placeholders in the text only (R44); merge refuses mixed types and one group; merge unites variants/findings/marks/`disabled` remap; merge sweeps for the united variants; merge keeps a switched-off group's occurrences off; split next free number; split carries switches and repairs canonical; company canonical without leading "the" on merge and split; split refusals; `add_never_hide` persists and disables / nothing to disable; `add_always_hide` persists and hides / typed entry / value absent; key order; key only for what is masked; key without bare surname (R52); key without particle surname and tiny variants.

### TDD evidence

RED (tests and fixture written first, `themask/review.py` absent):

```
$ uv run pytest tests/test_review.py -q -p no:cacheprovider
____________________ ERROR collecting tests/test_review.py _____________________
tests/test_review.py:15: in <module>
    from themask.review import ReviewCounts, ReviewState
E   ModuleNotFoundError: No module named 'themask.review'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.31s
```
Expected: the module under test did not exist yet.

GREEN (after `review.py`): `37 passed in 6.03s` on the first run of the first 37 tests; after strengthening and adding tests: `40 passed in 5.48s`.

### Beyond the unit tests

- **Mutation check** — 25 hand-made breakages of `review.py` (no `enabled = True`, no direct scan, numbering from groups only, no R52, aliasing in `from_analysis`, `disabled` not remapped on merge/split, empty groups kept, key for every enabled group, wrong lowest number, "the" kept in canonical, sources left as "sweep", alphabetical type order, no sweep after merge/hide, lists not saved, …). The first pass left two alive (`split` not remapping the original's `disabled`, sweep-found findings keeping source "sweep"); I strengthened `test_split_carries_the_switches_and_repairs_the_canonical` and `test_a_group_a_sweep_leaves_empty_is_dropped`; all 25 are killed now.
- **Real documents** — a throwaway probe (not committed) analysed all 28 corpus `.docx` files with the real engine and ran: a plain re-sweep (changes nothing in any file), a merge per type, a split, a `hide_text`, group switching. After each step it checked: no empty group, no duplicate placeholder, findings sorted and equal to their text, `disabled` indexes valid, groups in first-appearance order, `mask_plan()` builds (no overlaps), plan placeholders == key placeholders. Zero violations. A merge, a hide or a re-sweep on the 80 000-character `services-05.docx` takes about 0.25 s.

## Files changed

- `src/themask/review.py` (new, 388 lines)
- `tests/fixtures/review.py` (new, 34 lines; picked up by `conftest.py`'s plugin glob)
- `tests/test_review.py` (new, 473 lines)

## Self-review

- Completeness: every method and signature of the brief; every decision 1–11 (readings below). Edge cases: unknown ids, bad indexes, duplicate ids, blank/short/absent/line-crossing text, a group switched off, a group emptied by a sweep, a text that already holds placeholders.
- Quality: helpers are small and named for what they do (`_canonical`, `_in_text_order`, `_key_variants`, `_number`); `_hide` is the one place `hide_text` and `add_always_hide` share; all mutation is in place so the screen's list object stays valid.
- Discipline: nothing beyond the brief except what the decisions' own rules need (`_tidy`, the copy in `from_analysis`, the split repairs, the merge switches).
- Output pristine: no warnings in any run.

## Concerns (for the controller)

1. **"Order: by placeholder type then number" is ambiguous.** I used the order the types are declared (PERSON, COMPANY, AMOUNT, PERCENT, QUANTITY, EMAIL, PHONE, ADDRESS, IBAN, ID, URL, CUSTOM), as the spec lists them; alphabetical would put COMPANY first. One line in `key_entries` (`_TYPE_ORDER`) and one test to change if you meant alphabetical.
2. **Merge canonical = the fullest of the merged groups' canonical forms, not the longest variant.** The real engine reports "the Northwind Group" as a finding, so it is a variant while the canonical is "Northwind Group" (grouping strips the "the"); "longest variant" would make `the Kestrel Foods Company` the canonical and restore would write that back. For the same reason `split` (and `merge`) strip a leading "the" from a company's canonical as `grouping._canonical` does. For every group the analysis makes, the canonical already is the longest variant, so the two readings agree except in this case.
3. **R52 drop set** is exactly `PersonName.of(canonical).surnames()`, compared normalised, so it includes the particle part ("van der Berg", three words) as the ruling says "or its particle part", although decision 8 says "single-word". A bare surname of a person whose canonical is not a full name ("Mr J. Smith") is not dropped; the leak check will then see it and may report a false positive (safe direction). This matches what Task 14 can derive from `entry.value`.
4. **Two small additions to the decisions.** (a) `key_entries` skips an enabled group that has no active finding (all its occurrences switched off one by one), so the key always equals the plan — decision 8 says "enabled group", the brief's own test pins plan == key. (b) `merge` keeps each occurrence's switch: where the merged group is on, the occurrences of a group that was off stay off (otherwise merging would reveal what the owner hid, or hide what the owner left visible); `enabled = any(...)`.
5. **`hide_text` finds its occurrences itself** (besides the sweep) so the sweep's bare-name test (R50/R54: determiner, phrase, capitals line, month, term) does not apply to the owner's own selection. Without it "hide it by hand", the safety net R54 relies on, would not work for a bare surname in "Smith Report". It means `hide_text("Smith", PERSON)` hides every "Smith" that no finding covers, "the Smith report" included; the owner switches single occurrences off.
6. **Re-typing is by the whole group, as decided**, also when the selected text is only a derived variant of a group of another type (`hide_text("Acme", PERSON)` re-types all of `[COMPANY_1] Acme Supplies Ltd` to `[PERSON_2]`). Nothing becomes visible; only the label changes. Say if you would rather move just the occurrences of that text.
7. **Hand-off, Task 15/23 — numbering vs. the case's key.** A new review group (`hide_text`, `split`) takes the next number after the text's exact placeholders and the groups' own. `ReviewState` does not see key entries that do not occur in the new file (analysis drops them), so after "Add file to this case" a new group could reuse a number the key holds. Cheap fix when needed: an optional `reserved: Collection[str]` on `from_analysis` feeding `_next_placeholder`.
8. **Hand-off, Task 15/23 — seeds are not `fixed` in the review's sweeps.** The pipeline protects the key's groups from takeover; `ReviewState` cannot know which groups they are, so a sweep run by `hide_text`/`merge` may let a longer variant of another group take over a seed's finding (still hidden, only under another placeholder).
9. **Hand-off, Task 14/15 — leak check vs. switched-off occurrences.** A group with some occurrences switched off keeps its key entry, so the leak check will find those visible occurrences. If that should not block, the check needs the plan (spans left visible on purpose).
10. `add_always_hide`/`add_never_hide` let an `OSError` from `UserLists.save` through; the in-memory list has changed then, the groups have not.
11. **Commit trailer**: the harness requires `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and the ledger says implementers' own model trailers are accepted (b3daf3a carries Opus 5.5), so the commit has that line, not the boilerplate's Fable 5.1 line.
12. **Baseline flake**: on the untouched branch, `tests/pdf/test_extractor.py::test_twenty_four_pages_are_read_quickly` failed once in my baseline run while the machine was loaded by other work (load average above 100); it passes in the full runs below. Unrelated to this task.

## Final verification

On the committed tree (`857e89d`), from the worktree, with the machine loaded by other work:

```
$ uv run pytest -q && uv run ruff check src tests tools && uv run ruff format --check src tests tools && uv run mypy src
2402 passed in 68.14s (0:01:08)
All checks passed!
87 files already formatted
Success: no issues found in 31 source files
```

Baseline before my change was 2361 passed + the one timing flake of concern 12 (2362 tests); the 40 new tests make 2402. An earlier full run before the last test-only edits: `2401 passed in 93.54s`.

---

# Fix report — ruling R61 (`reserved` placeholders of an existing case's key)

Asked by the controller after the first report: concerns 3a (numbering vs. the case's key) and 3b (seeds not `fixed` in the review's sweeps) are resolved by R61; concern 3c is settled by R60 (nothing to do here). Concerns 1 and 2 were accepted as built.

## What changed

`src/themask/review.py` (405 lines now, up from 388: still one class plus small helpers; the growth is mostly docstrings):

- `ReviewState.from_analysis(analysis, user_lists, case_lists, reserved: Collection[str] = ())` and `ReviewState.__init__(..., reserved=())`; the state keeps `self.reserved` as a `frozenset[str]`. Callers that do not pass it behave exactly as before.
- **Numbering** — `_next_placeholder` takes the highest number of the type among the exact `[TYPE_N]` of the text, the groups' placeholders **and the reserved placeholders**, plus one. So `hide_text` (new group), `split` and a re-typed group never take a reserved number, even when no group of this file holds it. A reserved entry that is not an exact placeholder is ignored by the numbering (it cannot clash with anything).
- **Sweeps** — `_sweep`, the one place the review runs `sweep`, now passes `fixed=[*fixed, *keyed]`, where `keyed` are the groups whose placeholder is reserved. `hide_text` and `merge` both go through it, so a longer text the owner hides, or the united variants of a merge, never take over a keyed group's finding (the analysis protected them the same way).
- Docstrings (module, class, `from_analysis`, `_next_placeholder`, `_sweep`) say so.

## Tests (`tests/test_review.py`, 4 new, 44 in the file)

- `test_a_number_the_case_key_holds_is_never_taken_by_a_new_group` — reserved `[COMPANY_2]`, no group in the file: `hide_text("Baltic Fasteners GmbH", COMPANY)` gets `[COMPANY_3]` (the controller's case).
- `test_a_split_and_a_re_typed_group_skip_the_numbers_the_case_key_holds` — reserved `[COMPANY_5]` and `[CUSTOM_2]`: a split gets `[COMPANY_6]`, a re-typed group `[CUSTOM_3]`.
- `test_a_group_the_case_key_holds_is_not_taken_over_by_a_longer_hidden_text` — a keyed group's finding survives a `hide_text` whose value contains it (the controller's case); the same state without `reserved` shows the takeover and the dropped group, so the test would catch a missing `fixed`.
- `test_a_merge_does_not_take_over_a_group_the_case_key_holds` — the same protection on the merge path.

The shared `hand_made` helper now takes `reserved=()`.

RED (tests written first; `from_analysis` had no `reserved`):

```
$ uv run pytest tests/test_review.py -q -p no:cacheprovider
E       TypeError: ReviewState.from_analysis() takes 4 positional arguments but 5 were given   (x18)
18 failed, 26 passed
```
The 18 are the 4 new tests plus the 14 hand-made ones that go through the shared helper, which now forwards `reserved`. Expected: the parameter did not exist.

GREEN after the change: `44 passed in 4.90s`.

Mutation check of the R61 pieces (each makes at least one of the 4 tests fail): numbering ignores `reserved`; sweeps ignore the keyed groups; keyed groups fixed only when a target is given (merge unprotected); `reserved` never stored; `from_analysis` drops `reserved`. All five killed.

## Note, no change made

Re-typing a keyed group (`hide_text` with another type) gives it a new number, so that value has two placeholders across the case's files (the old one stays in the case's key). That is the owner's explicit choice, as before; the old placeholder is no longer reserved-protected afterwards, but its findings are now `"user"` findings, which no sweep takes over either.

## Commit and verification

- `225f01e feat: keep an existing case key's numbers and groups safe in the review (R61)` (on top of `857e89d`; trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` as before). Files: `src/themask/review.py`, `tests/test_review.py`. The tree is clean.
- On the tree that was committed, from the worktree:

```
$ uv run ruff format --check src tests tools && uv run ruff check src tests tools && uv run mypy src && uv run pytest -q
87 files already formatted
All checks passed!
Success: no issues found in 31 source files
2406 passed in 87.08s (0:01:27)
```

2402 before this change plus the 4 new tests. Focused: `uv run pytest tests/test_review.py -q` → `44 passed`.

## Status after the fix

DONE_WITH_CONCERNS as before, with one change to report: `src/themask/review.py` is now 405 lines (the controller's guide was about 400); it is still one class plus small helpers and I did not split it. The hand-offs 3a and 3b of the first report are closed by this change; 3c is the controller's R60.

---

# Fix report — review round 1 (one Important, one Minor, ruling R62)

Commit `58533b7 fix: never-hide stops hiding only what is the term; a plain always-hide keeps a group's type (R62)`, on top of `225f01e`. Files: `src/themask/review.py`, `tests/test_review.py`. Nothing from the parked list was touched (hide_text over switched-off text, atomic list save, `_canonical` duplication, naming).

## IMPORTANT 1 — `add_never_hide` failed open

Cause: any matching variant switched the whole group off, so `add_never_hide("Price")` made "Mark Price" visible, and `add_never_hide("THE ACME")` made "Acme Supplies Ltd" visible.

Fix (`add_never_hide`): the term is matched as before (`on_never_hide_list` against a list of just that value: case, singular/plural, leading "the"), but applied per group:

- the group is **switched off** when its **canonical form** is the term, or **every one of its occurrences** (finding texts) is;
- otherwise only the occurrences whose text is the term are added to `group.disabled`, and the variants that are the term are **dropped from `group.variants`**, so the key (`key_entries`) and later sweeps agree with it. The group's own value and its longer forms stay hidden, which is what a fresh analysis does (a longer text that holds a term is no term).

A group that is switched off keeps its variants, as before (switching it off is reversible).

Tests:

- the brief's `test_never_hide_disables` (canonical value) still passes unchanged;
- `test_add_never_hide_persists_and_disables_the_groups_it_matches` is replaced by `test_add_never_hide_persists_and_switches_off_the_group_whose_value_it_matches` (the group's own value `THE ACME SUPPLIES LTD`: group off, list saved, plan 6 − 2);
- new `test_add_never_hide_of_a_shorter_form_switches_off_only_those_occurrences` (fixture, `THE ACME`: group still on, only the "Acme" occurrence off, "Acme" gone from the variants, the plan still has "Acme Supplies Ltd");
- new `test_add_never_hide_of_a_surname_keeps_the_full_name_hidden` (the reviewer's probe: PERSON "Mark Price", variants {Mark Price, Price}, `add_never_hide("Price")`: group on, "Price" occurrence off, variants {"Mark Price"}, plan = ["Mark Price"], key variants = ["Mark Price"]);
- new `test_add_never_hide_switches_off_a_group_whose_every_occurrence_is_the_term` (canonical is the case key's "Acme Supplies Ltd", the file only says "Acme": group off, empty plan).

## MINOR 3 — the exact-placeholder guard of `hide_text` had no test

New `test_hide_text_never_touches_a_placeholder_the_text_holds`: on "[CUSTOM_4] and Orion.", `hide_text("[CUSTOM_4]", CUSTOM)` and `hide_text("CUSTOM_4", CUSTOM)` both raise `ValueError` and leave no group and an empty plan. Removing `existing_placeholders` from `taken` now fails it (mutation P1 below).

## RULING R62 — a plain always-hide entry keeps the type of the group that has it

`add_always_hide` passes `retype=text != value.strip()` to `_hide` (an entry is typed exactly when `always_hide_entry` cut a `TYPE:` prefix off), and `_hide(value, kind, retype=True)` takes the new switch: without `retype`, a group of another type that has the value among its forms is joined as it is, and the new occurrences take that group's type (`kind = group.type`). `hide_text` is unchanged (it always re-types), and so is an explicit `TYPE:value` entry, `CUSTOM:value` included.

Tests: `test_a_plain_always_hide_entry_joins_the_group_that_has_it_and_keeps_its_type` (`add_always_hide("Acme")` leaves `[COMPANY_1] Acme Supplies Ltd` a company, same id, and sweeps the second "Acme" in as a COMPANY "user" finding; list saved) and `test_a_typed_always_hide_entry_re_types_the_group_that_has_it` (`add_always_hide("CUSTOM:Acme")` makes it `[CUSTOM_1]`).

## TDD evidence

RED (the new tests written first, against `225f01e`'s code):

```
$ uv run pytest tests/test_review.py -q -p no:cacheprovider
FAILED test_add_never_hide_of_a_shorter_form_switches_off_only_those_occurrences   (the whole group was switched off)
FAILED test_add_never_hide_of_a_surname_keeps_the_full_name_hidden                 (the whole group was switched off)
FAILED test_a_plain_always_hide_entry_joins_the_group_that_has_it_and_keeps_its_type   (the group became [CUSTOM_1])
3 failed, 47 passed
```
The other new tests (value match, every-occurrence, placeholder guard, typed entry) describe behaviour the old code already had or guards that already existed; the mutation check below shows they bite.

GREEN: `uv run pytest tests/test_review.py -q` → `50 passed` (44 + 6 new; one test replaced).

Mutation check (each makes at least one test fail): old rule (any matching form switches the group off); partial branch keeps the variants; partial branch leaves the occurrences on; no switch-off when every occurrence is the term; no switch-off when the canonical is the term (this one fails the brief's own test); `existing_placeholders` removed from `taken`; plain entry re-types; typed entry never re-types; a joined group's new findings take the entry's type instead of the group's. All nine killed.

Real documents: the throwaway probe was extended with never-hide of random groups' shorter variants and canonicals (170 whole-group switch-offs, 13 partial switch-offs) and plain always-hide entries equal to a variant of a random group (112) on all 28 corpus `.docx`: every invariant of the first probe holds (no empty group, no duplicate placeholder, sorted findings, valid `disabled` indexes, plan placeholders == key placeholders, every key variant is a variant of its group) and no plain entry ever changed a group's type.

## Verification

On the committed tree (`58533b7`), from the worktree:

```
$ uv run ruff format --check src tests tools && uv run ruff check src tests tools && uv run mypy src && uv run pytest -q
87 files already formatted
All checks passed!
Success: no issues found in 31 source files
2412 passed in 42.92s
```

2406 before this round plus 6 new tests.

## Status

DONE_WITH_CONCERNS as before; the one open point is size: `src/themask/review.py` is now 420 lines (405 before this round), still one class plus small helpers, not split.
