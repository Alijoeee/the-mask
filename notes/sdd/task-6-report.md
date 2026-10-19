# Task 6 report: detection engine and pattern recognizers

**Status:** DONE_WITH_CONCERNS (all requirements met and tested; the concerns are about Presidio
built-ins and later tasks, listed at the end)

Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-6`, branch `task-6`, on top of 8479e36.

| Commit | Subject |
|---|---|
| `1163e4a` | feat: Presidio engine with contract pattern recognizers |
| `387f4d5` | fix: stop at a missing language model instead of downloading it (found in self-review) |

## What I implemented

### `src/themask/detect/engine.py`: `Engine(model_name="en_core_web_md")`, `analyze(text) -> list[Finding]`

- Loads `nlp_config.yaml` with `importlib.resources.as_file` and passes it to
  `NlpEngineProvider(conf_file=...)`. The `model_name` argument replaces the model named in the file
  (it is set in `provider.nlp_configuration` before `create_engine()`).
- Registry: Presidio's predefined recognizers for `en`. I removed Presidio's `EmailRecognizer`,
  `UrlRecognizer` and `PhoneRecognizer` and added in their place:
  - `PhoneRecognizer(supported_regions=PHONE_REGIONS)`, with `GB NL DE FR BE IE TR US ES IT CH AT DK SE NO PL`;
  - `UkNinoRecognizer()`. Presidio leaves it off by default, but the mapping lists `UK_NINO`;
  - our 11 recognizers (`patterns.contract_recognizers()`).
- Mapping (controller decision 1): `EMAIL_ADDRESS→EMAIL`, `PHONE_NUMBER→PHONE`, `IBAN_CODE→IBAN`,
  `CREDIT_CARD→ID`, `URL→URL`, `PERSON→PERSON`, `ORGANIZATION→COMPANY`, `LOCATION→ADDRESS`, and
  `US_SSN/US_PASSPORT/UK_NHS/UK_NINO/US_BANK_NUMBER/US_DRIVER_LICENSE/US_ITIN/CRYPTO/IP_ADDRESS/MEDICAL_LICENSE→ID`.
  `DATE_TIME` and `NRP` are dropped. Our recognizers report placeholder type names directly. Any
  other entity becomes `ID`; this is tested with a MAC address.
- `source`: `"model"` when `recognition_metadata["recognizer_name"]` is `SpacyRecognizer`, and
  `"pattern"` for every other recognizer.
- Findings scored below `MIN_SCORE = 0.3` are dropped. Results are sorted by `(start, end, type)`.
  **Overlaps are not resolved.** The only merging is of exact duplicates, meaning the same type and
  the same span (for example `US_BANK_NUMBER` and our account number, both mapped to ID); the one
  with the highest score is kept.
- Pattern findings are trimmed of surrounding whitespace and trailing punctuation (`. , ; : ! ?`,
  quotes, and a closing bracket whose opening bracket lies outside the value). This makes decision 6
  hold for Presidio's recognizers too, for example a URL at the end of a sentence. Model spans are
  left as spaCy gives them, so "Northwind Trading B.V." keeps its final full stop.
- `analyze()` is laid out so Task 7 can slot in: `_presidio_findings(text)`, then the score filter
  and the sort. Task 7 adds its rule findings and the LOCATION gate between those two steps.
- Self-review fix (`387f4d5`): Presidio calls `spacy.cli.download` for a model that is not
  installed. `Engine` now raises `OSError("The language model … is not installed.")` before that
  can happen.

### `src/themask/detect/nlp_config.yaml` (decision 2)
spaCy `en_core_web_md`. Mapping: PER/PERSON→PERSON, ORG/ORGANIZATION→ORGANIZATION,
LOC/GPE/FAC/LOCATION→LOCATION. `low_score_entity_names: []`, so companies keep 0.85 (tested).
`labels_to_ignore` holds Presidio's defaults plus DATE, TIME and NORP, but not ORG. Every
en_core_web_md label is either mapped or ignored, so Presidio logs no "unmapped label" warnings.

### `src/themask/detect/patterns.py`
`CheckedPatternRecognizer(PatternRecognizer)` is a small base class. It runs its patterns itself and
calls `score_match(text, match, pattern)` for each match, which returns a score or 0 to drop it. I
needed this because Presidio's `validate_result` sees only the matched text and can only give 1.0 or
0. It also removes duplicates only after every match has been checked, which matters: Presidio's
dedupe treats same-span, same-score results as equal and would keep one at random, for example a
9-digit passport number that also matches the BSN pattern. A pattern may capture its value in a
group named `value`, which keeps context words such as "account number" out of the span. The flags
are inline (`(?i:…)`).

| Recognizer | Entity / score | Notes |
|---|---|---|
| `AmountRecognizer` | AMOUNT 0.85 | Currency sign or ISO code before or after the figure (codes upper case only: "TRY" is money, "try" is not). Digit groups split by `.` `,` (any length), or by a space (plain, no-break, narrow no-break, thin, figure) or an apostrophe before exactly three digits. Ranges `EUR 10-20`, `1.000,-`, magnitudes `k m mn mln mio bn thousand million billion trillion`. Number words one…ninety-nine plus scales, then a currency word or code, optionally with the figures in brackets: "fifty thousand (50,000) euros". No currency *word* before a figure, so "Euro 6 emission standard" stays visible. |
| `PercentRecognizer` | PERCENT 0.85 | `12.5%`, `12,5 %`, `8 per cent`, `8 percent`, `pct`, ranges `5-10%`, words "five per cent", "five (5) per cent", "five (5%)". |
| `QuantityRecognizer` | QUANTITY 0.8 | Every unit decision 5 lists, plus singulars, `pc box packs rolls bags containers kilos kgs cbm m3 m³ L`. Never a time unit. Single letters are case-sensitive. Not right after a currency (`€2.5m` is an amount). Number words count only with a scale word or bracketed figures, so "in two cases" and "one item" stay prose. |
| `VatRecognizer` | ID 0.9 valid / 0.6 format only | Per-country formats with optional separators. EU and XI are checked by `stdnum.eu.vat`, **plus** GB (`stdnum.gb.vat`), CH (`stdnum.ch.uid`) and NO (`stdnum.no.mva`). |
| `RegistrationNumberRecognizer` | ID 0.7 | One of the context words in decision 5, at most 40 characters on the same line before `number/no/nr/nummer`, then 5–15 letters and digits (checked). Also `KvK 12345678` and `HRB 123456` with no "number". |
| `BicRecognizer` | ID 0.9 | Must be valid for `schwifty.BIC` **and** meet one more condition (see decision C). |
| `AccountNumberRecognizer` | ID 0.7 | `account/acct/a/c` within 20 non-digit characters, then 6–18 digits; `sort code` then `12-34-56`. An IBAN on an "Account:" line is left to Presidio's IBAN check. |
| `NationalIdRecognizer` | ID 0.85 | BSN (`stdnum.nl.bsn`; `123456782`, `1234.56.782`, `123 456 782`), TCKN (`stdnum.tr.tckimlik`), and passport numbers after "passport number/no/nr". |
| `BareNumberRecognizer` | AMOUNT 0.4, 0.75 in context | Context words are the eight from decision 5. The 0.75 is Presidio's own context boost (0.4 + 0.35). Excludes years 1900–2099, durations (`1,000 days`, `2,500 working days`, `a 1,000-day period`, any of day/week/month/year/hour) and references (`section 1159`, `Article 1101`, `§`, and `2016/679`). See decision A. |
| `EmailAddressRecognizer` | EMAIL_ADDRESS (Presidio's patterns and context) | Replaces Presidio's recognizer. See decision B. |
| `WebAddressRecognizer` | URL 0.6 / 0.5 | Replaces Presidio's recognizer. See decision B. |

### Tests
- `tests/fixtures/engine.py` holds the session-scoped `engine` fixture. It imports the engine
  inside the fixture, so a test run that never asks for the engine does not import Presidio or
  spaCy.
- `tests/detect/test_patterns.py` has 219 tests. Every test from the brief is included with its
  values unchanged. On top of those: positives in more forms for every recognizer, exact-span tests
  (trailing punctuation, whole e-mail, phone and URL spans), and negatives for every recognizer. The
  negatives run the recognizer **on its own**, so that a find by another recognizer cannot hide a
  mistake. Engine tests cover text order, `text == slice`, scores ≥ 0.3, sources, the company
  score, money/percent/quantity coming only from patterns, dates staying visible, the entity
  mapping, overlaps being kept, empty text, the exact `PHONE_REGIONS`, national-format numbers that
  Presidio's default regions miss (BE, TR, ES, DK, SE, NO, PL), and the missing-model guard.
  Special spaces are written as `\N{…}` escapes.

## Decisions I made where the brief was open (please check)

**A. What counts as a bare number.** I read "numbers ≥ 1,000 with separators or decimals" as: the
value is at least 1,000, whether written `48,000`, `1.250.000,00`, `1 250 000` or `48000`. That is
the only reading under which the brief's "excludes years 1900–2099" and its `in 2026` test do
anything. Decimals below 1,000 (`12.50`, `10.2`) are not candidates. So clause numbers such as
`10.2`, at a line start or after "clause", can never be bare numbers. They are below 1,000, and
their digits are not in groups of three. I did **not** add a separate "line-start `\d+\.\d+`" rule.
With these candidates it could only fire on thousands-grouped values: a table row `48.000⇥Total`
would have been dropped, which is a leak, and the rule removes no real clause number. Tests:
`10.2 The Supplier shall…`, `clause 10.2 applies`, `12.3.4 Delivery`, `Section 4.1(b)`. I also added
the reference-word exclusion (`section 1159`) so that statute numbers stay visible.

**B. Replacing Presidio's e-mail and URL recognizers** (the brief's own test needs it). Evidence
from stock Presidio 2.2.364:
- The e-mail validator calls `tldextract.extract("j.smith@northwind.example").fqdn` and gets `''`,
  so the address is dropped and `test_email_phone_url` fails.
- `UrlRecognizer` has no boundary after its TLD list. It returned `'https://www.no'` (".no" is
  Norway) for `https://www.northwind.example/legal`, which would mask only the first part and leak
  the rest. It also returned `'j.sm'` (San Marino) from the e-mail address.

Our replacements take anything after `https://` or `www.` up to the next space (then trimmed), and
for a bare domain require a whole known TLD (lower case only; `[a-z]{2}` or a common gTLD such as
.com, .eu or .example). A side effect: tldextract is no longer called at all at runtime.

**C. BIC also needs a second sign.** schwifty accepts many upper-case contract words as BICs, for
example SUPPLIER (Liechtenstein), CUSTOMER, TERMINATION, DEFINITIONS, ARBITRATION, OBLIGATIONS,
DELIVERY, BREACHES, MEETINGS, HEADINGS, PARTNERS and FORECAST. So a valid code must also be in
schwifty's bank registry (`BIC.exists`), or contain a digit, or have "BIC", "SWIFT" or "bank
identifier" within 40 characters before it. Real BICs like DEUTDEFF and HSBCGB2L are not in the
registry, so the digit and label rules matter. A letters-only code that is not in the registry and
has no label is dropped. The test corpus takes its BICs from schwifty's registry, so it is
unaffected.

**D. Coverage beyond the brief's lists**, each tested: GB, CH and NO VAT numbers; `UK_NINO` turned
on; KvK and HRB without "number"; spelled-out numbers with figures in brackets; ranges; Swiss
apostrophes; figure space; magnitudes on quantities ("2.5 million units"); the extra units above.
The aim is "when in doubt, hide". Each one can be removed if you want the strict lists.

**E. Commit trailer.** I ended both commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`,
not the boilerplate's `Claude Fable 5.1`. The trailer names the model that wrote the commit; this
session's harness requires the Opus 5.5 line, and the plan's own wording is "the attribution trailer
this session requires". If you want the trailers uniform, an amend of the message is all it takes.

## Verification

```
$ uv run pytest -q -rw            → 621 passed in 3.01s (219 in tests/detect), no warnings
$ uv run ruff check src tests     → All checks passed!
$ uv run ruff format --check src tests → 19 files already formatted
$ uv run mypy src                 → Success: no issues found in 9 source files
```

Performance: a 12,090-word synthetic contract with values in every sentence took **5.0 s** to
analyse (budget: 60 s for 30 pages). The time goes to Presidio's lemma context enhancer, Presidio's
O(n²) `remove_duplicates`, the phone matcher over 16 regions, and spaCy.

## TDD evidence

- **RED:** `uv run pytest tests/detect/test_patterns.py -q` →
  `E ModuleNotFoundError: No module named 'themask.detect'`,
  `1 error during collection`. This was expected: the package did not exist yet.
- **GREEN:** the same command gave `211 passed in 2.71s` on the first implementation. All tests
  passed on the first try, so I checked that they really catch regressions by running mutation
  plugins (`pytest -p <mutant>`, each breaking one behaviour in-process, with no edits to the
  worktree). Every mutant was caught:

  | Mutant | Failing tests |
  |---|---|
  | engine trims nothing | 3 (URL spans) |
  | year exclusion removed | 7 |
  | BIC = schwifty validity only | 4 (SUPPLIER/TERMINATION/…) |
  | e-mail rejects `.example` (stock-Presidio behaviour) | 4 |
  | stock Presidio URL recognizer | 6 (`https://www.no`, `j.sm`, `Goods.It`) |
  | durations not excluded | 7 |
  | Presidio's default phone regions | 1 at first. I strengthened the test with numbers only the owner's regions find, and now 7 fail |

- **Missing-model guard:** RED with downloads stubbed to raise →
  `RuntimeError: download attempted: ('xx_no_such_model',)`, 1 failed. GREEN → 1 passed. The
  stub was a scratch plugin; no network was used.

## Files

- `src/themask/detect/__init__.py`: package docstring only. It does not import the engine, so the
  later `detect` modules do not pull in spaCy.
- `src/themask/detect/engine.py`
- `src/themask/detect/nlp_config.yaml`
- `src/themask/detect/patterns.py`: 677 lines, all of them the recognizers the plan assigns to this
  file.
- `tests/fixtures/engine.py`
- `tests/detect/__init__.py`
- `tests/detect/test_patterns.py`

## Self-review

- Completeness: every item in the brief and every controller decision is checked off.
  - Decision 1 (mapping) and decision 4 (sources).
  - Decision 2 (YAML).
  - Decision 3 (regions; the test pins the exact list).
  - Decision 5 (every recognizer and score).
  - Decision 6 (trailing punctuation; the exclusions tested).
  - Decision 7 (sorted, no overlap resolution, Task 7 hook point).
  - Decision 8 (negatives for every recognizer; `\N{}` escapes).
- Quality: I restructured the regex composition into named fragments plus `_any_of`, so that
  `ruff format` (which the repo follows) keeps the patterns readable. Comments explain each choice
  in the repo's plain-English style.
- Found and fixed in self-review: Presidio's model auto-download path (`387f4d5`), and a phone
  regions test that did not really pin the regions.

## Concerns (for the controller, mostly later tasks)

1. **Presidio's `IpRecognizer` hides four-level clause numbers.** "Clause 12.3.4.1 applies" gives
   `ID '12.3.4.1'` at 0.6, which goes against "clause numbers stay visible". It is a Presidio
   built-in that decision 1 keeps (`IP_ADDRESS→ID`). A possible fix for Task 7 or 24: drop
   IP_ADDRESS after a clause word or at a line start, or replace the recognizer.
2. **Presidio's US driver-licence recognizer scores product codes at exactly 0.3.** Its weak
   alphanumeric pattern turns codes like `A1234` and `B20260101` into ID findings at 0.3, and these
   are kept because the threshold is "< 0.3 dropped". A question for Task 24.
3. **Bare-number fragments inside other values are expected noise.** `20 123` and `4567` inside a
   phone number, `1643` inside an IBAN, `1015` in a postcode, `9001` in "ISO 9001". Task 8's
   longest-span rule removes them. When the longer value is not recognised, the fragments are still
   hidden, which leaks less.
4. **Task 8's "check" flag will catch most phone numbers and URLs.** Presidio's own scores are
   PHONE 0.4 and URL 0.5/0.6 without context words, so Task 8's `needs_check` (< 0.7) flags nearly
   every one of them. Task 8 or 24 may want to tune this.
5. **Logging (Task 19): Presidio writes document words to its DEBUG log.**
   `LemmaContextAwareEnhancer` logs the words around each finding at DEBUG
   (`lemma_context_aware_enhancer.py:274`, `"Context list is: %s"`). Keep the `presidio-analyzer`
   logger at WARNING or above.
6. **An IBAN with a wrong check digit gets no IBAN or ID finding.** That is as the brief asks, but
   only parts of its digits end up hidden, as PHONE and AMOUNT fragments. A "format only" ID for
   IBAN-shaped strings may be worth adding in Task 24: an IBAN with a typing error still identifies
   the account.
7. **Model noise for Task 7 and 8.** spaCy tags "Price", "IBAN", "BIC", "Order", "EU" and "CHF" as
   ORG, which becomes COMPANY at 0.85, and "Annex 2" as LOCATION. This is for the never-hide list,
   the legal-form cap and the LOCATION gate.

## Ruling R12: four Presidio recognizers dropped

**Commit:** `d729ebd` fix: drop the Presidio recognizers that hide clause numbers and codes (R12)

**What changed:** `engine.py` gains `_DROPPED_RECOGNIZERS`, the one place that lists what the engine
does without, with a one-line reason for each:
- `IpRecognizer`: reads four-level clause numbers (12.3.4.1) as IP addresses.
- `UsLicenseRecognizer`: flags product codes such as A1234 at exactly the 0.3 threshold.
- `UsBankRecognizer`: takes any 8 to 17 digits near "bank" or "account"; our own recognizer finds the
  labelled account numbers.
- `MedicalLicenseRecognizer`: finds US DEA numbers, which these contracts do not hold.

`Engine.__init__` removes these four together with the three replaced recognizers. Their entities
stay in `_PRESIDIO_TYPES`, so the mapping still holds if one of them is ever brought back. Nothing
else changed. IP addresses are no longer found, which is a known limit.

**This resolves concerns 1 and 2 above.**

**Covering tests** (`tests/detect/test_patterns.py`, at the end):
- `test_four_level_clause_numbers_stay_visible`: `12.3.4.1 applies` and `clause 12.3.4.1` give no
  findings.
- `test_codes_are_not_ids`: `product code A1234`, the DEA-valid `code AB1234563` and
  `bank reference 123456789012` give no ID. I added the last two so that each dropped recognizer has
  a test that fails if its removal silently stops working.
- `test_ip_addresses_are_not_found`: `192.168.0.1` gives no findings. The docstring records this as
  a known limit.

**RED** (before the change): `uv run pytest tests/detect -q` gave `6 failed, 219 passed`. The four
recognizers produced, in turn:
- `ID '12.3.4.1'` at 0.6 (IpRecognizer), in both clause texts;
- `ID '192.168.0.1'` at 0.6 (IpRecognizer);
- ID from US_DRIVER_LICENSE at 0.3 on `A1234`;
- `MEDICAL_LICENSE` at 1.0 on `AB1234563`;
- `US_BANK_NUMBER` at 0.4 on `123456789012`.

**GREEN:**
```
$ uv run pytest tests/detect -q        → 225 passed in 2.71s
$ uv run pytest -q                     → 627 passed in 2.60s
$ uv run ruff check src tests          → All checks passed!
$ uv run mypy src                      → Success: no issues found in 9 source files
$ uv run ruff format --check src tests → 19 files already formatted
```

## Fix round 1: review Important 1 and ruling R13 (a–d)

**Commit:** `c0f687c` fix: keep numeric dates and headings visible, match number words in linear time

### What changed

**Important 1: numeric dates no longer come back as phone numbers or IDs.**

`engine.py` keeps Presidio's `DateRecognizer` and uses its DATE_TIME spans as a veto:
`_presidio_findings` drops any PHONE, ID, AMOUNT or QUANTITY finding (`_DATE_SHAPED_TYPES`) that lies
within a date (`_within_a_date`). DATE_TIME results themselves are still dropped, as before. Every
hyphenated date shape in the DateRecognizer needs a four-digit year, so a sort code such as 12-34-56
is never vetoed; its existing test still passes.

In `patterns.py`, the account number and the sort code need their label directly before them on the
same line: `account` / `acct` / `a/c`, optionally followed by `number`, `no` or `nr`, then an optional
`:` or `#`. This replaces the earlier window of 20 characters. A value shaped like a hyphenated date
(`dd-mm-yyyy`, `yyyy-mm-dd`) is dropped (`_HYPHENATED_DATE`).

**R13-a: the BIC label counts only on the same line, directly before the code.**

`_BIC_LABEL` is a run of label words ("BIC", "SWIFT", "bank identifier", optionally followed by
"/SWIFT", "(SWIFT)" or "code"), then `:` or spaces, ending exactly where the code begins. Spaces here
cannot include a line break. It replaces the earlier window of 40 characters, which could reach across
lines.

**R13-b: number words now match in linear time.**

`_BELOW_HUNDRED` no longer carries its own hyphen form. A hyphen is now only `_WORD_GAP`, so
"twenty-one" has exactly one reading and the backtracking is gone. The language is unchanged: every
existing number-word test still passes.

**R13-c: domains written without `https://` or `www.` need a known top-level domain.**

The `[a-z]{2}` wildcard is gone. A bare domain needs either:
- a TLD from `_TOP_LEVEL_DOMAINS` (common generic ones, `.example`, and country codes that are not
  English words), with the name in any case; or
- a TLD from `_WORD_TOP_LEVEL_DOMAINS` (`at be it no us in`, and gTLDs such as `shop`, `law` or
  `group`), with the name written all in lower case.

So `acme.it` is a URL, while `the Supplier.it shall` stays text. Addresses starting with `https://` or
`www.` are unchanged and still allow any TLD.

**R13-d:** `product code A1234` and `code AB1234563` must now give no findings at all.
`bank reference 123456789012` keeps its "no ID" assertion, because as a bare number it is still an
AMOUNT.

### Covering tests (`tests/detect/test_patterns.py`)

- `test_dates_are_not_findings`: the full engine gives no findings for each of:
  - `dd.mm.yyyy`, `dd-mm-yyyy`, `31-12-2026`;
  - `yyyy-mm-dd`, `2026-12-31`;
  - `dd/mm/yyyy`;
  - `1 March 2026`, `March 1, 2026`;
  - the reviewer's sentence;
  - `taking into account the 01-03-2026 forecast`.
- `test_a_phone_number_next_to_a_date_is_still_found`: `call +31 20 123 4567 on 01.03.2026` gives
  PHONE only for `+31 20 123 4567`.
- `test_headings_after_a_bic_are_never_findings`: in the reviewer's IBAN / BIC / SUPPLIER text
  (plus a CUSTOMER line), the engine reports no "SUPPLIER" or "CUSTOMER" finding, and the BIC
  recognizer finds only `ABNANL2A`.
- BIC: new positives `BIC/SWIFT code:`, `BIC (SWIFT):` and `…, BIC DEUTDEFF`; new negatives
  `SWIFT\nDEUTDEFF` (label on the line before) and `the BIC of the SUPPLIER`.
- Account numbers: new negatives `the account holder, 12345678`, the reviewer's date sentence,
  `Account: 01-03-2026`, `account 2026-03-01` and `account\n12345678`. The existing positives still
  pass.
- `test_long_runs_of_number_words_are_quick`: 40 hyphenated number words go through the full engine
  in under 1 s.
- Web addresses:
  - `test_web_address_needs_a_whole_domain`, now at both recognizer and engine level, gives no URL
    for `warehouse.of`, `Supplier.to`, `Goods.it` and `Supplier.in`.
  - `test_web_addresses` adds `northwind.example`, `acme.co.uk`, `acme.it/terms`, `Acme.com`, and
    `https://www.acme.to/terms` (scheme form, any TLD).
- `test_codes_are_not_findings` and `test_a_bank_reference_is_not_an_id`.

### RED (tests run against the pre-fix code)

I had written the fixes before their tests, so to get a real RED I stashed only `engine.py` and
`patterns.py` (`git stash push -- …`), ran the tests, then restored the files with `git stash pop`.

- `uv run pytest tests/detect -q` gave **`20 failed, 237 passed`**. All 20 failures are new tests aimed
  at the fixes: 7 date cases, the phone-next-to-a-date case, the SUPPLIER/CUSTOMER headings, 2 BIC
  negatives, 4 account negatives, 4 missing-space URLs, and the timing test.
- The cases that passed on the old code too were the positives, `01/03/2026` and the word-month
  dates (no phone match), and R13-d (fixed by R12 already).
- Number words before the fix: 40 hyphenated words took **6.68 s** across the four number
  recognizers. After the fix they take **0.001 s**.
- A wider adversarial check (long runs of digits, separators, labels, domain parts and number words,
  around 2,000 characters each, against all 11 recognizers) peaks at **0.03 s**.

### GREEN

```
$ uv run pytest tests/detect -q        → 257 passed in 2.40s
$ uv run pytest -q                     → 659 passed in 3.06s
$ uv run ruff check src tests          → All checks passed!
$ uv run mypy src                      → Success: no issues found in 9 source files
$ uv run ruff format --check src tests → 19 files already formatted
```

The 12,090-word performance text still takes about 5.6 s. The Minors deferred to Task 24 are left
as they were.
