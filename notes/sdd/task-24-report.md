# Task 24 report: pass marks and tuning

Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-24`, branch `task-24`. Base: 39419f5, fast-forwarded (by the controller) to 92d396f (Tasks 20+21) before my first commit. Head: 2864638. Scope per R87: `tools/evaluate.py`, `tests/test_passmarks.py` (`test_pass_marks`, `test_thirty_pages_under_sixty_seconds`) and the tuning loop. `test_full_round_trip_every_docx` is **not written yet**; it waits for Task 18's Word half.

## Status: DONE_WITH_CONCERNS (concerns at the end; none blocks)

## Results (also in the plan under "## Results")

| Check (spec §9) | Baseline (92d396f) | Final (2864638) | Pass mark |
|---|---|---|---|
| Pattern-type items found before review | 99.3 % (907/913) | **100.0 % (913/913)** (Word 719/719, PDF 194/194) | ≥ 99 % |
| Names, companies, addresses found before review | 100.0 % (320/320) | **100.0 % (320/320)** (Word 255/255, PDF 65/65) | ≥ 95 % |
| Never-hide terms hidden by mistake | 0 | **0** | 0 |
| Thirty-page file read + analysed (slowest) | 3.4 s (supply-10.pdf) | **3.4 s** (Word 2.2 s) | < 60 s |
| Found secrets hidden as their own type (info) | 96.3 % | **99.9 %** | – |
| Groups that hide no secret (corpus) | 39 | **2** | – |
| Secrets split over several placeholders | 76 | **6** | – |

Measured on an Apple M3 with 16 GB (the 8 GB laptop is Task 25's). 35 files analysed (28 Word incl. 3 annexes, 7 PDFs); `scanned-01.pdf` is refused by `load_sources` (ScannedPdfError) and reported as not analysed.

Note on TDD for the pass marks: the pass-mark tests were **green on first run** at the baseline (99.3 % / 100 %), so the tuning loop was not needed to pass them; it was driven by what the evaluation showed behind the numbers (6 misses, 39 groups hiding no secret, 41 IDs typed PHONE, 17 split phones) and by the ledger's Task 24 items. RED for `test_passmarks.py` was only the missing module.

## What I built

### `tools/evaluate.py`
- `evaluate(corpus_dir, engine, user_lists) -> Evaluation` per controller decision 1: each manifest entry (docx and pdf, annexes on their own) goes `load_sources([path], False)` → `combined_text` → `analyze(…, CaseLists([], [], set()))` → `ReviewState.from_analysis`, and the review's `mask_plan()` is held against the truth.
- **Found** = every place of the secret (value and every listed variant, found case-sensitively with `flexible_pattern`'s edges and whitespace rules; places inside a longer place of the same secret dropped) lies inside **one** replacement of any type. Split across two replacements = not found.
- **Not counted** (listed as "not in the text"): secrets flagged `only_in_deletion`/`hidden` (the prepared copy accepts changes and the cleaner drops hidden runs) and secrets with no place in the analysed text (the IBAN on `mixed-01.pdf`'s picture page).
- `Evaluation`: `recall_pattern`, `recall_names`, `type_accuracy` (found secrets all of whose replacements have the truth type), `never_hide_false_positives` ("file: TYPE 'text'"), `misses` (file, type, value), `seconds_thirty_pages` (max load+analyse time over `thirty_pages` files), `documents` (per-file `DocumentResult`), `of_format("docx"|"pdf")`, `counts(types)`, `passed`.
- **Never-hide check**: the canonical and every active finding text of every enabled group, against `never_hide_check(user_lists, case_lists_after_analysis, names=all truth forms)` — defaults, owner lists, references/dates/standards, and the document's defined terms unless they are names of the truth — excluding texts that are truth forms (a hidden secret is never a mistake).
- Diagnostics: per type, per file, misses, never-hide hits, groups whose canonical is no truth form (marked when they overlap a secret), places a secret's group hides outside every secret ("stray"), secrets under more than one placeholder, secrets not in the text.
- CLI: `uv run python tools/evaluate.py [corpus_dir]` prints the §9 table per format and in all, `PASS`/`FAIL`, and the details; without a folder it generates the corpus into a temporary folder (puts the repo root on `sys.path` for `tools.make_corpus`); exit code 0/1. Verified both ways (26.9 s with generation).

### `tests/test_passmarks.py`
- `test_pass_marks` (slow): asserts recall_pattern ≥ 0.99, recall_names ≥ 0.95, `never_hide_false_positives == []`; prints misses, never-hide hits and the per-format numbers.
- `test_thirty_pages_under_sixty_seconds` (slow), parametrised over `supply-10.docx` and `supply-10.pdf` (the brief's body, both formats).
- 8 fast tests of the scoring rules: places as written (case and spacing), found only when every place is hidden, a place hidden in two pieces is a miss, another type is found but typed wrong, secrets not in the text are not counted, groups hiding no secret are listed (with the overlap flag), a hidden never-hide term is listed while a truth name that is a defined term is not, the recalls are shares per class.
- File runtime: ~34 s (`test_pass_marks` 22.7 s call + 4.7 s setup; thirty pages 2.2 s / 3.5 s). No deselect added; slow tests run by default.

## Tuning changes (10 commits, each with focused tests; full suite green before each)

| Commit | Change | Corpus effect |
|---|---|---|
| 868f25f | `records` is a quantity unit ("up to 350,000 records"; one record is none); a figure right after a reference word is no quantity ("the Article 30 records") | the 6 misses (all "N records"), 6 partial AMOUNT groups gone |
| 873be11 | the engine cuts a model finding at " / ", " — ", " – ", " · ", " • ", " \| ", " - " (spaces round), like line breaks/tabs (R58); "logistics", "non-disclosure" join the heading words | 29 running-header groups ("Northwind / Thamesgate — Supply Agreement" as one company, hiding the title, both parties under one placeholder) gone, and with them 54 of the 76 split secrets |
| a777cc9 | grouping: a phone number with its country code and in national form is one value (E.164 key; national form joins only when exactly one international number has it) — ledger Task 8 | 13 phones split by notation → 0 |
| c11dee0 | the label decides: a phone reading of digits our registration/account recognizer read after their label goes (Presidio's phone recognizer took "number" as context, 0.75 > 0.7); an NHS reading after a telephone label goes when the digits are a phone too | ID typed right 95→136/136, PHONE 62→66/66 (the last 4 phones split as ID + PHONE) |
| 8868aa3 | bare numbers: a year after a month with something glued on ("21 July 2026.3", PDF footnote marks), "No 1169/2011", "ISO 9001"/"EN 1090" (and a standard with its number is never-hide), "(10,000) days", "1700 CET"; int() never runs on > 4 digits (ledger: ValueError on ≥ 4,301 digits) | 2 PDF groups ("2026.3" hiding a date's year) gone |
| 1a7894b | labels: tab after a label ("BIC:\tDEUTDEBB"), "Sort code is …", hyphenated account numbers that are no date, a mistyped IBAN after its label → ID 0.6, labelled numbers exempt from the date veto ("Company No. 12/2024"); dates: unmatched leading bracket trimmed ("(01.03.2026"), numeric dates Presidio misses ("2026.03.01", "01-03-26", "01 03 2026") dropped as PHONE/ID/AMOUNT/QUANTITY | – (ledger, Task 6) |
| a192af4 | contract rules: "KG" after a weight word is the unit ("NET WEIGHT KG" was COMPANY 0.95); a word legal form before Tax/Warranty/Guarantee is no legal form ("UK Corporation Tax" was COMPANY 0.95); an address ends with its country; `"X" means` defines a term mid-line too | – (ledger, Tasks 7/8) |
| 4c0b3a4 | pipeline: a one-word person/company the engine found that makes a default term with the next word stays visible ("(1) The Disclosing Party" hid "Disclosing" at 0.9); engine: a model finding loses a leading label made of contract words/never-hide terms ("Country: Netherlands" was a company hiding the country; "BIC: DEUTDEBB" still names nobody); "Hauptstr. 12" read as a street | – (ledger, Task 7) |
| 780373a | Presidio context words match whole words only (`LemmaContextAwareEnhancer(context_matching_mode="whole_word")`): "sum" in "assume", "charge" in "discharge", "cc" in "account" no longer boost scores; no pinned score changed | – (ledger, Task 6) |
| ff76f53 | "First Party"/"Second Party" are roles (were COMPANY 0.9); a model finding loses a salutation ("Dear Smith" was its own person); "1.100 The Supplier" at a line start is a clause number; a web address after "Website:/Web:/URL:" is found with any TLD ("Website: acme.me" was visible) | – |
| 2864638 | evaluator, pass-mark tests, Results; tidy (roles list reflowed — verified only First/Second Party added; IBAN regex split) | – |

## TDD evidence (RED → GREEN; commands from the worktree)
- records: `uv run pytest tests/detect/test_patterns.py -q -k "records or single_record"` → RED 4 failed (3× not found, "Section 5 pallets" found as `5 pallets`), as expected; GREEN `uv run pytest tests/detect/test_patterns.py -q` → 265 passed.
- header separators: `-k running_header_separator` → RED `'Northwind / Thamesgate — Supply Agreement' != 'Northwind'`; GREEN 3 passed. Titles: `-k "contract_wording or title_in_a_running"` RED 3 failed → GREEN 26 passed.
- phones: `tests/detect/test_grouping.py -k "phone or national_form"` RED 1 failed (two groups) → GREEN 44 passed.
- labels decide: `-k "label_calls or nhs_number"` RED 5 failed (PHONE beside ID; NHS ID on "telephone 013 625 5086") → GREEN 39 passed.
- long digit run: `-k very_long_run` RED `ValueError: Exceeds the limit (4300 digits)` → GREEN.
- bare-number guards: `-k bare_number_exclusions` RED 7 failed → GREEN 280 passed; standards `tests/detect/test_lists.py` RED 5 failed → GREEN 137 passed; pipeline `-k references_standards` with the fixes stashed RED 5 failed → GREEN 5 passed.
- label gaps: `-k "tab or more_forms or mistyped_iban or shaped_like_a_date"` RED 7 failed → GREEN 287 passed; dates `-k "dates_are_not_findings or starts_like_a_date"` RED 4 failed → GREEN 294 passed.
- contract rules: legal forms RED 5 failed → GREEN 308 passed; addresses RED 2 failed → GREEN 310; mid-line definitions RED 2 failed → GREEN 313; pipeline tests with the rule fixes stashed RED 4 failed → GREEN.
- role word / label / salutation / str.: RED 3 failed (after making the label test use the text the model actually misreads) → GREEN; the label cut first broke 2 pinned tests ("BIC: DEUTDEBB" names nobody) — fixed in the implementation, not the tests → 1007 passed; "str." RED 2 failed → GREEN 22 passed.
- whole-word context: `-k whole_word` with the previous engine RED 2 failed (0.75 instead of 0.4) → GREEN 4 passed.
- last batch: `-k "first_and_second or salutation or bare_number_exclusions or after_its_label_needs"` RED 7 failed → GREEN 40 passed.
- Final: `uv run pytest -q -m "slow or not slow"` → **2817 passed in 110 s**; `uv run ruff check src tests tools` → clean; `uv run ruff format --check` → clean; `uv run mypy src` → no issues in 43 files. Output pristine.

## Controller decision 5: candid lists

**Truth items still missed: none** (0 of 1,233 counted).

**Truth items not counted (7)**, because the analysed text does not hold them: supply-03 `EUR 224,000.00`, nda-05 `Damian Sullivan`, dpa-03 `privacy@havenlicht.example` (only in tracked-deleted text); services-02 `€769,000.00`, nda-02 `Neil Cartwright`, dpa-03 `+353 1 471 4299` (only in hidden text); mixed-01.pdf `IE96 BOFI 9000 1735 4448 87` (only on the picture page 2). `scanned-01.pdf` is not analysed at all.

**False-positive groups on the corpus (canonical is no truth form): 2**
- supply-08.docx COMPANY `Project Falcon` (model 0.6, marked to check): kept on purpose — the corpus README says it is plain text that later tests add to always-hide.
- supply-08.docx COMPANY `Kraft` (model 0.6, check) in the table cell "Kraft carrier bags": a product word the model takes for an organisation; left (when unsure, hide; one click in review).
- Places hidden outside every secret by a secret's group: 0. Never-hide terms hidden: 0.

**Secrets under more than one placeholder (6, all found)**
- supply-08 `Gary Edwards`, nda-02 `Ricky Powell`, dpa-04 `Samuel Begum` (shared_surname files): "Mr Edwards" is a truth variant, but with two people of that surname the app keeps it a group of its own to check (Review Focus 3) — by design.
- dpa-03 `€1,500,000.00`, dpa-04 `GBP 1,000,000.00`: the truth lists the amount in words as a variant ("one million five hundred thousand euros"); figures and words are two groups. Not merged on purpose: restore writes a group's canonical (longest) form everywhere, so one group would turn the figures into words or the words into figures.
- dpa-02-annex `Merrion Payroll Services Limited`: its short form "Merrion" also stands inside the address "26 Merrion Square, Cork" (a street name), hidden as that ADDRESS — a truth-matching artefact, not a detection error (the one COMPANY "not own type").

**Ledger items (grep "Task 24") — not changed, and why**
- `1.100 The Supplier`-style clause numbers: fixed only at a line start before a capital; mid-sentence "clause 1.100" was already visible.
- "EUR 01.03.2026" as AMOUNT: a currency before a date is contrived; left.
- Rare TLDs without a label ("visit acme.me"): R13 deliberately limits bare domains to known TLDs; fixed only after a website label.
- Continental street-type-first addresses ("5 rue de la Paix", "10 Avenue Louise") and 4-digit postcodes ("1050 Brussels"): a recall gap outside the corpus (EN/NL/DE/IE/TR formats are covered); needs new street anchors with their own FP risks ("Place", "Via") — candidate for a later task. "Avenue Louise" is hidden, as a PERSON to check.
- All-caps parties without a legal form ("ACME GROUP"), "Contract Logistics Ltd" losing its role-word first token, "by and among Glenmore Freight, Kestrel Analytics and Acme Ltd" giving one group "Kestrel Analytics and Acme Ltd" (the "Marlowe Print and Packaging Ltd" reading), persons in party lists typed COMPANY: ambiguous readings in contract_rules where each fix trades one pinned case for another; everything stays hidden.
- The model missing short first names ("Jo Banks", "Theresa May"): no longer reproduces on the probes.
- "Quality" of Quality Foods Ltd stays visible: the documented trade-off (a contract word as a short name).
- Model guess "Product Limited Warranty" (0.6, check): the rule's 0.95 reading is gone; the model's own guess remains.
- Date veto "≥ 0.6 only": done differently — labelled registration/account numbers are exempt from the veto, so low-scored dates still keep unlabelled numbers visible.
- Docstring/perf items (engine docstring vs Presidio's duplicate removal, "linear time" claim, quadratic honorific scan and `_street_anchors` on adversarial input, duplicated vocabularies, mutation-killing tests for `_is_a_jurisdiction`/`_ENDS_A_PARTY`, stale R21 comment, "The registered seat of Greystone" — now hidden on the probe): no behaviour on the corpus; left for the final review.
- Outside detection: Task 11's w14:conflictIns/conflictDel, Task 13's masker minors (masker is out of bounds per decision 3).

## Files changed
- New: `tools/evaluate.py`, `tests/test_passmarks.py`.
- Detection: `src/themask/detect/engine.py`, `patterns.py`, `contract_rules.py`, `grouping.py`, `lists.py`, `pipeline.py`.
- Tests: `tests/detect/test_patterns.py`, `test_contract_rules.py`, `test_grouping.py`, `test_lists.py`, `test_pipeline.py` (only additions; no existing assertion changed or deleted).
- Docs: `docs/superpowers/plans/2026-10-17-the-mask-mac-v1.md` (## Results).

## Self-review findings (fixed before the final commit)
- The leading-label cut first made "BIC: DEUTDEBB" a model name (2 pinned tests failed): a label followed by a code still names nobody.
- The roles list reflow was checked by diffing the old and new `DEFAULT_NEVER_HIDE` keys: only `firstparty`, `secondparty` added.
- Engine: the recognizer name is now read after the None check; the evaluator lost an unused constant, an assert-based truth reader and a string-splitting hack.

## Concerns
1. **Restore trade-off of the phone merge**: a national-form occurrence ("telephone 030 360 7352") now comes back from restore as the group's canonical international form ("+31 30 360 7352") — the same number, other notation, like "Mr Smith" → "John Smith" (spec §10). The ledger asked for the merge; flagging it for the round-trip test.
2. **mac-v1 moved** (6bec7ea, Task 19 log test: `logging_setup.py`, `tests/test_logging.py`). Not merged (waiting for your word); a no-commit trial merge was clean and `tests/test_logging.py` + `tests/detect/test_patterns.py` passed (314), then aborted.
3. **One flaky run**: a full run once stopped with "1 failed, 1585 passed" and passed on the immediate rerun (2806 passed); position matches `tests/test_leakcheck.py::test_thirty_pages_are_scanned_in_under_two_seconds` (a wall-clock limit, already a ledger note). It passed 3/3 in isolation (3.2 s per run including setup).
4. **Commit trailer**: commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the attribution this session requires, as earlier implementer commits do), not the boilerplate's Fable 5.1.
5. `test_full_round_trip_every_docx` is still to write once Task 18's Word half merges (`restore_docx`, `simulate_ai` are not on this branch yet).
6. A count in a commit body is off: a777cc9 says "(20 were split)"; the baseline had 17 split phones, 13 by notation (fixed there) and 4 as ID + PHONE (fixed by c11dee0). Not rewritten (no interactive rebase here); the numbers in this report and in the plan are the checked ones.

---

## Fix round 1 (ruling R95) — commit 196b181

Every item got a counter-test next to its target test, written first and seen failing (RED) before the fix (GREEN). I re-ran the reviewer's probes (`scratchpad/r24/probes/`, outputs in `scratchpad/r24/fix1/`): every listed case now matches base or improves on it.

| Item | Fix | Counter-tests (RED → GREEN) |
|---|---|---|
| C1 | The line-start guard applies only to the clause shape `\d{1,3}\.\d{3}` (one point, no comma, no further groups, no decimals) — `patterns._is_a_clause_number` | `test_an_amount_at_the_start_of_a_line_is_still_found` (the 5 cases: `48,000\t…fee`, `12,500\t…`, `27,500 Implementation fee`, `1,250,000 Base price …`, `1.250.000 Gesamtpreis`) 5 failed → passed; `test_an_amount_before_what_it_pays_for_in_a_word_file_is_hidden` (generated .docx with a tab and a one-cell table, through `load_sources`) failed → passed; the 2 pinned exclusions still pass. Reviewer's file probe: every amount hidden in prices.docx and prices.pdf |
| I1 | A plain year 1900–2099 before "records" is the records' year (`_are_records_named`) | `test_a_reference_a_year_or_a_single_record_is_no_quantity` ("the 2025 records", "the 2026 and 2027 records") 2 failed → passed |
| I2 | The quantity reference guard only applies before "records" (no longer "parts" etc.) | `test_a_quantity_after_a_word_like_parts_is_still_found` ("spare parts 500 units", "replacement parts 2,000 pieces") 2 failed → passed. The earlier "Section 5 pallets" negative (my own, from 868f25f) is gone with the guard |
| I3 | After the country the address goes on when the next part is postcode-shaped: one or two words of ≤ 8 letters/digits, a digit among them, no label word (`_is_a_postcode_part`) | `test_addresses`: Eircode ", Ireland, D02 X285", ", London, United Kingdom, SW1A 1AA", ", Cardiff, Wales, CF10 1AA, United Kingdom", ", Edinburgh, Scotland, EH2 1JX" 4 failed → passed; ", Belgium, VAT BE…", "Attention Finance", "Company Secretary" still stay out |
| I4 | `Website/Web/URL/Internet/Homepage` + a colon or a tab, and a top-level domain of ≥ 2 letters | `test_a_word_after_a_web_label_is_no_web_address` (e.g./i.e. after web/internet/URL, "web site.Customers", "Website: e.g. the portal") 5 failed → passed; the 3 positives still pass |
| I5 | `score`: a secret with no place in the text is a miss (`all([])` made it found) unless the truth flags it (deleted/hidden) or its file lists `image_pages`; `_ratio(0, 0)` is 0.0; `test_pass_marks` asserts skipped == [scanned-01.pdf], 35 files analysed and the exact left-out set (6 flagged + mixed-01's IBAN) | `test_a_secret_missing_from_the_text_is_a_miss_unless_a_page_is_a_picture`, `test_no_secret_counted_is_no_pass` (failed → passed); slow `test_pass_marks` passes with the new assertions |
| M1 | A telephone/fax/switchboard/contact label right before the digits: the phone reading wins over a registration/account/NHS reading (`_read_as_labelled`) | `test_a_number_its_label_calls_a_telephone_number_is_no_id` ("Company telephone number:", "Company fax number:", "Registered office telephone number:", "Company contact number:", "company switchboard number") 5 failed → passed; "registered under number 08846969" and "Account number: 08846969" still ID |
| M2 | A spaced hyphen between two capitalised words is no separator, unless the contract's own words follow it (`_part_breaks`) | `test_a_spaced_hyphen_between_names_is_no_separator` (one company "Smith - Jones Logistics Ltd"; no lone "Managing") failed → passed; `test_a_spaced_hyphen_before_a_title_still_parts_a_header` ("Greystone - Brinkhof - Agreement": "Agreement" not hidden) guards the exception |
| Times | Model names that are a time of day ("17:00 CET", "09:00 GMT", "9.30 am") are dropped in `_checked_by_rules` | `test_a_time_of_day_is_never_a_name` 3 failed → passed |
| Extra (found in the probe diffs) | The term guard after a legal form written as a word needs the term in capitals and ignores its punctuation: "Acme Corporation warranty claims" and "The Acme Holdings Limited guarantee" keep their company (head lost "Corporation" and merged "Acme" into Acme Holdings Limited); "advises on UK Corporation Tax." is no company | `test_a_legal_form_before_a_word_in_lower_case_ends_the_company` 3 failed → passed; `test_no_legal_form_company["It advises on UK Corporation Tax."]` failed → passed |
| Extra | "subtotal" joins the price words (whole-word matching had dropped "Subtotal 48,000" from 0.75 to 0.4) | `test_a_context_word_counts_only_as_a_whole_word["Subtotal: 48,000 in all"]` failed → passed |

### Re-run (same corpus, `uv run python tools/evaluate.py <corpus>`, exit 0)

| Check (spec §9) | Word | PDF | All | Pass mark |
|---|---|---|---|---|
| Pattern-type items found before review | 100.0 % (719/719) | 100.0 % (194/194) | 100.0 % (913/913) | ≥ 99 % |
| Names, companies, addresses found before review | 100.0 % (255/255) | 100.0 % (65/65) | 100.0 % (320/320) | ≥ 95 % |
| Never-hide terms hidden by mistake | 0 | 0 | 0 | 0 |
| Thirty-page file read + analysed (slowest) | 2.5 s | 3.5 s | 3.5 s | < 60 s |
| Found secrets hidden as their own type | 99.9 % | 100.0 % | 99.9 % | – |

The numbers did not drop. Misses 0; groups hiding no secret 2 (Project Falcon, Kraft); split secrets 6 (as before); left out exactly the 7 expected secrets; 35 files analysed, scanned-01.pdf skipped. The plan's Results table still holds (same figures).

### Commands and output
- `uv run pytest tests/test_passmarks.py -q -m slow -s` → 3 passed in 34.7 s (docx 1.0/1.0/2.4 s, pdf 1.0/1.0/3.6 s)
- `uv run pytest -q -m "slow or not slow"` → **2855 passed** in 113 s
- `uv run ruff check src tests tools` → All checks passed; `uv run ruff format --check src tests tools` → 119 files already formatted; `uv run mypy src` → no issues in 43 files

### Left as they are
- The parked items (Either/Neither Party, GMT, EC, Federal Republic of Germany) and the accepted phone merge, as ruled.
- "Address: …, the Netherlands, Attention Finance": the address now ends at the country, and the model's own "Attention Finance" is a company to check (0.6). Base hid it inside the over-long address.
- "Ship to: Keizersgracht 123 - 1015 CJ Amsterdam" leaves "CJ Amsterdam" visible, as base did. A spaced hyphen before a Dutch postcode is not read as the start of an address part. This is pre-existing and not in this round's list.
- `test_full_round_trip_every_docx` still waits for Task 18's merge. mac-v1 is still not merged into task-24.

---

## Fix round 2 (R97 + round trip)

Worktree `/home/user/the-mask-worktrees/task-24` (cloud, Linux), branch `task-24`, on top of 9438038 (the controller's WIP checkpoint; mac-v1 0baa904 is merged in at b715080). Commits: 993a12e (fix), ec8ec1c (docs).

### Status: DONE_WITH_CONCERNS (concerns at the end; none blocks)

### What I inherited and what I did with it
- **WIP commit 9438038**: the finished `test_full_round_trip_every_docx` and RED cases for R97 (a) and (c). Kept as they are. The round trip passes on all 28 Word files with no change to the test, so there is no `test:` commit.
- **The interrupted implementer's uncommitted diff**: `contract_rules.py`, `engine.py` and `patterns.py`, with tests in `test_contract_rules.py`, `test_patterns.py` and `test_pipeline.py`. The last file was not on the dispatch's list but was in `git status`. It implemented all four items, and `tests/detect` was green (1044 passed). I saved it as a patch (`git diff > …/inherited-src.patch`) and reverted only its source half (`git apply -R`) to see every new test fail (RED below). Then I re-applied it and reviewed it line by line. I probed it with made-up strings through the whole pipeline, against a copy of HEAD's source (`git archive HEAD src`).
  - **Kept**: all four implementations and every inherited test.
  - **Redone**: formatting (`ruff format --check` flagged `patterns.py` and `test_contract_rules.py`). I restructured the quantity guard into two named helpers, `_is_a_reference` and `_is_the_records_year`, in the style of HEAD's `_are_records_named`. The regexes are now built compactly (`_QUANTITY_REFERENCE`, `_YEAR`, `_OWNER` via `_any_of`, `_BETWEEN_YEARS`), and a 101-character docstring line in `engine.py` is wrapped.
  - **Added**: fixes for two regressions that the inherited (a) brought against HEAD (see (a) below), each with RED tests.

### What changed, per R97 item
- **(a) References** (`src/themask/detect/patterns.py`: `_QUANTITY_REFERENCE`, `_REFERENCE_BEFORE_A_QUANTITY`, `_SPACED_DIGITS`, `_is_a_reference`, called from `QuantityRecognizer.score_match`).
  - A figure is a reference, whatever unit follows it, after clause(s), section(s), article(s), schedule(s), annex(es), appendix/appendices, exhibit(s), paragraph(s), "§" and "Part"/"PART" with its capital.
  - "parts", "part" in lower case and the words "art", "para" and "sec" are not references. Examples: "spare parts 500 units", "the art 12 pieces", "replacement parts 2,000 pieces", "the spare part 5 units".
  - My two additions:
    1. "Art.", "Sec." and "Para.", written with their full stop, stay references. The inherited diff hid "the Art. 30 records of processing activities" as QUANTITY "30 records", which HEAD kept visible. See Concern 1.
    2. After a reference word, a figure that goes on with a group of digits after a space ("as set out in Schedule 3 500 pallets") stays a quantity (when unsure, hide). The inherited diff left "500 pallets" visible, where HEAD hid "3 500 pallets".
  - The bare-number guard (`_REFERENCE_BEFORE`) is untouched.
- **(b) Hyphenated headers** (`src/themask/detect/engine.py`: `_part_breaks`, new `_is_header_word` = `is_contract_wording(word) or is_default_term(word)`). A spaced hyphen between two capitalised words is still cut when the word on either side is a header word. "Confidential - Acme Supplies Ltd - Page 3" now gives the one company "Acme Supplies Ltd". HEAD gave one company "Confidential - Acme Supplies Ltd - Page". "Smith - Jones Logistics Ltd" stays one company, and "Greystone - Brinkhof - Agreement" keeps "Agreement" visible (the round-1 tests pass unchanged).
- **(c) Years and counts before "records"** (`patterns.py`: `_YEAR`, `_YEAR_RECORDS`, `_OWNER`, `_BETWEEN_YEARS`, `_OWNER_BEFORE`, `_is_the_records_year`).
  - A figure from 1900 to 2099 before "records" is their year only after "the", "its", "their", "our", "your", "his", "her" or "my", or a possessive ("Acme's", "Supplier’s", "Suppliers'"). Other years of a list may stand between ("the 2024, 2025 and 2026 records").
  - Anywhere else it is a count: "up to 2000 records", "about 2025 records", "approximately 1999 records", "no more than 2050 records", "a total of 2000 records", "the first 2000 records".
- **(d) Dutch postcodes after a spaced hyphen** (`src/themask/detect/contract_rules.py`: `_SPACED_DASH`, `_starts_next_part`, and `_town_follows`, factored out of `_postcode_anchors` with its logic unchanged).
  - A spaced hyphen, or the en dash Word makes of one, before a Dutch postcode with its town starts the next part of the address being read. "Ship to: Keizersgracht 123 - 1015 CJ Amsterdam" is one ADDRESS. HEAD gave ADDRESS "Keizersgracht 123", AMOUNT "1015" to check, and left "CJ Amsterdam" visible.
  - A hyphen starts no address on its own: `_postcode_anchors` still needs `_STARTS_A_PART`. The address stops before "- Supply Agreement", and the engine still cuts "Greystone - Brinkhof - Agreement".

### Tests (counter-tests next to their targets; no existing assertion changed or removed)
- `tests/detect/test_patterns.py`:
  - `test_a_reference_a_year_or_a_single_record_is_no_quantity`:
    - from the WIP: R97 (a) "Section 5 pallets", "Annex 2 Units of Measure", "Schedule 3 Pallets", "under Clause 4 cartons are listed", "Part 2 Units", and R97 (c) "Acme's 2025 records are kept.";
    - inherited: (c) "the Supplier’s 2025 records", "the Suppliers' 2025 records", "its 2025 records", "the 2024, 2025 and 2026 records", "THE 2025 RECORDS ARE KEPT"; (a) "PART 2 UNITS OF MEASURE", "Exhibit 4 boxes are attached", "Appendix 3 Items and Prices", "as paragraph 2 units are counted", "§ 5 pallets";
    - mine: "the Art. 30 records of processing activities", "ART. 30 RECORDS", "under Sec. 5 pallets are listed", "as Para. 2 units are counted".
  - `test_a_quantity_after_a_word_like_parts_is_still_found`:
    - from the WIP: "the spare part 5 units", "the art 12 pieces", and the five counts from the ruling;
    - inherited: "the first 2000 records", "The Processor holds 2000 records.".
    - The comment above this test was the only changed line: R95's "only records after a reference word is a reference" became R97's rule.
  - New (mine): `test_a_count_after_a_reference_without_its_comma_is_still_found`: "Schedule 3 500 pallets", "Clause 4 250 units" with a no-break space, "the Article 30 500 records".
- `tests/detect/test_contract_rules.py` (inherited):
  - `test_a_dutch_postcode_after_a_spaced_hyphen_goes_on_the_address` (5 cases: hyphen, en dash with country, "Delivery address:", a hyphen before a title that no address continues over, address then title);
  - `test_a_spaced_hyphen_starts_no_address_on_its_own` ("Page 2 - 1500 KG Steel");
  - `test_a_spaced_hyphen_by_a_never_hide_word_still_parts_a_header` (engine; "Confidential/CONFIDENTIAL - … - Page 3", "Draft - … - Version 2", "… - Netherlands", "Confidential - Greystone - Page 2").
- `tests/detect/test_pipeline.py` (inherited): `test_a_hyphenated_running_header_hides_only_its_company` (masked text "Confidential - [COMPANY_1] - Page 3"), `test_a_dutch_postcode_after_a_spaced_hyphen_is_hidden_with_its_street` (one ADDRESS group, "Ship to: [ADDRESS_1]").

### RED → GREEN (commands from the worktree)
- **Inherited tests against HEAD's source** (the inherited source half reverted with `git apply -R`, every test kept): `uv run pytest tests/detect/test_patterns.py tests/detect/test_contract_rules.py tests/detect/test_pipeline.py -q -k "reference_a_year or word_like_parts or spaced_hyphen or dutch_postcode or hyphenated_running_header or starts_no_address"` gave **28 failed, 21 passed**. The 21 that passed are guards that hold both before and after:
  - 12 no-quantity cases: the 4 from round 1, and the 8 year cases (R95 already made every year a year);
  - 5 count cases: round 1's 3, "the spare part 5 units" and "the art 12 pieces";
  - 4 rule cases: the 2 round-1 hyphen tests, "Ship to: Keizersgracht 123 - Supply Agreement" and "Page 2 - 1500 KG Steel".

  The failures were the expected ones:
  - (a): 10 cases, for example `assert {'2 Units': 0.8} == {}` ("Annex 2 Units of Measure"), `{'5 pallets': 0.8} == {}` ("Section 5 pallets", "§ 5 pallets") and `{'4 cartons': 0.8} == {}`.
  - (c): 7 cases, for example `assert {} == {'2000 records': 0.8}` ("up to 2000 records") and `{} == {'2025 records': 0.8}` ("about 2025 records").
  - (b): 5 engine cases. The finding was the whole header, for example `'Confidential - Acme Supplies Ltd - Page'` and `'Draft - Acme Supplies Ltd - Version 2'`. The pipeline test got `[COMPANY_2] 3` for the header line.
  - (d): 4 rule cases, for example `assert {'Keizersgracht 123'} == {'Keizersgracht 123 - 1015 CJ Amsterdam'}`. The pipeline test got groups `ADDRESS 'Keizersgracht 123'` and `AMOUNT '1015'`.
- **The same tests with the source re-applied**: all green (`tests/detect`: 1044 passed before my additions).
- **My additions** (a): `uv run pytest tests/detect/test_patterns.py -q -k "reference_a_year or without_its_comma"` gave RED 7 failed: `{'30 records': 0.8} == {}`, `{'30 RECORDS': 0.8} == {}`, `{'5 pallets': 0.8} == {}`, `{'2 units': 0.8} == {}`, `{} == {'3 500 pallets': 0.8}`, `{} == {'4\xa0250 units': 0.8}` and `{} == {'30 500 records': 0.8}`. After the fix, GREEN: `uv run pytest tests/detect/test_patterns.py -q` gave 356 passed.

### Probes (made-up strings, whole pipeline; HEAD = `git archive HEAD src`, final = this commit)
| Text | HEAD | Final |
|---|---|---|
| Schedule 3 Pallets / Section 5 pallets / Part 2 Units | number hidden (QUANTITY) | visible |
| The Goods under Clause 4 cartons are listed | "4 cartons" QUANTITY | visible ("Goods under" is a model COMPANY guess flagged to check, the same at HEAD) |
| the Art. 30 records of processing activities | visible | visible (inherited diff: "30 records" hidden) |
| as set out in Schedule 3 500 pallets shall … | "3 500 pallets" QUANTITY | "3 500 pallets" QUANTITY (inherited diff: visible) |
| spare parts 500 units / the art 12 pieces / replacement parts 2,000 pieces | QUANTITY | QUANTITY |
| SPARE PART 5 UNITS | "5 UNITS" QUANTITY | visible (see Concern 2) |
| Confidential - Acme Supplies Ltd - Page 3 | one company incl. "Confidential" and "Page" | "Confidential - [COMPANY_1] - Page 3" |
| Northwind - Acme - Supply Agreement - Page 2 | "Supply Agreement - Page" COMPANY to check | title and page visible ("Northwind - Acme" one company to check: parked) |
| Smith - Jones Logistics Ltd / John Carter - Managing Director | one company / "John Carter - Managing" | unchanged |
| up to / about / approximately / no more than / a total of N records | visible | QUANTITY |
| the 2025 records / Acme's 2025 records | visible | visible |
| Ship to: Keizersgracht 123 - 1015 CJ Amsterdam (also with ", the Netherlands"; the en dash form is in the rule tests) | ADDRESS street + AMOUNT "1015", "CJ Amsterdam" visible | one ADDRESS |
| Delivery address: Damrak 1 - 1012 LG Amsterdam | ADDRESS + AMOUNT + COMPANY "LG" | one ADDRESS |
| Keizersgracht 123 - 1015 CJ Amsterdam - Supply Agreement | street + AMOUNT "1015" to check | address up to "Amsterdam"; title visible |

### The round trip (`test_full_round_trip_every_docx`, from the WIP commit, unchanged)
I read the test against the brief's version. It asserts everything the brief's version does: export not blocked; every key value in the restored text; outside `existing_placeholders` files, the set of placeholders left is exactly {"[PERSON_9]"}. On top of that it checks:
- the fingerprint: `plan_docx(ai, case).sha256` passed as `expected_sha256`;
- every truth secret (but the deleted or hidden ones) in the restored text, a check that no value came back in another's place;
- `needs_check == []`, and `altered_restored` equals the altered items of the plan;
- the one altered item is the AI's `[PERSON 1]` (none when an annex names no person), and `unknown == ["[PERSON_9]"]`;
- for `existing_placeholders` files (supply-09, nda-03, dpa-04): the file's own `[PERSON 1]` left as written, and `[PERSON_9]` reported unknown.

It passes on all 28 Word files. No export, restore or masker module was touched, and there was nothing to report as BLOCKED.

Command: `uv run pytest tests/test_passmarks.py -q -m slow -s -k round_trip`, run on HEAD ec8ec1c. Output:
```
supply-01.docx: key 41, planned 61, restored 60 (1 changed), unknown ['[PERSON_9]']
supply-02.docx: key 44, planned 65, restored 64 (1 changed), unknown ['[PERSON_9]']
supply-03.docx: key 42, planned 62, restored 61 (1 changed), unknown ['[PERSON_9]']
supply-04.docx: key 39, planned 61, restored 60 (1 changed), unknown ['[PERSON_9]']
supply-05.docx: key 40, planned 61, restored 60 (1 changed), unknown ['[PERSON_9]']
supply-06.docx: key 39, planned 64, restored 63 (1 changed), unknown ['[PERSON_9]']
supply-07.docx: key 43, planned 66, restored 65 (1 changed), unknown ['[PERSON_9]']
supply-07-annex.docx: key 17, planned 25, restored 24 (1 changed), unknown ['[PERSON_9]']
supply-08.docx: key 43, planned 64, restored 63 (1 changed), unknown ['[PERSON_9]']
supply-09.docx: key 41, planned 62, restored 60 (0 changed), unknown ['[PERSON 1]', '[PERSON_9]']
supply-10.docx: key 43, planned 64, restored 63 (1 changed), unknown ['[PERSON_9]']
services-01.docx: key 47, planned 66, restored 65 (1 changed), unknown ['[PERSON_9]']
services-02.docx: key 46, planned 66, restored 65 (1 changed), unknown ['[PERSON_9]']
services-03.docx: key 47, planned 68, restored 67 (1 changed), unknown ['[PERSON_9]']
services-04.docx: key 47, planned 67, restored 66 (1 changed), unknown ['[PERSON_9]']
services-05.docx: key 48, planned 70, restored 69 (1 changed), unknown ['[PERSON_9]']
services-05-annex.docx: key 14, planned 22, restored 21 (1 changed), unknown ['[PERSON_9]']
nda-01.docx: key 28, planned 51, restored 50 (1 changed), unknown ['[PERSON_9]']
nda-02.docx: key 28, planned 49, restored 48 (1 changed), unknown ['[PERSON_9]']
nda-03.docx: key 27, planned 50, restored 48 (0 changed), unknown ['[PERSON 1]', '[PERSON_9]']
nda-04.docx: key 26, planned 49, restored 48 (1 changed), unknown ['[PERSON_9]']
nda-05.docx: key 27, planned 48, restored 47 (1 changed), unknown ['[PERSON_9]']
dpa-01.docx: key 30, planned 53, restored 52 (1 changed), unknown ['[PERSON_9]']
dpa-02.docx: key 30, planned 55, restored 54 (1 changed), unknown ['[PERSON_9]']
dpa-02-annex.docx: key 11, planned 19, restored 18 (0 changed), unknown ['[PERSON_9]']
dpa-03.docx: key 31, planned 55, restored 54 (1 changed), unknown ['[PERSON_9]']
dpa-04.docx: key 31, planned 55, restored 53 (0 changed), unknown ['[PERSON 1]', '[PERSON_9]']
dpa-05.docx: key 31, planned 58, restored 57 (1 changed), unknown ['[PERSON_9]']
.
1 passed, 13 deselected in 77.74s (0:01:17)
```
Reading the lines:
- "planned" = "restored" + the unknown placeholders. "1 changed" is the AI's `[PERSON 1]`, caught and restored once confirmed.
- "0 changed" has two causes. In the three `existing_placeholders` files (supply-09, nda-03, dpa-04), the first `[PERSON_1]` is the file's own, so it stays as written and is listed unknown. dpa-02-annex's key names no person.

### Evaluation re-run (pass marks)
Command: `uv run python -m tools.make_corpus <scratchpad>/r97/corpus` (the generator the tests' `corpus` fixture uses; 28 Word files with their truth and 8 PDFs), then `uv run python -m tools.evaluate <scratchpad>/r97/corpus`, which printed **PASS** and exited 0.

| Check (spec §9) | Word | PDF | All | Pass mark |
|---|---|---|---|---|
| Pattern-type items found before review | 100.0 % (719/719) | 100.0 % (194/194) | 100.0 % (913/913) | ≥ 99 % |
| Names, companies, addresses found before review | 100.0 % (255/255) | 100.0 % (65/65) | 100.0 % (320/320) | ≥ 95 % |
| Never-hide terms hidden by mistake | 0 | 0 | 0 | 0 |
| Thirty-page contract analysed (slowest) | 4.3 s | 7.8 s | 7.8 s | < 60 s |
| Found items hidden as their own type (info) | 99.9 % | 100.0 % | 99.9 % | – |

- 35 files analysed; `scanned-01.pdf` is not analysed. Misses 0. Never-hide terms hidden 0. Groups hiding no secret: 2 (supply-08's two, as before). Places hidden outside every secret: 0. Secrets under more than one placeholder: 6 (as before). Secrets not in the text: the same 7.
- Every detection figure equals round 1's. The corpus holds none of the shapes R97 touches. I counted them over every analysed text, printing counts only: no reference word, "Part" or "Art./Sec./Para." before a figure and unit, no year before "records", no spaced hyphen at all, and no spaced hyphen or en dash before a Dutch postcode. The only "N records" are counts ("up to N records"), which stay quantities.
- Times: this Linux container measured 4.3 s (Word) and 7.8 s (PDF), against the M3's 2.2 s and 3.4 s in the plan. The plan's table keeps the M3 figures; a dated bullet records this re-run (commit ec8ec1c).

### Full gate (from the worktree root, on the committed tree)
- `uv run pytest -q -m "slow or not slow"` on ec8ec1c: **3010 passed, 6 skipped in 348.21s (0:05:48)**. Output pristine: no warnings and no failures; the 6 skips are the macOS-only tests, as on mac-v1. An earlier run of the same tree with `-p no:cacheprovider` gave 3010 passed, 6 skipped in 325 s. No wall-clock test failed, so nothing was re-run alone.
- `uv run ruff check src tests tools`: All checks passed!
- `uv run ruff format --check src tests tools`: 129 files already formatted.
- `uv run mypy src`: Success: no issues found in 48 source files.
- Focused: `uv run pytest tests/detect -q` gave 1044 passed on the inherited state, before my additions. `uv run pytest tests/detect/test_patterns.py -q` gave 356 passed after them.

### Commits (on top of 9438038; nothing amended, squashed or rebased; not pushed)
- 993a12e fix: references, hyphenated headers, record counts and Dutch postcodes (R97)
- ec8ec1c docs: the round-trip pass mark and the R97 re-run under Results

### Files changed this round
- `src/themask/detect/patterns.py`, `src/themask/detect/engine.py`, `src/themask/detect/contract_rules.py`
- `tests/detect/test_patterns.py`, `tests/detect/test_contract_rules.py`, `tests/detect/test_pipeline.py`
- `docs/superpowers/plans/2026-10-17-the-mask-mac-v1.md` (Results: the round-trip bullet, and the dated re-run bullet)
- `tests/test_passmarks.py`: unchanged since the WIP commit.

### Self-review findings (fixed before the commit)
- Two regressions of the inherited (a) against HEAD, found by probing HEAD and the inherited state side by side: "the Art. 30 records" hidden, and "Schedule 3 500 pallets" left visible. Both are fixed, each with RED tests.
- Formatting: `ruff format --check` failed on two inherited files. Fixed.
- Readability: the inherited guard was inlined in `score_match`, with regexes that `ruff format` spread over ten lines. It is now two named helpers and compact regex building; `_AND` was renamed `_BETWEEN_YEARS`, with a comment. One docstring line was over 100 characters and is wrapped.
- Checked that nothing still uses the removed names (`_RECORDS`, `_PLAIN_YEAR`, `_are_records_named`). The bare-number guard keeps its own `_REFERENCE_BEFORE`.
- Checked that no assertion was weakened: the WIP commit and the inherited diff only add test cases. The one changed line is the comment above `test_a_quantity_after_a_word_like_parts_is_still_found`, whose R95 wording ("only records after a reference word is a reference") R97 replaces.

### Concerns
1. **Conservative reading of R97 (a), "drops art/para/sec".** I dropped the words, but kept "Art.", "Sec." and "Para." as references when they are written with their full stop. Abbreviated like that they are unambiguous, and the ruling's own counter-example has none ("the art 12 pieces"). HEAD kept "the Art. 30 records of processing activities" visible, a phrase a DPA uses, and the literal reading would have hidden "30 records". UK-style abbreviations without a full stop ("Art 30 records", "para 2 units") now count, as the ruling drops those words. If the controller wants the literal reading, the change is to delete `|(?:art|sec|para)\.` and its four test cases.
2. **All-caps "PART".** "PART" in capitals is read as the heading reference ("PART 2 UNITS OF MEASURE", an inherited test), so the unlikely all-caps "SPARE PART 5 UNITS" leaves "5 UNITS" visible. HEAD hid it.
3. **Side effects of (b), accepted by the ruling's "either side".**
   - A double name with a contract word or never-hide term next to its hyphen is now cut. "Mary Price - Jones" gives PERSON "Mary Price" and a flagged PERSON "Jones": both hidden, but under two placeholders (HEAD gave one).
   - In "Draft - Acme Supplies Ltd - Version 2", "Version 2" stays as the model's own COMPANY guess, flagged to check. At HEAD it was inside the one whole-header company.
4. **Reading of (c).** Taken literally ("a year only after the/a possessive"): any other word before a year-range figure makes it a count, so "In 2025 records were lost" hides "2025 records". "these 2025 records" is a count too. Year ranges ("the 2024-2025 records") stay parked.
5. **Pre-existing, the same at HEAD (not touched).**
   - The model's flagged COMPANY guess on a title-case heading hides "Annex 2 Units of Measure" whole, alone or in a sentence.
   - "Page 2 - 1500 KG Steel" gives QUANTITY "2 - 1500 KG" (a range reading).
   - In "Greystone - Brinkhof - Agreement", "Brinkhof" stays visible when nothing else names it.
   - "The Goods under Clause 4 cartons…" gives a model guess "Goods under".
6. **Edges of (d).** A weight with a capitalised word after a street and a spaced hyphen has the shape of a Dutch postcode and town, so "Keizersgracht 123 - 1500 KG Steel per month" gives the address "Keizersgracht 123 - 1500 KG Steel". It is hidden either way, and is contrived. On the other side, "Address: Northwind Trading B.V. - 1015 CJ Amsterdam" now hides "1015 CJ Amsterdam" (HEAD hid nothing), and "12 High Street - 1015 CJ Amsterdam" is one address.
7. **Timing in the plan.** The Results table's times are the Apple M3's (Word 2.2 s, PDF 3.4 s). This container measured 4.3 s (Word) and 7.8 s (PDF). I did not overwrite the M3 figures. I added a dated bullet with the container's figures, and replaced the bullet that said the round trip was still to come.
8. **Environment.** In this container `uv` prints a deprecation warning for `UV_NATIVE_TLS` before every command. It comes from the environment, not from the tests.
