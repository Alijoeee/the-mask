# Final whole-branch review — mac-v1 at 3e7d6ea (Mac phase, Tasks 1–25)

Reviewer: Claude (Fable 5.1, final-review subagent), 19 October 2026. Scope: `git diff 4253722..3e7d6ea`
(153 files), read as the files of the repository at HEAD; the pointer list
`notes/sdd/final-review-pointers.md` worked through item by item; the ledger's rulings R1–R106 as the
yardstick where the plan and the code disagree. Nothing in the repository was edited, committed or
switched. Every scratch file is under
`/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/final-review-scratch/`
("SCRATCH" below): `scripts/*.py` are the reproductions, `out/` their inputs and outputs, `corpus/` a
copy of the generated corpus. Every reproduction builds its own made-up Word file with lxml/zipfile; no
real document was used. Each is run as `uv run python SCRATCH/scripts/<name>.py` from the repository
root; the output quoted below is what it printed on this box.

**What I read in full:** leakcheck.py, docx/{package,cleaner,masker,reader,revisions,restorer}.py,
detect/{grouping,patterns,pipeline,sweep,engine,lists}.py, textnorm.py, export.py, review.py,
restore/*, keystore/*, netguard.py, logging_setup.py, paths.py, model.py, placeholders.py,
instruction.py, pdf/to_docx.py, the head and outline of pdf/extractor.py and
detect/contract_rules.py, ui/* (all screens, workers, app), tests/helpers.py, tests/conftest.py,
tests/ui/conftest.py, every tests/fixtures module, the two task reviews and the ledger's rulings.

## 0. Counts

| Severity (my rating, by the brief's definitions) | Count | Items |
|---|---|---|
| Critical | 3 | F-1 (R100), F-2 (R101), F-3 (R102) |
| Important | 6 | F-4 link targets and attribute-held contact data (new), F-5 the glued image note (new), F-6 merging two stored placeholders (new), F-7 R105 G1, F-8 R104 zip limits, F-9 A1/A2/A3 number folds (must-fix by ruling; Minor by impact) |
| Minor, recommended for the wave (cheap) | 11 | F-10 … F-20 |
| No longer reproduces / nothing to do | 5 | A7 (R103, verified), A11 (README), the MaskPlan validation, the zip archive comment, the `int()` guard |

Every Critical and Important above has a reproduction I ran (section 1). Claims I could not or did not
reproduce are listed apart in section 1.5 as "unverified".

The suite, lint and types at HEAD: see section 4 (`uv run pytest -q`: see the line quoted there; ruff
"All checks passed!"; mypy "Success: no issues found in 52 source files").

---

## 1. The must-fix list for the fix wave (ordered by severity)

Each item: where, the behaviour, the reproduction (script and its output), the fix, the regression test.
"Pointer" names the item of `final-review-pointers.md`. The fix wave is one implementer: F-1 … F-9 are
the real work; F-10 … F-20 are each a few lines.

### F-1 [Critical] Grouping identity is `normalize()`, so values that differ only in a decimal point, a currency symbol or a dot become ONE placeholder and restore to the first value (pointer A4, ruling R100)

- **Where:** `src/themask/detect/grouping.py` `_by_value` (keys `normalize(finding.text)`),
  `_Bucket.of_seed`/`by_seed_key` and `_keep_shared_variants_out` (seed matching on `normalize`),
  `src/themask/review.py` `_holding` (the group `hide_text` joins, on `normalize`).
- **Behaviour:** a real round trip writes the wrong value silently (§5 anti-goal).
- **Reproduction** `scripts/engine_batch.py`, section A4, real engine, full `export_case` and
  `restore_text`:
  ```
  [AMOUNT_1]/AMOUNT 'EUR 1.25' variants=['EUR 1.25', 'EUR 125'] places=['EUR 1.25', 'EUR 125'];
  [AMOUNT_2]/AMOUNT '$100' variants=['$100', '€100'] ...; [EMAIL_1]/EMAIL 'a.b@example.com' variants=['a.b@example.com', 'ab@example.com'] ...
  masked : 'The unit fee is [AMOUNT_1] per item and the annual cap is [AMOUNT_1] per customer. The deposit is [AMOUNT_2] and the refund is [AMOUNT_2]. Questions to [EMAIL_1] or to [EMAIL_1].'
  restore: 'The unit fee is EUR 1.25 per item and the annual cap is EUR 1.25 per customer. The deposit is $100 and the refund is $100. Questions to a.b@example.com or to a.b@example.com.'
  report : 6 placeholders restored, 0 need your check.
  ```
- **Fix (R100, precise):** add one public identity function and use it everywhere a value's identity
  is decided:
  1. In `leakcheck.py` make the number fold public: `number_fold(text) -> str` = the `_COMPACT` view of
     `_folds` (letters and digits, each decimal point the mark, trailing decimal zeros dropped). Do not
     write a second copy of the fold rules (the external review's architectural point).
  2. New `detect/identity.py` (or in `grouping.py`): `value_key(kind, text) -> str`:
     - AMOUNT, PERCENT, QUANTITY: the currency/unit tokens (letters, with symbols mapped to codes:
       `€`→EUR, `$`→USD, `£`→GBP, `₺`→TRY, `¥`→JPY, `₹`→INR, `₽`→RUB, and the words
       euro(s)/pound(s)/dollar(s)/… the AmountRecognizer already knows → the same codes), sorted and
       joined, then `|`, then `number_fold` of the rest. Position-independent, so "EUR 1,250" and
       "1,250.00 EUR" are one value, "EUR 1.25" / "EUR 125" and "$100" / "€100" are not.
     - EMAIL, URL: `NFKC` + casefold + every whitespace removed; dots and punctuation kept.
     - PHONE, IBAN, ID: letters and digits only (`normalize`, as today; `_phone_keys` stays).
     - PERSON, COMPANY, ADDRESS, CUSTOM: `normalize` as today.
  3. Use `value_key` in `_by_value`, in `_Bucket.of_seed` (`names`) and `by_seed_key`, in
     `_keep_shared_variants_out`, and in `review._holding`. The sweep keeps `flexible_pattern`
     (R11 already guards decimals); identity decides what is one value, the sweep only finds spellings.
- **Regression tests (`tests/detect/test_grouping.py`, `tests/test_review.py`, `tests/test_restore.py`):**
  the three pairs above are separate groups with their own placeholders, and a round trip through
  `export_case` + `restore_text` restores each to its own value; "EUR 1,250.00" / "EUR 1.250,00" /
  "1,250.00 EUR" stay one group; "10%" / "10.0%" one group; "NL91 ABNA 0417 1643 00" /
  "NL91ABNA0417164300" one group; `hide_text("EUR 125", AMOUNT)` makes a new group next to "EUR 1.25";
  a seed entry "EUR 1.25" does not absorb a finding "EUR 125" in an added file.

### F-2 [Critical] Media parts survive wherever the text does not show them, and the export gate lets them through (pointer A5, ruling R101)

- **Where:** `src/themask/docx/cleaner.py` `_sweep` (keeps any `word/media/*` that a relationship
  reaches), `_replace_pictures` (body drawings and `v:imagedata` only), the module docstring's
  "Not touched" list; `src/themask/export.py` has no gate for parts the leak check cannot read.
- **Behaviour:** a picture reachable from `w:background` (a letterhead), a picture bullet
  (`numbering.xml`), the theme (`theme1.xml` `a:blipFill`), a VML shape fill (`v:fill r:id`) or an
  orphan relationship stays in the masked copy with its relationships; the export passes. Pixels
  often ARE the marked value (a logo is the company name, a signature is personal data).
- **Reproduction** `scripts/engine_batch2.py`, section A5 (real engine, full export; the PNG bytes
  are opaque):
  ```
  export blocked: False | leak hits: []
  media parts left in the masked copy: ['word/media/background.png', 'word/media/bullet.png', 'word/media/fill.png', 'word/media/orphan.png', 'word/media/themeimage.png']
  image relationships left in document.xml.rels: 3
  w:background kept: True | v:fill r:id kept: True | theme name reset: True
  numbering.xml still has numPicBullet: True
  ```
  (A header picture in the same file was replaced by the note, as today.)
- **Fix (R101, precise):**
  1. Cleaner, new step after the text parts, before `_sweep`: for every XML part (not only text parts)
     neutralise what references media, so that nothing dangles: remove `w:background` whole
     (document.xml); remove every `w:numPicBullet` and every `w:lvlPicBulletId` (numbering.xml);
     in the theme replace each `a:blipFill` by `<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>`
     (keeps the three children `a:fillStyleLst`/`a:bgFillStyleLst` must have); delete the `r:id` of
     every `v:fill` (a VML fill without `r:id` is a plain fill) and remove `v:imagedata` shapes
     anywhere a text part did not already handle them; remove `a:blip` fills in `wps:spPr`/`a:spPr`
     of kept shapes (`a:blipFill` → `a:noFill`, as `_strip_drawing_picture` does); treat
     `am3d:model3d` like a picture (note + removal). Count each in `CleanReport.images`.
  2. Then remove every part under `word/media/` and every part whose content type (Override or
     Default) starts with `image/`, `audio/`, `video/` or `model/`, with `pkg.remove_part` (which drops
     their relationships and Overrides), whatever still points at them.
  3. Export gate (`export._checked` or a new `_media_left(path)` called beside `scan_package`): open the
     saved output and fail closed when any part of those names/content types remains or any
     relationship whose Type ends in `/image`, `/audio`, `/video`, `/media` or `/model` remains; report
     it as a `LeakHit(part=<name>, placeholder="(picture)", context="a picture or media file the cleaner could not remove is still in the file")`
     so the dialog shows it in the blocked list. Update the cleaner's docstring ("Not touched").
- **Regression tests (`tests/docx/test_cleaner.py`, `tests/test_export.py`):** the file of the
  reproduction (SCRATCH/out/a5.docx shape: background, picture bullet, theme image, VML fill, orphan
  rel, header picture) cleans to a package with no `word/media/*`, no image relationship, no
  `w:background`, no `numPicBullet`/`lvlPicBulletId`, a theme without `a:blip`, and python-docx opens it;
  a package in which a media part is planted after cleaning makes `export_case` return `blocked=True`
  with the "(picture)" hit; the corpus's three image files still export unblocked.

### F-3 [Critical] Namespace declarations and non-standard element/attribute names are never read by the leak check and never stripped (pointer A6, ruling R102)

- **Where:** `src/themask/leakcheck.py` `_Reader._element` (reads `element.text`, attributes, tails;
  never `element.nsmap`, never a tag's local name); `src/themask/docx/cleaner.py` strips nothing.
- **Reproduction** `scripts/a6_namespaces.py` (key: COMPANY "Northwind Trading B.V." with variants;
  `xmlns:ns0="urn:northwind-trading-bv:contract-schema"` declared on `w:document`, an element
  `<nw:NorthwindTradingBV/>` inside a run; masked the way an export masks):
  ```
  masked document.xml holds 'northwind-trading-bv' (declaration): True | 'NorthwindTradingBV' (element name): True | text masked: True
  scan_package hits: [] <- nothing: the declaration and the element name are never read
  ```
  By the brief's definition this is a marked value in the masked copy with the gate open. The
  shape (a document-assembly schema named after the party) is uncommon but real.
- **Fix (R102, precise):**
  1. Leak check: in `_Reader._element`, for each element compute the declarations it makes itself
     (`{p: u for p, u in element.nsmap.items() if parent is None or parent.nsmap.get(p) != u}`) and
     add a `_Block(uri, label=f"xmlns:{prefix or ''}", no_digits=True)` for each URI and one for each
     non-empty prefix; `_is_format_vocabulary`'s `_FORMAT_ADDRESSES` test already exempts the standard
     addresses, extend that tuple with `http://purl.org/dc/`, `urn:schemas-microsoft-com`,
     `http://schemas.microsoft.com/` (already covered by "http://schemas.") so only exotic URIs are
     searched. For elements and attributes whose namespace is NOT one of the standard ones (the
     `NS` values, `TYPES_NS`, `RELS_NS`, purl.org/dc, w3.org, urn:schemas-microsoft-com, the
     markup-compatibility and office namespaces), add a block for the local name with the name rules
     (R63). The joined `_block_hits` search needs no change.
  2. Cleaner, last step before `_sweep`, for every part it parsed: `etree.cleanup_namespaces(root,
     keep_ns_prefixes=KEEP)` where `KEEP` = every prefix named in any `mc:Ignorable`,
     `mc:MustUnderstand` or `mc:ProcessContent` attribute anywhere in that part (space-separated
     lists) plus every prefix of `NS`. **Trap:** python-docx and Word write
     `mc:Ignorable="w14 wp14"` on `w:document` (the corpus files do); a cleanup that drops an unused
     `xmlns:w14` makes Word refuse the file as corrupt. The leak check still scans whatever is kept.
- **Regression tests (`tests/test_leakcheck.py`, `tests/docx/test_cleaner.py`):** the reproduction's
  file yields one hit on `xmlns:ns0=` and one on the element name when the declaration is used;
  an unused declaration whose URI holds a value is gone after `clean`; a part with
  `mc:Ignorable="w14 wp14"` keeps `xmlns:w14` and `xmlns:wp14` after `clean` and python-docx opens
  the result; the 28 corpus files still export unblocked.

### F-4 [Important, new] Contact data that stands only in a hyperlink target, a simple field's instruction attribute or a permission mark never reaches the review and is never checked, so it ships in the masked copy

- **Where:** `src/themask/docx/reader.py` (the text map reads `w:t` and `w:instrText` only: a
  `w:hyperlink`'s target lives in the .rels, a `w:fldSimple`'s instruction in `@w:instr`, a
  `w:permStart`'s editor in `@w:ed`); `src/themask/docx/cleaner.py` keeps all three;
  `src/themask/docx/masker.py` `_unwrap_hyperlinks`/`_mask_simple_fields` act only on MARKED values.
- **Behaviour:** an e-mail address behind "click here", a `HYPERLINK "mailto:…"` simple field, and the
  e-mail in `w:permStart w:ed=…` (Word's "Restrict Editing → Exceptions") are personal data of the
  EMAIL class, visible to anything that reads the file's links (Word, Copilot), not shown on any
  screen, not catchable by the gate because nobody could mark them. When the target's domain happens
  to hold a marked company name the export is BLOCKED instead (fail closed, confusing: "take the value
  out of the file in Word").
- **Reproduction** `scripts/b_links_attrs.py` (no engine needed: the detection runs on
  `extract_text` and nothing else) and `scripts/engine_batch3.py` (real analysis, full export):
  ```
  review text after clean: 'Notices to the Supplier: click here or this address.\nThe Buyer may edit this clause.\nSigned by John Carter for the Buyer.'
    'pieter.de.vries' in the review text: False  /  'legal.desk' ...: False  /  'jane.doe' ...: False
  groups: [PERSON_1]/PERSON 'John Carter' ...; [COMPANY_1]/COMPANY 'Northwind Trading B.V.' ...
  export blocked: False | allowed: [] | unmarked: []
  masked file holds 'pieter.de.vries@pdv-advocaten.example': True
  masked file holds 'legal.desk@lexpoint.example': True
  masked file holds 'jane.doe@brightwater-foods.example': True
  masked file holds 'John Carter': False
  ```
  With `mailto:…@northwind.example` (the marked company's domain) the same export is blocked
  (`engine_batch2.py`: "export blocked: True").
- **Fix (precise; "a leak is worse than hiding too much", the AI reads text, not links):** a new
  cleaner step `_remove_external_links(root)` after `_remove_hidden_runs`, counted in a new
  `CleanReport.links_removed`:
  1. every `w:hyperlink` with an `r:id` (external target) → `_unwrap` (its runs stay; the anchor-only
     internal links stay as they are); `_release` then drops the relationship as nothing refers to it;
  2. `HYPERLINK`, `INCLUDEPICTURE`, `INCLUDETEXT`, `INCLUDE`, `IMPORT` and `LINK` join
     `_FLATTENED_FIELDS` (the result text stays, the instruction with its address or path goes; the
     masker's instruction passes then have nothing external left to rewrite);
  3. `a:hlinkClick`, `a:hlinkHover`, `a:hlinkMouseOver` elements removed wherever they stand; VML
     `href`/`o:hrlabel`/`o:href` attributes deleted;
  4. `w:permStart` and `w:permEnd` removed (block-level and inline);
  5. every `w:fldData` removed (base64 field data; Word regenerates it);
  6. belt and braces, last: delete every `w:author`, `w:ed` and `w:edGrp` attribute left in any
     text part after the revisions were resolved (co-authoring marks and anything Word adds next year).
  Keep R23/R26/R27/R82 as they are: they still cover internal anchors and bookmark names.
  Add one sentence to README's export paragraph: "Links to web pages and e-mail addresses are
  removed from the masked copy; the link text stays."
- **Regression tests (`tests/docx/test_cleaner.py`, `tests/test_export.py`):** the reproduction's file
  cleans to a package whose bytes hold none of the three addresses, whose rels have no hyperlink
  relationship, whose text still reads "click here or this address"; an internal `w:anchor` link is
  kept; a `HYPERLINK` complex field becomes its result text; `w:permStart` gone; the corpus's three
  hyperlink files (services-01, nda-01, dpa-01) export unblocked and their masked copies hold no
  `mailto:`.

### F-5 [Important, new] The "[image removed]" note is glued to the text before it, so the model reads "Acme Supplies Ltd[image" as a PERSON: a garbage key value, a second placeholder for the same party, and a broken note in the masked copy

- **Where:** `src/themask/docx/cleaner.py` `_replace_with_note`/`_note` (a `w:t` holding exactly
  `[image removed]` put where the picture was, with no space before or after it);
  `src/themask/detect/pipeline.py` lets a finding run across the note.
- **Behaviour (realistic: a logo beside the company name in a header paragraph):** the review text
  reads `Acme Supplies Ltd[image removed]`; the engine finds PERSON "Acme Supplies Ltd[image" (0.85,
  longer than the rule's COMPANY, so it wins the span); the key stores
  `[PERSON_2] = "Acme Supplies Ltd[image"` with variants `Ltd[image`, `A. Ltd[image`; the masked
  header reads `[PERSON_2] removed]`; the AI sees two placeholders for one party and a dangling
  "removed]"; a restore writes "Acme Supplies Ltd[image removed]" back (right party, garbage form).
- **Reproduction** `scripts/engine_batch3.py`, last section (real engine, full export):
  ```
  review text: '...\nAcme Supplies Ltd[image removed]'
  groups: [COMPANY_1]/COMPANY 'Acme Supplies Ltd' ...; ...; [PERSON_2]/PERSON 'Acme Supplies Ltd[image' variants=['A. Ltd[image', 'A. Supplies Ltd[image', 'Acme Supplies Ltd[image', 'Ltd[image'] places=['Acme Supplies Ltd[image']
  blocked: False | key: [('[PERSON_1]', 'John Carter'), ('[PERSON_2]', 'Acme Supplies Ltd[image'), ('[COMPANY_1]', 'Acme Supplies Ltd'), ...]
  masked header text: ['[PERSON_2]', ' removed]']
  ```
- **Fix (two guards, both cheap):**
  1. Cleaner `_note`: write the note in a run of its own, and put a space `w:t` (xml:space="preserve")
     before it when the run content before it in the paragraph ends in anything but whitespace, and
     after it when what follows starts with anything but whitespace. The note's wording stays exactly
     `[image removed]` / `[embedded object removed]` / `[equation removed]` /
     `[embedded content removed]` (global constraint); only spacing changes. Apply to all four notes.
  2. Pipeline `_cleaned` (or `analyze`): the exact occurrences of the four note strings in the text are
     boundaries like line breaks: a finding is cut at them and never contains one. (The sweep then
     still finds "Acme Supplies Ltd" in the header as a COMPANY_1 variant.)
- **Regression tests (`tests/docx/test_cleaner.py`, `tests/detect/test_pipeline.py`):** a header
  paragraph "Acme Supplies Ltd" + inline picture cleans to the text "Acme Supplies Ltd [image removed]";
  the analysis of "Acme Supplies Ltd[image removed] sells" yields one COMPANY group whose canonical
  has no bracket; the corpus image files (supply-05, nda-03, dpa-01) still pass the pass marks.

### F-6 [Important, new; answers F1] Merging two groups that both carry a stored placeholder is accepted, and the added file then restores one party as the other, silently

- **Where:** `src/themask/review.py` `merge` (no check of `self.reserved`; `keep` = the lowest number;
  the canonical becomes the fullest form); `src/themask/export.py` `_merged` (keeps the stored values,
  as R86 says) — together they map two stored values onto one placeholder in the added file.
- **Reproduction** `scripts/f1_reserved_merge.py` (stored key [COMPANY_1] Acme Supplies Ltd,
  [COMPANY_3] Zeta Holdings B.V.; the annex's review has both as seeded groups; the owner merges them):
  ```
  merge accepted; surviving group: [COMPANY_1] canonical now 'Zeta Holdings B.V.'
  mask plan of the annex: [(0, 17, '[COMPANY_1]'), (22, 40, '[COMPANY_1]')]
  merged key saved with the case: [('[COMPANY_1]', 'Acme Supplies Ltd'), ('[COMPANY_3]', 'Zeta Holdings B.V.')]
  restored annex text: 'Acme Supplies Ltd and Acme Supplies Ltd sign this annex.' | report: 2 placeholders restored, 0 need your check.
  ```
  By the letter this is the Critical definition (a wrong value, silently); it needs the owner's own
  merge of two stored parties, so I rate it Important. The plausible same-party case (a stored
  "Acme" short-form group merged into "Acme Supplies Ltd") restores the full form, which the design
  accepts, so refusing costs little.
- **Fix / ruling I recommend (F1):** `ReviewState.merge` raises
  `ValueError("[COMPANY_1] and [COMPANY_3] are both in the case's key and cannot be merged; leave them as two values.")`
  when more than one of the groups has a placeholder in `self.reserved`. When exactly one is reserved
  it survives whatever its number, and keeps its canonical form (the stored value the key will keep
  anyway, so the review shows what restore will write; the other groups' forms join its variants).
  `split` of a reserved group never changes its canonical either. R86 stands unchanged.
- **Regression tests (`tests/test_review.py`):** the reproduction's merge raises with that message;
  merging an unreserved group into a reserved one keeps the reserved placeholder and canonical;
  splitting a reserved group leaves its canonical as it was.

### F-7 [Important] A count written as a range after a reference number goes visible (pointer A10, ruling R105 G1), plus the cheap G2 companion

- **Where:** `src/themask/detect/patterns.py` `_SPACED_DIGITS` (only `\d<space>\d`), used by
  `_is_a_reference`.
- **Reproduction** `scripts/a10_quantity_range.py` (QuantityRecognizer alone) and
  `scripts/engine_batch3.py` (full pipeline):
  ```
  'Schedule 3 - 500 pallets per week'                            -> []
  'Minimum volumes: Clause 7 – 250 tonnes per quarter.'          -> []
  'Schedule 3 500 pallets'                                       -> [('3 500 pallets', 0.8)]
  'Section 2 - 10,000 units minimum'                             -> []
  'Article 3 to 1,000 pieces'                                    -> []
  full pipeline: 'Schedule 3 - 500 pallets per week.' -> nothing hidden
  ```
- **Fix:** `_SPACED_DIGITS = re.compile(r"\d(?:" + _SPACE + "|" + _TO + r")\d")` (the Task 24
  reviewer verified it on a scratch copy: 356 pattern tests green). G2 if the implementer finds it a
  one-liner: in `_QUANTITY_REFERENCE` require the capital for `Schedule|Section|Article|Exhibit`
  used as words (keep the abbreviations with their full stop in any case), so "shall schedule 500
  pallets" and "per article 12 pieces" are counts again (today: nothing hidden, confirmed). G4
  ("Price - Jones Logistics Ltd" → "Price" visible, confirmed) stays parked: owner-visible.
- **Regression tests (`tests/detect/test_patterns.py`):** the two sentences of R105 hidden as
  QUANTITY; "Schedule 3 Pallets", "Annex 2 Units of Measure", "the Art. 30 records" still visible;
  with G2: "The Supplier shall schedule 500 pallets for collection each week." hides "500 pallets".

### F-8 [Important, robustness] `DocxPackage.open` has no limit on the number of entries or the expanded size (pointer A8, ruling R104)

- **Where:** `src/themask/docx/package.py` `open` (`archive.read(i)` for every entry).
- **Reproduction** `scripts/a8_zip_limits.py`:
  ```
  file size on disk: 306945 bytes; declared expanded size: 314574354
  DocxPackage.open: no refusal; took 3.1s; peak RSS grew by 299 MB
  30,000 entries: opened, 30003 parts, 0.4s (no entry-count limit)
  ```
  A 1 GB declared entry would take the app down with a MemoryError (the worker thread catches it
  and says "Something went wrong"; a 4 GB one is killed by the OS).
- **Fix (R104):** before reading, `infos = archive.infolist()`; refuse with `NOT_A_DOCX_MESSAGE`
  when `len(infos) > 10_000`, any `info.file_size > 256 MiB`, or `sum(file_size) > 1 GiB`; read each
  entry through `archive.open(info)` with a hard cap of `file_size` bytes
  (`ZipExtFile` already stops at the declared size and raises `BadZipFile` on the CRC when the
  header lied, which `_UNREADABLE_ZIP` turns into the same refusal). Same check in `_root_tag`'s
  caller is not needed (it reads one entry already in memory).
- **Regression tests (`tests/docx/test_package.py`):** a zip with one entry declared at 300 MB is
  refused without reading it (assert peak RSS or simply that `open` raises in well under a second);
  10,001 entries refused; 9,999 small entries accepted; the corpus files open.

### F-9 [Minor by impact, MUST-FIX by ruling] The number folds: A1 (a decimal part ends a number), A2 (the byte-scan threshold), A3 (a shared fold is attributed to one entry only)

- **Where:** `src/themask/leakcheck.py` `_located` (extends `end` over the folded-away ".00" and
  then asks `_touched` at the extended end, where " 100" is a thousands group), `_Needles.for_bytes`
  (measures the folded key `eur10`, 5 chars, instead of `normalize("EUR 10.00")` = `eur1000`, 7),
  `_Needles.of` (`setdefault`: the first entry keeps a shared fold).
- **Reproduction** `scripts/a1_a2_a3_leak_folds.py`:
  ```
  'Fee EUR 1,250.00 100 units'      -> 0 hit(s)        (A1)
  'Fee EUR 1,250 100 units'         -> 0 hit(s)        (the plain-space sibling, R70's accepted gap)
  'Fee EUR 1,250.00 and 100 units'  -> 1 hit(s)
  'Fee: EUR 1,250.00\t100 units'    -> 1 hit(s)
  numbers needles: {'eur10': '[AMOUNT_1]', '10': '[AMOUNT_1]'} | for_bytes: {}   (A2)
  bytes part holding 'EUR 10.00' -> 0 hit(s)   /   control: bytes part holding 'EUR 1,250.00' -> 1 hit(s)
  numbers needles (fold -> placeholder): {'eur1250': '[AMOUNT_1]', '1250': '[AMOUNT_1]'}   (A3)
  text 'EUR 1,250' (entry 2's value) left visible -> [('[AMOUNT_1]', ...)]
  cross-type: ID '12345678' and PHONE '1234 5678' -> [('[ID_1]', ...)]
  ```
  Impact today: the twin masks every finding the sweep found (and the sweep's `flexible_pattern`
  finds "EUR 1,250.00 100 units"), so these only weaken the proof at places the sweep could not take.
- **Fix:** (A1) in `_located` keep the unextended end; call `_touched(text, start, end, key,
  right_is_open=(end_extended != end_unextended) or _CENTS.match(text, end_unextended))` and skip the
  right-hand digit test when the match took in a decimal point or cents follow; additionally, when
  the matched text itself contains a `,` or `.` group separator, a PLAIN space is not a separator on
  either side (a number written with commas or dots does not go on with a space-grouped thousand:
  this closes "EUR 1,250 100 units" and the parked "No. 100 1,250.00" too). (A2) `_Needles.of` keeps
  `len(normalize(form))` per key and `for_bytes` tests that length (≥ 6) and "not all digits" on the
  original form (R14 b). (A3) `_Needles` maps each fold to a tuple of placeholders and `find` yields one
  `_Match` per placeholder; `_located` keeps all placeholders of a place; `_counted` then reports one
  hit per placeholder (the dialog's "left visible on purpose" and "blocked" lists name every entry
  that folds to the place). After F-1 the amount pair of the pointer becomes one group, so the
  remaining shapes are cross-type (ID/PHONE/IBAN digits).
- **Regression tests (`tests/test_leakcheck.py`):** the six A1 lines above with their expected
  counts (both "100 units" shapes hit; "1 250" not in "1 250 000"; "125,000" in "125,000.00";
  "1,250" in "In 2025 1,250 units"); "EUR 10.00" planted in a binary part is a hit; two entries
  sharing a fold each get a hit for the same place.

### F-10 [Minor, cheap; answers F4] `w14:conflictIns` / `w14:conflictDel` are neither resolved nor counted, and keep their author in the masked copy

- **Reproduction** `scripts/b_revisions.py` section B2:
  ```
  has_revisions: False
  accepted view text: 'Price: EUR 9,999' | rejected: 'Price: EUR 9,999EUR 1,111'
  after accept_all+clean: 'conflictIns' in xml: True | 'Jane Doe' (author) in xml: True | 'EUR 9,999' in xml: True | 'EUR 1,111' in xml: False
  after reject_all+clean: 'EUR 9,999' in xml: True | 'EUR 1,111' in xml: True | author: True
  ```
  The text is in the review (hidden if marked); the author's name is not (spec 8.4: revision authors
  and dates are removed). Rare shape (a file saved mid co-authoring conflict).
- **Fix:** in `revisions.py` add `w14:conflictIns` to the "inserted" set (`_INS` behaviour) and
  `w14:conflictDel` to the "deleted" set (`_DEL` behaviour) in `_TRACKED`/`_ACCEPT`/`_REJECT`, and in
  `reader.py` to `_INSERTED`/`_DELETED` and `_REVISIONS`; F-4's attribute sweep catches the rest.
- **Test:** `tests/docx/test_revisions.py`: the reproduction's paragraph accepts to "Price: EUR 9,999",
  rejects to "Price: EUR 1,111", `has_revisions` is True before and False after.

### F-11 [Minor, cheap] A misplaced `*Change` record makes `reject_all` empty its container

- **Reproduction** `scripts/b_revisions.py` section B1: `w:sectPrChange` directly in `w:body` →
  `text after reject_all: ''` (accept_all is fine). Word never writes it; robustness only.
- **Fix:** in `_restore`, act only when `current.tag` is the record's owner (`rPrChange`→`rPr`,
  `pPrChange`→`pPr`, `sectPrChange`→`sectPr`, `tblPrChange`→`tblPr`, `tblPrExChange`→`tblPrEx`,
  `trPrChange`→`trPr`, `tcPrChange`→`tcPr`); otherwise just remove the record.
- **Test:** the reproduction keeps both paragraphs after `reject_all`.

### F-12 [Minor, cheap; owner-visible] `hide_text` / `add_always_hide` of text inside a switched-off occurrence is a silent no-op

- **Reproduction** `scripts/b_review_noop.py`:
  ```
  hide_text returned group: [COMPANY_1] | disabled after: {1} | plan places: [(0, 17), (49, 53)] <- the unticked place stays visible, no error
  after never-hide 'Acme': disabled {2} ...; after always-hide 'Acme': disabled {2} plan places: [(0, 17), (25, 42)] <- 'Acme' at 49-53 still visible
  ```
- **Fix:** in `ReviewState._hide`, after the group is found/made, discard from `group.disabled` every
  index whose finding's text normalises to the value (and switch the group on, as today).
- **Test:** `tests/test_review.py`: both sequences above end with the place in the plan.

### F-13 [Minor, cheap] The R84 twin blocks an export after the owner split occurrences off and switched the new group off (fail closed, confusing)

- **Reproduction** `scripts/twin_split_off.py`: key [COMPANY_1] with variant "Acme"; two "Acme" places
  split into [COMPANY_2] and switched off → `twin text: '[COMPANY_1] sells. [COMPANY_1] buys. Acme delivers. Acme ships.'`,
  `leftovers the gate would see in the twin: [('[COMPANY_1]', ...), ...]` → the export is blocked
  although the owner chose to show those places (the per-occurrence untick route works).
- **Fix:** `export._whole_plan` replaces the findings of EVERY group, keyed or not (R84's wording:
  "the places the owner switched off too"); the leak check still searches only key values, so the
  twin can hide no true leftover.
- **Test:** `tests/test_export.py`: the reproduction's review exports unblocked with the two places
  listed under `allowed_hits`.

### F-14 [Minor, cheap] `_merged` adds the review's canonical and variants to a stored entry without `_key_variants`' filters (a bare surname enters the key: false block, pointer Task 15)

- By reading (`export._merged`: `forms = {*entry.variants, update.value, *update.variants}`), not
  reproduced end to end. **Fix:** filter `forms` with `is_searchable` and, for PERSON, drop the bare
  surname forms of `entry.value` (reuse `review._key_variants` by making it accept a type, canonical
  and forms). **Test:** adding a file whose review has "Smith" among the person's forms leaves the
  merged entry without "Smith".

### F-15 [Minor, cheap; answers F2] A key holding the same placeholder twice is accepted and the last entry wins silently

- **Reproduction** `scripts/f2_duplicate_placeholder.py`:
  `from_json accepted duplicate placeholders: ['[PERSON_1]', '[PERSON_1]']` /
  `restore_text('[PERSON_1] signs') -> Jane Doe signs (last entry wins, silently)`.
  The pipeline cannot produce it (one entry per group, numbers unique by construction, `_merged`
  keyed by placeholder), so this is validation of what is read from disk.
- **Fix:** `Case.from_json` raises "Not a stored case." when two entries share a placeholder (the
  store then lists the file as unreadable instead of restoring with it). **Test:** `tests/test_model.py`.

### F-16 [Minor; answers F3] `LeakBlockedError` is unused

- Remove it from `errors.py` (and the test that imports it, if any). A reserved exception that
  nothing raises misleads the next reader; `ExportResult.blocked` is the contract.

### F-17 [Minor, robustness; answers F5] Garbage collection in worker threads vs. PySide6 teardown

- See section 2 F5 for the reasoning. **Fix:** in `ui/app.main` after the window is built:
  `gc.disable()` and a `QTimer` on the GUI thread that calls `gc.collect(generation)` every 2 s
  (cycling generations 0, 0, 1, 0, 0, 2 as Spyder's `GarbageCollector` does), stopped at exit; the
  tests' `collect_in_the_main_thread_only` fixture stays. **Test:** `tests/test_main.py`: after
  `main()` has built the window, `gc.isenabled()` is False and the timer is active; a test that
  allocates cyclic garbage sees it collected after the timer fires.

### F-18 [Minor] `OWNER_NAME = "Alican Yazdic"` in `src/themask/about.py` (pointer A9, owner's instruction)

- Confirmed still the placeholder at HEAD. `tests/test_about.py` (`OWNER_NAME in about_label.text()`)
  must still pass.

### F-19 [Minor] Timing tests that flake under load (pointer C)

- Limits at HEAD: `tests/pdf/test_extractor.py::test_twenty_four_pages_are_read_quickly` < 10 s (and a
  5 s one above it); `tests/test_leakcheck.py::test_thirty_pages_are_scanned_in_under_two_seconds`
  < 2.0 s; `tests/ui/test_review_screen.py` 500-highlight test `loaded < 2.0 and switched < 2.0`;
  `tests/detect/test_contract_rules.py::test_rules_are_quick_on_a_long_contract` < 1.0 s and
  `…texts_made_to_be_slow` < 2.0 s; `tests/detect/test_patterns.py::test_long_runs_of_number_words_are_quick`
  < 1.0 s; `tests/docx/test_reader.py::test_thirty_pages_are_read_quickly` < 2 s.
- **Fix:** multiply each limit by 3 (a quadratic blow-up is orders of magnitude, so 3× keeps every
  test meaningful); rename the leak-check test and its docstring (24 pages, "six seconds"); leave the
  30 s corpus test and the 60 s pass mark (spec §9) as they are. Never delete.

### F-20 [Minor] README (pointer A11) — nothing to fix

- No wording at HEAD says export or restore are future work (grep for future/not yet/later/planned:
  only "Windows follows in a later phase"). Add the one sentence of F-4 when that lands.

### 1.5 Verified as "no longer reproduces" or "nothing to do"

- **A7 (R103, restore screen):** verified by reading `restore_screen.py` (`_order_cases`, `_is_a_guess`,
  `_another_fits_better`, `_case_title`, `_preview`) and `matcher.suggest_cases`/`case_in_file_name`:
  file-name code first, no preselection on a tie (combo at -1, "Several cases fit this file — choose
  one.", Restore disabled), titles with file names and dates, up to five "placeholder → value" lines,
  the hand pick kept with the "fits better" notice (R106). The 99 restore-screen tests run green in the
  suite. Accepted reading noted: with no case fitting at all the newest is preselected.
- **A11 README:** fine (above).
- **MaskPlan (pointer B, Task 2):** `MaskPlan.__post_init__` now rejects `start < 0` and
  `end < start` and sorts by `(start, end)` — no longer applies.
- **Zip archive comment (pointer B, Task 14):** `scripts/b_zip_comment.py`: `source comment:
  b'Acme Supplies Ltd deal file' | saved comment: b''` — `DocxPackage.save` writes fresh entries, so
  neither the comment nor local-header names reach a masked copy. No longer applies.
- **`int()` on long digit runs (pointer B, Task 6):** every `int(` in src is on ≤ 4-digit captures,
  an IBAN capped at 34 characters, or guarded (`patterns.py:747`); placeholders cap at 9 digits.

### 1.6 Unverified (by reading only; no reproduction run)

- `a:hlinkClick` on a kept text box keeps its target and tooltip until F-4; the tooltip attribute is
  scanned, so a marked value there blocks (fail closed).
- `_blanked` is O(words × edits) per instruction (2.4 s on a 61k-character instruction): no realistic
  file has such an instruction.
- The byte scan reads UTF-8 and UTF-16 only; a latin-1 "Café Noël" in a binary part is missed; after
  F-2 the binary parts left are embedded fonts and unknown parts.
- The three untested cleaner branches of Task 12 (VML textbox guard, replace-whole fallback, fldData
  drop) — F-4 removes `w:fldData` anyway.

---

## 2. Triage of the pointer sections B, C, D, E and the answers to F

Legend: **fix now** (in the wave, with the F-item that covers it) / **park** (the cost if left) /
**no longer applies**.

### B. Parked items with a leak, restore or crash angle

| Pointer item | Verdict |
|---|---|
| Task 11: `_restore` assumes a *Change record sits in its owner; misplaced record empties the body on `reject_all` | **fix now** (F-11; reproduced; cheap guard). Cost if left: a damaged file silently loses its "before" text in a redline. |
| Task 11: `w14:conflictIns`/`conflictDel` neither resolved nor counted | **fix now** (F-10; reproduced: author attribute survives, has_revisions False). Cost if left: a colleague's name in a masked copy of a file saved mid-conflict. |
| Task 12: emptied-link unwrap stops at the hidden run's parent (`w:sdt` between link and run) | **fix now, subsumed** by F-4 (every external `w:hyperlink` is unwrapped, so no `mailto` target survives, whatever stood inside). |
| Task 12: unbalanced `fldChar`s after a partially hidden field | **park** (Word repairs or shows the field code; no value involved; not reproduced). |
| Task 12: linked inline picture keeps its URL on the note when wrapped in `w:hyperlink`; `a:hlinkClick`; VML `href`/`o:hrlabel` | **fix now, subsumed** by F-4. |
| Task 12: VML `v:fill r:id` picture fills, `am3d:model3d`, media via orphan/duplicate relationships | **fix now, subsumed** by F-2 (reproduced: fill.png and orphan.png survive). |
| Task 12: base64 `w:fldData`; external `saveThroughXslt` path | **fix now (fldData, F-4 step 5)**; `saveThroughXslt` → **park** (settings.xml; the leak check scans the path attribute for marked values; an unmarked path is a server name at worst). |
| Task 13: unquoted multi-word field values with a field-name word; backslash-led UNC paths; `_blanked` O(words × edits) | **park**: by reading, R31 holds (the exemption is keyed to the single word, a longer value still hits); the UNC path is caught only when marked — after F-4 the `INCLUDE*`/`LINK` fields are flattened so the path is gone; 2.4 s only on a 61k-character instruction. |
| Task 13: no guard against a plan replacement inside an existing placeholder | **no longer applies**: by reading, every producer of a finding excludes exact placeholders (`analyze` filters `_detected + _listed`; `_seed_matches`, `sweep`, `_shared_form_groups`, `ReviewState._hide` all take `existing_placeholders` as taken spans). |
| Task 14: byte scan UTF-8/UTF-16 only; compressed streams | **park** (after F-2 the binary parts left are embedded fonts and unknown parts; a latin-1 string in one is an exotic shape). |
| Task 14: zip archive comment | **no longer applies** (reproduced: `save` writes fresh entries; the comment is gone). |
| Task 14: namespace declaration URIs; glossary exemption open-ended | **fix now** (F-3). The glossary is removed by the cleaner; the open-ended `word/glossary/.+` exemption in `_STANDARD_PART` only exempts part NAMES of a folder that is gone — park. |
| Task 14: rId/GUID collisions with short digit-only needles; R31 over-exemption after a format switch; blocks over 8,192 chars lose the exemption; instruction edges glue; damaged theme part "not a .docx"; one link counted twice; hyphenated words fold onto a glued short name; R69 "shall" for "S. Hall"; "10.00%" checkable; cents rule errs to block | **park**, all on the fail-closed side (false blocks or odd contexts), none a leak. Cost: an occasional blocked export the owner must resolve in Word. |
| Task 14: R70 gap "No. 100 1,250.00" | **fix now** with F-9 (the comma/dot-grouped rule closes it). |
| Task 15: R86 adds the review's canonical to a stored entry's variants without `_key_variants`' filters | **fix now** (F-14, cheap). |
| Task 15: NB1 hand-built overlapping groups | **park**: `MaskPlan` raises on overlaps; the pipeline and `ReviewState` never produce them (checked by reading: `hide_text` takes every finding's span as taken). |
| Task 15: a visible e-mail containing a URL's domain still blocks; `leak_hits`/`allowed_hits` share a list; empty `out_dir` left behind on failure | **park** (fail closed / cosmetic). After F-4 the link-target cross-talk disappears. |
| Task 15: the R86 question | **answered**, F1 below. |
| Task 18: same placeholder twice in a key | **fix now** (F-15, validation only). |
| Task 18: banner paragraphs with extra children emptied not deleted; fallback copy differing from its Choice restored silently; a deleted banner word becomes an invented tracked change; '>' line / numbered-item banner stay; stray ']' | **park** (cosmetic in the restored file, which is the owner's; no wrong value). |
| Task 18: OSError not in the docstring; error-path tests missing; `_comment_parts` public | docstring/tests → **park**; `comment_parts` IS public and imported by `docx_restore.py` (verified). |
| Task 8: sweep shapes ("Smith in London", heading word or month tagged PERSON, "Dear Smith", "Smith/Jones"); duplicated vocabularies; grouping's own sweep | **park** (owner-visible in the review; the pass marks hold). |
| Task 9: `hide_text` cannot reach a switched-off occurrence; always-hide after a partial never-hide is a no-op | **fix now** (F-12; reproduced). |
| Task 9: merging a never-hidden group into an enabled one takes the term back; `add_*` mutate before save; `review._canonical` vs `grouping._canonical` | **park** (owner-visible; after F-13 the twin masks such places; an unsaved entry survives in memory until the next save). |
| Tasks 22+23: the PySide6 teardown race | **fix now** (F-17); answer F5 below. |
| Task 6: `int()` on ≥ 4,301 digits | **no longer applies** (every `int(` is guarded or capped; verified by grep). |
| Task 2: `MaskPlan` sort/validation | **no longer applies** (implemented in `model.py`). |
| Task 1: `LeakBlockedError` | **fix now** (F-16, remove). |
| Task 19: guard covers Python sockets only; module-level state; `_write_to` trusts the handler registry; `decision_process`; UI `restore_logging` not restoring pdfminer; Windows `sendmsg` | **park**. Coverage verified by reading: `connect/connect_ex/sendto/sendmsg/bind/listen` on the class, `create_connection/create_server/getaddrinfo/gethostbyname*/gethostbyaddr/getnameinfo` replaced, tldextract offline; `urllib`, `http.client`, `requests`, `asyncio` all go through those. Native Qt network is not imported (AST test). The Wi-Fi-off smoke test stays the owner's proof. |
| Task 25: `check_bundle_lock` ValueError; icon not validated; `iconutil` stderr; `platforminputcontexts/`; `entry_points.txt`; Designer/SQL/QML payload | **park** to the Windows phase / SBOM (build tooling only; nothing the running app does). |

### C. Timing tests → **fix now** (F-19): limits ×3, `slow` not needed, nothing deleted.

### D. Deferred minors already tuned by Task 24 → **park**, all of them: the pass marks at HEAD are
913/913, 320/320, 0 never-hide hits, 28/28 round trip (the suite's `tests/test_passmarks.py` ran green
in my full run), and every listed shape is owner-visible in the review. G2 goes in with F-7 only if it
is a one-liner; G4 and the rest stay as owner-visible limits (section 3).

### E. Structure and test-quality minors → **park** to the Windows phase, no exceptions. Specifically:
the duplicated relationship plumbing (`cleaner._relationships`/`_target_path`/`_by_name` vs
`DocxPackage._relationships`/`_target_part`) agrees on `unquote` + casefold + `normpath` by reading, so
no behavioural difference to fix; module sizes (leakcheck 1,572, contract_rules 1,535, cleaner 1,060,
grouping 831, restore_screen 754, review_screen 710, main_window 617) are a split for later; the
vocabularies duplicated three ways and `_count` copied four times likewise. The docs items (BIC
check-digit claim, "thirty pages" names, "the way the leak check decides" docstrings) can ride along
with F-19's rename if the implementer is in those files, else park. Tasks 20+21's `closeEvent` wait
and the cursor-only scroll test: park.

### F. The five questions — my rulings

1. **R86 / merges that change a reserved placeholder's value.** Do not refuse merges in general;
   refuse merging TWO reserved groups (F-6: reproduced wrong restore), and when one reserved group
   is in a merge it survives (whatever its number) and keeps its canonical, so the review shows the
   value the key will keep. `split` never changes a reserved group's canonical. R86 stands. Reason:
   the stored value must not move under the earlier files (R86), and two stored parties can never
   be one placeholder in the new file without a silent wrong value; a stored short-form group merged
   into its full name only restores the full form, which the design accepts.
2. **Duplicate placeholder in a key.** Validate in `Case.from_json` (raise "Not a stored case.") —
   F-15. Not in `CaseStore.save`: nothing in the app can build such a case (one entry per group,
   unique numbers, `_merged` keyed by placeholder), so a duplicate only ever comes from a file on
   disk, and a file that cannot be trusted belongs in the unreadable list, not in a restore.
3. **`LeakBlockedError`.** Remove (F-16). The contract is `ExportResult.blocked`; an exception that
   nothing raises invites the next implementer to raise it and the dialog does not expect it.
4. **`w14:conflictIns`/`conflictDel`.** The revisions resolver treats them as `w:ins`/`w:del`
   (accept keeps the insertion and drops the deletion, reject the reverse) and `has_revisions`
   counts them (F-10); the cleaner's attribute sweep (F-4 step 6) removes any author left. Reason:
   the text inside is what the co-authoring session put in or took out; leaving the wrapper leaves
   an author name and a mark Word reads as a revision in the "accepted" copy.
5. **The PySide6 teardown race.** App-side mitigation in the wave (F-17), test-only workaround kept.
   Can the APP hit it? The window for it is a worker thread allocating (and so collecting) while the
   GUI thread tears Qt objects down. By reading `ui/*`: the three workers hold plain data and
   reference no widget; the window deletes a worker or the export dialog only after `wait()`; but
   during the 2–8 s engine load at startup the owner can open the Cases or Restore screen, whose
   `refresh` clears and rebuilds `QTableWidgetItem`/`QListWidgetItem`s while spaCy allocates
   heavily in the loader thread — item-sized teardown, which the Task 22 reviewer could not crash in
   24 tries (whole-window teardown crashed 5/6, and that happens only at exit after the workers are
   joined). So: unlikely, not impossible, and the cost is a segfault with nothing written (the gate
   writes only after the check; a restore runs on the GUI thread). The GUI-thread timer collector is
   the standard remedy (Spyder, pyqtgraph) and costs ~15 lines; take it.

---

## 3. What I would tell the owner about using v1 safely (limits no one-line change fixes)

1. **The MASK hides values, not the story.** Industry, places, unusual terms and clause structure can
   still identify the parties (design §10). Read the masked copy once before uploading it.
2. **Until the fix wave lands:** files with a letterhead picture in the page background, picture
   bullets or a themed template may keep those pictures (F-2); web and e-mail links whose text is not
   the address keep the address (F-4); a value written in two spellings of one number or currency
   symbol can come back as the first spelling (F-1). After the wave, links are removed from masked
   copies and pictures block the export.
3. **The leak check proves marked values are gone; it cannot find what nobody marked.** The review
   screen is the net: look at the "check" rows, at headers/footers (the pane shows them after the body)
   and at anything the model typed oddly ("John Carter - Managing" keeps "Managing" visible; a
   title-case heading like "Annex 2 Units of Measure" may be hidden as a flagged company; "shall
   schedule 500 pallets" is visible until F-7's companion; a one-word double name "Price - Jones" shows
   "Price").
4. **Restore writes the group's full form** ("Mr Smith" comes back as "John Smith"; a national phone
   number as the international form) — intended (design §10, Task 24 note).
5. **Restored files and copied text hold the real values.** The restored file is written next to the
   AI's file: if that folder syncs (iCloud Drive, OneDrive, a synced Downloads), the restored contract
   syncs too. Keep the AI's downloads in a local folder. Copied text is on the clipboard in clear.
6. **Copilot with a Microsoft 365 licence can read your OneDrive/SharePoint/Outlook originals**; the
   masked copy does not hide those (design §10).
7. **The always-hide list is stored in clear** (`~/Library/Application Support/The MASK/lists.json`,
   owner-readable only): put product and project code names there knowing it is a text file.
8. **Keys die with the Mac or the user account**, and expire after the retention (30 days by default,
   settable up to 365 in Settings; the purge runs at every start). Set a longer retention before a
   long-running matter; a deleted or expired case means the masked files can never be restored.
9. **A font or theme named after a party blocks the export** (R66): re-save the file from Word with a
   standard font. A damaged theme part is refused as "not a .docx" (fail closed).
10. **PDFs:** only selectable text is read; image-only pages are listed and left out; multi-column
    pages read line by line across columns; nothing hidden in the PDF (comments, form fields,
    attachments, properties) is carried over.
11. **Do not mask a masked copy again**: placeholders already there are respected and numbering
    continues, but a second round makes the key harder to follow.
12. **"No network" rests on two things:** the Python-level guard (the suite runs under it) and your
    own Wi-Fi-off smoke test of the built app with a network monitor (R89). Qt and macOS frameworks are
    outside the guard; nothing in the app calls them for the network, but the monitor is the proof.
13. **Merging two stored placeholders in an added file's review is refused after F-6**; until then,
    do not merge two groups that both came from the case's key.
14. **The built app is ad-hoc signed:** a rebuilt app is a new program to the Keychain and macOS may
    ask again (README). No CI exists; the local suite is the gate.

---

## 4. Commands run and their last lines

All from `/home/user/the-mask` at 3e7d6ea, read-only (`-p no:cacheprovider`; nothing written to the
repository). SCRATCH = `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/final-review-scratch`.

| Command | Last line |
|---|---|
| `uv run pytest -q -p no:cacheprovider` (full suite, once, in the background) | `3255 passed, 8 skipped in 349.30s (0:05:49)` / `EXIT 0` (log: SCRATCH/out/full-suite.log) |
| `uv run ruff check src tests tools packaging` | `All checks passed!` |
| `uv run mypy src` | `Success: no issues found in 52 source files` |
| `uv run python -m tools.make_corpus SCRATCH/corpus` | 65 files in 8.7 s |
| `uv run python SCRATCH/scripts/a1_a2_a3_leak_folds.py` | `cross-type: ID '12345678' and PHONE '1234 5678', text '1234 5678' -> [('[ID_1]', 'Call [ID_1] now.')]` |
| `uv run python SCRATCH/scripts/a8_zip_limits.py` | `30,000 entries: opened, 30003 parts, 0.4s (no entry-count limit)` |
| `uv run python SCRATCH/scripts/a10_quantity_range.py` | `_SPACED_DIGITS = \d[ \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}\N{THIN SPACE}\N{FIGURE SPACE}]\d` |
| `uv run python SCRATCH/scripts/b_revisions.py` | `after reject_all+clean: 'EUR 9,999' in xml: True \| 'EUR 1,111' in xml: True \| author: True` |
| `uv run python SCRATCH/scripts/b_zip_comment.py` | `saved entries: ['[Content_Types].xml', '_rels/.rels', 'word/document.xml']` |
| `uv run python SCRATCH/scripts/b_review_noop.py` | `after always-hide 'Acme': disabled {2} plan places: [(0, 17), (25, 42)] <- 'Acme' at 49-53 still visible` |
| `uv run python SCRATCH/scripts/f2_duplicate_placeholder.py` | `restore_text('[PERSON_1] signs') -> Jane Doe signs (last entry wins, silently)` |
| `uv run python SCRATCH/scripts/a6_namespaces.py` | `scan_package hits: [] <- nothing: the declaration and the element name are never read` |
| `uv run python SCRATCH/scripts/b_links_attrs.py` | `rels of the masked file: ... Target="mailto:pieter.de.vries@northwind.example" TargetMode="External"/></Relationships>` |
| `uv run python SCRATCH/scripts/f1_reserved_merge.py` | `restored annex text: 'Acme Supplies Ltd and Acme Supplies Ltd sign this annex.' \| report: 2 placeholders restored, 0 need your check.` |
| `uv run python SCRATCH/scripts/engine_batch.py` (A4 round trip; A5 first try blocked by my own payload) | `report : 6 placeholders restored, 0 need your check.` (A4) |
| `uv run python SCRATCH/scripts/engine_batch2.py` (A5 with opaque media; link probe with the marked domain) | `export blocked: True \| allowed: [] \| unmarked: []` (the marked-domain link blocks; A5: `media parts left in the masked copy: [...5 parts...]`) |
| `uv run python SCRATCH/scripts/engine_batch3.py` (links with neutral domains; G2/G4; glued note) | `masked header text: ['[PERSON_2]', ' removed]']` |
| `uv run python SCRATCH/scripts/twin_split_off.py` | `leftovers the gate would see in the twin: [...] <- export blocked although the owner chose to show these` |

Size of the fix list: 20 items (F-1 … F-20): 3 Critical, 6 Important, 11 Minor-and-cheap; of these
A1–A11 of the pointer list are covered by F-1, F-2, F-3, F-7, F-8, F-9, F-18, F-20 and the verified
A7; sections B/C add F-10 … F-17, F-19. Nine of the twenty are one-to-ten-line changes.

---

## Scoped re-review of the fix wave (branch final-fixes, HEAD fa4df8e, 19 commits on 3e7d6ea)

Reviewer: Claude (Fable 5.1), 19 October 2026, lean scope. Read the whole fix diff
(`git diff 3e7d6ea..fa4df8e`: 35 files, +2,258/−274) and the implementer's report
(`notes/sdd/final-fix-wave-report.md`, sections 1–5). Re-ran every reproduction of the review
against the fixed worktree (`scripts/rc.py` re-pointed by `MASK_ROOT`; the one API change,
`_whole_plan(groups)`, adapted in `twin_split_off.py`), plus three new checks
(`rr_corpus_export_all.py`, `rr_f3_ignorable.py`, `rr_f4_anchors.py`). Nothing in the worktree
was edited, committed, switched or pushed (`git status --short` empty before and after).

### Per item

| Item | Verdict | Evidence (my scripts against fa4df8e; the implementer's tests ran in the full gate) |
|---|---|---|
| F-1 R100 identity | **ADDRESSED** | `engine_batch.py`: six groups, each with one variant; export + `restore_text` gives the original text back verbatim: `restore: 'The unit fee is EUR 1.25 … cap is EUR 125 … deposit is $100 … refund is €100 … a.b@example.com or to ab@example.com.'`, `6 placeholders restored, 0 need your check.` One shared fold: `identity._number_key` imports `leakcheck.number_fold` (the `_COMPACT` view of `_folds`); no second copy of the decimal/zero rules anywhere in the diff. Corpus agreement: `rr_corpus_export_all.py` exports all 28 Word files unblocked, 0 allowed hits, 0 leftovers (`28 files exported in 61s; problems: []`); the suite's pass marks and round trip (inside `-m "slow or not slow"`) green. |
| F-2 R101 media | **ADDRESSED** | `engine_batch2.py` A5: `media parts left in the masked copy: []`, `image relationships … : 0`, `w:background kept: False \| v:fill r:id kept: False`, `numPicBullet: False`, export not blocked. Corpus image files supply-05, nda-03, dpa-01 export unblocked with no `word/media/*` and no image relationship (sweep above). Planted after cleaning: `blocked: True \| hits: [('word/media/planted.png', '(picture)', 'a picture or media file the cleaner could not remove is still in the file')] \| outputs: []`. |
| F-3 R102 namespaces | **ADDRESSED** | `a6_namespaces.py`: the unused `ns0` declaration is gone from the masked file; the used one and the element name are hits: `[('word/document.xml', 'xmlns:nw="http://[COMPANY_1].example/2026/templates"'), ('word/document.xml', 'element name="[COMPANY_1]"')]`. The mc:Ignorable trap: `rr_f3_ignorable.py` cleans all 28 corpus files, every prefix any `mc:Ignorable` names stays declared, python-docx opens every saved file: `files: 28 \| problems: []`. The corpus sweep also checks `xmlns:w14` on every masked document.xml. |
| F-4 R112 links/marks | **ADDRESSED** | `b_links_attrs.py` + `engine_batch3.py` (real analysis, neutral domains): `masked file holds 'pieter.de.vries@…': False`, `'legal.desk@…': False`, `'jane.doe@…': False`, export not blocked; the rels part is gone. With the marked company's domain (`engine_batch2.py`) the export that was blocked at 3e7d6ea now passes with the addresses gone. Internal anchors and bookmarks (`rr_f4_anchors.py`): `bookmark names: ['bm1']`, `anchors: ['bm1', '_Toc9']`, `r:id links: 0`, link text kept, `scan hits: []`. Corpus hyperlink files (services-01, nda-01, dpa-01): no `mailto:` and no hyperlink relationship left (sweep). README sentence present. |
| F-5 R113 notes | **ADDRESSED** | `engine_batch3.py`: review text `'…\nAcme Supplies Ltd [image removed]'`; groups: one COMPANY "Acme Supplies Ltd" with both places, no PERSON garbage; masked header `['[COMPANY_1]', ' ', '[image removed]']`. |
| F-6 R107 reserved merge | **ADDRESSED** | `f1_reserved_merge.py`: `ValueError: [COMPANY_1] and [COMPANY_3] are both in the case's key and cannot be merged; leave them as two values.`; the survive-with-canonical and split cases are in `tests/test_review.py` (green). |
| F-7 R105 range + G2 | **ADDRESSED** | `a10_quantity_range.py`: `'Schedule 3 - 500 pallets per week' -> [('3 - 500 pallets', 0.8)]`, the en-dash, "Section 2 - 10,000 units" and "Article 3 to 1,000 pieces" likewise; "Annex 2 Units of Measure" and "Schedule 3 Pallets and Packaging" still visible. Full pipeline: "shall schedule 500 pallets", "shall exhibit 12 units", "per article 12 pieces" now hidden as QUANTITY; G4 ("Price - Jones …") parked as ruled. |
| F-8 R104 zip limits | **ADDRESSED** | `300 MB entry: refused in 0.00s before reading`; `30,003 entries: refused in 0.24s`; corpus files open. |
| F-9 A1–A3 folds | **ADDRESSED** | `a1_a2_a3_leak_folds.py`: `'Fee EUR 1,250.00 100 units' -> 1 hit`, `'Fee EUR 1,250 100 units' -> 1 hit`, the other four lines 1 hit; A2: `for_bytes: {'eur10': …}` and `bytes part holding 'EUR 10.00' -> 1 hit`; A3: both `[AMOUNT_1]` and `[AMOUNT_2]` reported, and `[ID_1]` + `[PHONE_1]` for the cross-type pair. |
| F-10 R110 conflicts | **ADDRESSED** | `b_revisions.py` B2: `has_revisions: True`; accepted `'Price: EUR 9,999'`, rejected `'Price: EUR 1,111'`; after accept/reject + clean: no `conflictIns`, no author. |
| F-11 misplaced record | **ADDRESSED** | B1: `text after reject_all: 'Clause 1. The Buyer pays.\nClause 2. The Seller delivers.'`. |
| F-12 hide re-enables | **ADDRESSED** | `b_review_noop.py`: `disabled after: set()`, plan places `[(0, 17), (25, 42), (49, 53)]` in both sequences. |
| F-13 R114 twin | **ADDRESSED** | `twin_split_off.py`: twin places `[(0, 17), (25, 29), (36, 40), (51, 55)]`, `leftovers the gate would see in the twin: []`. |
| F-14 `_merged` filter | **ADDRESSED** | By the diff (`export._merged` → `review.key_variants`) and its two tests in `tests/test_export.py` (green in the gate). |
| F-15 R108 duplicate | **ADDRESSED** | `f2_duplicate_placeholder.py`: `ValueError: Not a stored case.` |
| F-16 R109 | **ADDRESSED** | `LeakBlockedError` gone from `errors.py`; `tests/test_about.py` asserts it. |
| F-17 R111 collector | **ADDRESSED** | `ui/app.GarbageCollector` (gc.disable, GUI-thread QTimer, 0,0,1,0,0,2 every 2 s, stopped after the workers are joined); the subprocess start-up test prints `collector running: True`, `gc enabled … False`, `gc enabled after: True`. |
| F-18 owner name | **ADDRESSED** | `OWNER_NAME = "Alican Yazdic"`; About test green. |
| F-19 wall clocks | **ADDRESSED** | Every limit ×3, the two "thirty pages" names corrected; `test_twenty_four_pages_are_scanned_in_under_six_seconds` call 0.92 s on this box. |
| F-20 README | nothing to fix | the F-4 sentence landed. |

### The fix diff itself: no new Critical or Important

Read for leaks, wrong restores, crashes and visibility changes; probed the shapes above and the
corpus. Nothing rises to Critical or Important. Parked observations (Minor, no second wave):

- N-1 A damaged non-text XML part (`styles.xml` that is not XML) is now refused at clean time
  ("not a .docx") because R101/R102 parse every XML part — fail closed; the implementer's
  concern 1. Ruling suggested: documented limit ("re-save the file in Word").
- N-2 The G2 companion makes a lower-case "schedule 3 pallets" / "section 3 metres" a count
  (over-hiding side; contracts capitalise references). Owner-visible.
- N-3 `"INCLUDE"` in `_FLATTENED_FIELDS` is not a Word field name (harmless extra).
- N-4 R112 flattens the HYPERLINK fields a TOC is built of: the TOC text stays, the clickable
  links go (cosmetic; the AI reads text).
- N-5 The leak scan now builds a declaration block per element (`element.nsmap`): 24 pages scan
  in 0.92 s against a 6 s limit (was ≈0.2 s): acceptable.

### Commands (from `/home/user/the-mask-worktrees/final-fixes` at fa4df8e)

| Command | Last line |
|---|---|
| `uv run pytest -q -m "slow or not slow" -p no:cacheprovider` (everything incl. pass marks and round trip; log SCRATCH/out/fix-suite.log) | `3343 passed, 8 skipped in 370.94s (0:06:10)` / `EXIT 0` |
| `uv run ruff check src tests tools packaging` | `All checks passed!` |
| `uv run ruff format --check src tests tools packaging` | `142 files already formatted` |
| `uv run mypy src` | `Success: no issues found in 53 source files` |
| `uv run pytest tests/test_leakcheck.py tests/docx/test_cleaner.py -q -k "twenty_four or every_corpus_file or namespace" --durations=6` | `5 passed, 197 deselected in 12.75s` (scan call 0.92 s) |
| `uv run python SCRATCH/scripts/rr_corpus_export_all.py` | `blocked: True \| hits: [('word/media/planted.png', '(picture)', …)] \| outputs: []` (after `28 files exported in 61s; problems: []`) |
| `uv run python SCRATCH/scripts/rr_f3_ignorable.py` | `files: 28 \| problems: []` |
| `uv run python SCRATCH/scripts/rr_f4_anchors.py` | `scan hits: []` (bookmark `bm1`, anchors `['bm1', '_Toc9']`, no r:id links) |
| the thirteen review scripts re-run (`a1_a2_a3…`, `a6…`, `a8…`, `a10…`, `b_revisions`, `b_zip_comment`, `b_review_noop`, `f2…`, `b_links_attrs`, `f1_reserved_merge`, `twin_split_off`, `engine_batch`, `engine_batch2`, `engine_batch3`) | outputs quoted in the table above |

**Verdict: APPROVED.** F-1 … F-19 ADDRESSED, F-20 needed nothing; no new Critical or Important;
N-1 … N-5 parked as Minor with the rulings suggested above.
