# Task 24: review of fix round 2 (R97 + round trip), lean mode

Reviewer: Claude (review subagent), 19 October 2026. Scope: the fix diff b715080..ec8ec1c (9438038 WIP tests, 993a12e fix, ec8ec1c docs) and items (a)–(g) below. The worktree `/home/user/the-mask-worktrees/task-24` was read only: `git status --short` is empty after the review.

**Method.** Every claim comes from the real engine: `Engine()` and `analyze(CombinedText.join([("x", text)]), engine, UserLists([], []), CaseLists([], [], set()))`, run on three sources side by side:
- **HEAD**: the worktree at ec8ec1c.
- **base**: `git archive b715080 src`.
- **inherited**: `git archive 9438038 src` plus the implementer's saved `scratchpad/r97/inherited-src.patch`.

Groups are written as placeholder/TYPE "canonical" (source score, check = needs_check). The harness is `scratchpad/review/probes/probe.py`, the probe lists are `scratchpad/review/probes/*.txt`, and the outputs are in `scratchpad/review/out/`. "scratchpad" is `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad`.

## (a) Reference words: ADDRESSED

| Probe | HEAD | base |
|---|---|---|
| `Schedule 3 Pallets`; `The pallets are described in Schedule 3 Pallets and Packaging.` | visible | QUANTITY "3 Pallets" |
| `Section 5 pallets`; `…as set out in Section 5 pallets shall be returned.` | visible | QUANTITY "5 pallets" |
| `under Clause 4 cartons are listed` | visible | QUANTITY "4 cartons" |
| `The Goods under Clause 4 cartons are listed.` | "4 cartons" visible; model COMPANY "Goods under" (0.60, check), the same at base | + QUANTITY "4 cartons" |
| `Part 2 Units`; `The terms are in Part 2 Units of the Agreement.` | visible | QUANTITY "2 Units" |
| `SCHEDULE 3 PALLETS AND PACKAGING`; `Annex 2 units of measure apply.`; `Exhibit 4 boxes are attached.` | visible | QUANTITY hidden |
| `Annex 2 Units of Measure`, alone and in a sentence | [COMPANY_1] = the whole heading (model 0.60, check); no QUANTITY | identical output |
| `spare parts 500 units`, alone and in a sentence | QUANTITY "500 units" | same |
| `the art 12 pieces`; `The Supplier shall supply the art 12 pieces each month.` | QUANTITY "12 pieces" | same |
| `and replacement parts 2,000 pieces`, and in a sentence | QUANTITY "2,000 pieces" | same |
| `Schedule 3 500 pallets`; `as set out in Schedule 3 500 pallets shall be delivered` | QUANTITY "3 500 pallets" (the 500 hidden, with the 3) | same |
| `the Art. 30 records`; `The Processor keeps the Art. 30 records of processing activities.` | visible | visible |

The quantity rule is fixed as ruled. One exact probe string is still hidden in the full pipeline: title-case `Annex 2 Units of Measure`. The quantity rule no longer causes it (HEAD finds no QUANTITY). The model's flagged COMPANY guess on the heading does, and it does so identically at base. Parked as P1.

## (b) Spaced hyphen: ADDRESSED

| Probe | HEAD | base |
|---|---|---|
| `Confidential - Acme Supplies Ltd - Page 3` | `Confidential - [COMPANY_1] - Page 3`, COMPANY "Acme Supplies Ltd" (rule 0.95) | `[COMPANY_1] 3`, COMPANY "Confidential - Acme Supplies Ltd - Page" (model 0.85) |
| the same after `Acme Supplies Ltd sells the Goods.\n` | one group "Acme Supplies Ltd", both places | two groups, the header's including Confidential/Page |
| `Smith - Jones Logistics Ltd`, alone and in `The Buyer is …, a company in England.` | one COMPANY "Smith - Jones Logistics Ltd" (model 0.85) | same |
| `Greystone Logistics Ltd and Brinkhof B.V. sign.\nGreystone - Brinkhof - Agreement` | `[COMPANY_1] - [COMPANY_2] - Agreement` | same |

Side effects that improved on base:
- `CONFIDENTIAL - ACME SUPPLIES LTD - PAGE 3`, `STRICTLY CONFIDENTIAL - Acme Supplies Ltd`, `Final - … - Page 1` and `Supply Agreement - … - Page 2` now hide only the company.
- `Confidential - Jane Smith - Page 3` gives PERSON "Jane Smith". `Confidential - Northwind - Page 3` gives a flagged COMPANY "Northwind".
- `Jane Smith - Finance Director`, `John Carter - Sales Manager` and `Mary Jones - Legal Counsel` leave the title visible. Base hid "Finance", "Sales" and "Legal Counsel" inside the person.

Unchanged (R95 reading): `John Carter - Managing Director` gives PERSON "John Carter - Managing".

## (c) Records: ADDRESSED

| Probe (bare phrase, and in a sentence) | HEAD | base |
|---|---|---|
| `the 2025 records`; `The Supplier shall keep the 2025 records for audit.` | visible | visible |
| `Acme's 2025 records`; `… are kept for six years.` | "2025 records" visible ("Acme" is a model PERSON 0.85 check, the same at base) | same |
| `up to 2000 records`, `about 2025 records`, `approximately 1999 records`, `no more than 2050 records`, `a total of 2000 records` | QUANTITY "<n> records" (0.80) in all 10 probes | visible |

## (d) Dutch postcode after a spaced hyphen: ADDRESSED

`Ship to: Keizersgracht 123 - 1015 CJ Amsterdam` gives `Ship to: [ADDRESS_1]`, ADDRESS "Keizersgracht 123 - 1015 CJ Amsterdam" (rule 0.85). Base gave ADDRESS "Keizersgracht 123", AMOUNT "1015" (0.40, check), and left "CJ Amsterdam" visible.

Related probes at HEAD:
- The en dash with `, the Netherlands` gives one ADDRESS.
- `Delivery address: Damrak 1 - 1012 LG Amsterdam` gives one ADDRESS. Base also had an AMOUNT and a COMPANY "LG".
- `Ship to: Keizersgracht 123 - Supply Agreement` and `… Amsterdam - Supply Agreement` leave the title visible.
- `Page 2 - 1500 KG Steel` starts no address (QUANTITY "2 - 1500 KG", the same at base).
- The R95 address cases still hold: `…, Dublin 2, Ireland, D02 X285` is one ADDRESS, and `…, the Netherlands, Attention Finance` ends at the country.

## (e) Round-trip test: ADDRESSED

Against the brief's version, `test_full_round_trip_every_docx` asserts all of the following:
- **From the brief:** the export is not blocked; every key value is in the restored text; outside `existing_placeholders` files, the placeholder set is exactly {"[PERSON_9]"}. `find_placeholders` also returns changed forms, so a leftover "[PERSON 1]" would fail this check.
- **Fingerprint:** `plan_docx(ai, res.case).sha256` is passed as `expected_sha256`.
- **Altered placeholder caught and restored on confirmation:** `rep.needs_check == []` and `rep.altered_restored == len(altered)`, and the altered item is exactly "[PERSON 1]" when the key holds [PERSON_1].
- **Unknown placeholders:** `rep.unknown == ["[PERSON_9]"]`.
- **Truth secrets:** every truth secret (except deleted or hidden ones) is in the restored text.
- **`existing_placeholders` files** (supply-09, nda-03, dpa-04) are left out of the set assertion. For them, the test asserts [PERSON_9] unknown and the file's own "[PERSON 1]" left as written.

The analysis passes the same `CaseLists` object to `analyze` and to `from_analysis`, which is a correct strengthening of the brief.

**Run:** `1 passed, 13 deselected in 72.84s`. The 28 per-file lines are identical to the report's printout (checked by diff).

**No wrong substitution.** Like the brief, the test checks this only through presence: a value restored in another's place at one occurrence would still pass if the right value stood elsewhere. I checked it independently with `scratchpad/review/probes/roundtrip_align.py`. It runs the same pipeline on a freshly generated corpus. It then walks the AI file's text, and requires each literal stretch to stand unchanged in the restored text and each key placeholder (the altered one included) to be followed by **its own** value. Text and values are whitespace-normalised and the banner is removed.
- Result: `TOTAL occurrences 1497, restored to their own value 1497, problems 0`, all 28 files, no key placeholder left.
- Negative control (expected values of [COMPANY_1] and [COMPANY_2] swapped, nda-01): caught at the first [COMPANY_1].

Whether to add this check to the test is parked as P6.

## (f) The two regressions found in the inherited diff: ADDRESSED (real, fixed, covered)

| Probe | base | inherited | HEAD |
|---|---|---|---|
| `the Art. 30 records` (also `… of processing activities`, `ART. 30 RECORDS`) | visible | QUANTITY "30 records" | visible |
| `as set out in Schedule 3 500 pallets shall be delivered` | QUANTITY "3 500 pallets" | visible (**leak**) | QUANTITY "3 500 pallets" |
| `the Article 30 500 records` | visible | visible | QUANTITY "30 500 records" (better) |

Coverage: the 4 full-stop cases in `test_a_reference_a_year_or_a_single_record_is_no_quantity`, and `test_a_count_after_a_reference_without_its_comma_is_still_found` (3 cases).
- Against the inherited source: `7 failed, 22 passed`. Exactly the 7 new cases fail.
- At HEAD: `29 passed`.

## (g) The fix diff: no Critical; 1 Important and 4 Minor new regressions, all narrow, parked per lean mode

`uv run pytest tests/detect -q` gives `1051 passed`. Ruff, format and mypy are clean. None of the regressions below appears in the corpus. The pass marks are unchanged (4 passed). Each regression is new against base b715080.

**G1 (Important, hiding): a count written as a range after a reference number is dropped.**
- Probes, HEAD against base:
  - `Schedule 3 - 500 pallets per week` and `Minimum volumes: Schedule 3 – 500 pallets per week.`: nothing hidden at HEAD. Base hid QUANTITY "3 - 500 pallets".
  - `Clause 7 – 250 tonnes per quarter`: visible. Base hid "7 – 250 tonnes".
  - `Clause 12 - 2000 KG Limit applies.`: visible. Base hid "12 - 2000 KG".
  - `Annex 1 – 2,000 units per month`, `Section 2 - 10,000 units minimum` and `Article 3 to 1,000 pieces`: only the figure is caught, as a flagged AMOUNT 0.40, and the unit stays visible. Base hid the whole range as QUANTITY.
- Cause: the range reading "3 - 500 pallets" starts right after the reference word, so `_is_a_reference` drops the whole match, count included. The `_SPACED_DIGITS` exception covers "3 500" but not "3 - 500" or "3 to 500". For "records" this was already so at base (`Article 30 - 500 records` is visible in both).
- This is the sibling of the ruled "Schedule 3 500 pallets" case.
- Verified one-line fix on a scratch copy: `_SPACED_DIGITS = re.compile(r"\d(?:" + _SPACE + "|" + _TO + r")\d")`.
  - All 5 range probes go back to base's QUANTITY.
  - Schedule 3 Pallets, Section 5 pallets, Clause 4 cartons, Part 2 Units and the Art. 30 records stay visible.
  - `tests/detect/test_patterns.py`: 356 passed.

**G2 (Minor, hiding): the reference words are also verbs and common nouns.**
- These are all visible at HEAD and were hidden as QUANTITY at base:
  - `The Supplier shall schedule 500 pallets for collection each week.`
  - `The Buyer shall schedule 24 pallets per delivery slot.`
  - `The Buyer schedules 400 units per delivery.`
  - `The Supplier may schedule 2,000 units per month.`
  - `The Retailer shall exhibit 12 units of the Products in each store.`
  - `Packing: per article 12 pieces per carton.`
  - `Each article 500 pieces, packed per carton.`
  - `In each section 40 pallets are stored.`
- This follows literally from R97's word list, which is case-free except for "Part".
- Possible fix: require the capital for schedule/exhibit/article/section, as for "Part", or skip the guard after "shall/will/may/must/to".

**G3 (Minor, visibility of dates): a full date right before "records" loses its year.**
- At HEAD:
  - `From 1 January 2026 records must be kept for seven years.` becomes `From 1 January [QUANTITY_1] must be kept…`.
  - `On 31 December 2025 records were transferred…`, `Since 25 May 2018 records of processing activities must be maintained.` and `With effect from 1 March 2026 records shall be kept in the EU.` behave the same way.
- Base left all four visible.
- It is the same rule as the accepted "In 2025 records were lost" (conservative side). But here a visible-by-default date is cut in two, and a DPA phrase like "Since 25 May 2018 records of processing" is plausible.
- Fix: in `_is_the_records_year`, take a month name (or day and month) before the year as a date's year, or let the engine's date veto drop a QUANTITY whose figure ends a Presidio date.

**G4 (Minor, hiding): a one-word side of a spaced-hyphen double name that is a contract word or default term becomes visible.**
- At HEAD:
  - `Price - Jones Logistics Ltd shall deliver the Goods.` becomes `Price - [COMPANY_1] shall deliver the Goods.`. Base hid one COMPANY "Price - Jones Logistics Ltd".
  - The same happens for `Page - Turner Ltd` ("Page" visible), `Holland - Smith Logistics Ltd`, `Law - Smith LLP` and `Key - Jones Ltd`.
- With two-word sides, both parts stay hidden under two placeholders, as in the accepted "Mary Price - Jones": `Sarah Law - Jones`, `James Page - Turner`, `Laura Holland - Smith`.
- Cause: the R97 "either side" cut, then `_names_nobody` or the never-hide check drops the lone word.

**G5 (Minor, contrived): a postcode-shaped figure after a spaced hyphen joins the address.**
- `Keizersgracht 123 - 2025 NL Edition` becomes one ADDRESS, with the year hidden. At base, "2025 NL Edition" stayed visible.
- `Keizersgracht 123 - 1500 KG Steel per month` gives the ADDRESS "… - 1500 KG Steel" (implementer's concern 6). It is hidden either way; base had a model PERSON there.

Improvements seen in the same probes:
- the header and title cases under (b);
- `Address: Northwind Trading B.V. - 1015 CJ Amsterdam` now hides the postcode and town;
- `Registered office: … - Chamber of Commerce 12345678` no longer puts "the Netherlands" in a company guess;
- `Weena 12 - 3011 AB Rotterdam - Netherlands` leaves the country visible.

## Parked (for the final whole-branch review)
- **G1–G5** above. G1 is the one I'd take first: it has a one-line fix, verified.
- **P1 (pre-existing):** a title-case heading is hidden whole as a flagged model COMPANY guess. Examples: `Annex 2 Units of Measure`, and `In accordance with Appendix 3 Items and Prices, …`, which gives [COMPANY_1] "Appendix 3 Items and Prices" (0.60, check). The output is identical at base.
- **P2 (pre-existing):**
  - Bare `Greystone - Brinkhof - Agreement` hides nothing when nothing else names the parties.
  - `Kanaalzicht - Harbourline - Page 2` gives one COMPANY "Kanaalzicht - Harbourline", two parties under one placeholder. This is the class of the parked "Northwind - Acme".
- **P3 (pre-existing):** the (d) rule only continues an address already being read.
  - `Weena 12 - 3011 AB Rotterdam - Tel …` has a Dutch street without a street word or label. It gives COMPANY "Weena 12", AMOUNT "3011" and COMPANY "AB Rotterdam": all hidden, but typed wrong.
  - `Schedule 3 - 1015 CJ Amsterdam` leaves "CJ Amsterdam" visible.
- **P4:** in `There's 2000 records in the system.`, "2000 records" stays visible: `_OWNER`'s `\w['’]s` also matches the contraction.
- **P5 (accepted class, conservative):** these give QUANTITY: `As of 2025 records…`, `By 2030 records shall be digital.`, `these 2025 records`, `During calendar year 2025 records…`, and the second year in `the 2024 records and 2025 records`.
- **P6:** the round-trip test asserts "no wrong substitution" by presence only (as the brief does). An occurrence-level check like `roundtrip_align.py` would make it a real assertion.
- **P7 (accepted readings, observed as described):**
  - `Mary Price - Jones` gives two PERSON groups.
  - `Draft - Acme Supplies Ltd - Version 2` gives "Version 2" as COMPANY 0.60, check.
  - `In 2025 records were lost.` gives a QUANTITY.
  - `SPARE PART 5 UNITS` stays visible.
  - Bare `Art 30 records` gives a QUANTITY.
- **P8 (pre-existing, model):** in `Sarah May - Jones signed for the Buyer.`, the model finds only "Sarah", so "May - Jones" stays visible. The same happens at base.

## Commands run
All from `/home/user/the-mask-worktrees/task-24`. To leave the worktree untouched, they used `uv run --no-sync`, `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`, `ruff --no-cache` and a mypy cache in the scratchpad.

| Command | Last line |
|---|---|
| `uv run pytest tests/test_passmarks.py -q -m slow -s -k round_trip` | `1 passed, 13 deselected in 72.84s (0:01:12)` |
| `uv run pytest tests/test_passmarks.py -q -m slow` | `4 passed, 10 deselected in 121.32s (0:02:01)` |
| `uv run pytest tests/detect -q` | `1051 passed in 19.42s` |
| `uv run ruff check src tests tools` | `All checks passed!` |
| `uv run ruff format --check src tests tools` | `129 files already formatted` |
| `uv run mypy src` | `Success: no issues found in 48 source files` |
| `PYTHONPATH=<inherited>/src uv run pytest tests/detect/test_patterns.py -q -k "reference_a_year or without_its_comma"` | `7 failed, 22 passed, 327 deselected in 2.23s` |
| the same on HEAD | `29 passed, 327 deselected in 2.01s` |
| `uv run python scratchpad/review/probes/probe.py <list>` on HEAD, base and inherited (items, g, g2, g3, f) | outputs in `scratchpad/review/out/` |
| `uv run python scratchpad/review/probes/roundtrip_align.py <worktree> <workdir>` | `TOTAL occurrences 1497, restored to their own value 1497, problems 0` |
| negative control (`roundtrip_align_negctl.py`) | `TOTAL occurrences 1, restored to their own value 0, problems 1` |
| G1 fix on a scratch copy: `PYTHONPATH=scratchpad/review/headfix/src uv run pytest tests/detect/test_patterns.py -q` | `356 passed in 7.14s` |

APPROVED. Items (a)–(f) are addressed. (g): the diff has no Critical leak or restore defect. G1 (Important) and G2–G5 (Minor) are parked for the final review, and G1 is recommended as a one-line follow-up.
