# Task 12 report: Cleaner (hidden places)

**Status: DONE_WITH_CONCERNS** (one concern that the process rules ask me to raise rather than fix myself:
`cleaner.py` is 859 lines, see "Concerns", item 1).

Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-12`, branch `task-12`, three commits on top of
`mac-v1` c7a4bfa:

- `70a5d50 feat: cleaner removes comments, properties, hidden text, images and settings traces`
- `f6fd5b4 feat: cleaner flattens property fields, clears content control titles` (extension round)
- `1e160c9 fix: cleaner drops hidden links, keeps text beside pictures, leaves no dangling part` (fix round 1, the last section)

The numbers in the body (91 test cases, 1433 in the suite, 26 mutants) are those of the first commit;
the extension section has those of the second commit (99, 1441, 30); the last section has the current ones
(117 test cases, 1459 in the suite, 51 mutants).

Files (both new, nothing else touched; no `tests/fixtures/cleaner.py` was needed):

- `src/themask/docx/cleaner.py` (859 lines)
- `tests/docx/test_cleaner.py` (1657 lines, 81 test functions, 91 test cases with parametrisation)

## What I implemented

`clean(pkg: DocxPackage, now: datetime | None = None) -> CleanReport`. It changes `pkg` in place and
reports what it removed. `now` is the time the core `dcterms:created` and `dcterms:modified` are set to
(UTC, to the second, `...Z`; a time without a zone is taken as UTC; default: the present).

`CleanReport(comments, images, objects, hidden_runs, properties_cleared, parts_removed, fields_flattened,
fallbacks_removed, equations_removed, altchunks_removed, attributes_cleared, stray_runs_removed)`, every
field with a default (`CleanReport()` is the empty report, so reports compare with `==`). The first six
are in the brief's order, the rest are the controller's extra fields plus R24's `stray_runs_removed`.
`properties_cleared` names each property that held something, as the brief spells them (`dc:creator`,
`cp:lastModifiedBy`, ..., `dcterms:created`, `Company`, `Template`, `TitlesOfParts`, ...) and
`custom:<name>` for each custom property; `parts_removed` is every zip entry that is gone, in zip order
(so the `.rels` parts that went along are in it).

Steps, in the controller's order (decision 10), with the placement choices in the next section:

1. Comments: the five comment parts found by name, by content type and by the main document's
   relationship type; `commentRangeStart/End` and `commentReference` out of every text part.
2. Revision traces: every `w:rsid*` attribute and every `w:rsid`/`w:rsids` element, in the text parts
   and in every other XML part under `word/` that mentions one (styles, numbering, settings, ...).
3. Per text part, in `TEXT_PARTS` order:
   - R24 (new, from the coordinator): runs with no `w:p` ancestor are deleted and counted
     (`stray_runs_removed`). The reader only walks paragraphs, so such a run (what accepting or
     rejecting a block-level `w:ins`/`w:del` leaves in the body, a table, a row or a cell) is never
     shown, never masked and would travel in the file. Checked: `extract_text` does not show it, the
     bytes still hold it.
   - R22: `fldSimple` and complex fields whose instruction begins with AUTHOR, USERNAME, USERINITIALS,
     LASTSAVEDBY, FILENAME, TEMPLATE, DOCPROPERTY or INFO (any case, any spacing, split over several
     `instrText` runs) become plain text; their result runs stay.
   - R19: text watermarks (a `w:pict` with a `v:textpath` shape, no note), `w:smartTag` unwrapped,
     children of `w:comboBox`/`w:dropDownList` removed, `w:ffData` removed, `w:hyperlink/@w:tooltip`
     deleted, `w:tblCaption`/`w:tblDescription` removed.
   - Hidden text: `w:r` whose own `w:rPr` has `w:vanish` or `w:specVanish`; the paragraph stays, empty.
   - Pictures and objects: `w:object` is OBJECT_NOTE; a `w:drawing` with `a:blip`, `c:chart` or
     `dgm:relIds` and a `w:pict` with `v:imagedata` are IMAGE_NOTE; the note takes the place of the
     element inside its run. Their relationships and parts go (media, charts with their workbooks,
     diagrams, embeddings, linked-picture paths, hyperlinks on a picture). Text boxes are kept.
   - R17: `m:oMath`/`m:oMathPara` become a run `[equation removed]`; `w:altChunk` becomes a paragraph
     holding `[embedded content removed]` and its part goes.
   - R19, last of its kind: `wp:docPr` loses `@descr` and `@title` and is named `Shape<N>` (numbered
     across the parts in reading order, after the pictures so a removed picture takes no number).
   - `w:dataBinding` removed (the content control keeps its text).
   - R16: every `mc:Fallback` deleted, `mc:AlternateContent` replaced by the children of its first
     `mc:Choice`.
   - The relationships the part no longer refers to are released, and the parts only they led to go.
4. Package: `docProps/core.xml`, `docProps/app.xml` (including `HLinks`), `docProps/custom.xml`;
   `customXml/*`, `word/glossary/*`; then the settings (`w:docVars`, `w:attachedTemplate` with its
   relationship, `w:rsids`, `w:trackRevisions`); finally a sweep of `word/charts/`, `word/diagrams/`,
   `word/embeddings/` and of `word/media/` parts nothing leads to, and of `.rels` parts left empty.

The module docstring lists the same steps and the limits below.

## Decisions where the brief and the controller left room

- Per part, not per step. The steps run for one text part after the other instead of each step over all
  parts. Nothing crosses parts except the `Shape<N>` counter (which follows `TEXT_PARTS` order either
  way), so the result is the same and each part is parsed once.
- Copies are skipped, not cleaned twice. Passes that count (hidden runs, pictures, fields, attributes)
  ignore everything inside an `mc:Fallback`, because step R16 deletes it; otherwise a picture with a VML
  fallback would be two images. The relationships the fallback used are released all the same.
- A drawing is a picture only by its own graphic: an `a:blip` inside a text box of the drawing does not
  make the text box a picture (the brief's "drawings that only hold a text box are kept"); the picture
  inside it is replaced alone. Same for `v:imagedata` in a VML text box.
- Hidden toggles honour `w:val`: `w:vanish w:val="0|false|off"` hides nothing; `w:webHidden` (the page
  numbers of a contents page) is not hidden text.
- A run that holds `w:commentReference` and also text keeps the text (only the reference goes); a run
  that held nothing else is deleted, as the brief says.
- Of several `mc:Choice` the first is kept (Word's pick); the reader would otherwise read all of them.
- `w:altChunk` is a block-level element, so its note is a run inside a new `w:p`, not a bare run.
- `@descr` and `@title` are deleted, not set to "". (If a reviewer's test expects `== ""` this is a
  one-line change.)
- `attributes_cleared` counts pieces: each tooltip, description, title, shape name changed, text
  watermark, smart tag, custom XML tag, list control that had items or a last value, form-field
  data, table caption or description, and `o:gfxdata`.

## Additions beyond the brief and the controller's list (each is small, tested, and easy to strike)

All of them are hidden places the leak check cannot see into, or are needed for the package to stay
whole:

1. `HLinks` in `app.xml`: it spells out every hyperlink target, so without it the leak check would
   block every contract with a marked e-mail address behind a link.
2. `w:mailMerge` in the settings (connection string, query, data source path) with its external links.
3. Template, mail-merge, linked-picture and picture-hyperlink relationships are released with the
   element that used them (the template path `file:///C:/...` was in `settings.xml.rels`, outside the
   XML the brief names). `o:relid` (old VML) is followed like `r:id`.
4. Inline `w:customXml` wrappers are unwrapped like smart tags (their `customXmlPr` holds attribute text).
5. `@w:lastValue` of list controls, and `o:gfxdata` (Word 2007's base64 copy of a VML shape, text
   included).
6. The picture of the first page (`docProps/thumbnail.*`), printer settings and digital signatures
   (`_xmlsignatures/`, which hold the signer's certificate), found by relationship type and by folder.
7. `w:rsid` elements (styles), not only attributes.
8. Comment parts are also found by relationship type, and parts that went take along the parts only
   they used (a chart's workbook, an altChunk's resources); empty `.rels` parts are removed.
9. Media still used by something else (a picture bullet in `numbering.xml`) stays with its link
   instead of leaving a dangling reference; media nothing uses goes.

## Not handled (stated in the module docstring)

Text hidden by a *style* (only the run's own properties are read, as decided); pictures that are not in
the text and are still used (page background, picture bullets, theme images); ActiveX controls;
embedded fonts; document protection in the settings; `cp:identifier`, `cp:version`, `cp:lastPrinted`
and `cp:revision` (the brief lists the core properties to clear and these are not among them); shapes
marked hidden (`wp:docPr hidden="1"`); the `tooltip` of an `a:hlinkClick`.

## Tests

`tests/docx/test_cleaner.py`: the brief's seven tests on the corpus (kept, with a few stronger
assertions: exact counts, and that the removed text is nowhere in the file), plus:

- corpus: template path and its relationship gone, alt text gone, text box present once (R16), shape
  renamed, `PAGE` footer field untouched, second `clean` changes nothing (5 files, byte for byte), and
  one test over all 28 files: visible text identical to the original minus hidden runs in both the
  accepted and the rejected view (computed without the cleaner), paragraph/table/row/cell/numbering/
  section/hyperlink/footnote-reference/bookmark counts unchanged, no `word/media`, comments,
  `customXml`, glossary, embeddings, charts, diagrams, people or `custom.xml` entry, no rsid attribute
  or element (parsed, not a substring, see self-review), package consistent, saved file opens in
  python-docx and in `DocxPackage.open` with the same text parts.
- one construct per test for every controller decision, built in memory with `package(...)`:
  comments (three ways of finding the parts, footnotes, a run with text), rsids (including a main
  document outside `word/`), settings (links that stay and go), hidden text (wherever it is, toggles,
  empty paragraph, hidden picture), fields (each of the eight names, simple and complex, split
  instruction, across paragraphs, nested both ways, unclosed, a contents page left alone), R19 (nine
  constructs), R17, R16, pictures (headers/footers, charts and diagrams with all parts, objects, linked
  pictures, a link on a picture, shared pictures, text boxes, a picture in a text box, a VML fallback),
  properties (core, app, custom, clock handling, missing/empty), thumbnail/printer/signatures, custom
  XML and data bindings, glossary, media still in use, and R24 (three tests).
- `assert_consistent(pkg)` is the oracle used throughout: every Override has a part, every relationship
  a target, every `r:*` reference a relationship, no `.rels` left empty, no run inside a run.

## TDD evidence

RED (tests written first, against a do-nothing stub of the public API so every test fails on its
assertion and not on an import error):

```
$ uv run pytest -q tests/docx/test_cleaner.py --no-header -p no:cacheprovider
...
FAILED tests/docx/test_cleaner.py::test_comments_gone - assert 0 == 2
FAILED tests/docx/test_cleaner.py::test_properties_cleared - AssertionError: ...
FAILED tests/docx/test_cleaner.py::test_images_replaced - assert (2 == 2 and 0 == 2)
FAILED tests/docx/test_cleaner.py::test_hidden_text_removed - AssertionError: assert ('€769,000.00' not in ...
FAILED tests/docx/test_cleaner.py::test_settings_scrubbed - assert (b'w:rsids' not in ...
...
73 failed, 10 passed in 3.61s
```

Expected: the 73 fail because the stub removes nothing. The 10 that pass are the "leave it alone"
guards (`test_textbox_kept`, `test_file_still_opens_with_python_docx`,
`test_the_footer_field_that_is_not_personal_stays`, `test_the_report_of_a_file_with_nothing_to_clean`,
`test_other_fields_are_left_alone`, `test_a_personal_field_in_the_instruction_of_another_is_left_alone`,
`test_a_field_that_is_never_closed_does_no_harm`, `test_a_shape_definition_alone_is_not_a_watermark`,
`test_text_boxes_are_kept`, `test_properties_that_are_missing_or_already_empty_are_fine`); they are
meant to pass on a no-op and to fail on an implementation that cleans too much.

R24 was added the same way: its three tests were run before the rule existed
(`2 failed, 1 passed`: `assert (0 == 6)` and `assert (0 == 1)` on `stray_runs_removed`; the third is
the guard that runs in paragraphs and text boxes are not stray), then the rule was written.

GREEN:

```
$ uv run pytest -q tests/docx/test_cleaner.py -W error -p no:cacheprovider
91 passed in 5.26s
$ uv run pytest -q
1433 passed in 19.79s
$ uv run ruff check src tests tools        -> All checks passed!
$ uv run ruff format --check <my two files> -> 2 files already formatted
$ uv run mypy src                           -> Success: no issues found in 18 source files
```

## Other verification

- Mutation check: I broke `cleaner.py` on purpose in 26 ways (release does nothing, vanish toggle ignored,
  fallback copies not skipped, nested field flattened, no sweep, comment parts by name only, text box
  content counted as a picture, all choices kept, alt text kept, rsids only in text parts, settings
  links kept, note always wrapped in a run, webHidden hides, smart tag props kept, every field personal,
  dependents not followed, HLinks kept, clock ignored, fallbacks left, shared picture dropped early,
  hidden runs kept, comment markers kept, empty rels kept, and three for R24) and ran the file's tests
  for each. The first round (23 ways) left two survivors, which exposed two real gaps (nothing proved that a
  removed part takes the parts only it used, nor that a picture something else still uses is kept); I
  added a test for each and all 26 are now killed. The source was restored byte for byte after each.
- Independent consumer: all 28 cleaned corpus files open in macOS `textutil -convert txt` (Apple's
  Open XML importer); `[image removed]` shows twice in `supply-05`, `nda-03` and `dpa-01`, the text box
  note once in `services-03`, the hidden figure and the comment text are absent. (No Word or LibreOffice
  on this machine, so "opens in Word" is **not** verified; the docstring claims only python-docx and
  `DocxPackage.open`.)
- Totals over the corpus: comments 6, images 6, hidden runs 3, fallbacks removed 3, attributes cleared
  3 (the three text-box names), everything else 0; this matches the feature table in
  `tests/corpus/README.md`.
- Speed: a file with 500 pictures cleans in about 0.4 s; the corpus-wide test (28 files, cleaned, saved,
  reopened in python-docx, text compared in two views) takes about 2 s, the whole file about 5 s.

## Self-review: what I found and fixed in my own work before reporting

- The rsid sweep skipped text parts outside `word/` (the package allows any main-document name); fixed
  and tested.
- `_release` assumed a relationship element was still in its tree when a part that went could have
  taken it; now guarded.
- `_discard` called itself for each dependent; a hostile file chaining thousands of parts would reach
  the recursion limit. It is iterative now.
- Unused constant and parameter removed; an O(n^2) comprehension for `parts_removed`; the docstring said
  the result "opens in Word", which I had not verified (now says what is verified).
- Test side: my first corpus check searched the bytes for `rsid` and failed on the made-up company
  "Riverside Partners" (innocent letters), so it parses and looks for attributes/elements instead; an
  `or` assertion that proved nothing and a sloppy third R24 test were rewritten; `len(files) == 28` was
  loosened so adding a corpus file does not break the cleaner's tests; implicit string concatenations
  that this repo's ruff flags (ISC004) were restructured.

## Concerns and notes for the controller

1. **Size (reason for DONE_WITH_CONCERNS).** `cleaner.py` is 859 lines (876 after the last section's extension): the brief planned a modest file,
   and the eleven decisions plus R24 make it large, though it has one responsibility and is sectioned by
   step. I did not split it. The natural split, if wanted: the relationship plumbing (`_Rel`,
   `_relationships`, `_referenced`, `_discard`, `_release`, `_references`, `_content_types`, about 170
   lines) duplicates what `DocxPackage` keeps private (`_relationships`, `_content_types`); promoting
   it to the package's public API would shrink the cleaner and let Task 13 reuse it for the hyperlink
   relationships it must remove.
2. **The cleaner changes the text, so offsets must be taken after it.** Hidden runs, stray runs and
   fallbacks disappear, pictures/equations/embedded content gain notes, personal fields lose their
   instruction text. Task 15 (`export_case`/`load_sources`) must compute the `DocText` that the review
   shows and that `apply_mask` maps through from the package **after** `clean` (accept/reject, then
   clean, then `extract_text`), not before, or every offset after the first change is wrong.
3. **R22 list (closed by the extension in the last section).** I used the controller's eight names exactly. Not on it: TITLE, SUBJECT, KEYWORDS,
   COMMENTS, USERADDRESS and DOCVARIABLE. DOCVARIABLE matters most: `w:docVars` are removed, so an
   updated DOCVARIABLE field would turn into an error in the masked file.
4. **Two constants live in `cleaner.py`**: `EQUATION_NOTE` and `ALTCHUNK_NOTE` (the strings are the
   controller's). `IMAGE_NOTE`/`OBJECT_NOTE` stay in `instruction.py`; moving the two there is a
   one-line follow-up if wanted.
5. **Commit trailer.** The boilerplate says every commit ends with
   `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; the harness reminder named another line
   (Sonnet 5.5). I followed the boilerplate (the project's own rule, and the reminder yields to it);
   amend if you want the other.
6. `[Content_Types].xml` keeps its Default entries for extensions whose parts are gone (`png`, ...).
   Harmless; nothing reads them without a part.

## Extension round: R22 and R19 extended (commit f6fd5b4)

Two small rulings from the coordinator, done together before any review round.

What changed in `src/themask/docx/cleaner.py` (859 to 876 lines):

- **R22 extended.** Fields whose instruction begins with DOCVARIABLE, TITLE, SUBJECT, KEYWORDS,
  COMMENTS or USERADDRESS are flattened like the existing eight: same mechanism (a `fldSimple` is
  unwrapped, the markers and instruction runs of a complex field go, the result runs stay), same
  rules (any case, nested-in-instruction and unclosed fields left alone). The set is now
  `_FLATTENED_FIELDS`, renamed from `_PERSONAL_FIELDS` because TITLE and DOCVARIABLE are not personal;
  `_is_personal` is `_is_flattened`. This closes concern 3 above (DOCVARIABLE would have turned into an
  error once `w:docVars` is removed).
- **R19 extended (found by Task 13).** `w:alias` and `w:tag` of a content control are removed, each
  counted once in `attributes_cleared`. I removed the elements instead of emptying `w:val`: both are
  optional in the schema, so the control stays valid and nothing is left behind. The control, its
  `w:id` and its content stay.
- The module docstring, the `CleanReport` docstring and the comment on the field set say so. The
  section dividers of both files are now 100 columns wide (cosmetic; they were uneven). I kept the
  module in one piece as asked.

Covering tests (`tests/docx/test_cleaner.py`, +8 cases):

- `test_each_field_that_reads_what_the_cleaner_removes_is_flattened`: one case per new keyword (6),
  each with a `fldSimple` and a complex field.
- `test_a_field_that_reads_a_removed_document_variable_keeps_its_result_as_text`: a DOCVARIABLE field
  over a settings part with `w:docVars`; after cleaning the result is plain text and neither
  DOCVARIABLE nor the variable is anywhere in the file.
- `test_the_title_and_tag_of_a_content_control_go`: built with lxml on a copy of `supply-01`; after
  `clean` the saved zip is searched entry by entry for the alias and tag values (absent), the control
  keeps its `w:id` and its text, and `attributes_cleared == 2`.
- `test_the_items_of_a_list_content_control_go_and_its_text_stays` (existing): its first control has
  an alias, so the expected count went from 2 to 3 and it now also asserts the alias is gone.

RED (before the change; the six keywords and the variable test flatten nothing, the title/tag test
clears nothing, the changed count is 2 instead of 3):

```
$ uv run pytest -q tests/docx/test_cleaner.py --no-header -p no:cacheprovider
9 failed, 90 passed in 5.72s
   6 x  assert (0 == 2)        (the six keyword cases)
   1 x  assert (0 == 1)        (the DOCVARIABLE test)
   1 x  assert 2 == 3          (the list-control count)
   1 x  AssertionError: assert 0 == 2   (title and tag)
```

GREEN, the commands as asked, on the committed code:

```
$ uv run pytest tests/docx/test_cleaner.py -q -W error
99 passed in 5.26s
$ uv run pytest -q
1441 passed in 19.72s
$ uv run ruff check src tests tools        -> All checks passed!
$ uv run ruff format --check <my two files> -> 2 files already formatted
$ uv run mypy src                           -> Success: no issues found in 18 source files
```

Mutation check on the final code: the 26 earlier mutants plus four new ones (the six new names
dropped, USERADDRESS dropped, alias/tag kept, alias/tag not counted) are all killed (30 of 30). One
of the old mutants had gone stale after the rename (its replacement still said `_is_personal`, so it
died of a NameError, not of behaviour); I fixed it and it is killed by
`test_a_personal_field_in_the_instruction_of_another_is_left_alone`, the right test.

Self-review of this round: my first version checked that the alias/tag element sat in `w:sdtPr`;
those two names exist nowhere else in WordprocessingML, so the check was dead code and I removed it
with its constant. Nothing else changed in behaviour: the corpus-wide checks, the second-clean and
the layout tests still pass unchanged.

Still not covered by the plan or by any ruling: `w:sdtPr/w:placeholder/w:docPart/@w:val` (the name of a
building block, normally `DefaultPlaceholder_...`) is left as it is.

## Fix round 1: review findings, R28 and R29 (commit 1e160c9)

The review found the core leak surface clean on all 28 corpus files and four Important problems, and the
controller added two rulings. Before changing anything I reproduced each finding on f6fd5b4 with a throwaway
probe, so the "before" values below are what I saw, not what I was told.

### What changed, finding by finding (`src/themask/docx/cleaner.py`, 876 to 1029 lines)

**Important 1: a hidden value survived through its link.** Before: hidden text inside
`<w:hyperlink r:id>` left the empty hyperlink, whose `mailto:` target stayed in `document.xml.rels`; inside
`<w:fldSimple w:instr=" HYPERLINK ...">` the address stayed in `@w:instr` (probe: "address still in file:
True" in both forms). Now `_remove_hidden_runs` calls `_unwrap_emptied_links` on the parent of every run it
removes: a `w:hyperlink` or `w:fldSimple` that holds no run any more is unwrapped (not deleted, so a bookmark
inside it stays), then its parent is looked at, so a link around a field goes whole. The relationship is
released by the existing reference diff. A link that also holds visible text keeps its target.

**Important 2 / R28: a picture and a text box in one drawing.** Before: `_holds` made any drawing with an
`a:blip` outside a text box a picture, so "Signed for Zeta Holdings by Mary Major" became "[image removed]".
Now `_replace_picture` replaces a drawing whole only if it holds no text box of its own; otherwise it strips the
picture pieces and puts the note beside the drawing:

- DrawingML: every own `pic:pic` is removed and every own `a:blipFill` becomes `a:noFill`;
- VML: the shape holding each `v:imagedata` is removed (just the `v:imagedata` if that shape has a
  `v:textbox`);
- one note per drawing, so `images` still equals the number of notes;
- if something picture-like is left after stripping (a chart or ink in a group), the drawing is replaced whole
  as before (text lost, nothing picture-like left, and a second clean finds nothing).

**Important 3: removed parts left dangling references.** Before (probe): the package was inconsistent in all
three cases.

- (a) `w:sectPr/w:printerSettings r:id`: the elements are now removed in the text parts (together with
  `w:dataBinding` and `w15:dataBinding`, `_remove_links_to_parts`), and the existing release removes the part.
- (b) Word 2016 `cx:chart` (waterfall, treemap) and (c) ink `w14:contentPart`, which Word relates as custom XML:
  both are now in `_DRAWING_PIECES`, so their drawing becomes IMAGE_NOTE and its parts go through the normal
  release.
- Safety net: `_xml_references` / `_named_by_xml`. A part whose relationship id is still named by the XML of
  its source part is not swept (`_ALWAYS_GONE` folders) and not removed by folder or relationship type
  (`_remove_hidden_parts`). The cost, which the ruling accepts: a construct this cleaner does not know, that
  references a part in those folders, keeps both the reference and the part.

**Important 4: alt text outside `wp:docPr`.** `_anonymise_shapes` now handles `wp:docPr` and every `cNvPr`
element by local name (`wps:cNvPr`, `wpg:cNvPr`, `pic:cNvPr` ...), in one document-order pass with one
`Shape<N>` counter, and clears the `alt` and `title` attributes of VML shapes. I did not rename the VML `id`:
other attributes (connectors, OLE objects) refer to it.

**R29.**

- `_clear` blanks every matching element (`findall`) and everything inside it (child elements removed,
  `itertext` decides whether it "held something"); `dc:identifier` and `cp:version` are added to the cleared
  list.
- `w15:dataBinding` is removed like `w:dataBinding`.
- A flattened complex field loses everything from its `begin` to its `separate` (to its `end` if it has no
  result): the runs in between are removed by position, so a nested `{ QUOTE "Mary" }` or `{ DOCVARIABLE X }` no
  longer turns into body text. `_remove` and `_remove_from_run` now accept an element that is already out of
  the tree (the mutation run showed that the common five-run field needs this).

Also: the module docstring describes all of this; the "Not touched" list now says "a VML fill" too.

### Covering tests (`tests/docx/test_cleaner.py`, +18 cases: 99 to 117)

- Important 1: `test_hidden_text_in_a_link_takes_the_link_with_it` and
  `test_hidden_text_in_a_simple_field_takes_the_field_with_it` (both assert on the bytes of the saved zip),
  `test_a_link_in_a_field_goes_when_nothing_visible_is_left_in_either`,
  `test_a_link_that_also_holds_visible_text_keeps_its_target` (guard).
- Important 2: `test_a_group_of_a_picture_and_a_text_box_loses_only_the_picture`,
  `test_a_vml_group_of_a_picture_and_a_text_box_loses_only_the_picture`,
  `test_a_text_box_with_a_picture_fill_loses_only_the_fill` (each: text and structure kept, note first, image
  part and alt text gone, package consistent, a second clean empty), plus the guard
  `test_a_shape_with_a_picture_fill_and_no_text_is_a_picture`.
- Important 3: `test_printer_settings_and_signatures_go` (now with the `w:sectPr/w:printerSettings` element, as
  asked), `test_a_word_2016_chart_is_a_picture_with_its_parts`, `test_an_ink_drawing_is_a_picture_and_its_part_goes`,
  and `test_a_part_that_the_text_still_refers_to_is_never_removed` (two cases: a swept folder, a relationship
  type).
- Important 4: `test_alt_text_and_names_of_grouped_shapes_go`, `test_alt_text_of_a_vml_text_box_goes`.
- R29: `test_core_properties_are_blanked_whatever_they_hold`,
  `test_the_data_binding_of_a_word_2013_control_goes_like_the_older_one`,
  `test_a_field_in_the_instruction_of_a_flattened_field_goes_with_it` (a QUOTE field, a DOCVARIABLE); the core
  fixtures and the pinned `properties_cleared` order now include identifier and version.

RED, before the source change (18 new or changed cases fail, each for its own reason: the address is still in the
saved bytes, `['[image removed]'] != [IMAGE_NOTE, SIGNED]`, `assert (0 == 1)` for the chart and ink, the part is
swept although named, `b'Zeta'` is still in `core.xml`, `printerSettings` is still in the file):

```
$ uv run pytest -q tests/docx/test_cleaner.py --no-header -p no:cacheprovider
18 failed, 98 passed in 5.64s
```

GREEN, the commands as asked, on the committed code:

```
$ uv run pytest tests/docx/test_cleaner.py -q -W error
117 passed in 5.42s
$ uv run pytest -q tests/docx/test_cleaner.py::test_every_corpus_file_is_cleaned_and_keeps_its_visible_text
1 passed in 4.59s        (the whole-corpus consistency test: 28 files, text, layout, package, python-docx)
$ uv run pytest -q
1459 passed in 19.77s
$ uv run ruff check src tests tools         -> All checks passed!
$ uv run ruff format --check <my two files> -> 2 files already formatted
$ uv run mypy src                           -> Success: no issues found in 18 source files
```

Other evidence: the 21 new mutants (hidden link or simple field kept, pictures always whole, `pic:pic` or fill or
VML shape kept, note missing, chartEx or ink not a picture, printer settings or `w15` binding kept, both guards
off, first core element only, children kept, identifier/version not cleared, instruction region kept, group
names or VML alt kept, intolerant `_remove`) plus the 30 earlier ones: 51 of 51 killed, each by the test meant
for it; the source was restored byte for byte. All 28 cleaned corpus files open in macOS `textutil`; corpus
totals are unchanged (6 comments, 6 images, 3 hidden runs, 3 fallbacks).

### Left as logged (not changed, as instructed)

Partially hidden field markers; the URL of a linked inline picture on the note; the `v:fill` / 3D / `fldData` /
`saveThroughXslt` class of pictures and links; rsids outside `word/`; the plumbing duplicated from
`DocxPackage`; the `o:relid` in the test oracle.

### Notes

- `cleaner.py` is now 1029 lines (the size concern above stands; the reviewer will judge the split).
- A VML shape's `id` can carry a name a user gave the shape. It is not cleared (see Important 4), so it remains a
  small residual in pure-VML text boxes.
