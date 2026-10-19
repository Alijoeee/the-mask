# Task 7 report: names, companies, addresses: model + contract rules

**Status:** DONE_WITH_CONCERNS (concerns at the end: file size, additions beyond the brief, two Task 6 tests adapted)
**Branch / worktree:** `task-7` in `/Users/alijoeee/Developer/the-mask-worktrees/task-7`, from mac-v1 at 33ca131
**Commit:** `8d4a246 feat: contract-aware rules for parties, signatures, addresses`
**Tests:** 1521 passed on task-7 (was 1219), 0 failed, no warnings; `ruff check src tests`, `ruff format --check src tests` and `mypy src` clean.
**Merge check (read-only):** `git merge-tree --write-tree mac-v1 task-7` merges cleanly. The full suite on that merged tree (exported to my scratchpad, no branch or worktree touched) gives 1561 passed, and ruff on `src tests tools` plus mypy are clean.

## What I implemented

### `src/themask/textnorm.py` (controller decisions 1 and 2)
- New public `has_legal_form(value) -> bool` and `strip_legal_form(value) -> str`. Both rest on one private helper (`_legal_form_words`), which `variants_of` now uses too, so there is only one implementation. Matching works as before: dots optional, case ignored for all-letter forms, `se/ab/co/as` only when capitalised, two-word forms tried first. `strip_legal_form` removes one trailing form plus whatever it leaves dangling (`,` `&` `and`). It keeps the name's own spelling and spacing (`"Northwind  Trading BV"` gives `"Northwind  Trading"`), returns `""` for a bare form and returns a value with no form unchanged.
- `LEGAL_FORMS` gains `"Ltd. Sti."` right after `"Ltd. Şti."`. `test_legal_forms_are_the_agreed_list` is updated to match. `variants_of` behaves as before; the only new result is that `"... Ltd. Sti."` values now get their stripped variant.
- `normalize` folds the dotless `ı` to `i` after casefold, so `normalize("GIDA") == normalize("Gıda") == "gida"`.
- `flexible_pattern` adds `(?![.,]\d)` when the value ends with a digit and `(?<!\d[.,])` when it starts with one (ruling R11). It no longer finds "EUR 5" in "EUR 5,000.00", "250" in "1,250", "5%" in "2,5%" or "250.000" in "1.250.000".

### `src/themask/detect/contract_rules.py` (new; decisions 3, 5, 6, 7)
Each public function builds a `_Document` (the text plus its word list) and runs private rules over it. All are pure functions of the text. Every finding has `source="rule"`.

- `find_parties(text)` reads the parties clause line by line. It starts at `BETWEEN`, `Between` at a line start, `between:`, `made/entered into/concluded/executed ... between`, or a `PARTIES` heading, which must start within the first 4,000 characters.
  - A party's name may start right after the keyword, after a marker (`(1)`, `(b)`, `1.`), or after a line ending in `and ; , :`. Parties joined by "and" are both read ("between Northwind Trading B.V. and Acme Supplies Ltd").
  - The clause ends at the line of the last party (ending in "."), at the first line after a party that names none, at a heading in capitals, or at BACKGROUND/WHEREAS/RECITALS and similar.
  - A party with a legal form is a COMPANY at 0.95; without one it is a COMPANY at 0.9. It is a PERSON instead when it has an honorific, or is followed by "of 12 …", "an individual", "residing", "born" or "a sole trader".
- `find_legal_form_companies(text)`: 1 to 6 capitalised words before a legal form, as COMPANY at 0.95.
  - Words joined by `&`, by particles (`van der`, `de`, …) or by an "and" with exactly one word after it ("Marlowe Print and Packaging Ltd", but not "Acme and Northwind Trading B.V.") belong to the name. So do compound forms ("Müller & Söhne GmbH & Co. KG"), "Acme, Inc." and "Smith & Co.".
  - The name stops at punctuation, a line break, small words and sentence adverbs ("Accordingly"), role and document words (Supplier, Schedule …) and months ("In March Acme Ltd").
  - A possessive "'s" is never part of the name. A full stop is kept for "B.V." and in mid-sentence ("Acme Ltd. shall"), and dropped at a sentence end ("We buy from Acme Ltd.").
- `find_signature_blocks(text)`: `Name:`, `Full/Print/Printed name:`, `By:`, `Signed by`, `Attention:`, `Attn:`/`Attn.`, `FAO:` and `For the attention of`, at a line start or after a tab ("Signed by" and "For the attention of" anywhere).
  - A name is a PERSON at 0.9, or a COMPANY at 0.95 when it has a legal form. Several names on one line are read ("Mr John Carter, Head of Sales" gives only Mr John Carter; "Mr X and Ms Y" gives both).
  - When the label's line is blank or holds only an underscore blank, the value comes from the next line, but only if that whole line is a name and not another label.
  - Job titles and departments are never names (`is_job_title`). `Title:` lines are never read.
- `find_addresses(text)` finds addresses from several kinds of anchor:
  - an `Address:`, `Registered office:`, `Postal/Delivery/… address:` or `Principal place of business:` label (0.9), skipping a company name that comes first;
  - "registered office (is) (situated) at", "principal place of business at", "head office" and the like (0.9);
  - streets with a house number (0.85): English (`10 Downing Street`, `12 St John's Road`, with a `Unit 5,` prefix), NL/DE (`Keizersgracht 123`, `Berliner Straße 12`; suffixes straat weg laan plein gracht kade dijk singel steeg markt straße strasse allee gasse platz damm ufer), and Turkish (`Büyükdere Caddesi No: 185`, `Gül Sok. No. 3`);
  - postcodes with their town (0.8): UK `SW1A 2AA`, NL `1015 CJ` + town, and five digits + town (DE/FR/TR). They pull in the street part before them when it has a number (`Weena 12, 3011 AB Rotterdam`, `12 rue de la Paix, 75002 Paris`).
  - From its anchor the span runs part by part (comma to comma) to the last postcode, town or country part, at most 8 parts and 30 words. It stops at `(` `;` " and " quotes, a tab, a line break, or a part that is not address-like ("VAT number …", "a company …"). Overlapping spans are merged and keep their highest score. A label or phrase address must contain a digit or no role word ("Address: the Supplier's registered office" is not one).
  - Jurisdictions ("the laws of the Netherlands", "the courts of Amsterdam", "England and Wales") produce nothing.
- `find_defined_terms(text) -> set[str]` takes terms from `(the "Supplier")`, `("Buyer")`, `(the “Supplier”)`, `(the ‘Supplier’)`, `(the 'Supplier')`, `(hereinafter (referred to as) the "X")`, `hereinafter "X"` and `(each a "Party" and together the "Parties")`, plus definitions clauses (`"Business Day" means …`, `1.1 “X” means …`). Leading "the" inside the quotes is dropped.
- `apply_rules(text) -> (findings, terms)`: all of the above, sorted by (start, end, type). Each span and type appears once, with its highest score.

### `src/themask/detect/engine.py` (decision 4)
`Engine.analyze` now does `rules, _ = apply_rules(text)` and returns `rules + _checked_by_rules(text, presidio_findings, rules)`, with the same `MIN_SCORE` filter and sort as before. `_checked_by_rules` is built from small helpers:
- `_lines_of` cuts a model finding at its line breaks. It keeps parts with at least 2 visible characters, minus headings and labels (`_is_heading_or_label`: a part followed by ":" such as "Attention", "Address" or "CUSTOMER:", or a part in capitals without a legal form that fills its line, such as "CUSTOMER"). The model really produces `"Northwind Trading B.V.\nCUSTOMER\n"`, `"Northwind Trading B.V.\nAttention"` and `"Legal Counsel\nAddress"`.
- A model finding on the same span as a rule finding is dropped (the rule's stays). Pattern findings are never dropped.
- `_is_job_title_name` drops a model PERSON or COMPANY that is a job title.
- `_at` keeps a model ADDRESS (LOCATION) only when it overlaps a rule address or lies within 2 characters of one.
- `_marked_if_unconfirmed` gives a model COMPANY with no legal form and no overlapping rule finding `min(score, 0.6)` (`UNCONFIRMED_COMPANY_SCORE`).

## Controller decisions: where each one is met
1. Public legal-form API used by `variants_of`, `contract_rules` and `engine`; `Ltd. Sti.` added → `textnorm.has_legal_form/strip_legal_form`. Tests: `test_has_legal_form`, `test_strip_legal_form*` and `test_legal_form_helpers_agree_with_the_company_variants` (all 28 forms × with/without dots × capitals).
2. R11 guards and the dotless-ı fold. Tests: `test_flexible_pattern_number_is_not_found_inside_a_longer_number`, `..._is_found_next_to_punctuation` and `test_normalize_folds_turkish_dotless_i`.
3. The brief's six functions, `source="rule"`, 0.95 for legal-form companies. The brief gives no other scores, so I chose 0.9 for names and labelled addresses, 0.85 for streets and 0.8 for postcode-only addresses (all above Task 8's 0.7 check line).
4. Engine merge, LOCATION gate (≤ 2 characters), COMPANY cap, newline split (≥ 2 visible characters), rule beats model on the same span. Tests: the `test_engine_*` and `test_model_*` tests in `tests/detect/test_contract_rules.py`.
5. Title lines never findings; job titles never PERSON (rules and engine). Tests: `test_signature_block`, `test_signature_lines_without_a_name_find_nothing`, `test_title_lines_and_job_titles_are_never_findings` and `test_job_titles`.
6. Address span and stops; postcodes UK/NL/DE/FR/TR; the listed street words and more. Tests: `test_addresses` (17 cases), `test_address_lines_each_give_an_address`, `test_address_scores`, `test_an_address_has_at_most_eight_parts` and `test_no_address` (21 negatives).
7. Negatives (jurisdictions, job titles, defined terms, months, "Schedule 3", headings in capitals) → `test_never_findings_from_the_rules` (10 texts), plus the negatives under each rule.
8. `analyze` built from small helpers. Measured on a 12,060-word text (75,375 characters, the brief's clauses repeated): **whole engine 3.45–3.55 s**, of which the Task 6 Presidio/spaCy analysis is about 3.4 s, the rules 0.07 s and the merge 0.01 s (Apple silicon, 3 runs). `test_rules_are_quick_on_a_long_contract` guards the rules on about 12,000 words (< 1 s). `test_rules_are_quick_on_texts_made_to_be_slow` guards 5 adversarial inputs (< 2 s; they now take ≤ 0.41 s).

## Testing and evidence

### TDD evidence
- **RED 1 (textnorm):** `uv run pytest tests/test_textnorm.py -q` gave `ImportError: cannot import name 'has_legal_form' from 'themask.textnorm'`, as expected since the API did not exist. Probing the old code showed the behaviour the new tests forbid: `EUR 5` found in `EUR 5,000.00` (True), `250` in `1,250` (True), `5%` in `2,5%` (True), `normalize("GIDA")="gida"` vs `normalize("Gıda")="gıda"`, and `variants_of("Marmara Tekstil Ltd. Sti.")={'Marmara', 'Marmara Tekstil Ltd. Sti.'}`.
  **GREEN 1:** the same command gave `514 passed`; full suite `1306 passed`.
- **RED 2 (rules and engine):** `uv run pytest tests/detect -q` gave `ModuleNotFoundError: No module named 'themask.detect.contract_rules'`. `uv run pytest tests/detect/test_patterns.py -q` gave `FAILED test_sources … - rule + model` (1 failed, 256 passed), since the rule source did not exist yet. With `contract_rules.py` written but the engine unchanged, 4 engine tests failed (`test_a_rule_finding_beats_the_model_on_the_same_span`, `test_model_places_are_kept_only_at_an_address`, `test_model_company_without_a_legal_form_is_marked_for_checking`, `test_model_findings_never_cross_a_line`; 187 passed).
  **GREEN 2:** after the engine change, `uv run pytest tests/detect -q` gave `450 passed`; full suite `1499 passed`.
- **RED 3 (from the corpus check below):** new tests for the parties clause ending with its last party and for names after an honorific gave 7 failed, 198 passed. Expected: the parties region ran on into "1. PRODUCTS", and the honorific rule did not exist. **GREEN:** 205 passed.
- **RED 4 (self-review):** `test_parties_clause_ends_with_the_first_line_that_names_no_party` failed with `Extra items in the left set: 'Words'`. **GREEN:** 206 passed.
- **RED 5 (self-review, robustness):** `test_no_address[Address:\nName: John Carter]` failed with `text='Name'`; `test_no_address[Registered office:\nTelephone: …]` failed with `text='Telephone'`; `test_an_address_has_at_most_eight_parts` failed. `'12 High Street, London SW1A 2AA, ' * 3000` took **147.5 s**. **GREEN:** 215 rules tests pass, and the worst adversarial case takes 0.29–0.41 s.
- **Final:** `uv run pytest tests/detect/test_contract_rules.py tests/test_textnorm.py tests/detect/test_patterns.py -q` gives `986 passed`; `uv run pytest -q` gives `1521 passed`; ruff, format and mypy are clean.

### Corpus check (scratch only)
I exported the merged Task 4 generator (commit 239bb97) read-only into my scratchpad, built the 28 .docx files and their truth, extracted text roughly with python-docx (body, tables, headers and footers), ran `Engine.analyze`, and checked whether each truth occurrence was covered by a finding.

| type | occurrences | covered now | Task 6 analyzer alone |
|---|---|---|---|
| ADDRESS | 127 | **99.2 %** (126 rule spans exactly equal to the truth value) | 0.0 % (model spans only cover pieces) |
| PERSON | 271 | **99.6 %** | 79.7 % |
| COMPANY | 528 | **87.5 %** | 81.8 % |

- The remaining COMPANY misses are short names in headers and footers ("Confidential · Northwind / Thamesgate") and possessives ("Kronberg's account manager"). These are first-word variants that Task 8's sweep covers.
- The one ADDRESS miss comes from my rough extractor gluing a duplicated text box ("…Germany.Text box note").
- **Zero false positives from the rules** after the fixes. Before them, six headings in capitals came from the parties region ("PRODUCTS", "SCOPE", "KEY PERSONNEL", …), which led to RED 3.
- The defined terms found cover **862 of 1,335** model false-positive occurrences (Buyer, Customer, Service Provider, Discloser, Personal Data, the Effective Date, Confidential Information, …). Task 8's never-hide step can drop those, which is why I kept the `"X" means` form.

## Files changed
- `src/themask/textnorm.py` (modified)
- `src/themask/detect/contract_rules.py` (new, 1,243 lines)
- `src/themask/detect/engine.py` (modified)
- `tests/test_textnorm.py` (new tests; agreed `LEGAL_FORMS` list updated)
- `tests/detect/test_contract_rules.py` (new, 215 tests including the brief's six verbatim; the `PARTIES` string is checked identical to the brief's)
- `tests/detect/test_patterns.py` (two Task 6 assertions adapted, see concerns)

## Self-review findings (all fixed before the commit)
- The parties region ran past the parties into numbered headings, and read the first word of a prose line as a party ("Words"). The clause is now read line by line with explicit start and end rules (RED 3 and 4).
- "Address:" alone on its line took the next line's label as the address ("Name", "Telephone"). A label line is never a value now (RED 5).
- Address building was quadratic on long comma-joined lines (147 s). It is now bounded to 8 parts and 30 words, the backward walk is bounded, `_is_an_address` uses bisect, and `_legal_form_length` is memoised per document.
- The short-name check recomputed every name's forms for every term (O(terms × names)). It now uses an index (`_ShortNames`) with exact-form and first-word dicts, and bisects for initials.
- The same-span rule also dropped pattern findings. It now drops only model findings, as decision 4 says.
- `_is_heading_or_label` sliced the whole rest of the text for each piece; it now looks at the rest of the line only.
- `ruff format` turned the word lists into one word per line (the file was 1,600+ lines). They now go through a `_vocabulary("""…""")` helper.

## Concerns and judgement calls for the controller
1. **File size.** `contract_rules.py` is 1,243 lines: four rule families plus about 200 lines of vocabulary and regexes. It stays within the plan's intent (parties, legal forms, signature blocks, Attention/Address lines, registered-office phrases, defined terms), but if you want it smaller, the natural split is a package (`names`, `addresses`, `terms`). I have not split it.
2. **Additions beyond the brief** (each small and tested; veto any):
   - **Names after an honorific** ("Mr Bennett", "Mr Dean Andrews", "Mevr. van der Berg", "MR JOHN SMITH") as PERSON at 0.9, inside `apply_rules`. There is no new public function. On the corpus it lifts PERSON coverage from 91.1 % to 99.6 %, because the model misses these. An honorific in capitals needs a name in capitals ("MS Teams" stays visible), and job titles stay out ("Mr Chairman").
   - **`"X" means` definitions** in `find_defined_terms`, beyond the listed bracket and hereinafter forms.
   - **A party's short name is never a defined term.** For `Acme Supplies Ltd ("Acme")`, `(hereinafter "Northwind")` and `Kestrel Analytics Limited ("KAL")` (initials count only straight after the name), the term is left out of `terms` and found as a COMPANY (or PERSON) at the quoted span. Otherwise Task 8's never-hide step would keep "Acme" visible everywhere, which would be a leak.
   - **`is_job_title(text)`**: one extra public helper in `contract_rules`, which the engine needs for decision 5.
   - **A running-text policy on top of `has_legal_form`** (`_written_as_a_legal_form`). The spelling still comes only from textnorm; the policy covers case in running text:
     - lower-case forms count only for "plc" ("500 kg", "a limited company" and "the Company incorporated" are no companies);
     - `SE/AB/AS/Co` without dot or slash need capitals, and never count after a name in capitals ("THE GOODS AS DESCRIBED");
     - "LIMITED" between capitals is a word ("PRODUCT LIMITED WARRANTY").
     So `has_legal_form("Acme ltd")` is True, but the rule does not find "Acme ltd" in prose; the model still can (that is how `test_model_companies_keep_their_score` now works). I do not see this as a second implementation, but I am flagging it.
   - The heading/label filter on split model pieces (needed to keep `test_headings_after_a_bic_are_never_findings` green, because the model swallows "CUSTOMER"), a `PARTIES` heading as a clause keyword, street words beyond the list (kade dijk singel steeg markt allee gasse damm ufer Bulvarı/Blv./Cd./Sk.), next-line values for labels in table cells, and a `Unit 5,` prefix.
3. **Two Task 6 tests adapted to decision 4** (`tests/detect/test_patterns.py`):
   - `test_sources` now allows the "rule" source and checks that "Northwind Trading B.V." comes from the rule.
   - `test_model_companies_keep_their_score` used "Baltic Fasteners GmbH", which the rule now owns (0.95, "rule"). It now uses "Baltic Fasteners gmbh", which the rule leaves alone, to keep its intent (Presidio does not lower a company's score). The brief's own `test_legal_form_company_in_prose` keeps the GmbH sentence.
4. **For Task 8:** `Engine.analyze` discards the `terms` from `apply_rules`. The pipeline should call `find_defined_terms(text)` (or `apply_rules`) for `CaseLists.defined_terms`. Model noise the never-hide lists need to cover:
   - defined terms and role words as COMPANY/PERSON, 862 occurrences equal to a document's own defined term;
   - labels "VAT" (47×) and "IBAN" (25×) as COMPANY, capped at 0.6;
   - institutions ("the European Central Bank", "the Bank of England", "the European Commission");
   - "Wales" as COMPANY (1×).
   Company short names in headers and footers depend on the sweep.
5. **For Task 24 tuning:**
   - Initials-and-surname mentions typed COMPANY by the model ("L. Davies"; covered, wrong type), and "Kronberg" typed PERSON.
   - "of" is not a name connector, so the rule gives "Ireland plc" for "Bank of Ireland plc". The model usually finds the longer span, which wins Task 8's longest-span resolution.
   - Multi-line addresses are found line by line. A country line on its own stays visible.
   - Irish Eircodes count only through a street anchor.
   - Dutch postcodes whose letters include F, I, O, Q, U or Y are not postcode anchors (this is what keeps "2026 EU Member States" visible).
   - The word lists (function words, roles, job titles) are English and hard-coded.
6. **Commit trailer.** I used `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, the session's attribution for the model that wrote the commit, as accepted for Tasks 4 and 6. The boilerplate names Fable 5.1. Amend if you want the other.

---

# Fix round 1 (review round 1 + ruling R21)

**Status:** DONE — commit `efc7fe0 fix: keep signatories in capitals, read parties only where they are named` on `task-7` (on top of `8d4a246`).
**Tests:** `uv run pytest tests/detect -q` → 506 passed; `uv run pytest -q` → 1555 passed (was 1521); `uv run ruff check src tests`, `ruff format --check`, `uv run mypy src` clean. On the merged tree (`git merge-tree --write-tree mac-v1 task-7`, mac-v1 at c7a4bfa incl. Task 10, exported to scratch): 1678 passed, `ruff check src tests tools` and mypy clean.

## What changed, per finding

**Critical 1: capitalised signatory names leaked** (`engine.py` `_lines_of` / new `_names_nobody`)
- A split piece is now dropped only when it names nobody: `is_contract_wording(piece)` (new public helper in `contract_rules`: every word is a role, heading or label word, such as SUPPLIER, CUSTOMER, TERMINATION, Attention, IBAN), `is_job_title(piece)`, or `is_job_title(the piece's whole line)`. The last case catches "Managing" from the model's `"JANE SMITH\nManaging"` on the line "Managing Director", which `is_job_title("Managing")` alone would not.
- The old "capitals that fill the line" rule and the "followed by a colon" rule are gone. Label pieces are caught by the vocabulary instead ("Attention", "Address", "Telephone:", "IBAN"; I added `iban bic swift vat` to the label words).
- Tests: `test_a_name_in_capitals_on_a_line_of_its_own_stays_found` (the reviewer's 5 layouts, verbatim apart from a prefix for the witness case) and `test_a_part_of_a_job_title_is_no_name`. `test_model_findings_never_cross_a_line` and `test_headings_after_a_bic_are_never_findings` still pass.

**Important 1: `find_parties` hid weekdays, months, jurisdictions, currencies and terms**
- A line of the parties clause is read only when it shows it names a party (`_names_a_party`):
  - `_PARTY_CONTEXT`: "a/an (limited) company / corporation / partnership / individual / sole trader", "incorporated/registered/established in/under/at/with/and", "company number", "registered office/number/address", "principal place of business", "residing at", "of <digit>", "hereinafter", a defining bracket `(the "X")`/`("X")`/`(each a "X")`, or a bracketed party number `(1)`;
  - a legal-form company on the line;
  - "This/The Agreement/Contract/Deed … made/entered into … between" on the clause's first line (`_AGREEMENT_IS_MADE`).
- New stop list for parties, `_NOT_A_PARTY` = the company stop words (including months and days) + `_COUNTRIES` + `_CURRENCIES` + company/companies.
- Tests: `test_no_parties_without_a_party`, run on `find_parties` and on `apply_rules` (no PERSON/COMPANY). It has the reviewer's 8 sentences verbatim plus "4. PERIOD BETWEEN EXCHANGE AND COMPLETION" (a contents line) and "made between Euro and Sterling zones".

**Important 2: defined terms hidden by other rules**
- Address labels: `_is_an_address` now rejects a value without a digit when it starts with lower-case "the " ("the Site", "the Premises") or equals one of the document's defined terms (with or without "the"). `_addresses(doc, terms)` gets the terms from `_definitions` (all quoted terms).
- Short names: `_Term` carries `anchor`, the position of its bracket or its "hereinafter"; a `means` definition has none. `_ShortNames.type_of` takes the last rule name that ends before the anchor on the same line. The term is a short name only if the text between them is defining words alone (straight after) or that name is a party (the bracket ends the party's description), and only if the term is one of the name's short forms (word-runs from the start, initials, or a person's first, last or full name). The prefix (`starts`) match is gone.
- Tests: `test_a_defined_term_after_an_address_label_is_no_address`, `test_a_term_that_shares_a_word_with_a_name_stays_a_term` (the reviewer's 4 cases) and the new `test_a_short_name_at_the_end_of_a_party_is_hidden_not_a_term`. That last one keeps `(1) Acme Supplies Ltd, a company …, whose registered office is at … ("Acme")` hidden: a pure straight-after rule would have made "Acme" a defined term, and so a never-hide entry in Task 8, which is a leak.

**Important 3: `find_parties` stopped after party 1**
- A line that is just "AND"/"and" is a separator, not a heading.
- A party line ending in "." ends the clause only when the next non-blank line does not start with a party number (`_party_follows`).
- Comma lists are read with `_listed_parties`, all or nothing: `, Name (, Name)* (,) and Name`. So "Acme Supplies Ltd, Amsterdam, the Netherlands (the "Supplier")" still gives one party, because "Netherlands" is in the country stop list and breaks the list.
- Tests: `test_parties_separated_by_a_line_that_is_just_and` (WENDELIN ACHTERBERG as PERSON), `test_parties_that_each_end_in_a_full_stop` (Practical Law layout: NORTHWIND TRADING B.V. and GLENMORE FREIGHT), `test_parties_in_a_list` (3 layouts) and `test_a_list_that_runs_into_an_address_names_one_party`.
- **Note:** the reviewer's exact sentence "made between Northwind Trading, Glenmore Freight and Kestrel Analytics" has no party context of any kind. Under the Important 1 fix it now gives no rule parties at all (the model still finds such names; capped COMPANY 0.6 is likely). The list reading is tested on the same names with context present: "This Agreement is made between …", a defining bracket, or "(1)".

**Important 4: catastrophic backtracking in `_LINE_LABEL`**
- The pattern is now `[ \t]*(WORD(?:[ \t]+WORD){0,3})[ \t]*:` with `WORD = [^\W\d_][\w'’./-]*`: words must stand apart, so a long word has one reading.
- RED: `apply_rules("Name:\n" + "a"*n)` took 0.11 s at n = 100 and 0.53 s at n = 150 (the failing match, without a colon). GREEN: 5,000 letters, and a 900-character schemeless URL, run in 0.00 s.
- Tests: `test_rules_are_quick_on_texts_made_to_be_slow[long-word]` and `[long-web-address]` (3,000 letters; a 333-character web address).

**Ruling R21: LOCATION rescue** (`engine.py` `_checked_by_rules`, `_types_of_short_forms`)
- A model place with no rule address within 2 characters is now re-typed as PERSON or COMPANY with `score = min(score, 0.7)` (`SHORT_NAME_PLACE_SCORE`). This happens when its normalised text (minus a leading "the") is a variant (`variants_of`), or the first word (≥ 4 letters, not COMMON_WORDS), of any PERSON or COMPANY finding in the document, rule or model, after the same-span and job-title filters.
- Refinement (flagging it): defined terms never take part, either as names giving short forms or as rescued places. The corpus check below showed why: the model takes "the Delivery Point" for a COMPANY in one clause and for a place in another, and "Discloser" likewise, so a literal rescue spread 12 more defined-term hits ("the Delivery Point" 20 → 30, "Discloser" 71 → 73). With the refinement those are gone.
- Every other place without address context is still dropped.
- Tests: `test_a_short_name_taken_for_a_place_is_found_as_its_company` (footer "Greystone" → COMPANY 0.7 when "Greystone Logistics Ltd" is in the body), `test_an_initial_and_surname_taken_for_a_place_is_found_as_the_person` ("H. Field" → PERSON 0.7 with "Name: Hannah Field"), `test_a_defined_term_taken_for_a_place_is_not_found_as_a_name`, and `test_a_place_that_is_no_name_still_stays_visible` ("the laws of the Netherlands and the courts of Amsterdam" next to Greystone Logistics Ltd gives no ADDRESS, and only the company is found).

## TDD evidence
- RED: `uv run pytest tests/detect/test_contract_rules.py -q -k "not long-word and not long-web-address"` gave **28 failed, 218 passed**. The failures were all 10 no-party sentences, the 3 layouts (5 tests), the address-label term, the 4 shared-word terms, the 5 capitals layouts, the job-title fragment and the 2 R21 rescues. Expected, since none of the fixes existed. The long-word cases were measured separately, as above.
- RED: `-k taken_for_a_place` gave `FAILED test_a_defined_term_taken_for_a_place_is_not_found_as_a_name` (the place was rescued as COMPANY 0.7), the expected effect of the literal rescue.
- GREEN: `uv run pytest tests/detect -q` gives **506 passed**; `uv run pytest -q` gives **1555 passed**; the merged tree gives 1678 passed.

## Corpus re-check (same scratch set-up as before)

| type | reported before | after this round |
|---|---|---|
| ADDRESS | 99.2 % | 99.2 % |
| COMPANY | 87.5 % | **88.6 %** (+6 occurrences: R21 rescues) |
| PERSON | 99.6 % | **100.0 %** |

- Rule false positives: 0.
- Model false positives: 1,332 (was 1,335): "Telephone:" is gone as a split label, and nothing new appears.
- Whole-engine timing on 12,060 words is unchanged: 3.45 s (rules 0.07 s). Adversarial inputs take ≤ 0.42 s.

## Files changed in this round
`src/themask/detect/contract_rules.py`, `src/themask/detect/engine.py`, `tests/detect/test_contract_rules.py`.

## Left as the reviewer asked
The Minors logged for Task 24 are untouched: departments as PERSON, KG/Corporation/Limited guards, quantities as addresses, an address span running past the country, persons typed COMPANY in party lists, a role word as first token, address vocabulary, the quadratic honorific scan, and duplicated vocabulary sets. One more for Task 24: Practical Law short names in brackets without quotes ("(Supplier)") are not defined terms yet.

---

# Fix round 2 (re-review round 1, ruling R25)

**Status:** DONE. Commit `ccc61a1 fix: no towns as parties, short names by party description (R25)` on `task-7`, on top of `efc7fe0`.

**Tests:**
- `uv run pytest tests/detect -q`: 550 passed.
- `uv run pytest -q`: 1599 passed (was 1555).
- `uv run ruff check src tests`, `ruff format --check` and `uv run mypy src`: clean.
- Merged tree (`git merge-tree --write-tree mac-v1 task-7`, mac-v1 at 53237fb, exported to scratch): 1771 passed; `ruff check src tests tools` and mypy are clean.

## What changed, per finding

**New Important 1: a town after a party read as a party.**

- Every name in the parties clause must now show it is a party (`_shows_a_party`): a legal form, an honorific, its number in brackets straight before it ("(1) "), or a description or defining bracket straight after it (`_PARTY_DESCRIPTION`).
  - Description examples: ", a company registered in", "incorporated", "whose registered office", "having its registered office", "of 12", "an individual", "residing", "(company number", "hereinafter".
  - Defining bracket examples: (the "X"), ("X"), (each a "X").
  - This replaces round 1's per-line gate (`_PARTY_CONTEXT`, `_AGREEMENT_IS_MADE`, `_names_a_party` are gone). "This Agreement is made between" alone no longer vouches for a name.
- A comma list is accepted only when all its names have a legal form, or none has one and a defining bracket follows the list (`_is_a_list_of_parties`). A name without a legal form among names with one is a town, so the whole list is dropped. The names with a legal form are still found by the legal-form rule.
- Defense in depth for R21: a model place after "the laws of", "the courts of", "court in", "jurisdiction of" and similar is never rescued as a name (`_is_a_jurisdiction`).
- Tests:
  - `test_a_town_after_a_party_is_no_party`: the reviewer's six layouts (Frankfurt/London, Leeds/Rotterdam, Amsterdam with and without ", and", New York/Springfield, "Frankfurt, Hamburg and Berlin" after a party). It checks that no town appears among the rule findings and that only legal-form companies remain.
  - `test_the_jurisdiction_after_parties_with_towns_stays_visible`: through the engine; only the two companies are found.
  - `test_no_parties_without_a_party` gains "made between Rotterdam and Hamburg", "Frankfurt, Hamburg and Berlin" and the plain list "Northwind Trading, Glenmore Freight and Kestrel Analytics".
  - `test_parties_in_a_list` now has the bracket layouts; new `test_parties_with_legal_forms_in_a_list`.
- **Behaviour note:** a list of names without legal forms and without a defining bracket ("This Agreement is made between Northwind Trading, Glenmore Freight and Kestrel Analytics.") now gives no rule parties, because it cannot be told from a list of towns. Those names are left to the model.

**New Important 2: short names keyed on the nearest name, and refused at a line break.**

- `_ShortNames` now takes its owners from two places:
  - the party whose description holds the bracket. A description runs from the party's name to the next party, the first ";", or the first full stop that ends a line, over line breaks (`_descriptions`);
  - the name the bracket stands straight after: only blanks, line breaks included, commas and defining words between them, within 40 characters.
- The term must be one of the owner's short forms.
- Tests: `test_a_short_name_in_its_partys_description_is_hidden_not_a_term` (representative between, parent company between, line break, soft line break), plus `test_a_short_name_of_another_company_in_a_partys_description_is_hidden_too` ("Northwind Group" for the parent named straight before its bracket). The Price/Customer/Delivery/Premier negatives still pass.
- To read party (2) after a soft line break, a line that names no party now keeps the clause open when the previous line did not end a party's description (`_ENDS_A_PARTY`: ";", "; and", ".", ")" or a closing quote).

**R25 (3): reference headings and "LABEL: code" pieces.**

- `is_contract_wording` accepts a reference straight after a contract word (`_REFERENCE`: "1", "4.2", "A", "II"), so "SCHEDULE 1", "EXHIBIT A", "APPENDIX 1", "ANNEX II" and "Schedule 3 Prices" count.
- In the engine, a part that is "label: value", where the value is a code, names nobody. A code here is a number, or one word in capitals: "BIC: DEUTDEBB".
- So does a one-word part with digits and no lower-case letters, or with no letters at all (`_is_a_number`). This drops "7.5" and the IBAN typed PERSON that dpa-05's model span also left.
- A word in capitals on a line of its own still counts as a possible name ("ACME"). I found that slip in self-review: my first version also dropped one-word capitals.
- Tests: `test_contract_wording` (13 texts) and `test_names_and_bare_references_are_not_contract_wording`, both direct unit tests. Through the engine: `test_a_heading_or_label_on_the_next_line_is_no_name` (SCHEDULE 1, EXHIBIT A, Country, Bank, the dpa-05 "BIC: DEUTDEBB" lines), `test_a_clause_number_or_code_on_the_next_line_is_no_name`, and `test_a_one_word_name_in_capitals_on_the_next_line_stays_found`. The last one feeds `Engine.analyze` a fixed model reading through `monkeypatch`, because the model seldom produces that span by itself.

**R25 (4): the colon rule.** A one-word part directly followed by ":" names nobody again (`_LABELS_ITS_LINE`), so "Country" and "Bank" are gone; the tests are above.

**R25 (5): recitals after the last party.**
- After a party line that ends in a full stop, only a party's number ("(1)", "1.", "1)") or an "AND" line continues the clause (`_PARTY_NUMBER`). "(A)" ends it.
- A name after a lettered marker has no number before it, so it is no party either.
- Test: `test_recitals_after_the_last_party_are_no_parties`.

**R25 (6): housekeeping.**
- `_COMMON_FIRST_WORDS` and the `COMMON_WORDS` import are gone from `contract_rules`.
- `is_contract_wording` has its own unit tests.
- The `SHORT_NAME_PLACE_SCORE` comment now says these findings are not marked for checking, since the pipeline marks only scores below 0.7.

## TDD evidence
- **RED:** `uv run pytest tests/detect/test_contract_rules.py -q` gave **26 failed, 266 passed**, all of them new tests:
  - 3 no-party sentences;
  - the 6 town layouts;
  - the recitals test;
  - 5 `is_contract_wording` reference cases;
  - the 4 short-name layouts;
  - the 5 heading/label engine cases;
  - the code-piece and jurisdiction engine tests.
  These were expected: the old code read "Frankfurt" as COMPANY 0.9, kept "Acme" as a term, and kept "SCHEDULE 1", "Country", "Bank" and "BIC: DEUTDEBB" as findings.
- **RED:** `-k one_word_name_in_capitals` failed. "ACME" was dropped by the first version of the code rule.
- **GREEN:** `uv run pytest tests/detect -q` gives **550 passed**; `uv run pytest -q` gives **1599 passed**.

## Corpus re-check (same scratch set-up)

| type | after round 1 | after round 2 |
|---|---|---|
| ADDRESS | 99.2 % | 99.2 % |
| COMPANY | 88.6 % | 88.6 % |
| PERSON | 100.0 % | 100.0 % |

- Rule false positives: 0. Model false positives: 1,331 (was 1,332; the "7.5" PERSON is gone).
- `find_parties` still finds exactly 2 parties in each of the 28 corpus files.
- Whole engine on 12,060 words: 3.6 s (rules 0.07 s).
- Adversarial inputs take at most 0.42 s (one long word after a label, 3,000 comma-joined towns after a party, a 2,000-name list).

## Files changed in this round
`src/themask/detect/contract_rules.py`, `src/themask/detect/engine.py`, `tests/detect/test_contract_rules.py`.

## Left as ruled
The Minors logged for Task 24 are unchanged.
