# Task 11 report: accept and reject all tracked changes

**Status:** DONE_WITH_CONCERNS (the code is done; the concerns are about later tasks and gaps
outside this task's files)
**Branch / worktree:** `task-11` in `/Users/alijoeee/Developer/the-mask-worktrees/task-11`, cut
from `mac-v1` at c7a4bfa
**Commit:** `53237fb feat: accept-all and reject-all for tracked changes`

## What I implemented

`src/themask/docx/revisions.py` adds `accept_all(pkg) -> int` and `reject_all(pkg) -> int`. Both
work on every part in `pkg.TEXT_PARTS`, including content under `mc:Fallback`. Each one returns
the number of revision elements the text parts held before it ran: `w:ins`, `w:del`,
`w:moveFrom`, `w:moveTo`, the seven `*PrChange` records, `w:numberingChange`, `w:cellIns`,
`w:cellDel` and `w:cellMerge`. The count is the same for both sides and includes the Fallback
copies. Afterwards `has_revisions(pkg)` is False. A second run returns 0 and leaves the XML
unchanged, byte for byte.

The work runs in seven small steps per part, in this order:

1. **Move ranges:** every `w:moveFromRangeStart/End` and `w:moveToRangeStart/End` is removed.
2. **Rows:** a row whose own `w:trPr` has a mark for the side being dropped is removed (accept
   drops `w:del`, reject drops `w:ins`). Otherwise the mark is removed.
3. **Cells:** for a mark in the cell's own `w:tcPr`, accept removes cells marked `w:cellDel` and
   reject removes cells marked `w:cellIns`. Any other cell mark (the other kind, `w:cellMerge`, or
   a mark inside old properties) is just removed.
4. **Paragraph marks** (`w:p/w:pPr/w:rPr/{ins,del,moveFrom,moveTo}`):
   - If the side kept does not have the mark, the paragraph joins the next one. Its content goes
     in front of the next paragraph's content, and the next paragraph's properties win.
   - If it does, only the mark is removed.
   - A mark that was inserted and then deleted is joined on both sides.
5. **Content:** on the side kept, the `w:ins`/`w:moveTo` (accept) or `w:del`/`w:moveFrom` (reject)
   wrapper is removed and its children stay in place. On the side dropped, the element is removed
   with everything in it.
6. **Property changes:**
   - Accept removes the record and keeps the current properties.
   - Reject restores the old properties (`_restore`), keeping what the old properties cannot hold.
   - `w:numberingChange` is removed on both sides.
7. **Deleted text left over:** accept removes stray `w:delText` and `w:delInstrText`. Reject
   renames every remaining one to `w:t` or `w:instrText`, keeping `xml:space`.

Rows, cells and paragraph marks go before content because their marks are also `w:ins` and
`w:del`. Old properties are restored last, after the marks they may hold are gone.

`tests/fixtures/revisions.py` uses python-docx for the package (body, header, footer, styles) and
lxml for the revision markup. It provides:

- `write_revisions(path)`: one file with one of each construct from decisions 2 and 3, with "The
  Buyer shall pay EUR [1,000→2,000] within [30→45] days." as the first line. It also holds the
  "bold" run (whose `w:rPrChange` has an old plain `w:rPr`), changes in the header and footer, and
  a text box whose `mc:Choice` and `mc:Fallback` copies hold the same change.
- `write_paragraph_marks(path, "ins" | "del")`: three paragraphs, "One", "Two" and "Three", with
  the mark of "Two" inserted or deleted.
- Fixtures:
  - `revisions_docx`: written once per session.
  - `rev_pkg`: opened fresh for each test.
  - `rev_pkg_marks`: the deleted-mark variant, which matches the brief's counts (1 newline when
    accepted, 2 when rejected). The inserted variant is tested with the opposite counts.

### Where I went beyond the decisions (all documented in the docstrings and tested)

- **Moved paragraph marks:** `w:pPr/w:rPr/w:moveFrom` and `w:moveTo` count as deleted and
  inserted marks. Without this, accepting a whole moved paragraph would leave an empty paragraph
  where it used to be.
- **Joining:**
  - Markup between the two paragraphs (bookmarks, comment ranges, permissions, `proofErr`,
    custom-XML range markers) is moved into the joined paragraph, between the two contents.
  - If no paragraph follows in the same container (the last paragraph of a cell, a paragraph just
    before a table, the last paragraph of the body), the paragraph keeps its mark and only the
    revision is removed. Word never writes that, and nothing moves.
- **Cascades:** a row left with no cells is removed, and so is a table left with no rows. This
  covers a whole table inserted (then rejected) or deleted (then accepted). Word sees a `w:tbl`
  with no rows as damaged.
- **`_restore` details:**
  - It keeps what the old properties cannot hold: the paragraph mark's `w:rPr` and the section
    break `w:sectPr` inside `w:pPr`, and the `headerReference`/`footerReference` of a `w:sectPr`.
    Without this, rejecting a paragraph change would remove section breaks and paragraph-mark
    formatting, and rejecting a section change would drop headers and footers.
  - A record with no old properties (whether the old element is missing or empty) means "none
    before". The property element is then removed if the file can do without it (`rPr`, `pPr`,
    `trPr`, `tcPr`, `tblPrEx`). A required `w:tblPr` and the structural `w:sectPr` stay, emptied.
  - `w:numberingChange` holds only `@w:original`, the old number text, and no old properties. So
    rejecting removes the record and keeps the numbering, instead of removing `w:numPr`.
  - Revision marks found inside old properties are removed before the old properties come back.
    They neither join a paragraph nor remove a row or cell. The current marks are the ones that
    say what was inserted.
- **Stray deleted text on reject:** reject also converts stray `w:delText` and `w:delInstrText`
  outside any deletion into text. The reader's rejected view reads them, so the "before" copy
  holds what the review saw instead of text the masker would skip.

## Tests and results

There are 49 tests in `tests/docx/test_revisions.py`:

- **The brief's six tests**, kept as written apart from line breaks. `test_reject_restores_old_formatting`
  also checks that `r is not None`.
- **The fixture file:**
  - The full text of both sides, all 23 lines.
  - No revision markup left on either side (`has_revisions`, plus a list of every revision,
    range-marker and deleted-text tag).
  - The count (36 on both sides) and a second run returning 0 with unchanged bytes.
  - The XML each construct turns into on each side.
  - The numbering is kept, the paragraphs are joined and their properties win, no move ranges are
    left, and the Fallback copy is resolved.
  - Stray deleted text, rows and cells.
  - The saved file reopens in python-docx and in `DocxPackage`.
- **The corpus:** for every `tracked_changes` file:
  - Accepting gives exactly the reader's accepted view of the original, and rejecting its rejected
    view.
  - The `only_in_deletion` value is missing from the accepted text and from the raw XML of every
    text part.
  - That value is present after `reject_all` on a freshly opened copy.
  - A file without revisions is left unchanged.
- **Hand-written files:**
  - Changes nested inside changes, including inside a hyperlink.
  - A deleted field instruction (`w:delInstrText` → `w:instrText` with `xml:space`).
  - A whole paragraph moved with block-level range markers.
  - Chained joins carrying bookmarks.
  - Marks that cannot be joined.
  - A mark inserted and then deleted.
  - A paragraph change next to a section break and a mark `w:rPr`.
  - Records with no old properties.
  - Revision marks inside old properties, including a damaged `w:trPrChange`.
  - An inserted numbering mark and math control-character marks.
  - Whole tables inserted or deleted.
  - A row left with no cells.
  - Footnotes, endnotes and a footer, while `word/comments.xml` stays untouched.

Mutation check: I applied 24 single-line mutations to `revisions.py`, one at a time. Examples are
skipping move ranges, never joining, joining at the end, dropping kept children, keeping empty
elements, removing required ones, the wrong order of records, stale cell or row marks being
honoured, only the document part, skipping Fallback, and counting after the run. The tests caught
every one. Two survived the first round (stale cell marks honoured, records in reverse order), so
I strengthened `test_revision_marks_inside_old_properties_are_not_brought_back` and
`test_a_change_record_without_old_properties`. Each now catches them. The script lives in the
scratchpad, not in the repo.

Speed: about 1 ms per side on the 30-page `dpa-05.docx`.

## TDD evidence

**RED 1** (no module yet): `uv run pytest -q tests/docx/test_revisions.py`

```
E   ModuleNotFoundError: No module named 'themask.docx.revisions'
ERROR tests/docx/test_revisions.py
1 error in 0.10s
```

This was expected, because `revisions.py` did not exist yet.

**RED 2** (stub whose `accept_all` and `reject_all` return 0 and change nothing): same command

```
46 failed, 2 passed in 3.35s
```

The two that passed were expected:

- `test_accept_text`: the reader's accepted view of the unresolved file already reads the first
  line that way, so the brief's test cannot tell a no-op apart from `accept_all`. The full-text and
  leftover tests can.
- `test_a_file_without_revisions_is_left_as_it_is`: doing nothing is correct there.

**RED for the tests added later:** with the matching mutation applied, mutations M21 to M24 each
failed exactly the test that was added or strengthened for it (`1 failed, 48 passed`).

**GREEN:**

```
$ uv run pytest -q tests/docx/test_revisions.py
49 passed in 3.32s
$ uv run pytest -q
1391 passed in 20.12s
$ uv run ruff check src tests tools
All checks passed!
$ uv run ruff format --check src tests tools
59 files already formatted
$ uv run mypy src
Success: no issues found in 18 source files
```

The output is clean, with no warnings. The 1391 tests are the 1342 baseline tests plus 49 new
ones.

## Files changed

- `/Users/alijoeee/Developer/the-mask-worktrees/task-11/src/themask/docx/revisions.py` (new)
- `/Users/alijoeee/Developer/the-mask-worktrees/task-11/tests/docx/test_revisions.py` (new)
- `/Users/alijoeee/Developer/the-mask-worktrees/task-11/tests/fixtures/revisions.py` (new; the
  root conftest loads it as a plugin)

I touched no other files. The fixture imports `XMLNS` from `tests/fixtures/docx.py` and the tests
use its `make_docx` fixture, but I did not change either.

## Self-review findings (fixed before the commit)

- **Ruff:** ISC004 flagged implicitly joined strings in the fixture's row list. I replaced them
  with a `_row` helper. Ruff format then fixed the quote style in the test file.
- **Docstring of `_resolve_property_changes`:** it first gave nested records as the reason for
  document order. Both orders actually handle nested records. The real reason is that the
  paragraph mark's `rPrChange` must come before the `pPrChange`, so a `w:pPr` that is left empty
  goes too. I fixed the docstring and added a test for it.
- **Weak tests:** two mutations survived the first round. I strengthened those two tests and added
  `test_marks_that_hold_no_text`.
- **Module docstring:** it now says where the result's text differs from the reader's view of the
  original (see concern 1).

## Issues and concerns

1. **Task 18 (export) should build the reviewed text from the resolved copies.** The text after
   `accept_all` or `reject_all` matches the reader's view of the original except in these places:
   - two joined paragraphs have no `\n` between them;
   - a removed row or cell leaves no empty lines behind;
   - a text box inside a tracked insertion or deletion is read by the reader in both views, but is
     removed on the side that drops it. I checked this: a text box in a `w:ins` shows in the
     original's rejected view, and `reject_all` removes it.

   If `text_after` and `text_before` stay `extract_text(original, view)`, as the plan's `SourceDoc`
   suggests:
   - `apply_mask` offsets will not line up with the resolved copy;
   - a value split by a joined paragraph mark ("John" | "Smith") is reviewed as two paragraphs but
     ends up as one in the masked copy.

   Suggestion: compute `text_after` and `text_before` with `extract_text` on the copies after
   `accept_all` and `reject_all`, and mask those same copies.
2. **Gap in the reader (Task 10, not caused by this task).** Run content outside any `w:p` is in
   neither view. The schema allows `w:ins` and `w:del` holding runs at body, table, row and cell
   level. Resolving unwraps it, but the content stays outside a paragraph, so the masker never sees
   it. I checked this: a body-level `w:ins` holding a run keeps its text in `document.xml` after
   `accept_all`, and the text is in no view. Suggestion: the reader should read such runs, or the
   cleaner should remove them.
3. **Left alone on purpose** ("convert nothing else"). None of these holds text the masker cannot
   see:
   - `w:tblGridChange`: old column widths. `has_revisions` does not count it, and it has no author.
   - The custom-XML revision range markers (`w:customXmlInsRangeStart` and the others). Word 2010
     and later no longer writes custom XML. They are moved along when two paragraphs are joined.
   - Rejecting `w:numPr/w:ins` only removes the mark, as decision 3 says; the numbering itself
     stays.
   - Rejecting `w:cellMerge` does not restore `@w:vMergeOrig`.
   - The empty `<w:rPr/>` or `<w:trPr/>` left after a mark is removed.
   - A footnote or endnote whose reference was deleted on the kept side stays in its part. It is
     still a text part, so it is read and masked.
   - Revisions inside `word/comments.xml`, which is not a text part. The cleaner removes comments.
4. **Commit trailer.** I used `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`: my model,
   this session's attribution setting, and the trailer on the merged Task 10 commits. I did not use
   the boilerplate's `Claude Fable 5.1` line. Say if you want it amended.
5. **Fixture path.** The fixture is at `tests/fixtures/revisions.py`, following your dispatch,
   instead of the brief's `tests/docx/fixtures/revisions.py`.
