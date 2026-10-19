# Task 5 report: PDF corpus (text, scanned, mixed)

Branch `task-5` (worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-5`, from mac-v1 at fbe2c02).
Commit: `9e25844 test: PDF corpus incl. scanned and mixed pages` (one commit, amended once to fold in two small follow-ups).
**Status: DONE_WITH_CONCERNS** (see "Concerns": file size, the font of the scan, the commit trailer).

## What was implemented

`generate(out_dir)` now writes, besides the 28 Word files and 28 truth files, **eight PDF files**, listed in `manifest.json` after all the Word entries:

| File | Made from | features | image_pages |
|---|---|---|---|
| supply-01.pdf, supply-04.pdf, supply-05.pdf, supply-06.pdf, supply-10.pdf, nda-01.pdf | the same-named contract | the twin's features that a PDF can have (`header_footer`, `table`, `image`, `footnotes`, `thirty_pages`) | `[]` |
| scanned-01.pdf | supply-01 | `["scanned"]` | `[1, 2, 3, 4, 5]` |
| mixed-01.pdf | dpa-01 | `["mixed"]` | `[2]` |

Entry keys are `file, format, features, truth, source, image_pages`; `truth` is the truth file of the source contract (`"supply-01.truth.json"`), so the PDFs add no truth files.

### Files

- **`tools/corpus/pdf_writer.py` (new, 710 lines)**: `write_pdf`, `write_scanned_pdf`, `write_mixed_pdf` (each returns the picture pages: `[]`, all pages, `[image_page]`).
  - Text PDF: reportlab `SimpleDocTemplate(..., invariant=1)`, A4, 2.5 cm margins, built-in Helvetica/Helvetica-Bold only (no font files). Running header from the spec's own header (`<Short A> / <Short B> — <Title>`) drawn by the `onPage` callbacks; footer `Page N of M · Confidential` by a NumberedCanvas-pattern canvas (`_Canvas.save`). Title 16 pt, headings 12 pt bold, body 10 pt, table cells 9 pt, header/footer 8.5 pt. Pricing table is a reportlab `Table` (ruled grid, shaded header row). Lettered lists use `bulletText` "(a)". Footnotes become a "NOTES" heading plus one paragraph per note at the end, marks are `<super>n</super>`. Logo/signature are reportlab `Image` flowables.
  - Paragraphs and tables are `split() -> []` subclasses, so nothing breaks across a page and a page break can never cut a value (the header/footer lines would otherwise sit inside it). Headings and signature lines keep with the next block through reportlab's own `keepWithNext`.
  - Scan: a small Pillow typesetter (word wrap with bold/italic/footnote-mark fragments, hanging indents, list labels, tables with auto-fitted columns, pictures, keep-with-next pagination) draws each page with `ImageDraw` into a 1240 x 1754 px (A4 at 150 dpi) greyscale PNG, header and footer included; reportlab places each PNG full-page, so there is no text layer (`extract_text()` is empty; the page content stream holds only the image `Do`).
  - Mixed: two passes. Pass 1 builds the all-text PDF while `_Document.afterFlowable/afterPage` record which block lands on which page. The blocks of page 2 are typeset as one picture page (text shrunk in 2 % steps until it fits one page; it needed 92 % for dpa-01), then pass 2 builds the final PDF (page 1 text, picture, pages 3+ text). The writer raises if pass 2's text pages differ from pass 1's or if pass 1 did not place every block once, in order.
  - Refusals: a character not in WinAnsi (the narrow no-break space) raises `ValueError`; a `TextBox` or `PageBreak` block raises `TypeError`; hidden text and tracked deletions are not shown (a reader's view).
- **`tools/make_corpus.py`**: imports and re-exports the three writers (`__all__`), adds `TEXT_PDFS`, `SCANNED_PDF`, `MIXED_PDF`, `PDF_FEATURES`, `_pdf_entry`, `_write_pdfs`; `generate` keeps the specs it needs and appends the PDF entries; the CLI message counts Word and PDF files. The Word part of the manifest is unchanged.
- **`tests/test_corpus.py`**: +13 tests (below); `manifest(corpus, fmt="docx")` now returns the Word entries unless asked for `"pdf"`; `test_features_are_real` uses it (it opened every entry as a zip); `test_deterministic` also asserts 8 PDFs are compared byte for byte.
- **`tests/corpus/README.md`**: new "PDF files" section (what each file is for, layout, what the six text PDFs guarantee, the scan and the mixed file, manifest keys) and updated lists.
- Docstring-only edits: `tools/corpus/model.py` and `tools/corpus/__init__.py` (they said the PDF writer was a later task), `tests/fixtures/corpus.py` (mentions PDFs/reportlab).

## Verification

Commands run from the worktree root.

**RED** (tests written before `generate()` wrote any PDF):

1. `uv run pytest tests/test_corpus.py -q` with the tests in place but `tools.make_corpus` not yet exporting the writers:
   `ImportError: cannot import name 'write_mixed_pdf' from 'tools.make_corpus'` (collection error). Expected: the brief makes `write_pdf`, `write_scanned_pdf`, `write_mixed_pdf` part of `tools.make_corpus`.
2. After exporting them but before wiring `generate()`:
   ```
   13 failed, 27 passed in 9.39s
   FAILED test_deterministic - assert 0 == 8
   FAILED test_pdf_corpus - assert (0 >= 8)
   FAILED test_text_pdf_has_text_and_running_header - FileNotFoundError ... supply-01.pdf
   FAILED test_scanned_pdf_has_no_text - FileNotFoundError ... scanned-01.pdf
   FAILED test_pdf_manifest_entries - ValueError: 'pdf' is not in list
   FAILED test_pdf_twins_share_the_truth_of_their_word_file
   FAILED test_every_truth_value_and_variant_is_in_the_text_of_the_text_pdfs
   FAILED test_no_occurrence_of_a_value_is_cut_in_the_text_pdfs
   FAILED test_text_pdfs_have_the_running_header_and_footer_on_every_page
   FAILED test_headings_in_the_text_pdfs_are_larger_than_the_body_text
   FAILED test_text_pdfs_have_their_table_pictures_and_notes   (later renamed ..._have_the_features_they_claim_and_no_others)
   FAILED test_scanned_pdf_is_one_picture_to_a_page
   FAILED test_mixed_pdf_has_one_picture_page_between_pages_of_text
   ```
   Expected: the corpus had no PDF files and no PDF manifest entries. The 27 passing were the 26 untouched old tests plus `test_pdf_writers_say_what_they_cannot_show`, which tests the writer module itself (see "Honesty note"). I first made the helper `text_pdfs()` assert the six twins exist, because several loops passed vacuously over an empty list.

**GREEN**:
- `uv run pytest tests/test_corpus.py -q` -> `40 passed in 12.9s` (27 old + 13 new).
- Full gate: `uv run pytest -q` -> `1259 passed in 16.4s` (was 1246); `uv run ruff check src tests tools` -> All checks passed; `uv run ruff format --check src tests tools` -> 48 files already formatted; `uv run mypy src` -> no issues. No warnings (`-rw -W default` run on the corpus tests is clean).

**The 13 new tests** (all in `tests/test_corpus.py`): the brief's three (`test_pdf_corpus`, `test_text_pdf_has_text_and_running_header`, `test_scanned_pdf_has_no_text`, with a >= 3 pages guard added to the last), plus: manifest entries and order (Word first, keys, `source`/`truth`/`image_pages`/`features` rules); PDFs share their Word twin's truth (and no `*.pdf.truth.json`, no flagged items or special spaces in the six); **every truth value and variant is in the pdfplumber text of each text PDF, proved with `normalize`**; every *occurrence* of a value in the Word twin is whole in the PDF (`count(pdf) >= count(docx)`); header equals the Word header and footer equals `Page N of M · Confidential` on every page; headings (lines larger than the page median) are upper-case and body median is exactly 10 pt on every page; claimed features are real and unclaimed ones absent (table count and first row vs the Word twin, pictures vs `word/media`, NOTES block and footnote texts, > 12,000 words iff `thirty_pages`); scanned PDF = one 1240x1754 picture covering each page, no text; mixed PDF = picture page 2 between text pages, the processor's IBAN only in the picture and the BIC in the text; writers refuse services-04 (narrow no-break space), services-03 (text box) and a page that does not exist.

**Determinism and compatibility**
- `generate` twice in two separate processes: `diff -r` identical (all 65 files).
- Against a generation from fbe2c02 (before my edits): all 28 `.docx` and 28 `.truth.json` byte-identical (`cmp` on each of the 56); only `manifest.json` differs, by the eight appended entries (its 28 Word entries are identical as JSON).
- Timing: `uv run python -m tools.make_corpus out` -> "Wrote 28 Word files with their truth and 8 PDF files ... in 2.2 s" (was 1.8 s; limit 30 s). The writers alone: text PDFs 0.01-0.06 s each, scan 0.3 s, mixed 0.1 s.

**Extra checks I ran outside the repo** (scratch only):
- macOS Vision OCR on the scan pages: 48 of 49 forms of supply-01's truth read back; the BIC `ABNANL2A` came out as `ABNANLZA` (the usual 2/Z slip). dpa-01 as a full scan: 38 of 38. The picture page of mixed-01 holds exactly two forms missing from its text layer (the IBAN and "Ms Kay"), and OCR reads both. Text size changes (110 to 130 %) did not improve OCR, so the scan stays at 100 %.
- Task 16 smoke test (its brief's algorithm, roughly): image-only pages are `[]` for text PDFs, all five for scanned-01, `[2]` for mixed-01; lines in the top/bottom 12 % repeated on >= 60 % of pages (digits normalised) are exactly the header and the footer on every PDF; page-median font size is 10 pt everywhere, so only headings are "larger"; pdfplumber `find_tables` finds the pricing table with whole cells.
- The text writer on all 28 specs (25 contracts and 3 annexes): it writes 24 of them, and in 23 of those every truth form the Word file shows is extractable from the page text (including the `€` and no-break-space ones); it refuses the 3 text-box contracts and services-04 as designed. The exception is `dpa-02-annex` (3 address values missing): a value that wraps inside a narrow table cell is interleaved with its neighbour cells in `extract_text()`, so read the cells with `extract_tables()`. None of the eight PDFs is affected; a future twin of an annex with such a table would be.

## Self-review

- Completeness: all seven controller decisions and the brief's Step 1-5 are covered. Items I checked against the text: running header/footer on every page; `Table`; heading sizes; `invariant=1`; Helvetica only (`/BaseFont` of every PDF is Helvetica or Helvetica-Bold, no FontFile); `€` and NBSP render; no narrow NBSP (refused); scan >= 3 pages without a text layer; manifest entries as specified; README PDF section; determinism test extended; Word/truth files unchanged.
- Quality: found and fixed while reviewing: signatures were splitting from their "By:" line (images now keep with the next block), the scan table wrapped amounts such as `EUR 235,549.38` over two lines because Vera is wider than Helvetica (columns now size to their longest cell when that fits), `_Pic` was confusingly close to `_Picture` (now `_Paste`), and a mixed-PDF page check could not notice a block missing from both passes (now checked explicitly).
- Discipline: no features beyond the controller's list except the layout fixes above and the refusals. Not done on purpose: hyperlink annotations (nda-01), PDF document properties (supply-04), text boxes, tracked changes/hidden text in PDFs.

## Concerns / decisions for the controller

1. **`pdf_writer.py` is 710 lines** (docx_writer is 540) with two jobs: the reportlab text PDF and the Pillow scan typesetter. Per the boilerplate I did not split it. The seam is the `# ---- scanned pages` section; the shared parts (`_shown`, `_look`, `_blocks`, `_labels`, the constants) would go in a third module to avoid an import cycle.
2. **Font of the scan.** The brief says a bundled default font is fine. Pillow's own default (Aileron) renders `€ £ ß é ü –` and the em dash as empty boxes (checked glyph by glyph), and the running header has an em dash, so the scan uses Bitstream Vera Sans, which ships inside reportlab (`reportlab/fonts/Vera*.ttf`, no file added to the repo). Vera also gives real bold and italic. If you want Pillow's default, the header text and any `€`/`ß` documents would need substitutes.
3. **Commit trailer.** The boilerplate asks for `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; my harness attribution rule says `Claude Sonnet 5.5`, which is the model I am, and earlier commits in this repo carry the trailer of the model that wrote them (`Opus 5.5`). I used `Claude Sonnet 5.5`. If you want the other line it is a message-only amend.
4. **`features` for the new entries** were my call: text PDFs list only what a PDF really has (`header_footer`, `table`, plus `image`, `footnotes`, `thirty_pages` where the twin has them); `scanned-01` is `["scanned"]` as specified, `mixed-01` is `["mixed"]` (not in the brief).
5. **`supply-10.pdf` has 24 pages / 12,811 words**, not 30; the README says so. `thirty_pages` is kept in its features because the Word definition is "over 12,000 words". Task 24 only uses supply-10.docx.
6. **Anyone reading `manifest.json` must now filter on `"format"`.** Existing tests do through `manifest(corpus)`. Task 10's fixtures and tests should do the same if they iterate the manifest. `normalize` is used as at fbe2c02; Task 7 is changing `textnorm.py`, so re-run `tests/test_corpus.py` after merging.
7. **Honesty note on TDD.** I prototyped the writer module first to learn how reportlab and Pillow behave (pagination hooks, fonts, determinism), then wrote the tests and ran them RED against an unwired `generate()`. The writer-level refusal test therefore never failed.
8. **Process slip.** In one command I ran a read-only `git status` and `grep` inside the task-7 and task-10 worktree directories (to see whether they read the manifest). Nothing was changed there.

## Files changed

`tools/corpus/pdf_writer.py` (new), `tools/make_corpus.py`, `tests/test_corpus.py`, `tests/corpus/README.md`, `tools/corpus/model.py` and `tools/corpus/__init__.py` (docstrings), `tests/fixtures/corpus.py` (docstring/comment).
