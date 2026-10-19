# Task 14 report: leak check

**Status:** DONE_WITH_CONCERNS
**Branch / worktree:** task-14 at /Users/alijoeee/Developer/the-mask-worktrees/task-14 (from mac-v1 d201148)
**Commit:** daf82d1 feat: leak check over every package part, name and variant

## Main concern, first: the binding scope gives false hits that block real exports

I implemented decisions 1 to 11 as written. Then I measured them the way the export will use them: each of the 28 corpus .docx files run through the app's own pipeline (accept_all, clean, analyze, every group's findings masked, banner), then scan_package with that file's full key (the groups' canonical and variants, with bare surnames left out as R52 says).

**6 of 28 clean masked files get hits.** None of these hits is a real leak:

| File | Part | Why it hits |
|---|---|---|
| dpa-01 | word/theme/theme1.xml `a:fillToRect/@b="180000"` | AMOUNT "1.800,00" normalises to 180000 |
| dpa-01 | word/numbering.xml `w:tab/@w:pos`, `w:ind/@w:left` = "1800" | AMOUNT variant "1.800" |
| dpa-03 | theme1.xml `a:satMod/@val="350000"` | AMOUNT 350,000 |
| nda-01 | word/fontTable.xml `w:sig/@w:csb0="80000000"` | AMOUNT 800,000.00 normalises to 80000000 |
| nda-04 | theme1.xml `a:satMod/@val="350000"` | AMOUNT "350 000" |
| services-03 | theme1.xml `a:gs/@pos`, `a:alpha/@val` = "35000" | AMOUNT 35.000 |
| dpa-05 | word/document.xml body text | PERSON variant "B. Lee" normalises to "blee", which is inside "reasonaBLE Endeavours" |

The digit-boundary rule does not help here, because each of these needles equals the whole attribute value.

I also probed the clean masked supply-01 with made-up keys. Every one of these blocks the export:

- A party "Microsoft Ireland Operations Limited" (variant "Microsoft"): 6 hits, in docProps/app.xml `<Application>Microsoft Office Word`, a rels Type URI, settings `w:compatSetting/@w:uri`, and theme font names ("Microsoft Himalaya").
- "Core Systems Ltd" (variant "Core"): 5 hits, in [Content_Types].xml, _rels/.rels and the part name docProps/core.xml.
- "Format Products Ltd": 10 hits ("openxmlformats" in content types and rels).
- EUR 100,000: 2 theme hits. EUR 50,000: 5 theme hits.
- A person "Sarah Hall": variants_of gives "S. Hall", which normalises to "shall". That is **28 hits** in the body of a clean contract. No edge rule can fix this one, because "shall" is a whole word.

**Effect downstream.** Task 15's own tests (supply-01, -03, -07) scan clean. Task 24's `test_full_round_trip_every_docx` asserts `not res.blocked` for every corpus docx, so it will fail on the 6 files above unless the rules change.

**Proposals for a ruling** (none is applied; the code follows the decisions):

- **P1 (numbers):** a digit-only needle does not count inside an attribute value that is a bare number or hex code (`[-+]?[0-9A-Fa-f]+(\.[0-9]+)?%?`: a measurement, colour, id or font signature). I measured it by patching it in for a test run only: **6 → 1 blocked** (only dpa-05 is left). What is lost: a digit-only value stored as a whole attribute value (form-field defaults, content-control tags, list items). The cleaner already removes all of those.
- **P2 (OOXML vocabulary):** either go back to R14 a + R19's text-bearing scope for attributes (the TEXT_PARTS attributes, rels Targets, docProps element text), or exempt the OOXML vocabulary: schema, relationship and content-type URIs, font and style names, the standard part names, and app.xml's Application, AppVersion and statistics. AppVersion "16.0000" normalises to 160000, which would collide with an amount of EUR 160,000. I did not measure P2 on the corpus, because no corpus party has such a name.
- **P3 (short letter needles):** match name-type needles (PERSON, COMPANY, ADDRESS, CUSTOM) by their own word structure: each word of the form must start a word in the text. Identifiers and numbers keep plain normalised containment, so "NL91ABNA0417164300" still matches the spaced IBAN. This fixes both "blee" and "shall". A weaker option is word edges for needles under 6 characters; that fixes "blee" but not "shall".

## What I implemented

### `src/themask/leakcheck.py` (new)

- **`LeakHit(part, placeholder, context)`**, a frozen dataclass.
  - `part` is the part name, `"<file name>"` or `"<part name>"`.
  - `context` is about 20 characters either side of the hit, on one line. It reaches up to 10 more characters to show a cut word whole, and an ellipsis marks each cut. For an attribute it reads `label="…"`. In bytes that are not plain text it is `"<binary part>"`.
- **`scan_package(path, entries)`**:
  - It opens the file with `DocxPackage.open` first, so a file that is not a .docx raises the package's own UnsupportedFileError (or ProtectedFileError for an encrypted one). It then walks every zip entry in zip order.
  - **XML parts** are parsed with comments and processing instructions kept, no entities expanded and nothing fetched. What is searched:
    - the element text and tails of each w:p or a:p, joined into one block per paragraph, so a value split across runs is found;
    - text outside paragraphs, each comment and each processing instruction, each as its own block;
    - every attribute value, each as its own block;
    - the %-decoded form of relationship Targets, `w:instr` and `w:instrText` stretches (R26).
  - A part with a DOCTYPE is also put through the byte scan, to cover whatever its DTD declares.
  - Each block is normalised on its own. The blocks are joined with `\x00`, which no needle can contain, and each needle is searched once per part with `str.find`.
  - **Digit-only needles** count only where no digit touches them. **Needles under 4 characters** are skipped.
  - **R31:** an unquoted instruction word that exactly equals a FIELD_NAMES entry, or the word right after `\*`, `\@` or `\#`, is exempt only for a needle of exactly that spelling. A switch such as `\h` normalises to fewer than 4 characters, so it can never match.
  - **Non-XML or unparseable parts:** the bytes are read as UTF-8, as UTF-16-LE and as UTF-16-LE from byte 1 (text may start at an odd offset). Only needles of 6 or more characters that are not all digits are searched.
  - **Names:** the file stem and every entry name are searched too.
  - **Nested matches** are reported once (outermost only). A key two entries share is reported once, under the first entry's placeholder. Exact duplicate hits are dropped.
- **Bare surnames (R52).** For each PERSON entry, `PersonName.of(value).surnames()` gives the forms (longest first). Each is searched with `flexible_pattern` in `extract_text(pkg).text`. An occurrence is kept when `stands_as_a_name(text, start, end, is_name=…)` holds. Kept occurrences are reported under their segment's part, placed after that part's other hits.
- **`unverifiable(entries)`** returns the placeholders whose value and every variant normalise to fewer than 4 characters.
- **`rescan_detection(path, engine, user_lists, entries)`** (R3) runs `extract_text`, `CombinedText.join([(path.name, text)])` and `analyze`. It drops the groups whose canonical is a placeholder and those whose normalised canonical or any variant equals a normalised entry value or variant.
- **Contexts never show a value.** In the stretch round a hit, every value and variant of every entry (normalised containment) and every person's surname (as a word) is replaced. Any span that touches the window widens it, so no value is ever half-shown at an edge. A last guard replaces the whole context with the placeholder if a needle or surname still shows. Part names that hold a value are shown hidden in `LeakHit.part` too. Mapping from normalised positions back to the original uses piecewise normalisation split before ASCII characters. I checked that it equals `normalize()` on 20,000 adversarial strings (combining marks, Hangul jamo, Indic vowels, ligatures, İ/ı, ß, full-width digits): 0 mismatches. A long text is mapped chunk by chunk.
- **No logging** of any kind.

### `src/themask/docx/masker.py`

`_FIELD_NAMES`, `_FORMAT_SWITCHES` and `_INSTRUCTION_WORD` are now public (`FIELD_NAMES`, `FORMAT_SWITCHES`, `INSTRUCTION_WORD`, per decision 4), with a comment saying the leak check uses them. Behaviour is unchanged and all 54 masker tests pass.

### Tests

- `tests/helpers.py` (new): `plant(src, part, payload, out)` inserts the payload before the part's last closing tag, or adds the part when it does not exist.
- `tests/fixtures/leak.py` (new):
  - `MASKED_ENTRIES` holds the brief's two entries.
  - `mask_file(src, entries, out)`: accept_all, clean, every `flexible_pattern` occurrence of value, variants and `variants_of` (longest wins, none crossing a paragraph), apply_mask, insert_banner, save.
  - A session fixture `masked_docx`: supply-01 masked for those entries, saved as MASKED-TEST.docx.
- supply-01 **does contain** both Northwind Trading B.V. and NL91 ABNA 0417 1643 00. `test_the_file_before_masking_has_hits` proves that the same scan finds both all over the unmasked file, including word/header1.xml.

## Tests and results

`tests/test_leakcheck.py` has 23 tests.

- **The brief's five**, with the R3 signature for rescan. I also added `test_the_file_before_masking_has_hits`.
- **Rules:**
  - digit boundaries (11250, 2025, 12500 and 1,2500 are no hits; "Pay 1.250" and "AB1250CD" are hits);
  - short values are not checkable (unverifiable returns ["[PERCENT_1]", "[ID_1]"], and "5%" and "AB1" are not searched);
  - a value split across runs is found, but text in two paragraphs is not joined;
  - a %-escaped mailto in a rels Target and in a fldSimple instruction (R26);
  - wp:docPr/@descr and w:hyperlink/@w:tooltip (R19);
  - PAGE, `PAGE \* MERGEFORMAT` and MERGEFORMAT are no hits for "Page" or "Merge-Format", while `QUOTE Page Industries` and `INCLUDETEXT \\Acme-NAS\share` are hits (R31);
  - bare surnames (R52): "the Price" is no hit; "Price shall attend.", "Price and Smith" (both) and "Attention: Price" in a header are hits;
  - XML comments, including one inside a w:t, and processing instructions.
- **Bytes:** UTF-16 at even and odd offsets, a plain-text part, unparseable XML, and digit-only values not searched in bytes.
- **Part names:** a `<part name>` hit, and the content hit's part shown hidden.
- **What a hit shows:** five forms in one paragraph, no value shown in any context; NFD accents and a ligature; long-text cuts and whole words.
- **Refusals:** not-a-docx and corrupt files raise UnsupportedFileError; an encrypted file raises ProtectedFileError.
- **Rescan:** detection finds the planted marked company again, but rescan leaves it out; the planted Dr Jane Smith comes back; no placeholder groups.
- **Timing:** supply-10 masked by its truth plus padding, 60 entries, no hits, under 2 s.

Every test that gets hits checks that no context and no part shows a value (normalised).

**Timing:** masked supply-10 (the real full-analysis masking, 24 pages) with 60 entries: median **0.062 s** over 7 runs (0.060–0.063 s). The test itself, including masking, runs in 0.26 s. Every part is really walked; styles.xml alone has 13,867 attribute values.

## TDD evidence

**RED 1:** `uv run pytest -q tests/test_leakcheck.py` gave `ModuleNotFoundError: No module named 'themask.leakcheck'` (expected: the module did not exist yet).

**RED 2:** against a stub whose `scan_package` returned `[]` after opening the package: `19 failed, 4 passed in 11.80s`. The 4 that passed only check absence or refusal: clean file, field names no hit, refusal, timing. This shows the other 19 test real behaviour.

**GREEN:**
- First run of the real module: 21 passed, 2 failed. Both failures were my own wrong expectations, not module bugs:
  - the surname context was correctly cut 20 characters after the hit;
  - an odd-offset UTF-16 part decodes to clean text, so it shows `[COMPANY_1]` rather than `<binary part>`.
- I fixed the expectations. I also added word widening for cut words, plus a test for it.
- After that: `uv run pytest -q tests/test_leakcheck.py` gave `23 passed in 6.86s`.
- Full suite `uv run pytest -q`: `2385 passed in 44.35s`, with no warnings.
- `uv run ruff check src tests tools`: All checks passed. `uv run mypy src`: no issues in 31 files. My four new files are ruff-formatted.

## Files changed

- src/themask/leakcheck.py (new)
- src/themask/docx/masker.py (3 constants made public)
- tests/test_leakcheck.py (new)
- tests/fixtures/leak.py (new)
- tests/helpers.py (new)

## Self-review findings and judgement calls

1. **Text joined per paragraph.** I read decision 2's "each normalised" as one block per paragraph for element text; texts outside paragraphs and attribute values are each searched alone. Reason: a value Word split across runs must be found, and separate fields of data XML must not join ("3" + "1250000").
2. **Contexts hide more than the hit.** They hide every entry's values and variants and every person's bare surname, not only the hit's own value. `LeakHit.part` is hidden too when a part name holds a value. A name hit uses the pseudo-part `<part name>`, like the brief's `<file name>`.
3. **`is_name` for R52.** `stands_as_a_name` gets `is_name` built from the entries (values, variants and surnames of people and companies). This mirrors `sweep.name_test`, so "Price and Smith" counts both names, as the sweep would have masked both. Without it, both would be read as a title-case phrase and missed.
4. **No double reports.** A surname occurrence that sits inside a value or variant occurrence ("Mr Smith") is not reported twice. Of "van der Berg" and "Berg" at one place, only the longer counts.
5. **Masker constants.** They were made public rather than copied, so both modules use one vocabulary.
6. **Commit trailer.** It is `Co-Authored-By: Claude Opus 5.5`. The boilerplate names Fable 5.1, but implementer commits in this repo carry the implementing model, and this session's attribution instruction is Opus 5.5.

## Other issues and limits

- **R31 as written:** a value spelt like *part* of a field word is a hit, for example "Page" in PAGEREF or NUMPAGES, or "Format" in MERGEFORMAT. Only exact equality is exempt, and the masker leaves those words as they are. This is another source of false hits; PAGE and NUMPAGES footers are common.
- **Unticked occurrences:** if the owner unticks a single occurrence of a marked value (Task 9), it stays in the file and scan_package reports it, as its contract says. Task 15 has to settle how key entries and unticked occurrences fit together.
- **Not covered:**
  - XML namespace declarations: lxml does not treat them as attributes, and scanning them would hit "microsoft" in every file;
  - a part's DTD, which only gets the byte rules;
  - XML nested deeper than 256 levels: the parser refuses it, so it gets the byte scan only (checked: no recursion error);
  - archives nested inside parts, which are deflated and so invisible to the byte scan (the cleaner removes word/embeddings);
  - zip archive and entry comments and extra fields (`DocxPackage.save` writes none).
- **Rescan:** an engine finding of a person's bare surname left visible on purpose ("the Bennett file") is listed as unmarked. Decision 7 filters only on values and variants.

---

# Fix round 1: rulings R63 and R64 (pre-review tweak)

**Commit:** 24b7bd8 fix: names by whole words, the file format's own vocabulary unsearched (R63, R64)

## Before and after

All 28 corpus .docx files, masked by the full pipeline and scanned with each file's full key:

| | Before (daf82d1) | After (24b7bd8) |
|---|---|---|
| Corpus files blocked | **6** (dpa-01, dpa-03, dpa-05, nda-01, nda-04, services-03) | **0** |

Probes on the clean masked supply-01:

| Made-up key entry | Hits before | Hits after |
|---|---|---|
| Microsoft Ireland Operations Limited | 6 | 0 |
| Format Products Ltd | 10 | 0 |
| EUR 100,000 | 2 | 0 |
| EUR 50,000 | 5 | 0 |
| Sarah Hall ("S. Hall") | 28 | 0 |
| Core Systems Ltd | 5 | 4 (see residuals) |

**Timing.** Masked supply-10 (24 pages) with 60 entries: median 0.127 s over 7 runs (0.122–0.129 s), up from 0.062 s because each block is now folded both ways. The budget is 2 s.

## What changed (src/themask/leakcheck.py)

### R63: names compared by their words

- The public constant `NAME_TYPES` lists PERSON, COMPANY, ADDRESS, CUSTOM, EMAIL and URL. These values are compared by their words: NFKC, case folded, ı read as i, marks and format characters dropped, and every other run of non-letters folded to one space. They count only on word edges.
- Marks are dropped rather than turned into spaces because case-folding "İ" leaves a combining dot (U+0307), which would otherwise split Turkish words. The same goes for soft hyphens and zero-width characters, which show nothing.
- AMOUNT, PERCENT, QUANTITY, IBAN, ID and PHONE keep the compact form with digit boundaries, exactly as before. A variant takes its entry's type.
- One rule for both forms everywhere: the scan, the byte scan, the file name and part names, the context hider and its last guard, and the surname dedupe all use the same matching. This also ends the garbled contexts such as "reasona[PERSON_2]ndeavours".
- The same exemption mechanism (R31) works in both folded forms.
- Containment of one hit in another (outermost only) is now judged in source positions, so it holds across the two forms.
- The word fold without its spaces is exactly `normalize`. I checked this on 30,000 adversarial strings: 0 mismatches. Tracing positions back is exact; long texts are traced in chunks cut between two ASCII letters or digits, where both folds also cut.
- **A paragraph's block is now what Word shows.** That is its texts (w:t, w:delText, a:t, m:t), its instructions, and "\t" or "\n" for w:tab, w:ptab, w:br, w:cr and a:br (w:noBreakHyphen becomes its own character). Any other element text inside a paragraph is now a block of its own, still scanned. Without this, under R63 a drawing's `wp:posOffset` text would glue onto a name or split it, and a tab would join two words.

### R64: the file format's own vocabulary is not searched

The `_Reader` skips:

- **(a)** for digit-only needles only, an attribute whose whole value is a bare number or hex code: `[-+]?(digits[.digits][%|pt|pc|pi|in|cm|mm|px|em|ex] | hex)`;
- **(b)** attribute values starting with `http://schemas.`, `http://www.w3.org` or `urn:schemas-microsoft-com` (case-insensitive), and every `Relationship/@Type`;
- **(c)** every attribute of `w:rFonts`, `w:font/@w:name`, and `@typeface` on `a:latin`, `a:ea`, `a:cs` and `a:font`;
- **(d)** the element text of `ep:Application`, `ep:AppVersion` and `ep:Template`.

No whole part is exempted.

## Judgement calls

1. **Typefaces outside the theme.** The (c) typeface rule applies wherever `a:latin`, `a:ea`, `a:cs` or `a:font` stand (for example DrawingML text in the document), not only in the theme. Each of them is a font declaration by definition.
2. **Bare numbers are single values.** A list such as `coordsize="21600,21600"` does not count as a bare number, so a tooltip "1,250,000" is still scanned.
3. **Where the address rule applies.** The (b) prefix rule is applied to attribute values. Element text is never a schema address in these parts.
4. **Byte scan.** The byte scan uses R63 for names too, as ruled. ASCII UTF-16 text read as UTF-8 shows its letters with NULs between them, which now split the words, so the UTF-16 decodings (both byte alignments) find it instead. The R14 b test stays green.
5. **Trailing full stop.** The final "." of a value such as "B.V." is no letter of the value, so a context reads "[COMPANY_1]." with the dot left after the placeholder.

## Residual false hits (not covered by the rulings; numbers from probes)

- **"Core" (4 hits).** A short name equal to an OOXML part-name word: the `/docProps/core.xml` PartName and the core-properties ContentType in [Content_Types].xml, the `docProps/core.xml` Target in _rels/.rels, and the part name itself. R64 keeps Targets and part names scanned, so this stays. The same can happen for theme, settings, styles, numbering, header, footer and media.
- **Theme scheme names.** `a:theme/@name="Office Theme"` and `a:fontScheme/@name="Office"` hit a party short-named "Office". In practice the analysis is unlikely to keep "Office" as a variant, because the word "office" in the body text would then hit too.
- **Element-text numbers.** An amount exactly equal to a docProps/app.xml statistic (`<Words>1816</Words>`: 1 hit) or to a drawing's `wp:posOffset` still hits.
- **VML path data.** Numbers in path data such as `path="m,l,21600r21600,l21600,xe"` are not bare, so they are still scanned.

## R63 recall trade-offs (accepted by the ruling)

- A name glued to other letters is no longer found ("NorthwindTrading", "northwindgroup.example").
- A dotted form written without its dots ("Acme BV" for "Acme B.V.") or different internal spacing ("3579KJ" for "3579 KJ") is found only through a variant. Companies usually have a short-name variant, such as "Acme", that still matches.

## Tests (tests/test_leakcheck.py: 32 tests; 23 before plus 9 new)

New tests:

- `test_names_count_only_as_whole_words`: "S. Hall" against "shall" and "B. Lee" against "reasonable endeavours" are no hits; "Signed by S. Hall." is a hit; the type split is checked against `NAME_TYPES`.
- `test_a_tab_parts_two_words_and_a_drawing_joins_none`.
- `test_sizes_colours_and_ids_are_no_amounts`: theme `a:gs/@pos`, `a:tint`, `a:satMod`, `w:ind/@w:left` and a `w:sig` hex code are no hits; the same 35.000 in a w:t is a hit.
- `test_a_party_named_like_the_file_format_counts_in_content_only`: rels Type, settings `w:uri` (all three prefixes), the font table, theme typefaces, `w:rFonts` and app.xml give no hits, and nor do Word's own copies in the masked corpus file (checked to hold "Microsoft"); a tooltip "Microsoft portal" is a hit.
- `test_corpus_files_masked_by_the_pipeline_have_no_hits`, parametrised over supply-01, supply-04, nda-02, dpa-01 and services-03: accept_all, clean, analyze, every enabled group's findings masked, banner, then a scan with the key built from the groups (bare surnames out, per R52) gives zero hits. About 0.5 s per file plus about 5 s of shared setup, so it is not marked slow.

Changed tests:

- `assert_nothing_shown` now checks independently with the R63/R14 semantics.
- The R31 test now uses "MergeFormat" (one word, so the exemption is exercised) and adds PAGEREF and NUMPAGES fields.

Every earlier test passed unchanged against the new module before the test edits: 23 of 23.

**RED.** The new tests run against the previous module (`git show daf82d1:src/themask/leakcheck.py`): `7 failed, 3 passed`. The failures were the whole-words test, the tab/drawing test, the layout numbers test, the Microsoft test, the R31 test (PAGEREF/NUMPAGES) and pipeline[dpa-01] and pipeline[services-03]. The 3 that passed are the corpus files that were already clean.

**GREEN:**

- `uv run pytest -q tests/test_leakcheck.py`: 32 passed in 9.85s.
- `uv run pytest -q`: 2394 passed in 48.15s, no warnings.
- `uv run ruff check src tests tools`: All checks passed.
- `uv run mypy src`: no issues in 31 source files.

---

# Fix round 2: ruling R64 extended with (e), (f) and (g)

**Commit:** 4935d2e fix: counts, geometry, standard part names and theme names are no values (R64 e-g)

## Measurements

All 28 corpus .docx files masked by the full pipeline: **0 blocked** (6 before the rulings, 0 after R63/R64, still 0 now).

Probes on the clean masked supply-01:

| Made-up key entry | Hits now | Hits after round 1 |
|---|---|---|
| Core Systems Ltd | **0** | 4 |
| EUR 1816 (equal to app.xml `<Words>1816</Words>`) | **0** | 1 |
| Office Depot Europe B.V. (with variant "Office") | 2, both in body text | 4 (2 were the theme) |
| Microsoft, Format, EUR 100,000, EUR 50,000, S. Hall | 0 | 0 |

The two remaining "Office" hits are the plain word "office" in "whose registered office is at": a true word match for that variant.

**Supply-10 scan:** masked supply-10 (24 pages), 60 entries: median **0.130 s** over 7 runs (0.128–0.131 s), against 0.127 s after round 1 and a budget of 2 s.

## What changed (src/themask/leakcheck.py)

### (e) Bare numbers outside the document's text, and drawing geometry

For digit-only needles, a block marked `no_digits` is not searched. That is:

- an attribute value that is a bare number or hex code (as before);
- the whole text of an element that bears none of the document's text, when that text is a bare number. Text-bearing elements are w:t, w:delText, w:instrText, w:delInstrText, a:t and m:t (I counted a:t and m:t as w:t-like), the dc: and cp: core properties, and XML comments and processing instructions;
- drawing geometry: every attribute of a VML element (any `urn:schemas-microsoft-com:` namespace) except string, alt, title and href, and a DrawingML shape guide's `a:gd/@fmla`.

This covers wp:posOffset, a:off and a:ext, coordsize, path, the style dimensions, o:spid, the app.xml counts and the HeadingPairs/TitlesOfParts `vt:i4` numbers. A bare number inside w:t is still a hit.

### (f) Standard part names, for name needles only

`_is_standard_part` matches the coordinator's list, plus `word/stylesWithEffects.xml` (a standard Word 2010 part, in the corpus), plus any rels part whose served part is on the list. For these:

- the part name is no name;
- `[Content_Types]` Default entries (Extension and ContentType) are no names;
- an Override whose PartName is a standard part is no name, ContentType included;
- an in-package relationship Target (not TargetMode="External") that resolves to a standard part is no name, and so is its %-decoded form;
- the hider leaves names visible in a standard part's name, so a hit's `part` reads docProps/core.xml, not docProps/[COMPANY_1].xml.

The outer file name and any other part name (for example word/media/core-logo.png) are still checked.

### (g) Theme and scheme names

`a:theme`, `a:clrScheme`, `a:fontScheme` and `a:fmtScheme` @name are not searched for any needle.

## Judgement calls

1. **ContentType attributes.** Ruling (f) names the PartName and Extension attributes. Without also exempting the Default content types and the content type of a standard part's Override, "Core" kept 1 hit (`…package.core-properties+xml`), against the requested 0. I exempt those for names only.
2. **Extra standard part.** `word/stylesWithEffects.xml` was added to the standard list.
3. **a:t and m:t.** These count as text-bearing, like w:t.
4. **Drawing geometry.** It covers all non-text VML attributes and `a:gd/@fmla`, not only path and coordsize.

## Consequences to know

These are by the ruling, and the cleaner removes all three:

- a digit-only value written alone as the text of a non-text element is not checked: a chart's cached `c:v`, a custom XML data element, or a `vt:lpwstr` custom document property;
- a digit-only value in VML attributes other than string, alt, title and href is not checked.

## Tests (36 in tests/test_leakcheck.py; 4 new)

- `test_the_names_of_standard_parts_are_no_names`: "Core" on the clean masked file gives 0 hits; the file is checked to really hold docProps/core.xml, a core-properties content type and a _rels/.rels target. "Core shall deliver." in a w:t is a hit. A non-standard part word/media/core-logo.png and the outer file name Core-deal.docx are still hits.
- `test_counts_of_the_extended_properties_are_no_amounts`: TotalTime, Pages, Words, Characters, Lines, DocSecurity and a HeadingPairs vt:i4, all 1250, give 0 hits for "1,250"; a w:t holding just "1250" is a hit.
- `test_a_drawings_geometry_holds_no_amounts`: wp:posOffset, wp:extent, a:gd/@fmla, VML coordsize, path and style give 0 hits; the same amounts in body text are 2 hits.
- `test_theme_and_scheme_names_are_no_names`: the four scheme names give 0 hits for "Office", and a tooltip is a hit. Word's own theme in the masked corpus file (checked to hold `name="Office`) gives no theme hit.

**RED:** the four new tests run against the module of 24b7bd8: `4 failed`. The module was then restored.

**GREEN:**

- `uv run pytest -q tests/test_leakcheck.py`: 36 passed in 10.88s.
- `uv run pytest -q`: 2398 passed in 47.86s, no warnings.
- `uv run ruff check src tests tools`: All checks passed.
- `uv run mypy src`: no issues in 31 source files.


---

# Fix round 3: deep review round 1 (C1, I1–I4, M3; rulings R65–R69)

**Commit:** 533a224 fix: number boundaries in the text, names folded twice, Word's own vocabulary only, counts (R65-R69)

## Measurements

- **Corpus:** the 28 corpus files masked by the full pipeline: **0 blocked** (unchanged).
- **Supply-10 scan:** 24 pages, 60 entries: median **0.167 s** over 7 runs (0.164–0.169 s), against 0.130 s before this round. Each block is now folded three ways and number boundaries are judged on the source text.
- **Leave-one-out (reviewer's p14):** **1,366 tried, 0 missed**. That is 202 on the default four files and 1,164 on the other 24; it equals the reviewer's 1,366/1,366 before the fix.

The reviewer's probes after the fix:

- **p1 (C1).** Now caught: "Instalment 2⇥125,000", "2025↵1,250", "1.⇥125,000 payable", "Fee: 125,000.00", "Tel. 2: +31 20 123 4567" and "Fee 125,000¹". "EUR 1,250" no longer hits "EUR 12,500" or "EUR 1,250,000". Two stay non-hits by R65's own definition, because a single space is a number separator: "In 2025 1,250 units" and "Article 4 12345678".
- **p15 (the tab-separated payment schedule on the real pipeline):** all three rows are now caught (all three were missed before).
- **p16:** the cleaner gives the theme and colour scheme Word's names again, so theme1.xml no longer holds "Northwind". The company-named font gives three hits (styles ascii, styles hAnsi, fontTable name).
- **p10/p13 (style vocabulary):** variants that are style words block 0 of 29 masked corpus files (Accent, Grid, Light, Medium, Dark, Index, Quote, Plain, Caption, Heading, Shading, Colorful). "Title", "Office", "Page", "Strong" and "Normal" still hit the visible text ("Title:", "registered office", the footer's "Page", body words). Those are true word matches, not vocabulary.
- **p2 (R68):** "North-wind", "Northwind Logistics" against "North-Wind Logistics", and "North Wind Logistics" are hits. CamelCase "AcmeHoldings" and the glued domain "acmeholdings.example" are still not hits: they have no punctuation to drop.
- **p9 (R69):** no compact-normalised value is left in any context.
- **p11 (M3):** three identical paragraphs give one hit with count 3. A displayed value plus a %-escaped copy in a link gives 2.
  - **Flag:** 16 MB of random binary media with 41 entries takes 8.7 s to scan. Byte-scan cost is parked, so I did not touch it.

## What changed

### src/themask/leakcheck.py

- **R65 (C1, M4): number boundaries.** Number matches are still found in the compact fold, but whether a digit touches them is now judged on the block's own text through the trace. A digit touches only when it is right beside the match, or beyond exactly one of space, NBSP, U+202F, ".", "," or "'". Tabs, breaks, anything else and the text's edge are boundaries. A trailing `[.,]\d\d(?!\d)` (cents) is not a neighbour. This applies to every number needle whose compact form starts or ends with a digit, so "EUR 1,250" now follows the rule too.
  - Digits are tested with `isdecimal`, so a footnote mark "¹" is a boundary.
  - The trace now cuts pieces before every character except marks and Hangul vowels and finals. That makes a footnote mark or an NBSP next to a digit traceable exactly.
- **R68 (I4): a second fold for names.** Punctuation with no whitespace beside it is dropped ("B.V." → "bv", "North-wind" → "northwind"). A match on word edges in either fold is a hit. The first fold keeps "S. Hall"/"shall", "B. Lee"/"reasonable" and "Page"/PAGEREF as non-hits, and the second fold does not change them.
  - **My addition: an initial guard.** In the second fold, a full stop between a single letter and a word of two or more letters stays a word break. Without it, a glued variant "S.Hall" folds to "shall" and hits every "shall" in a contract. The first fold already splits there, so nothing is lost.
- **R31 exemptions** now apply in all three folds.
- **R66 (I1): allowlists for fonts and theme names.**
  - Fonts and theme/scheme names are exempt only when they are on fixed lists:
    - fonts shipped with Office, Windows and macOS: about 300 names, their East Asian names as Word writes them (宋体, ＭＳ 明朝, 맑은 고딕 …), and the Noto, Yu, SimSun, Segoe UI, Sitka, Hiragino, PingFang, SF, Heiti and Songti families;
    - Word's theme names, gallery names and colour, font and effect scheme names; a font scheme named after Office fonts ("Arial Black-Arial") also counts.
  - The w:rFonts theme keywords (asciiTheme, hAnsiTheme, eastAsiaTheme, cstheme) and w:hint are always exempt, and so are theme typeface references such as "+mn-lt".
  - Every other font, theme or scheme name is scanned like text.
- **R67 (I2): built-in style names, for name needles only.**
  - Every `w:lsdException/@w:name` is exempt.
  - `w:style/w:name/@w:val` is exempt when it is a built-in name. The list is generated: Word's named styles, the numbered families (Heading 1–9, TOC, List…, Table…), the accented table styles (Light Shading … Accent 1–6, Grid/List Table 1–7) and every "… Char".
  - A pre-pass over the package's `w:styles` parts collects the ids of built-in styles. Those ids and the references to them (pStyle, rStyle, tblStyle, basedOn, next, link) are exempt.
  - Custom styles stay scanned.
- **R69 (I3): contexts.** Contexts and the final guard now hide every compact-normalised occurrence of each value, variant and surname, with no word edges. Surnames under 4 letters are hidden only as words, because compact hiding of "Ng" or "Lee" would garble every context.
- **R69 (M3): counting.**
  - `LeakHit` gains `count: int = 1`; hits that read the same are summed.
  - `hits_by_placeholder(hits)` totals the counts per placeholder.
  - A %-decoded copy counts unless the block it was decoded from holds that same place unescaped. The places are mapped back through `percent_decoded`'s origins.
  - Byte parts are judgement call 3 below.

### src/themask/docx/masker.py

`_percent_decoded` is now public as `percent_decoded`. There is no behaviour change.

### src/themask/docx/cleaner.py (R66)

- The document's theme and its colour, font and format schemes get Word's names back ("Office Theme", "Office"). Each changed name is counted in `CleanReport.attributes_cleared`; the docstring and step 9 of the module docstring say so.
- Fonts are not touched.
- Task 12's 117 tests stay green.

## Judgement calls

1. **R65 as written:** "Article 4 12345678" and "In 2025 1,250 units" stay non-hits, because a single space between digits is a number separator.
2. **R68 initial guard:** see above.
3. **Byte parts and counting:** the same bytes can read as a value both as UTF-8 and as UTF-16 (ASCII text in UTF-16 shows up in the UTF-8 reading too). So for each value, the reading that finds it most often counts, rather than the sum. Exact counts matter for the text parts, which is where unticked occurrences live.
4. **Standard part names keep surnames visible:** the part label of a standard part does not hide names (R64 f), so "docProps/core.xml" stays readable for a "Core" key.
5. **A collision this round does not fix:** "EUR 1,250.00" compacts to the same digits as "125,000", so it is a hit for a 125,000 entry. This comes from R14's compact rule and is outside R65.

## Tests

- **tests/test_leakcheck.py:** 44 tests, 8 new.
  - `test_a_tab_or_a_line_break_parts_two_numbers`: the three-row tab schedule, a year column, a line break and a numbered row.
  - `test_what_parts_a_number_from_a_number`: "Tel. 2:", "Fee 125,000.00", "125,000¹" and "EUR 1,250.50" are hits; "EUR 12,500" and "EUR 1,250,000" give no hit for "EUR 1,250".
  - `test_a_theme_named_after_the_company_is_renamed_and_its_font_found`: the p16 shape. After cleaning the theme names are Word's, and the company-named font gives three hits.
  - `test_built_in_styles_are_no_names_but_custom_ones_are`: a built-in Title style, its Char style, a pStyle reference and a latent style give no hits for "Title" or "Accent". A custom style "Northwind Heading" with id "Northwind" and a pStyle reference to it gives 3 hits.
  - `test_word_s_own_styles_in_the_corpus_are_no_names`: "Accent" gives 0 hits on the masked corpus file (p13 found 336).
  - `test_names_are_found_however_they_are_punctuated`: "North-wind", "Northwind Logistics" against "North-Wind Logistics", and "Acme BV" against "Acme B.V." are hits; a glued "S.Hall" variant does not hit "shall".
  - `test_a_context_hides_every_spelling_of_a_value`: the four context shapes from I3, with counts.
  - `test_each_place_is_counted`: three identical paragraphs give count 3; a raw plus %-escaped pair gives 2; UTF-16 bytes read two ways count once.
- `assert_nothing_shown` now uses the stricter compact check, surnames included.
- The R31 test uses "MergeFormat" and adds PAGEREF and NUMPAGES.
- **tests/docx/test_cleaner.py:** `test_the_theme_takes_back_the_names_word_gives_its_own`.

**RED:** the 9 new tests run against 4935d2e's leakcheck and cleaner (with a two-line `hits_by_placeholder` shim so the file imports): `9 failed`. Every earlier test passed against the new module before the test edits: 36 of 36.

**GREEN:**

- `uv run pytest -q tests/test_leakcheck.py`: 44 passed.
- `uv run pytest -q`: 2407 passed in 51.82s, no warnings.
- `uv run ruff check src tests tools`: All checks passed.
- `uv run mypy src`: no issues in 31 source files.
- Tracing property check: 0 mismatches on 40,000 adversarial strings; chunked mapping of long texts agrees in all three folds.

---

# Fix round 4: rulings R70 and R71

**Commit:** d8f3c7a fix: plain spaces part numbers but thousands, decimal parts stay apart (R70, R71)

## Measurements

| Check | Result |
|---|---|
| Leave-one-out, the reviewer's p14 over all 28 corpus files in one run | **1,366 tried, 0 missed** |
| Corpus files masked by the full pipeline | **0 of 28 blocked** |
| Supply-10 scan (24 pages, 60 entries), 7 runs, nothing running alongside | median **0.188 s** (0.187–0.195 s), against 0.167 s before |

The supply-10 time grew by about 20 ms: each block now gets a pass that finds decimal points, and every trace has a fourth view.

## What changed (src/themask/leakcheck.py)

### R70: a plain space parts numbers unless a thousands group follows

`_digit_at` now treats a plain space (U+0020) between digits as part of one number only when the run of digits on the far side of the space is exactly three long. I read "beyond" as you wrote it in your examples: the run on the far side, on both sides of the match. NBSP and U+202F keep R65 (always a separator), and so do ".", "," and "'".

- "1 250" inside "1 250 000": no hit.
- "1250" inside "1250 000": no hit.
- "In 2025 1,250 units": a hit, because "2025" is four digits.
- "Article 4 12345678": a hit, because "4" is one digit.
- **Consequence of reading the left side by the run before the space:** a bare "250,000" inside "1 250 000" is now a hit. The leading group "1" is one digit, so the space reads as a boundary. It errs toward a hit, which is the safe direction.

### R71: the number fold keeps the decimal part apart

The number fold marks a decimal point with "x", in the text and in the needles alike:

- "1,250.00" → "1250x00"
- "1.250,00" → "1250x00"
- "1.250.000,00" and "1,250,000.00" → "1250000x00"
- "125,000" → "125000"

A run of digit groups is joined by ".", ",", "'", NBSP or U+202F. A plain space joins no run, so "1,250.00 2,000.00" stays two runs and the first keeps its cents. A run's last separator is a decimal point when all of these hold:

- it is "." or ",";
- one or two digits follow it;
- the groups between the first and the last are thousands groups (and a first group of more than three digits only when there are none between).

**Guard (my addition):** runs whose middle groups are not thousands, such as the dotted telephone number "06.12.34.56.78" or the date "18.10.26", get no mark. Without it they would stop matching their own entries.

Other details:

- The mark appears only in the number view. Name folds are unchanged.
- A hit's context hides by a fourth view, plain letters and digits with no marks, so hiding behaves as R69 defined it.
- The four-letter minimum and the six-letter byte minimum count letters and digits without the mark.
- A number with a decimal part still counts as digits only for R64 (a, e).
- Long texts are now cut for tracing between letters only, because a cut between digits could split a number run.

### Three decimals ("your call")

"1,250.125" folds to "1250125". Three digits after the last separator are a thousands group, as in "1.250.125", so it holds no "1,250", and the "." with digits beyond it keeps "1,250" touched. Under the same rule, "1,250.125" does hit an entry "1,250,125".

## Tests (46 in tests/test_leakcheck.py; 2 new)

- `test_a_plain_space_parts_numbers_unless_a_thousands_group_follows`:
  - "1 250 000" and "1250 000" give no hit for "1 250";
  - "In 2025 1,250 units" and "Article 4 12345678" are hits.
- `test_a_decimal_part_stays_apart`:
  - "EUR 1,250.00" gives no hit for EUR 125,000;
  - "1,250" against "1,250.00" is a hit;
  - "1,250,000" against "1.250.000,00" is a hit;
  - "1,250.125" against "1,250" is no hit (the documented call).

**RED:** both new tests run against 533a224's module: `2 failed`.

**GREEN:**

- Tracing property check with number-heavy text: 0 mismatches on 40,000 strings; chunked mapping agrees in all views.
- `uv run pytest -q tests/test_leakcheck.py`: 46 passed.
- `uv run pytest -q`: 2409 passed in 52.38s, no warnings.
- `uv run ruff check src tests tools`: All checks passed.
- `uv run mypy src`: no issues in 31 source files.

# Fix round 5: ruling R72

**Commit:** a92bd29 fix: decimal points, folded decimal zeros, slashes and more number separators (R72)

## Measurements

| Check | Result |
|---|---|
| Leave-one-out, the reviewer's p14 over all 28 corpus files in one run | **1,366 tried, 0 missed** |
| Corpus files masked by the full pipeline | **0 of 28 blocked** |
| `unverifiable` on the 28 files' entries, compared with d8f3c7a | **unchanged** for every file |
| Supply-10 scan (24 pages, 60 entries), 7 runs, nothing running alongside | median **0.184 s** (0.182–0.187 s), against 0.188 s after R71 |
| Tracing property check: 40,000 random number-heavy strings, plus 300 long texts traced in chunks | **0 mismatches**; the chunked mapping agrees in every view |

## What changed (src/themask/leakcheck.py)

### 1. A decimal point differs from the separators before it

`_decimals` replaces `_decimal_points`. A run's last separator is its decimal point when all of these hold:

- it is "." or ",";
- one or two digits follow it;
- no earlier separator in the same run is the same character.

This replaces R71's thousands-group guard.

- These keep their mark: "1,250.00", "1.250,00", "1'250.50", "1 250,50", "1250.00", "12,5".
- These lose it: "08.123.456.78", "123.456.78", "192.168.100.12".

### 2. Trailing zeros of a decimal part fold away

- "x50" becomes "x5". "x00" becomes nothing, and the point folds away with it.
- Examples: "1,250.50" → "1250x5", "1,250.00" → "1250", "1,250.05" → "1250x05".
- `_marked(text)` builds the text that the number view folds from. The point becomes "x" (or a space when only zeros follow), and the trailing zeros become spaces. `_folds` and `_traced` both use it.

**Tracing fix.** The number view is now traced from the marked text itself (`_prefolded_traced`). My first version skipped whole pieces of the original text instead. That lost a Hangul vowel joined to a dropped zero: 59 of 40,000 property strings mismatched. The guard turned each mismatch into None, never into a wrong place. Now there are 0.

Item 2 needed two follow-on changes, both my calls. Without them it would miss real hits or invent false ones.

**What folds away belongs to the number found.** `_located` extends a number match over the zeros that fold away, and over the point as well when only zeros follow it. Without this:

- the "0" of "EUR 1,250.50" touched a match for "EUR 1,250.5", so there was no hit;
- an exact "1,250.0" left in a file was no hit for its own entry.

Side effect: contexts now hide the ".00". R65's test had "Fee [AMOUNT_1].00 per year." and now gets "Fee [AMOUNT_1] per year.". Three existing expectations were updated (listed below). Cents still show after the placeholder: "[AMOUNT_2].50".

**A number counts only where the text writes it with four letters and digits or more.** "10.00%" folds to "10" and "€159.00" to "159". Searched bare, "10" would hit every "Clause 10".

- A number match now counts only where `normalize` of the matched text, with its folded zeros, keeps at least `MIN_LENGTH`. This is R14 c's own measure, applied on the text side.
- So "10.00%" is found as "10.00" or "10,00", and "€159.00" as "159.00", but neither is found as "10" or "page 159".
- `unverifiable` is unchanged.
- I first tried a guard on the key side, which reported a value as not checkable when its fold was short. In the corpus it made services-02's [AMOUNT_9] ("€159.00") not checkable, and stopped searching forms like "900,00" in five files. I dropped it.

### 3. The second name fold keeps the slash

`_GLUED` no longer drops "/". "and/or" folds to "and or", so it is no "Andor". North-wind still hits Northwind, and Acme BV still hits Acme B.V.

### 4. Thin space and curly apostrophe

U+2009 and U+2019 join `_GROUP_SEPARATORS`, which feeds both the number runs and the touch check, with no-break space semantics.

- "1 250" with thin spaces inside "1 250 000" with thin spaces: no hit.
- The same holds with curly apostrophes.

## Consequences to know (each checked against d8f3c7a)

- **"Northwind A/S" no longer matches "Northwind AS"** in the second fold. Before, it was a hit. Its variants still match as written.
- **"EUR 1,250.00" now hits "EUR 1,250.05"**, shown as "[AMOUNT_1].05". It folds to 1,250, and R65 treats cents after a number as no other number. Before, it was no hit.
- **"EUR 7.40" is no longer searched in the bytes of non-XML parts.** It folds to "eur7x4", five letters and digits without the mark, below `MIN_RAW_LENGTH` of 6. "EUR 7.4" was not searched there before either. XML parts are unaffected.
- **Unchanged, noted:** "1,250" is not found in "1,250.5". One digit after the point is no cents, because R65's tail is two digits.

## Tests (50 in tests/test_leakcheck.py; 4 new, 1 extended, 3 expectations updated)

New:

- `test_a_decimal_point_is_unlike_the_separators_before_it`:
  - PHONE "08 123 456 78" against "Tel. 08.123.456.78": hit;
  - ID "123.456.78" against "Register 123 456 78.": hit.
- `test_the_zeros_that_end_a_decimal_part_fold_away`:
  - "EUR 1,250.50" and "EUR 1,250.5" hit each other, both ways;
  - "EUR 1,250.00" hits "EUR 1,250" and "EUR 1,250.0";
  - "EUR 1,250.00" against "EUR 125,000": no hit.
- `test_a_number_counts_only_where_written_with_four_letters_and_digits`:
  - "10.00%" and "€159.00" are checkable;
  - "Clause 10 applies for 10 days." and "See page 159.": no hits;
  - "10,00%" and "159.00": hits.
- `test_a_thin_space_and_a_curly_apostrophe_group_thousands`: no "1 250" inside "1 250 000" with either separator; "In 2025 1 250 units" (thin space) is a hit.

Extended:

- `test_names_are_found_however_they_are_punctuated`: "and/or" against "Andor" is no hit. The North-wind and Acme BV hits stay.

Updated expectations (the ".00" is now inside the hit):

- `test_what_parts_a_number_from_a_number`: "Fee [AMOUNT_1] per year.".
- `test_a_decimal_part_stays_apart`: "A fee of [AMOUNT_2] applies." and "A cap of [AMOUNT_3] applies.".

"1,250.00 vs 125,000 is still no hit" is covered twice: by `test_a_decimal_part_stays_apart` (entry 125,000) and by the new zeros test (entry 1,250.00).

**RED:** against d8f3c7a's module, 6 failed: the three new R72 tests, the extended test and the two tests with updated expectations. The four-letters test passes on d8f3c7a by construction, because that version kept the zeros. Two mutants show that the new code is what passes the tests:

- without the written-length check, that test fails (1 failed);
- folding away zeros but never the point fails 4.

**GREEN:**

- `uv run pytest -q tests/test_leakcheck.py`: 50 passed.
- `uv run pytest -q`: 2413 passed in 47.82s.
- `uv run ruff check src tests tools`: All checks passed; `ruff format --check` is clean too.
- `uv run mypy src`: no issues in 31 source files.

## How to verify it yourself

1. In the task-14 worktree, run `uv run pytest -q tests/test_leakcheck.py -k "decimal or zeros or thin_space or four_letters or punctuated"`. Expect 6 passed.
2. RED: run `git show d8f3c7a:src/themask/leakcheck.py > src/themask/leakcheck.py`, then `uv run pytest -q tests/test_leakcheck.py`. Expect 6 failed. Restore with `git checkout -- src/themask/leakcheck.py`.
3. Leave-one-out: from the worktree, run the reviewer's `r14/p14_loo.py` with all 28 corpus names. Expect "left-one-out: 1366 tried, 0 missed".
