# Task 2 report: data model and placeholder grammar

**Status:** DONE_WITH_CONCERNS (all requirements met and verified; the concerns are design observations and one trailer discrepancy for the controller to rule on, listed at the end)

> **Update after ruling R8 (commit `8479e36`, last section of this file):** the matcher no longer reads a bare name and number joined by a space, and it now reads markdown's escaped underscore and three Unicode spaces. Test counts, the "bare prose" concern (2) and the "not recognised" concern (3) below describe the first commit and are superseded by that section.

**Worktree / branch:** `/Users/alijoeee/Developer/the-mask-worktrees/task-2`, branch `task-2`
**Commit:** `b5f9e51fb5359ea854745330cf81a31193fdebf8` `feat: data model, placeholder grammar and fixed copy` (one commit, as the brief's Step 5 says; the test-plumbing step is in the same commit and named in its body)

## What I implemented

| File | What |
|---|---|
| `src/themask/model.py` (extended) | `PlaceholderType` untouched (verified identical to HEAD). Added `FindingSource` (the six-value `Literal`), `Finding` (frozen), `Group` (+ `active_findings()`), `Analysis`, `Replacement` (frozen), `MaskPlan`, `KeyEntry`, `MaskedFile`, `Case` (+ `expires_at`, `to_json()`, `Case.from_json()`), with the field order and defaults exactly as in the brief. |
| `src/themask/placeholders.py` (new) | `format_placeholder`, `PLACEHOLDER_RE` (exact form, named groups `type` and `number`), `PlaceholderMatch` (frozen, fields exactly `start, end, raw, placeholder, exact`), `find_placeholders`, `next_free_number`. One compiled tolerant regex plus a private `_scan` generator that both public functions use. |
| `src/themask/instruction.py` (new) | `AI_INSTRUCTION`, `BANNER_TEXT`, `IMAGE_NOTE`, `OBJECT_NOTE`. I compared all four programmatically with `global-constraints.md` (and the AI instruction with the quote in spec 8.8): identical, single line, pure ASCII. |
| `tests/test_placeholders.py`, `tests/test_model.py` (new) | The brief's tests (same names, same assertions) plus tests that pin each rule below. 238 + 38 = 276 tests. |
| Plumbing (dispatch's extra step) | `tests/__init__.py`, `tests/fixtures/__init__.py` (both empty), `tests/conftest.py` (env setting and `data_dir` kept, `pytest_plugins` glob added exactly as specified, spread over several lines), `pyproject.toml` (`pythonpath = ["."]`). |

## Grammar decisions (where the brief left room, or where I refined it)

1. **A bracket delimits a token on its own side; the word guards apply only to a bare edge.** The brief says "whole-word check `(?<![A-Za-z0-9])` ... `(?![A-Za-z0-9])`". I use exactly those two guards, but only where the token starts with a bare type name or ends with a bare number. Reason: wrapped round the whole token, as the brief literally reads, the guards make `[PERSON_1]s` backtrack to the partial match `[PERSON_1` and make `x[PERSON_1]` match `PERSON_1]`, so a restore would leave a stray bracket ("John Smith]s", "x[John Smith"). Mutant evidence below: the literal reading passes all of the brief's own tests and fails only my extra `test_markers_join_the_token_only_as_a_matching_pair`.
2. **Markers (`**`, `__`, backtick) join the token only as a matching pair.** `**[PERSON_1] signs**`, `[PERSON_1]**` and `**[PERSON_1]__` leave `[PERSON_1]` exact and untouched markers outside. A single `*` or `_` is not a marker (so `*[PERSON_1]*` and `Contract_[PERSON_1].docx` keep their surroundings).
3. **Backslash is part of the bracket, not a marker.** `\[` and `\]` are bracket variants, each usable on its own (`\[PERSON_1]`, `[PERSON_1\]`). A bare backslash before a name is not consumed (`C:\PERSON_1\x` yields `PERSON_1`). Downside: `C:\Contracts\[COMPANY_1]\x` takes the backslash with it, as an altered form that needs confirmation.
4. **Spaces belong to a bracket.** Spaces are consumed only just inside an opening bracket or just before a closing one, never around a bare name (`Dear  PERSON_1 , bye` yields `PERSON_1`).
5. **`exact` is `raw == canonical`**, which is the dispatch's definition (upper case, underscore, no leading zero, ASCII square brackets, no markers) in one comparison. `PLACEHOLDER_RE` is built to agree with it; a test checks the two on 33 strings.
6. **ASCII only** (`re.ASCII`, `[0-9]`). Without it, Unicode case folding lets a long s (U+017F), a dotted capital I (U+0130) or a dotless i (U+0131) stand in for a letter of a type name (relevant for a Turkish-speaking owner), and `\d`-style digits would admit Arabic-Indic or full-width digits. Tests pin all five.
7. **A number has at most nine digits.** `int()` raises on digit strings longer than 4300 characters (Python's limit), so an unbounded `\d+` would let a single odd line crash `find_placeholders`. Longer runs are simply not placeholders. Tested with a 5000-digit run.
8. **Numbers are canonicalised through `int`**: `[PERSON_007]` has `placeholder == "[PERSON_7]"` and is altered; `[PERSON_0]` is a valid exact form (never generated, so a restore reports it as unknown like `[PERSON_9]`).
9. **`next_free_number` counts altered forms too** (`PERSON_3`, `[person-5]`, `**[PERSON_4]**`), because a restore would take any of them for a placeholder of ours.
10. **Full-width brackets are written as `\N{FULLWIDTH LEFT SQUARE BRACKET}` / `\N{FULLWIDTH RIGHT SQUARE BRACKET}` in the regex source** (U+FF3B / U+FF3D; I checked the code points of the brief's literals).

## Model decisions

- `Group.active_findings()` returns `[]` when `enabled` is `False`, otherwise every finding whose index is not in `disabled`. The brief names the method without defining it; folding the group switch in means a consumer who forgets to check `enabled` can never mask something the owner switched off. Documented in the docstring and tested. If you want occurrence-level only, it is a one-line change.
- `MaskPlan.__post_init__` stores a new sorted list (the caller's list is not reordered), raises `ValueError("Replacements overlap: ...")` on `a.end > b.start` after sorting, and allows touching spans (`(0,5)`, `(5,8)`). The message names placeholders and offsets only, never text. Tests cover nested, same-span and out-of-order overlaps.
- `Case.to_json()` writes `created_at` converted to UTC with `isoformat()`, `PlaceholderType` as its string, `MaskedFile` and `KeyEntry` as nested objects, plain `json.dumps` (ASCII-safe, so a lone surrogate in odd document text still round-trips). Keys are the field names (shape pinned by `test_case_json_has_the_agreed_shape`). `created_at` must be timezone-aware (documented). `expires_at` is a property: `created_at + timedelta(days=retention_days)`.
- `Case.from_json()` converts `KeyError`/`TypeError` into `ValueError("Not a stored case.")`; `json.JSONDecodeError`, a bad timestamp and an unknown placeholder type are already `ValueError`. So callers can catch one exception type. Eight garbage inputs and six kinds of damaged case are tested.
- I added no fields, defaults or validation beyond the brief (for example `Analysis.warnings` has no default and `Replacement` does not validate `start <= end`).

## Testing and TDD evidence

**RED** (before any implementation; the brief's Step 2 expects import errors):

```
$ uv run pytest tests/test_placeholders.py tests/test_model.py -q
ERROR tests/test_placeholders.py   ->  E   ModuleNotFoundError: No module named 'themask.instruction'
ERROR tests/test_model.py          ->  E   ModuleNotFoundError: No module named 'themask.instruction'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
2 errors in 0.07s
```
Expected: neither `themask.instruction` nor `themask.placeholders` existed, and `model.py` had no dataclasses.

**GREEN** (after implementing):

```
$ uv run pytest tests/test_placeholders.py tests/test_model.py -q
276 passed in 0.16s

$ uv run pytest -q                      # whole suite, from the worktree root
325 passed in 0.23s                     # 49 existing (Task 1) + 276 new
$ uv run pytest -q -W error             # no warnings anywhere
325 passed in 0.20s
$ uv run ruff check src tests           # All checks passed!
$ uv run ruff format --check src tests  # 13 files already formatted
$ uv run mypy src                       # Success: no issues found in 6 source files
```

Additional checks I ran (scratch only, nothing committed):

- **The brief's test code, verbatim.** I extracted the two code blocks from the brief's Step 1 programmatically, added only the imports it omits, and ran them against the implementation: 19 passed. The brief's literal full-width brackets are in that run.
- **Mutation check of the regex** (a scratch pytest plugin swaps `_TOKEN_RE` for a wrong variant; every mutant is killed by the suite): literal whole-token guards (fails 2 cases of the marker/bracket test), the same with a possessive closing bracket (same 2), no `re.ASCII` (3 cases), marker taken without a partner (3), unbounded digits (3), outer spaces swallowed (2), ASCII brackets only (8), case-sensitive type names (24).
- **Plumbing probe.** With a temporary `tests/fixtures/zz_probe.py` (a fixture) and a test using it, the glob auto-load worked, also under `-W error` and when run from inside `tests/`. Both temporary files were removed before the commit; no dummy fixture module is committed. With no fixture modules the list is `[]` and the existing 49 tests pass.
- **Performance and robustness.** 2.7 MB of contract-like text with 12,000 tokens takes about 0.18 s. Fifteen pathological inputs (200k spaces after `[`, 100k `**`, 50k unclosed `[PERSON_1`, 1M digits, ...) each take under 0.13 s, so no backtracking blow-up. NUL, lone surrogates and emoji next to tokens do not raise.

## Files changed

```
 pyproject.toml              |   1 +
 src/themask/instruction.py  |  20 +++      (new)
 src/themask/model.py        | 169 +++      (extended; enum block unchanged)
 src/themask/placeholders.py | 103 +++      (new)
 tests/__init__.py           |   0          (new, empty)
 tests/conftest.py           |   8 +
 tests/fixtures/__init__.py  |   0          (new, empty)
 tests/test_model.py         | 282 +++      (new)
 tests/test_placeholders.py  | 312 +++      (new)
```

## Self-review findings (all fixed before the commit)

- **The write path decoded my `\uXXXX` escapes into literal characters** (the regex's full-width brackets and several test strings became look-alike glyphs: a long s, a dotless i, full-width digits). The code still passed, but nobody can review `"[PERSON_٣]"` by eye. Fixed with named escapes (`\N{...}`) in the regex and tests; `placeholders.py` and `test_placeholders.py` are now pure ASCII. `test_model.py` keeps deliberate readable sample data (accents, CJK) for the JSON round trip.
- **Ruff 0.17's default rule set is much wider than E/F**: it includes isort (I001), bugbear (B010 `setattr` with a constant), pytest-style (PT014 duplicate parametrize cases), comprehensions, `UP`, `TRY`, `RUF` and more. I wrote to it and `ruff check src tests` is clean.
- Tightened two awkward test comments and two docstrings; added a nine-digit and a ten-digit case so the two nine-digit limits (exact pattern and tolerant pattern) cannot drift apart unnoticed.
- YAGNI check: no extra public behaviour beyond the brief except the `FindingSource` alias, the named groups on `PLACEHOLDER_RE`, and the `ValueError` wrapping, all described above.

## Concerns and observations for the controller

1. **Commit trailer.** The process rules require `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`, and all five existing commits carry it. The attribution reminder my session received names `Claude Sonnet 5.5` instead. I followed the project's process rules, so the commit has the Fable line only (one trailer, like the others). Amend the trailer if you want the other one.
2. **Bare prose can match, by the brief's own grammar.** The separator `[_ -]` and case-insensitive type names apply with or without brackets, so `Company 1 shall pay Company 2` (a plausible AI paraphrase, which we want to catch) is found, but so are ordinary phrases such as `ID 12345`, `Phone 2`, `Address 5`, `Amount 500`, or the `Quantity 1` inside `Quantity 1,000`. This is harmless in a restore (altered forms need the owner's confirmation; ones not in the key are only listed as unknown), but note **Task 23's final assertion** `{m.placeholder for m in find_placeholders(restored_text)} == {"[PERSON_9]"}` would fail on any corpus text containing such a phrase, and `next_free_number` would skip a number. If that bites, the cheap fix is to allow the space/hyphen separators and lower case only inside brackets (bare forms then need `TYPE_N` with an underscore).
3. **Forms outside the brief's grammar, not recognised:** a markdown-escaped underscore `[PERSON\_1]` (likely in a "copy as markdown" paste), a non-breaking space inside a placeholder, double-escaped `\\[PERSON_1\\]`, and single-character emphasis (`*[PERSON_1]*` keeps its asterisks, which is deliberate). `[PERSON\_1]` seems the most plausible real-world miss; adding `\\?_` to the separator is a one-line change if you want it.
4. **`BANNER_TEXT` and `AI_INSTRUCTION` themselves contain well-formed placeholders** (`[COMPANY_1]`; `[PERSON_1]` and `[AMOUNT_2]`). `find_placeholders(BANNER_TEXT)` finds `[COMPANY_1]`, so Task 18 must remove the banner line before replacing placeholders (the plan already says so), and `next_free_number` on text that still carries the banner counts it.
5. **`uv run ruff check src tests tools`** (the boilerplate's full command) fails with `E902 No such file or directory` for `tools`, because that directory does not exist in this worktree yet. It is a missing path, not a lint finding; the brief's own command for this task (`ruff check src tests`) is clean.
6. **FYI for parallel implementers (Task 3's `textnorm.py` handles NBSP, curly quotes and dashes):** the file-writing step here decodes a lowercase `\uXXXX` typed in source into the literal character. `\N{NAME}` and `\UXXXXXXXX` survive. Worth passing on so confusable characters stay escaped in source.
7. **Import classification quirk:** ruff treats a `themask.x` import as third-party until `src/themask/x.py` exists, so I001 complains about import order in tests that are written before their module (it resolved once the modules existed). Parallel tasks may see the same transient finding.

---

# Follow-up: ruling R8, tighter `find_placeholders`

**Commit:** `8479e36` `fix: tighten the placeholder grammar so plain text is left alone (ruling R8)` on `task-2` (same trailer). Not a review fix round. Files: `src/themask/placeholders.py`, `tests/test_placeholders.py`.

## What changed

1. **A bracketless form needs `_`, `-` or markdown's escaped `\_` between the name and the number.** `PERSON_1`, `person-1`, `PERSON\_1` are altered forms; `Company 1`, `ID 12345`, `Phone 2`, `person 1`, `Person 1` are no longer found at all (neither is the `Quantity 1` inside `Quantity 1,000`).
2. **Inside brackets the separator may also be a space**, as in `[PERSON 1]` and `[ Person 1 ]`.
3. **`\_` is accepted as the separator everywhere** (`[PERSON\_1]`, `\[PERSON\_1\]`, `**PERSON\_1**`, half-bracketed `[PERSON\_1`), and **NBSP (U+00A0), narrow NBSP (U+202F) and thin space (U+2009) count as spaces wherever a space is allowed**: just inside an opening bracket, just before a closing one, and as the separator inside a pair of brackets. They are not accepted next to a bare name (`PERSON` + NBSP + `1` is prose).
4. **`exact=True` is unchanged**: still only the canonical `[TYPE_N]` (`raw == placeholder`). The `[PERSON_1]s` / `x[PERSON_1]` refinement stands, with its tests.

Implementation: two named pieces, `_SPACE` (the four spaces, written with `\N{NO-BREAK SPACE}`-style names) and `_SEPARATOR` (`_|-|\\_`), and in the pattern the type is now followed by `SEPARATOR`, or a space only when `open` matched and a lookahead sees the number followed by (spaces and) a closing bracket; otherwise the conditional falls to `(?!)`, so a bracketless name with no separator at all (`PERSON1`) cannot match either. Module docstring and comments updated.

**One interpretation to confirm:** "inside brackets" is read as a whole pair, so a space next to only one bracket does not count (`[PERSON 1`, `PERSON 1]`, `[Person 1 and Person 2]` are not placeholders; `[PERSON_1`, `PERSON_1]`, `[PERSON\_1` still are, since they use a real separator). This is the stricter reading and avoids flagging phrases such as `[see Company 1, Company 2]`; loosening it to "at least one bracket" is a one-line change in the lookahead.

## Tests

`tests/test_placeholders.py` went from 238 to 315 tests (`tests/test_model.py` unchanged at 38).

- **Altered, as the ruling lists them:** `PERSON\_1`, `[PERSON\_1]`, `[PERSON 1]`, `[ PERSON_1 ]` all give `[PERSON_1]`, `exact=False` (`test_an_escaped_underscore_and_a_spaced_pair_of_brackets_are_changed_forms`).
- **No match:** `Company 1`, `ID 12345`, `Phone 2`, `person 1`, `PERSON 1`, `Address 5 and Email 3 and URL 4`, and a sentence with `Amount 500 (Quantity 1,000)` (`test_a_name_and_number_separated_by_a_space_without_brackets_are_prose`); the same with NBSP, narrow NBSP and thin space (`test_unicode_spaces_are_prose_too_when_there_are_no_brackets`); `PERSON1` and `[PERSON1]` (in the near-miss list).
- **One bracket only:** `test_a_space_between_name_and_number_needs_both_brackets`.
- **Separator matrix:** `_`, `-`, `\_` each with no, both, opening-only and closing-only brackets (12 cases).
- **Spans:** `MORE_ALTERED_FORMS` gained the `\_` forms, the spaced forms with each bracket and marker style, and the Unicode-space forms, so `test_an_altered_token_is_replaceable_in_one_piece`, the `exact`-versus-`PLACEHOLDER_RE` agreement test and the `PLACEHOLDER_RE` refusal test cover them. `Person 1` moved from the altered list to the no-match tests.
- `next_free_number` counts `PERSON\_9` and ignores `Person 4` / `ID 12345`.
- All Unicode characters in the tests are written as `\N{...}` names (constants `NBSP`, `NARROW_NBSP`, `THIN_SPACE`), so the file stays pure ASCII.

## Evidence

**RED**, updated tests against the pre-R8 matcher (`uv run pytest tests/test_placeholders.py -q`): `41 failed, 274 passed`. The failures are exactly the ruling's changes: 11 span tests and 10 exact-agreement tests for the new `\_`/Unicode-space forms, 7 prose cases still matched (`Company 1` returned `[COMPANY_1]`), 5 one-bracket cases still matched, 4 separator-matrix cases with `\_`, 2 ruling forms (`PERSON\_1`, `[PERSON\_1]` found nothing), 2 `next_free_number` cases.

**GREEN:**

```
$ uv run pytest tests/test_placeholders.py -q
315 passed in 0.14s

$ uv run pytest -q && uv run ruff check src tests && uv run mypy src
402 passed in 0.23s                      # 49 existing + 315 + 38
All checks passed!
Success: no issues found in 6 source files
```

Also: `ruff format --check` clean, `pytest -W error` pristine (402 passed), and the brief's own test code run verbatim still passes (19/19).

**Extra checks (scratch only):**

- **Differential fuzz, old matcher (`b5f9e51`) against the new one, 800,000 random strings built from brackets, markers, type names, separators and digits.** With no spaces and no `\_` in the alphabet the outputs are identical (0 differences in 300,000 strings, so R8 changed nothing else). With plain spaces added (300,000 strings, 2,517 differences) every removed match is a space-separated one and a new match appears only where an old one was removed; with `\_` and Unicode spaces added (200,000 strings, 715 differences) matches are only gained. 0 unexplained differences.
- **Mutation check, 14 mutants of the new pattern, all killed:** space separator without brackets (21 failing tests), no `\_` (19), no hyphen (10), only plain spaces (9), space with only an opening bracket (5) or only a closing one (3), conditional without its failing branch (2), Unicode spaces as bare separators (5), no left or right word guard (2 and 5), marker without partner (3), no `re.ASCII` (3), unbounded digits (3), case-sensitive names (28).
- **Performance:** unchanged and linear. 2.8 MB of contract-like text with 20,000 tokens takes 0.2 s; 17 pathological inputs, including bracket-heavy ones aimed at the new lookahead (`[PERSON 1` repeated 50,000 times, `[PERSON 1` followed by 200,000 spaces, a million digits), each take under 0.09 s.

## What is left over (for information)

- A bare name joined by `_`, `-` or `\_` is still a changed form by ruling, so identifier-like text can be flagged: `ID-4711`, `user_id_5` (its `id_5`). These are listed for confirmation or as unknown, never restored without a click. Task 23's `== {"[PERSON_9]"}` assertion is now only at risk from such identifier-like text, not from ordinary prose.
- Still not read (deliberate or out of scope): double-escaped `\\[PERSON_1\\]`, single-character emphasis (`*[PERSON_1]*` keeps its asterisks), and other Unicode spaces (for example U+2007 figure space or U+3000 ideographic space), since the ruling names exactly three.
