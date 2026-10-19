# Task 4 report: made-up contract corpus (Word) with ground truth

**Status:** DONE_WITH_CONCERNS. The code is done and every check passes. The concerns are places
where the brief contradicts itself and I had to choose (see "Decisions to confirm"), plus the
manual Word check, which I could not do myself.

**Commit:** `14896f0 test: deterministic made-up contract corpus with ground truth` on `task-4`.

## What I built

- `tools/make_corpus.py` is the public API the brief asks for: `TruthItem`, `ContractSpec`,
  `build_spec(seed, kind, features, *, parties=None, project=None, bare_amount=False)`,
  `write_docx`, `write_truth`, `generate(out_dir) -> list[dict]` and
  `main` / `python -m tools.make_corpus [out_dir]`. The default folder is
  `tests/corpus/generated/`, which git already ignores. The file also holds `CATALOGUE`, which
  lists the documents with their seeds, parties and features.
- `tools/corpus/` holds the parts behind it. I split them into a package, as the dispatch allowed:
  - `model`: the contract as plain data, independent of file format.
  - `pools`: made-up companies, places, banks, the checked VAT numbers and the goods.
  - `parties`: people, addresses, phone numbers, registration numbers and IBAN/BIC.
  - `truth`: the registry of secrets, and how a truth file is read back from a finished document.
  - `compose`: the context, clause numbering and number formats.
  - `clauses`: wording shared by all four kinds.
  - `agreements`: supply, logistics services, NDA and DPA.
  - `annexes`: the annex documents.
  - `long`: the long schedules of the 30-page documents.
  - `build`: puts one contract and its annex together.
  - `docx_writer`: the Word writer.
- `tests/fixtures/corpus.py` holds the session fixture `corpus(tmp_path_factory) -> Path`.
- `tests/test_corpus.py` holds 26 tests: the brief's five plus checks on what later tasks rely on.
- `tests/corpus/README.md` (one page) and `tests/corpus/__init__.py`.
- `.gitignore` and `pyproject.toml` are unchanged. `.gitignore` already listed
  `tests/corpus/generated/`, and ruff runs with explicit paths.

### How it works

- **Contract as data, then a writer.** Each contract is built once as format-neutral data
  (`ContractSpec`): paragraphs of spans, tables, images, a text box, footnotes, comments and
  properties. Then it is written out. A tracked deletion is a span with `revision="del"`. A party
  name split the way Word saves it is three bold spans. Task 5 can add a PDF writer over the same
  data.
- **The truth is read back from the finished document, never written by hand.** The builder
  registers every secret together with the other ways it might be written. `truth_of` then reads
  the document's own text in three views: everything accepted, everything rejected, and hidden
  text.
  - It keeps a secret only if the text contains it.
  - It lists only the other forms that really appear on their own.
  - It sets `only_in_deletion` and `hidden` from those three views.
  - It raises an error if a value appears only in a shortened form, or if two secrets of the same
    type share a form.
  - So values and variants are always spelled exactly as in the document.
- **Deterministic.** Each document uses `random.Random(seed)` and a Faker (`en_GB`) seeded with
  `fake.seed_instance(seed)`. All dates are derived from the seed (`dcterms:created`/`modified`,
  revision and comment dates), and the zip entries carry Word's fixed 1980 date. The result is
  byte-identical files, not just identical truth and manifest. The test compares every file, and I
  also checked across separate processes with different `PYTHONHASHSEED` values.
- **Word realism.** python-docx builds the package. The rest is written as raw XML with lxml, the
  way Word writes it:
  - tracked changes: `w:ins`/`w:del` with author and date, `w:delText`, and `w:trackRevisions` in
    the settings;
  - a footnotes part with its separators and `w:footnotePr`;
  - the text box as `mc:AlternateContent`: DrawingML `wps:txbx` plus the VML `v:textbox` fallback;
  - `w:fldSimple w:instr="PAGE"`;
  - `w:hyperlink` with external `mailto:` and `https:` relationships;
  - lettered lists `(a)`, `(b)` that restart in each list;
  - `docProps/custom.xml`, and `app.xml` with `TitlesOfParts`, `HeadingPairs`, `Company` and
    `Manager`;
  - `w:attachedTemplate`, through an external relationship in `settings.xml.rels`, and `w:docVars`.

  I also dropped python-docx's thumbnail of a blank page, and gave the template's `w:zoom` its
  required `w:percent`.

## Brief and controller decisions: how each is met

| Item | How |
|---|---|
| Fixed assignments supply-01 to services-04 (decision 1) | `CATALOGUE`; `test_fixed_assignments` pins each file's exact feature set |
| Party names bold, split in three runs, every document (decision 2) | parties clause of all 28 files; `test_party_names_are_bold_and_split_across_three_runs`. Each name also appears unsplit at least once (notices, signatures, annex opening), because the brief's normalised-blob test needs a contiguous copy |
| R5 bare amounts (decision 3) | Table amounts always carry a currency. Exactly 3 bare amounts, all in "total price/fee of N per year" (services-05, nda-02, dpa-04), listed as AMOUNT; `test_amounts_without_a_currency_are_few_and_in_price_context` |
| No placeholder look-alikes (decision 4) | `find_placeholders` finds nothing in any file except `[PERSON_1]` in the `existing_placeholders` files; `test_no_placeholder_lookalikes_except_where_meant` |
| Truth format and flags (decision 5) | As specified; flags appear only when true; ASCII JSON (`\u00a0` for no-break spaces), so any platform's default encoding reads it. Dates, durations, governing law, defined terms and currency codes are never truth (tested) |
| Determinism (decision 6) | Above; `test_deterministic` compares every file |
| Manifest (decision 7) | List of `{"file","format","features","truth"}`; annex entries add `"annex_of"` |
| Fixture and CLI (decision 8) | Yes. Generation of all 28 files takes **1.8 s** (2.5 s wall clock with interpreter start); the CLI test asserts under 30 s |
| 30 pages (decision 9) | Long schedules built from about 70 varied sentences dealt from a shuffled deck. supply-10 has 12,905 words, services-05 13,243, dpa-05 13,220 |
| PAGE field and headers (decision 10) | Header "Short A / Short B — Title"; footer "Confidential · Short A / Short B · Page {PAGE}" |
| Comments name a truth person (decision 11) | `document.add_comment`; each comment's text names a person from the document, and its author is a different person |
| supply-01 "Northwind Trading B.V." over 3 runs, at least 3 occurrences, first one bold | Yes (5 occurrences). Its IBAN is NL91 ABNA 0417 1643 00, the one Task 14's fixture uses |
| supply-06 "Acme" in header, footer and footnotes; supply-08 "Project Falcon" exactly twice; services-03 "Text box note"; services-01 first EMAIL is a `mailto:` link | Each has its own test |

## Feature-to-file table

| Feature | Files (the first one is the fixed assignment) |
|---|---|
| `header_footer`, `table` | all 25 contracts (and the 3 annexes) |
| `comments` | supply-02, services-05, nda-05 |
| `tracked_changes` | supply-03, nda-05, dpa-03, dpa-05 |
| `secret_only_in_deletion` | supply-03 (AMOUNT), nda-05 (PERSON), dpa-03 (EMAIL) |
| `image` (logo and signature, alt text naming them) | supply-05, nda-03, dpa-01 |
| `footnotes` | supply-06, nda-01, dpa-02, dpa-05 |
| `hidden_text` | services-02 (AMOUNT), nda-02 (PERSON), dpa-03 (PHONE) |
| `textbox` | services-03, nda-04, dpa-03 |
| `properties` (core, app, custom.xml) | supply-04, nda-04, dpa-01 |
| `hyperlinks` | services-01, nda-01, dpa-01 |
| `shared_surname` | supply-08, nda-02, dpa-04 |
| `existing_placeholders` | supply-09, nda-03, dpa-04 |
| `nbsp_numbers` (NBSP and narrow NBSP groups) | services-04, nda-04, dpa-02 |
| `annex` (+ `<name>-annex.docx`) | supply-07, services-05, dpa-02 |
| `thirty_pages` | supply-10, services-05, dpa-05 |

| File | Features | Truth items | Words |
|---|---|---|---|
| supply-01 | (baseline) | 41 | 1,816 |
| supply-02 | comments | 44 | 1,812 |
| supply-03 | tracked_changes, secret_only_in_deletion | 43 | 1,813 |
| supply-04 | properties | 39 | 1,808 |
| supply-05 | image | 40 | 1,790 |
| supply-06 | footnotes | 39 | 1,807 |
| supply-07 / -annex | annex | 43 / 17 | 1,816 / 207 |
| supply-08 | shared_surname (+ Project Falcon) | 40 | 1,869 |
| supply-09 | existing_placeholders | 41 | 1,824 |
| supply-10 | thirty_pages | 43 | 12,905 |
| services-01 | hyperlinks | 47 | 1,712 |
| services-02 | hidden_text | 47 | 1,723 |
| services-03 | textbox | 47 | 1,772 |
| services-04 | nbsp_numbers | 47 | 1,730 |
| services-05 / -annex | thirty_pages, annex, comments, bare amount | 48 / 14 | 13,243 / 193 |
| nda-01 | hyperlinks, footnotes | 28 | 1,359 |
| nda-02 | shared_surname, hidden_text, bare amount | 28 | 1,380 |
| nda-03 | existing_placeholders, image | 27 | 1,358 |
| nda-04 | properties, textbox, nbsp_numbers | 26 | 1,332 |
| nda-05 | tracked_changes, secret_only_in_deletion, comments | 28 | 1,359 |
| dpa-01 | hyperlinks, image, properties | 30 | 1,618 |
| dpa-02 / -annex | annex, footnotes, nbsp_numbers | 30 / 11 | 1,638 / 160 |
| dpa-03 | tracked_changes, secret_only_in_deletion, hidden_text, textbox | 32 | 1,666 |
| dpa-04 | shared_surname, existing_placeholders, bare amount | 29 | 1,656 |
| dpa-05 | thirty_pages, footnotes, tracked_changes | 31 | 13,220 |

There are 980 truth items in all. By type: ADDRESS 75, AMOUNT 182, COMPANY 89, EMAIL 63, IBAN 25,
ID 107, PERCENT 133, PERSON 93, PHONE 53, QUANTITY 110, URL 50. There is no CUSTOM item.
*(Corrected in fix round 1: an earlier version of this report wrongly said "Project Falcon" was a
CUSTOM item.)*

## Tests and results

TDD evidence:

- **RED:** `uv run pytest tests/test_corpus.py -q` →
  `ImportError: Error importing plugin "tests.fixtures.corpus": No module named 'tools'`. This was
  expected: the tests and fixture were written before `tools/make_corpus.py` existed.
- **GREEN:** `uv run pytest tests/test_corpus.py -q` → `26 passed in 8.43s`.
- Full suite: `uv run pytest -q` → `855 passed in 8.93s`, with no warnings.
- `uv run ruff check src tests tools` → `All checks passed!`, and
  `uv run ruff format --check src tests tools` is clean.
- `uv run mypy src` → `Success: no issues found in 7 source files`.
- For my own check, `uv run mypy tools tests/fixtures/corpus.py tests/test_corpus.py`, strict →
  `Success: no issues found in 16 source files`.

The 26 tests are:

- the brief's five: counts, every type covered, features real, every truth value in the file,
  deterministic (strengthened to compare every file's bytes);
- fixed assignments;
- manifest entries;
- each feature in at least three documents;
- annexes belong to their contract and name both parties;
- each feature really present, all 16 checked;
- features not claimed are absent;
- truth items well formed;
- truth files are ASCII;
- values and variants written verbatim where the flags say;
- flagged items where later tasks look for them;
- dates, durations, jurisdictions and defined terms never in the truth;
- every number of four or more digits, amount, percentage, e-mail, URL, IBAN and BIC covered by
  the truth;
- R5 bare amounts;
- no placeholder look-alikes;
- party names bold in three runs;
- the supply-01 Northwind runs;
- supply-06 Acme;
- supply-08 Project Falcon;
- services-01 mailto;
- "supply-01 leaves nothing once its truth is masked": masking every value and variant in the text
  leaves no normalised truth value anywhere in the package. Tasks 15 and 19 rely on this;
- the CLI writes the same corpus, quickly.

Checks beyond the tests:

- **Schema validation:** all 28 files pass the ISO/IEC 29500 schemas, using the validator and XSDs
  that ship with the installed docx skill (`docx/scripts/office/validate.py`).
- **Visual check:** macOS Quick Look renders supply-01 and supply-05 (logo) as normal-looking
  contracts.
- **Microsoft Word:** I could not open a file in Word. The Word tool timed out twice on
  `open_document`. Word is running but does not answer AppleScript either, so it is probably
  showing a modal dialog, possibly a file-access prompt caused by my attempt. **The brief's step 4,
  "open supply-01.docx in Word by hand once", is still open for the owner**, who may also need to
  dismiss a Word dialog.

## Decisions to confirm (the brief contradicts itself)

1. **25 contracts, not 20.** The brief names supply-01 to 10, services-01 to 05, nda-01 to 05 and
   dpa-01 to 05, which is 25. Its own test asks for at least 20. With 3 annexes there are 28 Word
   files and 28 truth files. I kept every named file.
2. **"Each feature in ≥ 3 documents" against singular wording.** Decision 9 says "the thirty_pages
   document", and decision 4 mentions `[PERSON_1]` only in supply-09. I followed the ≥ 3 rule.
   - There are three 30-page documents (supply-10, services-05, dpa-05), which will lengthen Task
     24's slow tests.
   - `[PERSON_1]` and `[Name]` appear in supply-09, nda-03 and dpa-04. All three are tagged
     `existing_placeholders`, so the Task 24 round-trip exemption covers them. No other file has
     any placeholder-like token.
3. **Annex manifest entries** have their own truth file and an extra `"annex_of"` key. The main
   contract's entry has `annex` in its features.
4. **"Project Falcon"** in supply-08 is plain text, written exactly twice. It is **not** a truth
   item: it is the term Tasks 9, 21 and 23 add by hand as a user-added term. *(Corrected in fix
   round 1: this item first said, wrongly, that it was a CUSTOM truth item.)*
5. **Commit trailer.** I used `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, because
   that is the model that did the work and the trailer this session's harness requires. The plan
   says "the attribution trailer this session requires". The boilerplate's literal text names
   Fable 5.1. If you want it changed, it is a one-line `--amend`.
6. **Faker seeding.** I seed Faker per instance (`fake.seed_instance(seed)`) rather than with the
   class-level `Faker.seed(seed)`. Determinism per document is the same, without touching global
   state.
7. **UK companies show no VAT number.** `stdnum.eu.vat` has rejected GB numbers since Brexit. Every
   contract has at least one EU party with a valid VAT number.

## Notes for later tasks (found while building)

- **Task 10, Task 13 (text box):** the text box is written as Word writes it, so its text is in
  `document.xml` twice: in the DrawingML part and in the VML fallback. The reader and masker must
  cover both, or the leak check will (rightly) block the export.
- **Task 14 (short values):** values such as "5%" normalise to "5", and "€ 48,000" to "48000". A
  normalised search across the whole package will find those digits in XML attributes. supply-01
  deliberately avoids such short forms, because Tasks 15 and 19 search it that way (tested). The
  other files have them, as real contracts do. The leak check needs a rule for short values.
- **Task 12 (settings):** every file has `w:attachedTemplate`, with its external relationship in
  `word/_rels/settings.xml.rels`, and `w:docVars`. That makes `test_settings_scrubbed` meaningful.
  The cleaner should drop the relationship as well.
- **Task 12 (thumbnails):** real Word files can carry `docProps/thumbnail.jpeg`, a picture of page
  1. The cleaner spec does not mention it. The corpus does not include one.
- **Task 13 (revision authors and alt text):** revision authors, comment authors, image alt text
  and property values are all people or companies from the document's text, so the leak check has
  real values to catch there.
- **Truth values never contain characters XML escapes** (`&`, `<`). The brief's raw-XML blob test
  cannot see through `&amp;`, so I renamed one company to "Marlowe Print and Packaging Ltd".

## Self-review: problems found and fixed

- A comment's text named its own author. Comments are now written by the other party's contact.
- Footnotes had a separate one-space run. Each footnote is now a single run.
- DPA sub-processors had random roles ("Cobalt Mail Services Ltd for hosting"). Each now has a
  fixed role, shared by the contract and its annex.
- The supply annex gave fasteners a "shelf life". It is now "Lead time".
- The long schedules repeated a sentence in neighbouring paragraphs. Sentences are now dealt from a
  shuffled deck.
- An LLP was called "a company". It is now "a limited liability partnership ... under number
  OC…".
- The annex named the parties only in their split form, which failed the brief's blob test. The
  annex's opening sentence now names both in full.
- A company name contained "&". Renamed, as above.
- The template's `w:zoom` broke schema validation. Fixed by adding `w:percent`.
- I left national phone formats registered but unused. My truth guard caught my first attempt to
  write one without its international form. They now sit beside the international form, so 13
  PHONE items carry a national variant such as "030 360 7352".
- Strict-mypy and ruff nits fixed. `agreements.py` reached 923 lines, so the annex writers moved to
  `annexes.py`.

## Files

- New:
  - `tools/__init__.py`
  - `tools/make_corpus.py`
  - `tools/corpus/{__init__,model,pools,parties,truth,compose,clauses,agreements,annexes,long,build,docx_writer}.py`
  - `tests/fixtures/corpus.py`
  - `tests/test_corpus.py`
  - `tests/corpus/__init__.py`
  - `tests/corpus/README.md`
- 18 files, 5,048 lines. Most of the bulk is contract wording and made-up data.

---

# Fix round 1 (review findings, ruling R15)

**Commit:** `239bb97 test: corpus review fixes: validity test, no CUSTOM claim, lazy fixture import`

## What changed

1. **False "Project Falcon" claim (Important).** The reviewer was right: the generator never lists
   "Project Falcon". It is plain text in supply-08, written exactly twice, and later tasks add it
   by hand as a user-added term.
   - `tests/corpus/README.md` now says it is not a truth item.
   - This report is corrected in place, in the type counts and in "Decisions to confirm" item 4,
     with notes marking the corrections.
   - `test_supply_08_project_falcon_twice` now also asserts that no truth value or variant of
     supply-08 contains "Falcon".
   - `test_truth_items_are_well_formed` no longer tolerates a `CUSTOM` type.
2. **Validity test (Minor, raised).** The new `test_numbers_pass_their_own_checks` checks every
   truth file:
   - each IBAN with `schwifty.IBAN`, and its other spelling must be the same IBAN;
   - each BIC-shaped ID with `schwifty.BIC`, and it must be the bank schwifty derives from that
     document's own IBAN. `BIC()` on its own accepts a made-up "ABNANL2X", so this extra
     comparison is what makes the check real;
   - each VAT-shaped ID with `stdnum.eu.vat.is_valid`;
   - each PHONE with `phonenumbers.parse` and `is_valid_number`, and its national variant must
     parse to the same number;
   - each of the four kinds must have been checked at least once.

   It covers 25 IBANs, 25 BICs, 32 VAT numbers and 53 telephone numbers. The `pools.py` docstring
   now names this test as what checks them.
3. **Fixture import (Minor, raised).** `tests/fixtures/corpus.py` now imports `tools.make_corpus`
   inside the fixture. Checked: importing the plugin no longer loads the generator
   (`'tools.make_corpus' in sys.modules` is False). The generator import, about 0.3 s, now happens
   only when a test uses `corpus`.
4. **Docstring.** `tools/make_corpus.py` now says "25 contracts and the annexes three of them come
   with (28 Word files)".
5. **Found while fixing.** The README, and this report's decision-5 row, showed a raw no-break space
   where the text means the escape `\u00a0`. The file-writing tool had decoded it, as the
   boilerplate warns. Both now show the six characters `\u00a0`. No code file was affected
   (checked: no raw NBSP, NNBSP or thin space in any `.py` file).

The generator's output is unchanged. I generated the corpus with commit `14896f0` before any edit,
generated it again after the fixes, and `diff -r` reported no difference across all 57 files (28
`.docx`, 28 `.truth.json` and `manifest.json`).

## Tests

- **The new test can fail:** I corrupted a copy of the baseline corpus one value at a time and ran
  the test on each copy. It caught all four:
  - IBAN `…1643 00`→`…1643 01` (`InvalidChecksumDigits`);
  - BIC `ABNANL2A`→`ABNANL2X` (AssertionError);
  - VAT `NL219411670B01`→`NL219511670B01` (AssertionError);
  - phone `+31 30 360 7352`→`+31 39 360 7352` (AssertionError).

  On the clean corpus it passes. The data was already valid, so this test was green the first time
  it ran; the corrupted copies stand in for a RED run.
- `uv run pytest tests/test_corpus.py -q` → `27 passed in 8.76s`.
- `uv run pytest -q` → `856 passed in 9.09s`, with no warnings.
- `uv run ruff check src tests tools` → `All checks passed!`, and
  `uv run ruff format --check src tests tools` → `33 files already formatted`.
- `uv run mypy src` → `Success: no issues found in 7 source files`.
- Extra check: strict mypy on `tools` and the corpus tests → `Success: no issues found in 16
  source files`.

## Files changed in this round

- `tests/corpus/README.md`
- `tests/fixtures/corpus.py`
- `tests/test_corpus.py`
- `tools/corpus/pools.py` (docstring only)
- `tools/make_corpus.py` (docstring only)
- This report.

The other review Minors are left as deferred.
