# Task 10 report: Word package and text map

**Status:** DONE_WITH_CONCERNS (all requirements met; the concerns are additions beyond the brief that you may want to veto, plus gaps for later tasks).
**Branch / worktree:** `task-10` in `/Users/alijoeee/Developer/the-mask-worktrees/task-10`, branched from `mac-v1` at fbe2c02.
**Commit:** `b016cca feat: docx package wrapper and text map with accepted/rejected views`

## What I implemented

### `src/themask/docx/package.py`
- `DocxPackage.open(path)` reads every zip entry into memory and does not touch the file again. Error handling follows decision 1:
  - An OLE/CFB file (magic `D0 CF 11 E0 A1 B1 1A E1`) whose bytes contain `EncryptionInfo` or `EncryptedPackage` in UTF-16-LE raises `ProtectedFileError("This file is protected or encrypted. Please provide an unprotected copy.")`.
  - Any other OLE file, a non-zip, a damaged zip (bad directory, CRC, deflate, truncation, unknown method, zip-password entries, non-UTF-8 names), or a zip without `word/document.xml` raises `UnsupportedFileError("This is not a Word .docx file. If it is an old .doc, open it in Word and save as .docx.")`.
  - **Addition:** the same error is raised when the root of `word/document.xml` is not a transitional `w:document`, for example a "Strict Open XML" file or a part that is not XML (see Concerns).
- `copy()` deep-copies the parsed trees. Raw bytes are shared, which is safe because bytes are immutable; both dicts are copies.
- `names()` returns the zip order, reflects removals, and lists added parts last.
- `xml(name)` is parsed lazily, once, and cached. The parser uses `resolve_entities=False, no_network=True`, with a new parser per call (lxml parsers must not be used by two threads at once). A part that is not XML raises the `UnsupportedFileError` above, never a raw `XMLSyntaxError`.
- `raw(name)` returns the current serialisation for a parsed part and the original bytes otherwise. `set_raw` replaces bytes and drops any cached tree.
- `rels_of(part_name)` returns `self.xml("<dir>/_rels/<file>.rels")`, and `""` gives `_rels/.rels`. It raises `KeyError` when the part has no rels part (supply-01's `header1.xml` has none).
- `remove_part(name)` removes:
  - the zip entry;
  - **(addition)** the part's own `.rels`;
  - every internal `Relationship` in any `.rels` whose Target resolves to the part. Targets may be relative (`../customXml/item1.xml`, `./x`), absolute (`/word/x`) or %-escaped (`media/logo%201.png`), and are compared case-insensitively. `TargetMode="External"` relationships are never touched;
  - its `Override` in `[Content_Types].xml`.

  It is idempotent: a part that is not there changes nothing. A rels or content-types part that loses nothing stays unparsed, so its bytes are written out unchanged.
- `save(path)` writes a new deflated zip with `[Content_Types].xml` first and fixed 1980-01-01 entry dates, the same as Word. **Addition:** it raises `ValueError` if `path` is the file the package was opened from. This uses `samefile`, so it also catches case-only differences on APFS.
- `TEXT_PARTS` is a property: `word/document.xml`, then `word/header*.xml` in numeric order (header2 before header10), then `word/footer*.xml` likewise, then `word/footnotes.xml`, then `word/endnotes.xml`, counting only parts that exist. Comments are excluded.
- `NS` contains exactly the 16 prefixes from decision 6. `xml` works in both `xpath()` and `find()`, which I verified. It also exports `TYPES_NS`, `RELS_NS`, `DOCUMENT`, `CONTENT_TYPES`, `NOT_A_DOCX_MESSAGE` and `PROTECTED_MESSAGE`.

### `src/themask/docx/reader.py`
- `TextNode(elem, start, end, kind)` and `Segment(part, para, start, end)` are frozen dataclasses. `DocText(text, segments)` is a plain dataclass. The type aliases are `View = Literal["accepted","rejected"]` and `NodeKind = Literal["t","instr"]`.
- `paragraph_nodes(p, view)` walks the runs in document order:
  - It goes through `w:hyperlink`, `w:sdt/w:sdtContent`, `w:smartTag`, `w:fldSimple` and `w:customXml`, and through any container it does not name (such as `w:dir`, `w:bdo`, paragraph-level `mc:AlternateContent/mc:Choice`) by descending generically.
  - It skips nested `w:p`, the property elements (`pPr`, `rPr`, `sdtPr`, `sdtEndPr`, `customXmlPr`, `smartTagPr`) and `mc:Fallback`.
  - `w:ins` and `w:moveTo` content is read only in the accepted view; `w:del` and `w:moveFrom` content only in the rejected view.
  - Nodes: `w:t` is kind "t" and `w:instrText` is kind "instr". `w:delText` is kind "t" only in the rejected view, wherever it is. **Addition:** `w:delInstrText` is kind "instr" in the rejected view only.
  - Characters without a node: `w:tab` gives "\t", `w:br`/`w:cr` give "\n", `w:noBreakHyphen` gives U+2011, `w:softHyphen` gives nothing.
  - Inside a run, `mc:AlternateContent/mc:Choice` is read as run content. Other run children (drawings, pictures, objects, `w:ruby`) are walked like containers, so nested runs are read while text-box paragraphs stay their own segments.
  - An empty `w:t` gives a zero-length node.
  - An unknown view raises `ValueError`.
- `extract_text(pkg, view="accepted")` iterates `TEXT_PARTS` and visits every `w:p` (`root.iter`, pre-order) that has no `mc:Fallback` ancestor. That covers table cells, nested tables, content controls and text boxes, each where it occurs in document order (a text box after the paragraph it sits in). It makes one `Segment` per paragraph, empty ones included, and joins the texts with "\n".
- `has_revisions(pkg)`: true when any of the 11 tags from decision 5 appears in a `TEXT_PART`.
- `has_comments(pkg)`: true when `word/comments.xml` exists or any `TEXT_PART` contains a `w:commentReference`.

### `src/themask/docx/__init__.py`
Docstring only. There are no re-exports, so Tasks 11, 12 and 13 never need to edit this file and cannot conflict with each other in it.

### Tests and fixtures
- `tests/docx/fixtures/make_fixtures.py` deterministically writes the three committed fixtures (I checked that two runs give identical sha256):
  - `not-a-docx.doc`: a 512-byte version-3 CFB header.
  - `corrupt.docx`: 512 sha256-derived pseudo-random bytes, asserted to be neither zip nor CFB.
  - `encrypted.docx`: 1,536 bytes, a consistent minimal CFB (header, FAT sector, and a directory with a Root Entry and an empty `EncryptionInfo` stream).
- `tests/fixtures/docx.py` (loaded automatically as a plugin) provides:
  - the `fixtures` path fixture;
  - a `make_docx(body, parts=None, raw=None)` factory fixture that writes a minimal valid package with headers, footers, footnotes, endnotes and comments wired into the content types and rels. Tasks 11 to 13 can reuse it;
  - a `paragraph(xml)` helper.

  It deliberately does not import `themask.docx` at module level, so a broken module cannot break collection of the whole suite (the R15 lesson).
- `tests/docx/test_package.py` has 29 tests and `tests/docx/test_reader.py` has 35, 64 in all.

## Tests and results

- All of the brief's tests are present with the brief's assertions: `test_open_doc_renamed`, `test_open_corrupt`, `test_open_encrypted`, `test_remove_part_cleans_rels_and_types`, `test_extract_text_covers_all_parts`, `test_views`, `test_split_runs_map_back`, `test_original_untouched`.
- Tests from decision 7:
  - Offsets round-trip across all 28 corpus files and both views: segments are contiguous with "\n" between them, `dt.text[s.start:s.end]` equals the paragraph's own text, and every node's text equals `text[n.start:n.end]`.
  - Tab and line-break case (tab stops in `pPr` add nothing, empty `w:t`).
  - `w:instrText` is kind "instr".
  - Nested table cells are visited, as are cell-level and block-level content controls.
  - The text box is read once for services-03, nda-04 and dpa-03, and its segment lies under `mc:Choice`.
  - `save()` output reopens with python-docx and gives the same text.
  - The file-based error fixtures, with the exact messages.
- Further tests:
  - **Every text node is mapped exactly once** (all corpus files, both views). This is an oracle independent of the walker: XPath-style "every `w:t`/`w:instrText` (rejected: plus `w:delText`/`w:delInstrText`) outside the other view's changes and outside `mc:Fallback`" must equal the set of mapped nodes.
  - **Every truth value and variant is in its view** across the corpus. Deletion-only values are in the rejected view and absent from the accepted one; hidden values are in the accepted view.
  - All containers in both views; changes nested in changes; Choice/Fallback at run and paragraph level; ruby; a VML text box without a Choice.
  - Part order with comments left out; empty paragraphs keep their offsets; `has_revisions` for each of the 11 kinds (parametrised), in a footer, but not in comments.xml; `has_comments` in four cases.
  - Errors: the other encryption stream, a zip without a document, an empty file, a CRC-damaged part, a non-XML document, Strict OOXML.
  - Package operations: lazy parsing (a broken `styles.xml` does not stop open or extract), parsed changes flow to `raw`/`save`, `set_raw` over a parsed part, `rels_of`, `TEXT_PARTS` numeric order and removal, `NS` pinned exactly plus `xml:space` in xpath, relative/absolute/escaped/external targets, idempotent `remove_part`, deep `copy`, refusal to overwrite the original, content types first, deflate, `testzip`.
- **Performance (decision 8):** open + `extract_text` of supply-10 (48 KB file, 12,530 words, 397 paragraphs) takes 4.5 ms on the first run and 2.6 ms median over 20 runs. services-05 and dpa-05 take about 2.9 ms each. A test asserts under 2 s.
- **Mutation check:** I applied 20 targeted mutations to the implementation, one at a time. Examples: reading Fallback, `ins` in both views, dropping tab, wrong instr kind, dropping `numberingChange`, skipping the encryption check, skipping the Strict check, keeping the part's own rels, lexicographic header order, removing external links, unescaped target compare, shallow copy, content types not first, a stale tree after `set_raw`, unkept rels edits, saving over the original. 19 were caught at once. The survivor ("delText read in accepted") led to `test_deleted_text_is_only_in_the_rejected_view_wherever_it_is`, which now catches it. All 20 are caught.
- **Fuzz (scratchpad, not committed):**
  - 3,300 damaged variants of supply-02 (truncations, byte flips, flips in stored entries) through open, both views, `has_*`, `remove_part` and `save`.
  - 2,000 packages with damaged XML (flipped, deleted or inserted markup, `<!DOCTYPE>` with entities, `&bogus;`, NUL) re-zipped with valid CRCs.
  - Result: zero exceptions other than `MaskError` escaped. That is 4,041 `UnsupportedFileError` and 1,259 clean reads.

## TDD evidence

RED, with the tests and fixtures written and no implementation yet:
```
$ uv run pytest -q tests/docx
tests/docx/test_reader.py:18: in <module>
    from themask.docx.package import NS, DocxPackage
E   ModuleNotFoundError: No module named 'themask.docx'
ERROR tests/docx/test_package.py
ERROR tests/docx/test_reader.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
2 errors in 0.15s
```
This failure was expected: `themask.docx` did not exist yet.

GREEN, from the committed state:
```
$ uv run pytest -q tests/docx            -> 64 passed in 2.39s   (also clean with -W error)
$ uv run pytest -q                       -> 1310 passed in 12.93s (baseline 1246 + 64)
$ uv run ruff check src tests tools      -> All checks passed!
$ uv run ruff format --check src tests tools -> 55 files already formatted
$ uv run mypy src                        -> Success: no issues found in 17 source files
```

## Files changed (all new)
- `src/themask/docx/__init__.py`, `src/themask/docx/package.py`, `src/themask/docx/reader.py`
- `tests/docx/__init__.py`, `tests/docx/test_package.py`, `tests/docx/test_reader.py`
- `tests/docx/fixtures/make_fixtures.py`, `not-a-docx.doc`, `corrupt.docx`, `encrypted.docx`
- `tests/fixtures/docx.py`

No file outside my list was touched. The Task 5 and Task 7 paths are untouched.

## Self-review findings (fixed before commit)
- The mutation survivor described above: I added the stray-`w:delText` test.
- Lambdas closing over a loop variable in `remove_part` were replaced by `functools.partial` helpers.
- `str.isdigit` would have crashed `int()` on a name like `header²`. It is now `isdecimal`.
- `_target_part` no longer rejects a legitimate name that merely starts with "..".
- `remove_part` no longer re-serialises rels or content-types parts it did not change.
- Comments and docstrings were corrected where they under- or over-stated behaviour (the thread-safety reason, nested run content, comment/PI nodes).

## Concerns and notes for you

1. **Commit trailer.** The boilerplate and the plan say `Co-Authored-By: Claude Fable 5.1`. I used `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, as this session's harness requires and as every merged commit on `mac-v1` already does (Tasks 4 and 6). Tell me if you want it amended.
2. **Additions beyond the brief, small and tested, each easy to remove if you prefer the literal brief:**
   - (a) Refusing a document whose root is not a transitional `w:document`. Without this, a Word "Strict Open XML" .docx would give an empty text map. Nothing would be found, the leak check would have no entries, and the "masked" copy would go out with every value in it. I think this is a leak guard worth keeping. It uses the existing message ("open it in Word and save as .docx" is the right fix).
   - (b) Parse errors in `xml()` become the same `UnsupportedFileError`, so there is no stack trace (Review Focus 1).
   - (c) `remove_part` also deletes the part's own `.rels`. For example, a removed `comments.xml` could otherwise leave `comments.xml.rels` with `mailto:` targets behind for the leak check.
   - (d) `save()` refuses the source path (Global Constraint: originals are never modified).
   - (e) `w:delInstrText` counts as "instr" in the rejected view, by analogy with `w:delText`.
   - (f) Generic descent into containers the list does not name.
3. **Not read by the map (gaps for a ruling, not fixed).**
   - (a) OMML math text (`m:t`). TextNode has no kind for it.
   - (b) `w:altChunk` content: HTML or RTF embedded as a separate part. Word never saves these, but some generators do, and such a document would look empty. Same silent-leak shape as (2a); a check like (2a) could refuse it.
   - (c) Header and footer parts named outside `word/header*.xml` / `word/footer*.xml`. Discovery is by name as decision 4 specifies; content types could be used instead if you want non-Word producers covered.
   - (d) Values stored only in attributes, such as legacy form-field defaults and smart-tag `w:attr` values. The leak check covers marked ones.
   - (e) `has_revisions` follows decision 5's 11 tags, so `w:cellIns`, `w:cellDel`, `w:cellMerge` and `w:tblGridChange` alone do not count. Task 11 resolves cellIns/cellDel, so adding those two would strengthen its "afterwards has_revisions is False" check.
4. **For later tasks.**
   - `rels_of` raises `KeyError` when a part has no `.rels` (common for headers and footnotes). Tasks 12 and 13 should check `name in pkg.names()` or catch it.
   - `remove_part` is idempotent.
   - The masker (Task 13) gets zero-length nodes for empty `w:t`, and tabs and breaks have no node. A replacement that crosses a tab needs care.
   - Per R2, `DocText` must be taken from the prepared copy: `Segment.para` points into the package it was extracted from.
   - The cleaner (Task 12) must delete every `mc:Fallback` (R16), because the map never reads them.
   - Hidden text is in the accepted view, as Task 12's `test_hidden_text_removed` assumes.

---

## Addendum: ruling R18 applied (commit `bbb6981`)

You accepted the additions and kept the trailer. R18 ruled on two of the "not read" items (3c and 3e above), and R17 (equations and `w:altChunk`) goes to the cleaner. Here is what changed.

### What changed
- **`TEXT_PARTS` is found by content type, not by name.** A part's type is its Override in `[Content_Types].xml`, else the Default for its extension. That is the Open Packaging definition: part names are compared case-insensitively with %-escapes decoded, and types are compared case-insensitively.
  - The order is the main document, then headers, footers, footnotes and endnotes (the `...wordprocessingml.{header,footer,footnotes,endnotes}+xml` types). Within each kind, names ending in a number before the extension come first in numeric order (header2 before header10); the others follow in package order, using a stable sort.
  - Main document: `word/document.xml` always comes first, whatever its type, because `open()` has already checked that it is a Word document. I kept this because otherwise a `.docm`, a template, or a file with no Override for the document would drop its body from the map: the same silent-leak shape as Strict.
  - It is followed by any other part typed as a main document (`.docx`, `.dotx`, `.docm` and `.dotm` types). No part is listed twice.
- **One consequence beyond the ruling's text:** content types now decide which parts hold text, so `open()` also refuses a zip without `[Content_Types].xml`. It uses the same "not a .docx" message. Such a zip is not a valid Open XML package, and its headers would otherwise drop out of the map. Tell me if you would rather not have it.
- **`has_revisions`** also returns True for `w:cellIns`, `w:cellDel` and `w:cellMerge`, making 14 tags.
- **The reader's module docstring** now says that equation text (`m:t`) and `w:altChunk` parts are not read, and that the cleaner removes them with a visible note (R17).
- **Refactor:** `_tree(name)` returns a part's tree without caching a new parse. `_content_types()` and `_drop_children` share it, so reading the content types never changes the bytes `save()` writes. The name-based `_numbered` helper has been removed.

### Covering tests (10 new cases; 74 in `tests/docx`: 35 in `test_package.py`, 39 in `test_reader.py`)
- `test_reader.py::test_a_renamed_header_is_still_read` (the ruling's test). It renames `word/header1.xml` to `word/hdr.xml`, together with its Override and its relationship, checks that nothing is left under the old name, and asserts that the text is `"Body\nRenamed header"` with the second segment in `word/hdr.xml`.
- `test_reader.py::test_has_revisions_finds_every_kind[cellIns|cellDel|cellMerge]`: three new parametrised cases.
- `test_package.py::test_text_parts_are_found_by_content_type` builds one package covering every discovery rule:
  - numbered headers in numeric order (header3, header12) ahead of unnumbered ones kept in package order (hdr-b, hdr-a);
  - a header typed through a Default extension (`word/top.hdr`);
  - a `word/header5.xml` typed as plain XML, which is left out;
  - comments left out;
  - a second main-typed part placed after `word/document.xml`;
  - footnotes placed before endnotes even though the endnotes come first in the zip.
- `test_package.py::test_the_document_is_always_a_text_part[macro-enabled|template|untyped|typed-as-a-header]`. These cases pass both before and after the change, because they guard the main-document safety rule.
- `test_package.py::test_a_zip_without_content_types`.
- **Mutation check of the new code:** 8 mutations, all caught. They were:
  - the document listed twice;
  - missing content types accepted;
  - no number ordering;
  - Defaults ignored;
  - the document only by type;
  - other main documents dropped;
  - `cellMerge` and `cellIns` removed.

### Commands and output
RED (the tests written before the code change):
```
$ uv run pytest -q tests/docx
FAILED tests/docx/test_package.py::test_text_parts_are_found_by_content_type
FAILED tests/docx/test_reader.py::test_a_renamed_header_is_still_read - Asser...
FAILED tests/docx/test_reader.py::test_has_revisions_finds_every_kind[cellIns]
FAILED tests/docx/test_reader.py::test_has_revisions_finds_every_kind[cellDel]
FAILED tests/docx/test_reader.py::test_has_revisions_finds_every_kind[cellMerge]
5 failed, 67 passed in 2.48s
```
The failures were for the expected reasons. With name-based discovery the list came out as `[document, header3, header5, header12]`, and the renamed header's text was missing (`'Body' == 'Body\nRenamed header'`).

GREEN:
```
$ uv run pytest tests/docx -q                 -> 74 passed in 2.53s (also clean with -W error)
$ uv run pytest -q                            -> 1320 passed in 12.96s
$ uv run ruff check src tests tools           -> All checks passed!
$ uv run ruff format --check src tests tools  -> 55 files already formatted
$ uv run mypy src                             -> Success: no issues found in 17 source files
```
Performance is unchanged: opening and reading supply-10 takes 4.8 ms on the first run and 2.5 ms median, and its `TEXT_PARTS` is `['word/document.xml', 'word/header1.xml', 'word/footer1.xml']`.

### Still open
- Concern 3d: values held only in attributes (form-field defaults, smart-tag `w:attr`) are left to the leak check.
- The residual case of a header whose content type is wrong (for example a header typed as plain XML) is not read. Word would not open such a file either.

---

## Fix report: review round 1 (commit `021cb43`)

The items are the reviewer's Important 1 and 2 and your rulings R20 (items 3 and 4) and R19 (docstring). I left the Minors alone, as you asked.

### What changed
1. **altChunk-merged files (Important 1).** The main document is now the part named by the package's `officeDocument` relationship in `_rels/.rels`, falling back to `word/document.xml` when there is no such relationship or its target part is missing. `open()` checks that this part is a Word document; it still requires `word/document.xml` to exist (decision 1). No other main-typed part is a text part, so the .docx that an altChunk embeds (typed `document.main+xml`) is no longer read as XML. I removed the R18 `_MAIN_TYPES` discovery and the "`word/document.xml` always first" rule; the officeDocument rule replaces both. `TEXT_PARTS[0]` is always the main document.
2. **`w:ptab` (Important 2)** now contributes "\t" and gets no node, like `w:tab`.
3. **R20: DOCTYPE and XML comments.** Every part is parsed with `remove_comments=True` and `remove_pis=True`. Before this fix the text after a comment inside a `w:t` was lost entirely: `Acme<!--x--> B.V.` read as "Acme". A part with a DOCTYPE raises `UnsupportedFileError` with the "not a .docx" message. That happens in `open()` for the main document, and when any other part is parsed (`xml()`, `TEXT_PARTS`, `remove_part`). The check is `docinfo.doctype`, which is set by both `fromstring` and `iterparse` and catches internal-subset, SYSTEM and PUBLIC DOCTYPEs alike.
4. **R20: relationship-type discovery.** Each text kind (headers, footers, footnotes, endnotes) is the union of two sets: parts with that content type, and parts the main document relates to with that kind's relationship type, whatever their content type. Ordering is unchanged (numeric where the names allow it, otherwise package order), and no part comes twice. A single `_relationships(source)` reads each rels part once per `TEXT_PARTS` call.
5. **R19:** the reader's module docstring now lists the attribute-held text that is not read (watermark `v:textpath/@string`, `@w:tooltip`, `wp:docPr/@descr`, list items, form-field defaults, smart-tag attributes), with the cleaner and leak check as the cover.
6. **Test helpers.** `content_types()` and `relationships()` moved into `tests/fixtures/docx.py`, along with the `WML`, `REL`, `MAIN` and `PACKAGE_RELS` constants, and `make_docx` now builds its bookkeeping parts with them.

### Covering tests (9 new; `tests/docx` now has 83: 39 in `test_package.py`, 44 in `test_reader.py`)
- `test_reader.py::test_an_alt_chunk_is_not_a_text_part` (item 1). The payload is a whole .docx zip in `word/afchunk1.docx`, with an Override typed main+xml and an `aFChunk` relationship. The test asserts that the file opens, `TEXT_PARTS == ['word/document.xml']`, the text is `"Before\nAfter"`, and `has_revisions`/`has_comments` work.
- `test_package.py::test_the_main_document_is_the_one_the_package_names`: an officeDocument relationship to `/word/main.xml` beats a left-over `word/document.xml`. It also checks that an empty `_rels/.rels`, or one pointing to a missing part, falls back to `word/document.xml`.
- `test_package.py::test_the_main_document_must_be_a_word_document`: a named main part with an `<html/>` root is refused.
- `test_package.py::test_text_parts_are_found_by_content_type` was updated: a second main-typed part is in the package but not in `TEXT_PARTS`.
- `test_package.py::test_the_main_document_is_read_whatever_its_type[...]` (renamed) is still parametrised over macro-enabled, template, untyped and typed-as-a-header.
- `test_reader.py::test_alignment_tabs_separate_like_tabs` (item 2): `Jane Smith`, ptab, `Supply Agreement`, ptab, `Draft` reads as "Jane Smith\tSupply Agreement\tDraft", with nodes at (0,10), (11,27) and (28,33).
- `test_package.py::test_a_document_with_a_doctype_is_refused` (DOCTYPE with an entity holding a party name, refused at open) and `test_any_part_with_a_doctype_is_refused_when_it_is_read` (a header with a DOCTYPE: both `extract_text` and `xml()` raise).
- `test_reader.py::test_xml_comments_and_processing_instructions_are_left_out`: `Acme<!--x--> B.V.` and `North<?pi x?>wind` read as "Acme B.V.\nNorthwind", with a single merged `w:t` node.
- `test_reader.py::test_a_header_the_document_relates_to_is_read_whatever_its_type[missing|wrong]` (item 4): the header Override is either absent or says `comments+xml`, and the header is still in `TEXT_PARTS` and extracted.
- **Mutation check:** 10 mutations of the new logic, all caught by the intended tests. They covered:
  - ignoring officeDocument (redone so it no longer breaks the syntax: it fails the two officeDocument tests);
  - no fallback;
  - ignoring relationships, and separately ignoring content types;
  - allowing duplicates;
  - keeping comments;
  - parsing a DOCTYPE, and accepting a DOCTYPE at open;
  - `open()` checking only `word/document.xml`;
  - dropping ptab.
- **Fuzz** (both scratchpad fuzzers re-run against the new paths): 3,300 damaged zips and 2,000 damaged-XML packages. No exception other than `MaskError` escaped.

### RED, with the tests written before the code change
```
$ uv run pytest -q tests/docx
FAILED tests/docx/test_package.py::test_text_parts_are_found_by_content_type        (main2.xml listed)
FAILED tests/docx/test_package.py::test_the_main_document_is_the_one_the_package_names
FAILED tests/docx/test_package.py::test_the_main_document_must_be_a_word_document   (DID NOT RAISE)
FAILED tests/docx/test_package.py::test_a_document_with_a_doctype_is_refused        (DID NOT RAISE)
FAILED tests/docx/test_package.py::test_any_part_with_a_doctype_is_refused_when_it_is_read
FAILED tests/docx/test_reader.py::test_alignment_tabs_separate_like_tabs            ('Jane SmithSupply AgreementDraft')
FAILED tests/docx/test_reader.py::test_a_header_the_document_relates_to_is_read_whatever_its_type[missing]
FAILED tests/docx/test_reader.py::test_a_header_the_document_relates_to_is_read_whatever_its_type[wrong]
FAILED tests/docx/test_reader.py::test_an_alt_chunk_is_not_a_text_part              (['word/document.xml', 'word/afchunk1.docx'])
FAILED tests/docx/test_reader.py::test_xml_comments_and_processing_instructions_are_left_out ('Acme\nNorth')
10 failed, 73 passed in 2.50s
```

### GREEN, from the committed state
```
$ uv run pytest tests/docx -q                 -> 83 passed in 2.49s (also clean with -W error)
$ uv run pytest -q                            -> 1329 passed in 12.72s
$ uv run ruff check src tests tools           -> All checks passed!
$ uv run ruff format --check src tests tools  -> 55 files already formatted
$ uv run mypy src                             -> Success: no issues found in 17 source files
```
Performance: supply-10 opens and reads in 3.3 ms on the first run and 2.6 ms median, and `TEXT_PARTS` takes 0.08 ms.

### Notes
- `open()` still refuses a file whose main part is elsewhere when there is no `word/document.xml` at all (decision 1). Where both exist, a left-over `word/document.xml` that the package does not name is no text part. It is saved unread; the leak check still scans it for marked values.
- `TEXT_PARTS` now parses `_rels/.rels`, the main document's rels and `[Content_Types].xml` without caching them, so their bytes stay unchanged on save. A DOCTYPE in any of these also makes `TEXT_PARTS` raise the "not a .docx" error.
