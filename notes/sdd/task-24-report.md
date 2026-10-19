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
