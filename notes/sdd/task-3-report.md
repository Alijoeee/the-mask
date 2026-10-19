# Task 3 report: text normalisation and variants

**Status: DONE_WITH_CONCERNS** (all requirements met; a handful of interpretation calls and one tooling hazard you should see, listed below)

- Worktree / branch: `/Users/alijoeee/Developer/the-mask-worktrees/task-3`, branch `task-3`
- Commits: `94248f8 feat: text normalisation and value variants`, then `1aa2749 feat: spelling variants for IBAN and ID values` (ruling R9). Trailer on both: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`, as the process rules require.
- **Read this first:** the sections below describe the first delivery (`94248f8`; 378 tests in this file, 427 in the suite). Ruling R9 changed IBAN and ID afterwards; the current state and numbers (427 in this file, 476 in the suite) are in the last section, "Follow-up: ruling R9".
- Files: `src/themask/textnorm.py` (new, 326 lines), `tests/test_textnorm.py` (new, 718 lines). Nothing else touched (`model.py`, `uv.lock`, Task 2's files untouched).

## What was implemented

`src/themask/textnorm.py` exports:

| Name | What it is |
|---|---|
| `normalize(s) -> str` | NFKC, then casefold, then every character that is not a letter or digit is dropped (`[\W_]+`). That covers every Unicode space (NBSP, narrow NBSP, thin, figure, ideographic), the whole punctuation set in the brief, and also symbols and invisible characters (soft hyphen, zero-width space, BOM). `normalize("K4-F7 x") == "k4f7x"`. Non-ASCII letters survive (`Müller`, `Şahin`); Turkish `İ` folds to `i`. About 200 ms for 5 MB of XML. |
| `variants_of(value, t) -> set[str]` | Always contains `value`. Rules per type below. |
| `flexible_pattern(value) -> re.Pattern[str]` | Case-insensitive; whitespace runs in `value` become `\s+`; everything else `re.escape`d; `(?<![A-Za-z0-9])` / `(?![A-Za-z0-9])` added when `value` starts / ends with an alphanumeric character. |
| `LEGAL_FORMS: tuple[str, ...]` | The 27 forms, verbatim, in the brief's order. |
| `COMMON_WORDS: frozenset[str]` | The 41 stoplist words, verbatim. |
| `HONORIFICS: tuple[str, ...]` | The 12 honorifics, verbatim (new public constant, see deviation 1). |

`variants_of` rules, as built:

- **PERSON**: strip leading honorifics (case-insensitive, trailing dot allowed), add `F. Last` from the first and last remaining tokens. The surname alone is never added (`Mr Smith`, `Smith`, `Frau Müller` give only the value).
- **COMPANY**: strip one trailing legal form (dots optional, whole words only, case-insensitive; `se`/`ab`/`co` only when capitalised), add the first token if it has at least 4 letters and is not in `COMMON_WORDS` (compared case-insensitively). Handles the two-word `Ltd. Şti.` and the all-caps Turkish `LTD. ŞTİ.`.
- **AMOUNT**: bare number, number without zero decimals (`,00` / `.00` only; `1.000` is a thousands group and is left alone), each with and without the currency code/symbol (before or after the number). Magnitudes (`1.25m`, `2 million`) stay part of the number.
- **PHONE**: national format through `phonenumbers`, trying `None`, `GB`, `NL`, `DE`, `TR` in that order; first region that yields a valid number wins.
- **URL**: without scheme, without `www.`, and without both (only a literal `www.` label, never `www2.` or `wwwx.`).
- **PERCENT, QUANTITY, EMAIL, ADDRESS, CUSTOM**: the value only. (IBAN and ID were value-only in the first delivery; ruling R9 gave them their own rules, see the last section.)

## Interpretation calls and additions (please check; each is easy to revert)

1. **`HONORIFICS` is a public constant.** Task 8's grouping must strip the same list, so I exported it rather than leave a private copy to drift. Pure naming decision, no extra code.
2. **AMOUNT skips derived bare numbers under 4 characters once separators are dropped** (`_MIN_BARE_AMOUNT_LENGTH`). Without it, `EUR 5.00` would emit a bare `5`, and the sweep would hide every `5` in the contract (clause numbers, `5 days`). With-currency forms (`EUR 5`) are kept because the currency anchors them. The leak check already skips variants under 4 chars, so the two agree. Revert: set the constant to 0.
3. **PHONE requires `is_valid_number`, not just a successful parse.** Region hints are only meaningful if validity decides which one wins (GB parses almost anything). An invalid number's "national format" also lacks the trunk `0` and would be junk. Consequence worth knowing: a Turkish number that is also valid in Germany is read as German (`0212 555 12 34` becomes `0212 5551234`); that follows from the agreed order GB, NL, DE, TR and is harmless (an extra spacing variant), and a test pins the order.
4. **`flexible_pattern("")` and whitespace-only values raise `ValueError`.** A blank pattern matches everywhere (or every whitespace run), which would be catastrophic inside a sweep.
5. **COMPANY clean-up around the legal form** (beyond the brief, to avoid junk variants): a trailing `,` `;` `&` or `and` left behind is dropped (`Acme, Inc.` gives `Acme`, not `Acme,`; `Smith & Co.` gives `Smith`, not `Smith &`, which would match `Smith & Wesson`). If a legal form leaves a single word, that word goes through the same first-token test (`General Ltd` does not yield `General`).
6. **`A/S` matching consequence**: legal forms are matched through `normalize`, so `A/S` also matches `AS` (a real Norwegian form), and `as` joined `se`/`ab`/`co` in the "only when capitalised" set. Tested.
7. **Stacked honorifics** (`Prof. Dr. Jane Smith`) also yield the intermediate `Dr. Jane Smith`.
8. **`flexible_pattern` boundary condition uses `str.isalnum()`** (Unicode) while the lookaround classes stay exactly the brief's ASCII `[A-Za-z0-9]`. So a value ending in `é` or `ç` still gets a boundary. I deliberately did not widen the class to Unicode: with ASCII, a footnote mark right after a name (`Smith¹`) still matches, which errs towards hiding, consistent with "when unsure, hide". The cost: `Gül` also matches inside `Gülşen` (over-hide, never a leak).

## Tests and TDD evidence

`tests/test_textnorm.py`: **378 test cases** (49 pre-existing tests unchanged; full suite is now 427). The brief's tests are all present with assertions unchanged (reformatted by `ruff format`; the NBSP in the brief's `"john\xa0smith"` is written `"john\N{NO-BREAK SPACE}smith"`). Added coverage: every Unicode space kind, invisible characters, every listed punctuation mark, non-ASCII letters, case folding (`ß`, Turkish `İ`), idempotence; the three constants pinned to the agreed values; every entry of `LEGAL_FORMS` with and without dots; case rules, whole-word rule; every honorific in four spellings; every `COMMON_WORDS` entry in three cases; amount/phone/URL tables; boundary and escaping behaviour of `flexible_pattern`; an end-to-end test that other spellings are found by both `flexible_pattern` and `normalize`.

**RED** (run against the first draft of the tests, before `textnorm.py` existed):

```
$ uv run pytest tests/test_textnorm.py -q
ERROR collecting tests/test_textnorm.py
E   ModuleNotFoundError: No module named 'themask.textnorm'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.07s
```
Expected: the module under test did not exist.

**GREEN**:
```
$ uv run pytest tests/test_textnorm.py -q   ->  378 passed in 0.25s
$ uv run pytest -q                          ->  427 passed in 0.27s
$ uv run pytest -q -W error                 ->  427 passed in 0.22s   (no warnings)
$ uv run ruff check src tests               ->  All checks passed!
$ uv run ruff format --check src tests      ->  9 files already formatted
$ uv run mypy src                           ->  Success: no issues found in 5 source files
```

Honest note on the sequence: the implementation passed on its first run, so I checked the tests were not vacuous with a **mutation check**: 27 deliberate bugs applied one at a time to a scratch copy of `textnorm.py` (no casefold, no NFKC, ASCII-only whitespace, one honorific only, surname alone allowed, lower-case `co` accepted, stoplist ignored, 3-letter first token, ending-of-word legal form, no amount guard, `.000` treated as decimals, no phone validity check, wrong region order, `www` without the dot, empty URL variant, each `flexible_pattern` property removed one by one, three list entries removed). **27 of 27 were caught**; the unmutated copy passed.

The test file was rewritten once after the RED run (see the tooling hazard below): same assertions, `\u` escapes replaced by `\N{...}` names, plus one extra Turkish case (`ANADOLU GIDA LTD. ŞTİ.`).

## Self-review

- **Completeness**: every rule in the brief and dispatch is implemented and tested; lists are verbatim and pinned by tests.
- **Quality**: no duplicated logic (one definition of "same spelling": `normalize`, reused for honorifics, legal forms and the amount length guard). Constants carry comments saying how to match them, for Task 7.
- **Discipline**: additions are listed above; none is a new module, dependency or public function.
- **Output**: pristine (no warnings, `-W error` clean). Ruff 0.17.1's default rule set is broad here (imports sorted, bugbear, SIM, pyupgrade, PERF...); the code passes it unchanged.

## Concerns and known limitations

1. **Tooling hazard (affects other tasks).** The Write tool decodes `\uXXXX` sequences into raw characters when saving a file. My first test file silently ended up with literal NBSP, zero-width space, BOM and soft hyphen in the source (tests still passed; ruff flagged the zero-width space as PLE2515). `\N{NO-BREAK SPACE}` and `\xa0` survive intact. Any task that writes Python with invisible characters (Task 6's amount regex `[.,\s   ]`, its NBSP tests, Task 2's fixtures) should use `\N{...}` names, and check the written file for invisible characters.
2. **`ruff check src tests tools`** (command in the process rules) exits 1 with `E902 No such file or directory: tools`, because `tools/` does not exist on this branch yet (Task 4 creates it). Not caused by this change; `src tests` is clean.
3. **Surname particles**: PERSON initials use the first and last token as specified, so `Mevr. Anna de Vries` gives `A. Vries`. `Smith, John` (surname first) gives `S. John`. Rare; flagging in case grouping in Task 8 relies on these.
4. **Value-only types** (originally IBAN, ID, EMAIL, PERCENT, QUANTITY) get no spelling variants, per the brief. `flexible_pattern` only flexes whitespace that is already in the value, so a sweep for `NL91 ABNA 0417 1643 00` would not find `NL91ABNA0417164300`. **Resolved for IBAN and ID by ruling R9** (see the last section); EMAIL, PERCENT and QUANTITY stay value-only. The leak check (`normalize`) covers every spelling regardless.
5. **AMOUNT** does not parse number words (`one million euros`) or Swiss apostrophe grouping (`1'250'000`); those return only the value.
6. **Commit trailer**: I used the trailer from the process rules (`Claude Fable 5.1`). This session's own system reminder names `Claude Sonnet 5.5`; I followed the project rule.

## Notes for the tasks that consume this module

- **Task 7** (`find_legal_form_companies`): `LEGAL_FORMS` entries are matched by their `normalize`d spelling, whole word(s) only, and `se`/`ab`/`co`/`as` need a capital. The comment above `LEGAL_FORMS` states the contract. `Ltd. Şti.` is the only two-word form.
- **Task 8** (grouping, sweep): `HONORIFICS`, `normalize` keys and `variants_of` are all reusable; `flexible_pattern` rejects blank values, so filter blank variants before sweeping.
- **Task 12** (leak check): `normalize` on a 5 MB blob takes about 0.2 s; `needle in blob` is then instant.

## Follow-up: ruling R9 (IBAN and ID spelling variants)

Commit `1aa2749 feat: spelling variants for IBAN and ID values` on `task-3`, same trailer. Files: `src/themask/textnorm.py` and `tests/test_textnorm.py` only (2 files, +126 / -5). Not a review-fix round.

**What changed**

- **IBAN**: `variants_of` returns the original, the compact form (all whitespace removed) and the form in groups of four, whichever way the input was written. So `NL91 ABNA 0417 1643 00` gives `NL91ABNA0417164300`, and `NL91ABNA0417164300` gives `NL91 ABNA 0417 1643 00`. Odd groupings, non-breaking spaces and line breaks inside the IBAN are normalised the same way; the last group is short when the length is not a multiple of four (`NO93 8601 1117 947`). Case is kept as written. The grouped form is only built when the compact form is purely letters and digits, so `NL91-ABNA-0417-1643-00` does not get a made-up grouping.
- **ID**: the original plus the form with whitespace, dots and hyphens removed (`12.345.678` gives `12345678`; `NL 1234.56.782.B01` gives `NL123456782B01`). "Hyphens" covers the ASCII hyphen and the typographic (U+2010) and non-breaking (U+2011) hyphens that Word can put inside an identifier. Case and every other character (slash, underscore) are left as written. An already-compact ID such as `NL123456782B01` returns only the value.
- **EMAIL, PERCENT, QUANTITY, ADDRESS, CUSTOM**: unchanged (value only). I read "(lower-case only)" in the ruling as a description of how e-mails are matched (case-insensitively, by `flexible_pattern` and `normalize`), not as a request for a lower-case variant. If a lower-case variant was intended, it is a one-line addition.
- `variants_of` docstring updated. The old test that listed IBAN and ID among the "value only" types now lists the remaining five.

**Covering tests** (`tests/test_textnorm.py`, 49 net new cases, 427 in the file now): the four assertions from the ruling are in verbatim as `test_iban_variants`, `test_iban_written_without_spaces_gets_the_grouped_form`, `test_id_that_is_already_compact_has_only_the_value` and `test_id_variants`. Added: six ways of writing the same IBAN give exactly the same three-element set; three IBANs with different last-group lengths; case kept; hyphenated IBAN not regrouped; eight ID separator cases (dots, hyphens, spaces, non-breaking space, both Unicode hyphens, lower case kept); ID keeps `/` and `_`; three new end-to-end rows (compact IBAN found spaced, spaced IBAN found compact, dotted ID found compact); `"   "` and `"- . -"` added to the degenerate-input test for every type, so neither rule can emit an empty string.

**RED** (tests first, before touching `textnorm.py`):

```
$ uv run pytest tests/test_textnorm.py -q
FAILED tests/test_textnorm.py::test_iban_variants
FAILED tests/test_textnorm.py::test_iban_written_without_spaces_gets_the_grouped_form
FAILED ...::test_iban_comes_spaced_and_unspaced_whichever_way_it_was_written[...]  (6)
FAILED ...::test_iban_is_grouped_in_fours_with_a_short_last_group[...]             (3)
FAILED tests/test_textnorm.py::test_iban_keeps_the_case_it_was_written_in
FAILED tests/test_textnorm.py::test_id_variants
FAILED ...::test_id_loses_its_spaces_dots_and_hyphens[...]                         (8)
FAILED ...::test_another_spelling_is_found_by_the_pattern_and_by_normalize[...]    (3)
24 failed, 403 passed in 0.35s
```
Expected: IBAN and ID still returned only the value. The three guard tests that pass at this stage (`already_compact`, `hyphenated IBAN not regrouped`, `keeps every other character`) are there to stop an over-eager implementation.

**GREEN**:

```
$ uv run pytest tests/test_textnorm.py -q                                    ->  427 passed in 0.23s
$ uv run pytest -q && uv run ruff check src tests && uv run mypy src
      476 passed in 0.29s / All checks passed! / Success: no issues found in 5 source files
$ uv run ruff format --check src tests                                       ->  9 files already formatted
$ uv run pytest -q -W error                                                  ->  476 passed in 0.24s
```

**Mutation check** on a scratch copy: 13 deliberate bugs in the new code (groups of five, compact form keeps spaces, regroup non-alphanumeric input, no grouped form, empty variant allowed in either rule, either rule not registered, hyphens kept, dots kept, typographic hyphens kept, every punctuation mark removed, ID lower-cased like `normalize`). **13 of 13 caught.**

**What it buys** (probe on `Pay to NL91ABNA0417164300 or to NL91 ABNA 0417 1643 00`): a sweep for either spelling used to find only that spelling; with the variants it finds both.

**Notes**

- No minimum-length guard on the compact ID (unlike AMOUNT), because R9 does not ask for one: a very short custom ID such as `A-1` would give `A1`. Real identifiers (VAT, registration, BIC, BSN, passport) are six characters or more, so I left R9 exactly as ruled. A guard is one line if short custom IDs are ever expected.
- Only the "remove separators" direction exists for ID (a compact ID in the text will not yield a dotted form), because VAT, registration and passport numbers have no single standard grouping. IBAN has one, hence both directions.
- Task 8: when sweeping, `variants_of(...)` for IBAN and ID can now return more than one element, so the sweep should treat every returned variant as part of the group.
