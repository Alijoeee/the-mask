# Final fix wave — report (F-1 … F-20)

Implementer: Claude (Fable 5.1), 19 October 2026. Worktree `/home/user/the-mask-worktrees/final-fixes`,
branch `final-fixes` from mac-v1 `3e7d6ea`. One commit per item (F-10/F-11 paired), every commit
green on the tests it touches, the full gate run at the end (section 3). Every reproduction of the
review (`SCRATCH/scripts/*.py`) was turned into a regression test under `tests/`; nothing imports
from the scratch folder. Nothing pushed; no other worktree or branch touched; the Keychain never
asked (the tests' fail backend stays); no Briefcase build.

Commits, in order (short SHA — subject): 7681573 F-1 (R100); f6af12b F-2 (R101); e3c52ec F-3 (R102);
42d2c39 F-4 (R112); 77ed1a2 F-5 (R113); 17be4b6 F-6 (R107); ad4375b F-9 (A1–A3); 4429baa F-7 (R105);
201b182 F-8 (R104); 2185c36 F-10 + F-11 (R110); f2440ae F-12; 1e6b98c F-13 (R114); c4061ca F-15 (R108);
c383393 F-16 (R109); a193dae F-17 (R111); 5a37663 F-18; 6876f02 F-14; 77d964e F-19; fa4df8e the
self-review fixes (section 4). F-20 needed nothing.

Reading order of the sections below: 1 per item (what changed, the tests added, RED → GREEN,
readings that differ from the review), 2 pass marks and round trip, 3 the full gate, 4 self-review,
5 concerns.

## 1. Per item

### F-1 (R100) — one identity per value type — commit 7681573

**Changed.**
- `src/themask/leakcheck.py`: `number_fold(text)` made public = the `_COMPACT` view of `_folds`
  (no second copy of the fold rules).
- `src/themask/detect/identity.py` (new): `value_key(kind, text)`. AMOUNT/PERCENT/QUANTITY → the
  currency/unit words (signs mapped to codes: €→eur, $→usd with the US$/A$/C$/NZ$/HK$/S$ prefixes,
  £→gbp, ₺→try, ¥→jpy, ₹→inr, ₽→rub; the words the AmountRecognizer knows → codes; "per cent" /
  "percent" / "pct" → nothing, as "%" is; a range's dash/"to" → the token "to" so that "10-20" is not
  1020) sorted + "|" + `number_fold` of the rest; EMAIL/URL → NFKC + casefold + whitespace removed;
  PHONE/IBAN/ID → `normalize`; PERSON/COMPANY/ADDRESS/CUSTOM → `normalize`.
- `src/themask/detect/grouping.py`: `value_key` in `_by_value`, `_Bucket.of_seed` (names),
  `_Bucket.own`, the `by_seed_key` lookup in `group_findings`, and the derived-form keys in
  `_settle_variants` (so a derived form is owned by key, not by `normalize`).
- `src/themask/detect/pipeline.py`: `_keep_shared_variants_out` on `value_key`.
- `src/themask/review.py`: `_holding` compares under `value_key(kind, …)` of the requested type (a
  plain always-hide "Acme" still joins the COMPANY group; "EUR 125" as AMOUNT no longer joins
  "EUR 1.25").
- The sweep keeps `flexible_pattern` (R11 guards decimals): identity decides what is one value.

**Tests added.** `tests/detect/test_grouping.py`:
`test_values_that_differ_in_a_point_a_symbol_or_a_dot_are_different_values` (the reviewer's A4
sentence verbatim), `test_the_spellings_of_one_value_are_one_group` (6 cases: "EUR 1,250.00" /
"EUR 1.250,00" / "1,250.00 EUR" / "EUR 1 250"; "€100" / "EUR 100" / "100 euros"; "10%" / "10.0%" /
"10 per cent"; quantities; IBAN spaced/unspaced; e-mail case), `test_what_tells_two_values_apart`
(decimal part, range vs 1020, US$ vs USD (one), units, URL hyphen, e-mail dot vs space),
`test_a_seed_never_takes_a_value_that_differs_only_in_a_point`,
`test_a_seed_takes_another_spelling_of_its_value`. `tests/detect/test_pipeline.py`:
`test_a_case_entry_never_takes_a_value_that_differs_only_in_a_point` (seed "EUR 1.25" vs finding
"EUR 125" in an added file), `test_values_that_differ_in_a_point_a_symbol_or_a_dot_get_their_own_placeholders`
(real engine, six placeholders). `tests/test_review.py`:
`test_hide_text_of_a_value_that_differs_only_in_a_point_makes_a_new_group` (`hide_text("EUR 125",
AMOUNT)` → new group; `hide_text("1,25 EUR", AMOUNT)` joins "EUR 1.25"). `tests/test_restore.py`
(new): `test_values_that_differ_in_a_point_a_symbol_or_a_dot_restore_to_themselves` — the real
round trip `export_case` + `restore_text` on the reviewer's sentence: masked text
`… [AMOUNT_1] … [AMOUNT_2] … [AMOUNT_3] … [AMOUNT_4] … [EMAIL_1] … [EMAIL_2].`, the key's six
entries each with its own value, restored text == the original, "6 placeholders restored, 0 need
your check."

**RED → GREEN.**
RED: `uv run pytest tests/detect/test_grouping.py -q -k "differ or spellings or tells or seed_never or seed_takes"`
→ `10 failed, 5 passed` (e.g. `test_a_seed_takes_another_spelling_of_its_value … ValueError: too many values to unpack`);
`uv run pytest tests/test_review.py tests/detect/test_pipeline.py -q -k "differs_only or differ_in_a_point"`
→ `3 failed` (the pipeline test: `+ s [AMOUNT_1] per customer. The deposit is [AMOUNT_2] and the refund is [AMOUNT_2]. Questions to [EMAIL_1] or to [EMAIL_1].`).
GREEN: `tests/detect/test_grouping.py` → `59 passed`; `tests/test_review.py tests/detect/test_pipeline.py tests/test_restore.py tests/detect/test_sweep.py` → all passed (226 at that point);
the pass marks and round trip after F-1: `uv run pytest tests/test_passmarks.py tests/test_corpus.py tests/test_export.py tests/test_leakcheck.py tests/test_textnorm.py tests/restore -q -m "slow or not slow"` → `802 passed in 195.67s`.

**Read differently.** (1) `identity.py` imports `number_fold` inside `_number_key`, not at the top:
`leakcheck` imports `grouping` (PersonName) and `pipeline` (the rescan), and `grouping` imports
`identity` — a module-level import is a cycle either way. The fold still lives in one place; the
alternative (moving the fold into `textnorm.py`) is the Windows-phase structure item. (2) Two
small additions beyond the letter of R100, both on the "two spellings are one value" side: "per
cent"/"percent"/"pct" count as "%" (so "10%" and "10 per cent" are one group), and a range's dash
or "to" is kept as a token so "EUR 10-20" is not "EUR 1020". (3) `_holding` keys every group's
forms under the *requested* type, so a plain always-hide of "Acme" (CUSTOM) still joins the
COMPANY group that has it (R62 unchanged).

### F-2 (R101) — every picture goes; a picture left blocks the export — commit f6af12b

**Changed.** `src/themask/docx/cleaner.py`: new step `_remove_media(pkg, main, texts, report)`
before `_sweep`: for the text parts, the numbering, the theme and every XML part with a media
relationship, `_strip_pictures` removes `w:background` whole, every `w:numPicBullet` and
`w:lvlPicBulletId`, the `r:id` of every `v:fill`, every `v:imagedata` left (the shape with it,
the image alone in a text box), every `a:blip` (its `blipFill` → `a:noFill`, in the theme →
`<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>` so the fill style lists keep three
children; a `pic:pic` goes whole; an `a:buBlip` goes), each counted in `CleanReport.images`;
the released relationships are dropped (`_release`); then every part under `word/media/` and
every part whose content type starts with image/, audio/, video/ or model/ goes (`_discard` →
`remove_part`), whatever still points at it. `am3d:model3d` joined `_DRAWING_PIECES` (note +
removal). `_sweep` no longer keeps referenced media. Docstrings updated ("Not touched" list).
`src/themask/leakcheck.py`: `media_left(path)` → one `LeakHit(part, "(picture)", "a picture or
media file the cleaner could not remove is still in the file")` per media-named or media-typed
part and per `.rels` part holding an image/audio/video/media/model relationship (an unreadable
`[Content_Types].xml` or `.rels` counts as a hit). `src/themask/export.py`: `_scanned(path, key)`
= `scan_package` + `media_left`, used for the file and its twin.

**Tests added.** `tests/docx/test_cleaner.py`: `test_every_picture_goes_wherever_it_is_reached_from`
(the reviewer's a5.docx shape: background, picture bullet, theme image ×2, VML fill, orphan rel,
header picture → no `word/media/*`, no image relationship, no `w:background`, no
`numPicBullet`/`lvlPicBulletId`, theme without `blip` and with three `solidFill`s per list,
`images == 6`, python-docx opens the saved file), `test_a_3d_model_is_a_picture_with_its_part`,
`test_a_media_part_goes_by_its_content_type_wherever_it_is`; three existing tests updated with a
comment naming R101 (`test_the_image_of_a_picture_bullet_goes_with_the_bullet`,
`test_a_picture_that_something_else_still_uses_goes_as_well`,
`test_a_part_takes_the_parts_only_it_used_and_leaves_the_shared_ones`). `tests/test_export.py`:
`test_a_picture_the_cleaner_could_not_remove_blocks_the_export` (planted after cleaning →
`blocked`, hit `("word/media/planted.png", "(picture)", MEDIA_LEFT)`, nothing written),
`test_an_image_relationship_left_behind_blocks_the_export`. `tests/test_leakcheck.py`:
`test_a_media_part_or_relationship_left_in_a_file_is_a_hit`. The corpus's image files are
covered by the existing corpus export tests and the round trip (section 2).

**RED → GREEN.** RED: `uv run pytest tests/docx/test_cleaner.py -q -k "media or picture_bullet or 3d_model or shared_ones or wherever"` → `5 failed, 2 passed`.
GREEN: `tests/docx` → `308 passed` then `320 passed` (after F-4); `tests/test_export.py tests/test_leakcheck.py tests/test_corpus.py` → `135 passed in 80.52s`.

### F-3 (R102) — namespace declarations and foreign names — commit e3c52ec

**Changed.** `src/themask/leakcheck.py`: `_Reader._declarations` adds, for each namespace an element
declares itself (its `nsmap` minus the parent's), a `_Block(address, "xmlns:<prefix>", no_digits)`
unless the address is a format address, and a block for the prefix; `_Reader._name` adds a block
for the local name of every element and attribute outside the format namespaces (a camel-cased
name split into its words: "NorthwindTradingBV" → "Northwind Trading BV"), labelled `element
name=` / `attribute name=`; `_FORMAT_ADDRESSES` gained `http://purl.org/dc/`;
`_is_format_address` / `_is_format_namespace` helpers. `src/themask/docx/cleaner.py`:
`_strip_unused_namespaces` runs `etree.cleanup_namespaces(root, keep_ns_prefixes=KEEP)` on every
XML part, KEEP = every prefix named in any `mc:Ignorable`/`mc:MustUnderstand`/`mc:ProcessContent`
attribute of the part plus every prefix of `NS`.

**Tests added.** `tests/test_leakcheck.py`: `test_namespace_declarations_and_foreign_names_are_read`
(the reviewer's a6 shape: hits `xmlns:ns0="urn:[COMPANY_1]:contract-schema"`,
`xmlns:nw="http://[COMPANY_1].example/2026/templates"`, `attribute name="[COMPANY_1] Ref"`,
`element name="[COMPANY_1]"`, nothing shown),
`test_the_file_formats_own_namespaces_and_names_are_no_hits` (values spelt like "Schemas
Openxmlformats", "Purl Org", "document"/"body"/"rPr" → no hit). `tests/docx/test_cleaner.py`:
`test_a_declaration_nothing_uses_goes_and_one_in_use_stays` (unused `ns0` gone, used `nw` kept,
`mc:Ignorable="w14 wp14"` keeps both declarations, python-docx opens the result),
`test_every_corpus_file_keeps_its_ignorable_prefixes` (supply-01, the trap). Three existing
"left as it is" byte-equality tests now compare `content(pkg)` (the part with unused
declarations dropped the same way), with a comment naming R102.

**RED → GREEN.** RED: `uv run pytest tests/test_leakcheck.py tests/docx/test_cleaner.py -q -k "namespace or formats_own or declaration or ignorable"` → `2 failed, 2 passed` (the leak-check hits `[] == [...]`; the declaration still in the saved bytes).
GREEN: `tests/docx tests/test_leakcheck.py` → `364 passed`; `tests/test_export.py tests/test_corpus.py tests/test_restore.py` → `85 passed in 68.58s` (the 28 corpus files export unblocked).

### F-4 (R112) — links to the outside, permissions, field data, authors — commit 42d2c39

**Changed.** `src/themask/docx/cleaner.py`: `_remove_external_links(root)` after
`_remove_hidden_runs`: every `w:hyperlink` with `r:id` unwrapped (text stays; anchor links stay),
`a:hlinkClick`/`a:hlinkHover`/`a:hlinkMouseOver` removed, VML `href`/`o:href`/`o:hrlabel` deleted;
counted in the new `CleanReport.links_removed`. `_remove_editing_marks(root)`: `w:permStart`/
`w:permEnd` removed, every `w:fldData` removed, every `w:author`/`w:ed`/`w:edGrp` attribute left
deleted (counted in `attributes_cleared`). `HYPERLINK`, `INCLUDEPICTURE`, `INCLUDETEXT`,
`INCLUDE`, `IMPORT`, `LINK` joined `_FLATTENED_FIELDS`. The relationships go through the existing
`_release`; an emptied `.rels` part through `_sweep`. `README.md`: "Links to web pages and e-mail
addresses are removed from the masked copy; the link text stays." (F-20's sentence.)

**Tests added.** `tests/docx/test_cleaner.py`: `test_contact_data_that_stands_only_in_links_and_marks_goes`
(the reviewer's b_links file: none of the three addresses in the saved bytes, no hyperlink
relationship, no `permStart`/`permEnd`/`w:ed`/`edGrp`, text "Notices to the Supplier: click here
or this address.\nThe Buyer may edit this clause.\nSigned by John Carter for the Buyer.",
`links_removed == 1`, `fields_flattened == 1`), `test_an_internal_link_stays_and_a_hyperlink_field_becomes_its_text`,
`test_a_field_that_reads_a_file_or_an_address_becomes_its_result` (×5 field names),
`test_links_on_shapes_go_and_the_shapes_stay`, `test_field_data_and_editing_marks_go_and_the_rest_stays`.
Updated with a comment naming R112: `test_a_link_loses_its_tooltip_and_its_target_and_keeps_its_text`,
`test_a_link_that_also_holds_visible_text_keeps_the_text_and_loses_its_target`,
`test_a_link_on_a_picture_goes_with_it`, `test_other_fields_are_left_alone` (a REF field in place
of the HYPERLINK), the corpus layout count (`STRUCTURE` without `w:hyperlink`).
`tests/test_export.py`: `test_the_corpus_files_with_links_export_without_their_links` (services-01,
nda-01, dpa-01: unblocked, no `mailto:`, no hyperlink relationship in the masked copy);
`test_a_value_marked_in_one_file_leaves_the_names_and_links_of_the_others` and
`test_a_value_of_the_case_leaves_a_file_added_that_never_shows_it` now use a bookmark named after
the value (R82/R83 still exercised; the link goes anyway).

**RED → GREEN.** RED: `uv run pytest tests/docx/test_cleaner.py -q -k "links or link_ or hyperlink_field or reads_a_file or field_data or shapes_go"` → `12 failed, 7 passed`.
GREEN: `tests/docx` → `320 passed`; the three export tests → `5 passed`.

### F-5 (R113) — the note stands apart; the analysis cuts at a note — commit 77ed1a2

**Changed.** `src/themask/instruction.py`: `EQUATION_NOTE`, `ALTCHUNK_NOTE` moved here (the cleaner
re-exports them), `NOTES` tuple. `src/themask/docx/cleaner.py`: `_note` builds a run of its own
holding the note with a space `w:t` (xml:space="preserve") before it when the paragraph's text
before the element does not end in whitespace and after it when the text after does not start
with one (`_text_around`, which ignores the element's own subtree, fallback copies and nested
text-box paragraphs, as the reader does); `_put_note` cuts the run that held the element there
(what follows goes into a tail run with the same properties; an `mc:AlternateContent` stays for
`_remove_fallbacks`). Wording of the four notes unchanged. `src/themask/detect/pipeline.py`:
`_detected` passes the spans of the four note strings to `_cleaned`, which cuts a finding at
them as at a line break.

**Tests added.** `tests/docx/test_cleaner.py`: `test_a_note_stands_apart_from_the_text_beside_it`
(header "Acme Supplies Ltd" + picture → "Acme Supplies Ltd [image removed]", runs
`[["Acme Supplies Ltd"], [" ", "[image removed]"]]`), `test_a_note_is_spaced_by_what_stands_beside_it`
(×4: both sides, none where the text has spaces, none at the paragraph start, a tab),
`test_every_kind_of_note_is_spaced_the_same_way` (object and equation notes).
`tests/detect/test_pipeline.py`: `test_a_finding_is_cut_at_a_note_as_at_a_line_break` (the model's
"Acme Supplies Ltd[image" and "removed]Northwind" → `[COMPANY_1][image removed] sells. [embedded
object removed][COMPANY_2] buys.`), `test_the_real_engine_reads_a_name_beside_a_note_as_the_name`
(real engine: no canonical or finding holds "[", "Acme Supplies Ltd" is [COMPANY_1]). The corpus
image files are covered by the pass marks (section 2).

**RED → GREEN.** RED: `… -k "note or spaced …"` → the six cleaner tests failed (`'Acme Supplies Ltd[image removed]'`), the two pipeline tests failed.
GREEN: `tests/docx tests/test_review.py` → `378 passed` (after one correction of my own: an
`mc:AlternateContent` must stay for the fallback count), `tests/detect/test_pipeline.py tests/detect/test_sweep.py` → `176 passed`.

### F-6 (R107) — merging and splitting the key's groups — commit 17be4b6

**Changed.** `src/themask/review.py`: `merge` raises `ValueError("[COMPANY_1] and [COMPANY_3] are
both in the case's key and cannot be merged; leave them as two values.")` (the real placeholders;
three or more: "… are all in the case's key …; leave them as separate values.") when more than one
group's placeholder is reserved; with exactly one, it survives whatever its number and keeps its
canonical form; `split` of a reserved group never changes its canonical (it stays among the
variants). R86 (`export._merged`) unchanged.

**Tests added.** `tests/test_review.py`: `test_two_groups_the_case_key_holds_cannot_be_merged` (the
reproduction, the exact message), `test_a_group_the_case_key_holds_survives_a_merge_with_its_form`
(reserved [COMPANY_3] merged with [COMPANY_2] → [COMPANY_3], canonical kept, forms joined, plan),
`test_splitting_a_group_the_case_key_holds_leaves_its_canonical`. `tests/test_export.py`:
`test_a_merge_in_a_file_added_never_rewrites_a_value_of_the_case` updated (comment names R107: the
canonical stays the stored value in the review too; the longer form is a variant).

**RED → GREEN.** RED: the three review tests failed (`merge accepted`, canonical changed).
GREEN: `tests/test_review.py` → `56 passed`; the two export tests → `2 passed`.

### F-9 (A1–A3) — the number folds — commit ad4375b

**Changed.** `src/themask/leakcheck.py`: (A1) `_located` keeps the unextended end for the
right-hand digit test and passes `closed=` (the end was extended over a folded-away decimal part,
or the needle holds a decimal mark between digits) to `_touched`, which then skips the right-hand
test; `_touched`/`_digit_at` take `grouped` (the matched text holds a digit-`,`/`.`-digit): a plain
space is then no separator on either side. (A2) `_Needles.of` records per needle whether some
form of it has ≥ 6 letters and digits and is not all digits (`raw`); `for_bytes` filters on
that. (A3) needles map to a tuple of placeholders (`_add`); `find` yields a `_Match` per
placeholder; `_located` keeps every placeholder of a place (same span, different placeholder);
`_counted` reports one hit per placeholder.

**Tests added.** `tests/test_leakcheck.py`: `test_a_decimal_part_or_a_group_separator_ends_a_number`
(the reviewer's six lines with their counts, plus "Price No. 100 1,250.00 applies" → 1, "1 250 000"
→ 0, "125,000.00" → 1), `test_a_short_amount_is_found_in_the_bytes_of_a_part_by_its_own_length`
("EUR 10.00" in a binary part → hit; "EUR 10" not searched), `test_two_entries_that_fold_alike_are_each_reported`
(amount pair and the ID/PHONE pair → one hit per placeholder, each context with its own
placeholder, `hits_by_placeholder` 1 each). ("1,250" in "In 2025 1,250 units" and "1 250" not in
"1 250 000" are in the existing tests.)

**RED → GREEN.** RED: `uv run pytest tests/test_leakcheck.py -q -k "ends_a_number or own_length or fold_alike"` → `5 failed, 6 passed`.
GREEN: `tests/test_leakcheck.py` → `64 passed`; `tests/docx/test_masker.py tests/test_export.py tests/restore` → `239 passed`.

**Read differently.** Two of my first expectations were wrong, not the code: a `QUANTITY` entry
whose variant "1 250" folds like the amount's "1,250" is rightly a second hit at that place (A3),
so the A1 test's entries hold no such variant; and a value whose fold is shared keeps its own
placeholder in its own context (the hit's span is merged first), so the contexts read
`[AMOUNT_1]` / `[AMOUNT_2]` respectively.

### F-7 (R105) — a count written as a range after a reference — commit 4429baa

**Changed.** `src/themask/detect/patterns.py`: `_SPACED_DIGITS = \d(?:_SPACE|_TO)\d`; G2:
`_QUANTITY_REFERENCE` requires the capital for Schedule/Section/Article/Exhibit used as words
(the abbreviations with their full stop stay case-insensitive).

**Tests added.** `tests/detect/test_patterns.py`: `test_a_count_written_as_a_range_after_a_reference_is_still_found`
(R105's two sentences verbatim + "Section 2 - 10,000 units minimum", "Article 3 to 1,000 pieces"),
`test_the_range_after_a_reference_is_hidden_by_the_whole_pipeline` (engine), `test_a_reference_word_used_as_a_word_leaves_the_count_a_count`
("shall schedule 500 pallets …", "shall exhibit 12 units …", "per article 12 pieces …", "Each
section 3 metres long."). "Schedule 3 Pallets", "Annex 2 Units of Measure", "the Art. 30
records" are in the existing `test_a_reference_a_year_or_a_single_record_is_no_quantity`.

**RED → GREEN.** RED: `9 failed`. GREEN: `tests/detect/test_patterns.py` → `365 passed`.

### F-8 (R104) — zip limits — commit 201b182

**Changed.** `src/themask/docx/package.py`: `MAX_ENTRIES = 10_000`, `MAX_PART_SIZE = 256 MiB`,
`MAX_TOTAL_SIZE = 1 GiB`; `open` checks `infolist()` first (`_within_limits`) and refuses with
`NOT_A_DOCX_MESSAGE`; `_read_entry` reads through `archive.open(info)` capped at the declared size
and refuses an entry that gives another number of bytes (a CRC mismatch raises `BadZipFile`,
already a refusal).

**Tests added.** `tests/docx/test_package.py`: `test_an_entry_declared_too_big_is_refused_before_it_is_read`
(257 MiB declared, 260 KB on disk; refused in < 2 s), `test_too_many_entries_are_refused_and_many_are_fine`
(10,001 refused, 9,999 accepted), `test_entries_too_big_together_are_refused` (the total, with
the limits brought down by monkeypatch), `test_an_entry_whose_header_lies_about_its_size_is_refused`.
The corpus files open in the existing tests.

**RED → GREEN.** RED: `3 failed, 4 passed`. GREEN: `tests/docx/test_package.py` → `43 passed`.

### F-10 (R110) and F-11 — the revisions resolver — commit 2185c36

**Changed.** `src/themask/docx/revisions.py`: `w14:conflictIns`/`w14:conflictDel` in `_TRACKED`, in
`_ACCEPT.gone`/`_REJECT.gone` like `w:del`/`w:ins`; `_OWNERS` maps each `*Change` record to its
owner and `_restore` only removes a record that is not in its owner. `src/themask/docx/reader.py`:
the two in `_INSERTED`/`_DELETED` and `_REVISIONS`.

**Tests added.** `tests/docx/test_revisions.py`: `test_co_authoring_conflict_marks_are_resolved_like_insertions_and_deletions`
(the reproduction: accept → "Price: EUR 9,999", reject → "Price: EUR 1,111", `has_revisions`
True before / False after, no author left), `test_a_change_record_out_of_its_place_only_goes`.

**RED → GREEN.** RED: both failed. GREEN: `tests/docx/test_revisions.py tests/docx/test_reader.py …` → `301 passed`.

### F-12 — hiding a value switches its places back on — commit f2440ae

**Changed.** `src/themask/review.py`: `_hide` discards from `group.disabled` every occurrence whose
text has the value's key, adds the value to the group's variants, and `_holding` also matches the
forms a group was seen in (so an always-hide after a never-hide of the same short form reaches
the group whose variant the never-hide removed).

**Tests added.** `tests/test_review.py`: `test_hide_text_switches_a_place_switched_off_back_on`,
`test_always_hide_after_a_never_hide_of_the_short_form_hides_it_again` (both sequences of the
reproduction end with every place in the plan).

**RED → GREEN.** RED: both failed. GREEN: `tests/test_review.py` → `56 passed`.

### F-13 (R114) — the twin replaces every group — commit 1e6b98c

**Changed.** `src/themask/export.py`: `_whole_plan(groups)` replaces every finding of every group.

**Test added.** `tests/test_export.py`: `test_places_split_off_and_switched_off_whole_are_left_visible_not_leftovers`
(the reproduction: unblocked, two `allowed_hits` places for [COMPANY_1], the body text
`[COMPANY_1] sells. [COMPANY_1] buys. Acme delivers. Acme ships.`).

**RED → GREEN.** RED: blocked. GREEN: the export gate tests → `9 passed`.

### F-14 — the merged key filtered like a key entry — commit 6876f02

**Changed.** `src/themask/review.py`: `key_variants(kind, canonical, forms)` (public; `key_entries`
uses it). `src/themask/export.py`: `_merged` lists a stored entry's variants through it.

**Tests added.** `tests/test_export.py`: `test_a_stored_entry_takes_no_bare_surname_and_nothing_too_short_from_an_added_review`
(end to end), `test_the_merged_key_lists_forms_the_way_a_key_entry_does` (on `_merged` itself:
"Berg", "J", "" dropped from a "Jan van der Berg" entry; "Mr Berg" and "J. van der Berg" kept).

**RED → GREEN.** RED: the direct test failed (`['', 'Berg', …]`); the end-to-end test passes on
HEAD too (section 4 explains). GREEN: `9 passed`.

**Read differently.** After R107 the review's canonical of a seeded group is the stored value, and
`key_entries` already filters variants, so `export_case` could no longer hand `_merged` a bare
surname; the fix is the invariant on `_merged` itself (a future caller), tested directly.

### F-15 (R108) — a placeholder twice in a key — commit c4061ca

**Changed.** `src/themask/model.py`: `Case.from_json` raises "Not a stored case." when two entries
share a placeholder. **Tests added.** `tests/test_model.py`: `test_case_from_json_refuses_a_key_holding_a_placeholder_twice`;
`tests/keystore/test_cases.py`: a new `DAMAGED_FILES` entry "a placeholder twice in the key" (the
store's existing parametrized tests then prove it is refused on load and listed as unreadable).

**RED → GREEN.** RED: `DID NOT RAISE ValueError`. GREEN: `tests/test_model.py tests/keystore/test_cases.py` → passed (part of the `301 passed` run).

### F-16 (R109) — commit c383393
`LeakBlockedError` removed from `src/themask/errors.py`; `tests/test_about.py` no longer imports it
and `test_a_blocked_export_is_no_error_class` pins its absence.

### F-17 (R111) — commit a193dae
`src/themask/ui/app.py`: `GarbageCollector(QObject)` (a `QTimer`, `INTERVAL_MS = 2000`, generations
cycled 0, 0, 1, 0, 0, 2; `start()` = `gc.disable()` + timer, `stop()` = timer off + `gc.enable()`);
`main` starts it once the window is shown, owned by the application, and stops it after
`wait_for_workers()`. The UI tests' `collect_in_the_main_thread_only` fixture stays.
**Tests.** `tests/test_main.py`: the entry-point program prints `collector running: True`, `gc
enabled while the window lives: False`, `gc enabled after: True`
(`test_the_collector_runs_from_the_gui_thread_while_the_window_lives`, and the exact-stdout test
updated); `test_the_collector_collects_cyclic_garbage_when_its_timer_fires` (in-process, qtbot:
a cycle survives with the automatic collector off and is gone once the timer fires);
`test_the_collector_takes_the_generations_in_turn`.

### F-18 — commit 5a37663
`OWNER_NAME = "Alican Yazdic"`; `tests/ui/test_cases_settings.py::test_…about…` (`OWNER_NAME in about_label.text()`) passes.

### F-19 — commit 77d964e
Every wall-clock limit × 3, each with the comment "three times the usual, for a loaded machine":
`tests/pdf/test_extractor.py` 5 → 15 and 10 → 30; `tests/test_leakcheck.py` 2.0 → 6.0, renamed
`test_twenty_four_pages_are_scanned_in_under_six_seconds`; `tests/docx/test_reader.py` 2 → 6,
renamed `test_twenty_four_pages_are_read_quickly` (the docs item riding along: supply-10 is 24
pages); `tests/ui/test_review_screen.py` 2.0 → 6.0 (both); `tests/detect/test_contract_rules.py`
1.0 → 3.0 and 2.0 → 6.0; `tests/detect/test_patterns.py` 1.0 → 3.0. The 30 s corpus test and the
60 s pass mark unchanged; nothing deleted or marked slow. (F-8's new refusal test uses < 2 s:
the read it guards against takes ≥ 3 s, so ×3 of "well under a second" would make it blind.)

### F-20 — nothing to fix; the README sentence landed with F-4.

## 2. Pass marks and round trip

Measured after the last commit (`fa4df8e`) on the generated corpus (made-up files), with
`tools.evaluate.evaluate` run from the worktree root
(`PYTHONPATH=. uv run python <scratchpad>/passmarks.py`), and by the suite's own pass-mark tests
inside both full gates (`tests/test_passmarks.py`, `-m slow`):

```
pattern found/total: (913, 913)
names found/total: (320, 320)
never-hide false positives: []
misses: []
type accuracy: 0.9992
seconds for the thirty-page file: 8.0
documents evaluated: 35 in 44 s
```

Identical to HEAD's figures in the review (913/913, 320/320, 0 never-hide hits). The full round
trip (`test_full_round_trip_every_docx`: every Word file of the corpus masked, changed as an AI
tool would, restored; every key value and every truth secret back in the text) ran green in both
full gates — 28/28 (the manifest's 28 Word files; the test asserts file by file and fails on the
first). The 60 s mark (`test_thirty_pages_under_sixty_seconds`, docx and pdf) passed in both
gates as well.

## 3. The full gate

All from `/home/user/the-mask-worktrees/final-fixes` at `fa4df8e` (the final tree; the working
tree clean, `git status --short` empty):

| Command | Last line |
|---|---|
| `uv run pytest -q -m "slow or not slow" -p no:cacheprovider` (everything, slow included; log: `<scratchpad>/gate2-pytest.log`, 50 lines, no warning summary, no error) | `3343 passed, 8 skipped in 380.68s (0:06:20)` / `EXIT 0` |
| the same gate once before the self-review commit (all 20 items in, log `gate-pytest.log`) | `3343 passed, 8 skipped in 379.04s (0:06:19)` / `EXIT 0` |
| `uv run ruff check src tests tools packaging` | `All checks passed!` |
| `uv run ruff format --check src tests tools packaging` | `142 files already formatted` |
| `uv run mypy src` | `Success: no issues found in 53 source files` |

The 8 skips are HEAD's (the review's run had the same 8): vtool/iconutil/codesign and the R99
loop are macOS-only, one socket family is absent on this box. The only line on stderr in every
command is uv's own `UV_NATIVE_TLS` deprecation notice, printed by this container's environment
before anything runs; the test output itself is pristine.

No wall-clock test failed in either full gate, so none had to be re-run alone. The one run that
did fail under load was a partial run (the F-19 files) started while the first gate was going:
`tests/ui/test_review_screen.py` ended with 41 fixture errors and one failure there; alone it
passes (`52 passed in 14.53s`) and both gates passed it.

## 4. Self-review (the whole diff, `git diff 3e7d6ea..HEAD`)

Read the whole diff of `src/` and `tests/` after the last item. Found and fixed in the last commit
(`fa4df8e`):

1. `_located` (F-9) closed a match on the right when its needle held any "x": a literal letter
   (an id "AX1234") would have skipped the right-hand digit test and reported a hit inside
   "AX12345". Now `_DECIMAL_POINT_IN_KEY` (a mark between digits) decides. Fail-closed either
   way, but wrong.
2. `_Reader._element` (F-3) told a namespaced attribute by a ":" in its Clark name; a namespace
   URI without a colon would have slipped. Now by the leading "{".
3. `media_left` (F-2) reported every part when `[Content_Types].xml` could not be read; now one
   hit on that part (it is written by `pkg.save` from a parsed tree, so this is belt and braces).
4. Six docstring lines of mine over 100 characters (the formatter does not reflow docstrings) and
   the two `_Side` lines; the lines still over 100 in `leakcheck.py` (the CJK font names),
   `patterns.py:720` and `revisions.py:125` are HEAD's, untouched.

Checked and left as they are:

- `identity.py` imports `number_fold` inside the function: `leakcheck` imports `grouping` and
  `pipeline`, so a module-level import would be a cycle; one copy of the fold rules, as asked.
- `_remove_media` always parses the text parts, the numbering and the theme, and any XML part
  with a media relationship; `_strip_unused_namespaces` parses every XML part. So a damaged
  non-text XML part (a `styles.xml` that is not XML) now makes `clean` raise `UnsupportedFileError`
  ("not a .docx"), where before it passed through unread and the leak check byte-scanned it.
  Fail-closed, and Word refuses such a file too; noted under concerns.
- `_text_around` (F-5) leaves out a fallback copy and a text box's paragraphs, as the reader does
  (a chart's "This chart is not available…" fallback no longer earns the note a trailing space).
- `_put_note` leaves an `mc:AlternateContent` for `_remove_fallbacks`, so `fallbacks_removed`
  counts as before.
- `_hide` (F-12) also adds the hidden value to the group's variants: the review's letter asked
  only for the switch; without it, a form the never-hide list had removed would hide here but
  leave the key without it. The pass marks and the whole suite agree.
- `_two_stored` wording for three or more groups ("… are all in the case's key …; leave them as
  separate values.") is my extension of the two-group message the ruling fixes verbatim.
- The twin (F-13) now masks the findings of groups whose placeholder is not in the key; the
  masker then also takes those values out of the twin's links and instructions, which the twin
  discards anyway.
- Every test the wave changed is named with the ruling in a comment; none was weakened to pass
  and none deleted. The tests of `_merged` (F-14) and `media_left` call a private function and a
  public one respectively, as the neighbouring tests do.

## 5. Concerns

1. **A damaged non-text XML part is now refused at clean time** (see self-review): `clean`
   parses every XML part for R102 (and the numbering/theme for R101). A Word file with a
   malformed `styles.xml`/`webSettings.xml` gets "This is not a Word .docx file" instead of a
   masked copy whose damaged part the leak check only byte-scanned. Fail-closed and consistent
   with the cleaner's docstring ("a file that cannot be cleaned is not passed on as clean"); if
   the re-review prefers the old tolerance, the cleanup could skip parts that do not parse.
2. **Wall-clock tests under load.** While the first full gate ran, a second pytest process on the
   same four cores (the F-19 files) ended with 41 fixture errors in `tests/ui/test_review_screen.py`
   and one failure; alone, the file passes (`52 passed`) and both full gates passed it. The
   limits are now ×3; the new F-8 refusal test keeps < 2 s (a read of the 257 MiB entry takes
   ≥ 3 s, so ×3 of "well under a second" would make it blind).
3. **Identity edges (F-1).** "EUR 1.25m" and "EUR 1,250,000" stay two values (as before);
   "US$100", "USD 100" and "100 dollars" are one; the Nordic "kr"/"krona"/"kronor" fold to one
   word, "SEK 100" is another value. Two placeholders for one value cost a line in the key, never
   a wrong restore (the ruling's accepted side).
4. **R102 false blocks.** A namespace URI or a foreign element name that happens to spell a
   marked word now blocks (the ruling's accepted cost); the standard addresses, `purl.org/dc`
   and the W3C/Microsoft ones are exempt.
5. **The GUI collector (F-17)** is stopped only after `application.exec()` returns; if `exec`
   raised, the process ends anyway. The in-process test uses pytest-qt's `qtbot` outside
   `tests/ui` (its `collect_in_the_main_thread_only` fixture does not apply there); it restores
   `gc` in a `finally`.
