# Report: Tasks 20 and 21 (app shell, home screen, analysis worker; review screen)

Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-20`, branch `task-20` (started from `8d991e5`).

| Commit | Subject |
|---|---|
| `0fcf62c` | feat: app shell with drop zone and threaded analysis |
| `c98bc6c` | feat: review screen with highlights, grouped list and actions |

Both end with the boilerplate trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

**Final state:** `uv run pytest -q` 2710 passed in 83 s (baseline before my work: 2537 passed); `uv run ruff check src tests tools` clean; `uv run ruff format --check src tests tools` clean; `uv run mypy src` "no issues found in 43 source files". No warnings in the pytest summary.

---

## Section 1: Task 20, app shell, home screen, analysis worker

### What I implemented

**`src/themask/ui/` (new package; QtCore, QtGui and QtWidgets only)**

- `app.py`: `Settings` (dataclass `retention_days=30`, `out_dir=~/Documents/The MASK`; `load(path)` never fails and gives the default for a missing, unreadable or damaged file and for a value that makes no sense, `save(path)` is atomic, mode 0600), `settings_path()`, `AppContext(engine, user_lists, case_store, settings)` (`engine` is None until loaded), `build_context()` (KeychainKeyStore, `CaseStore(cases_dir(), …)`, `UserLists.load(lists_path())`, `Settings.load(settings_path())`; raises `MaskError` for a damaged lists file, never taking it for empty lists), `main()` (guard, log, QApplication reused if one exists, theme, context, window, `exec`, then waits for the threads; a damaged lists file or an unusable data folder is shown with `show_error` and gives exit status 1). `__main__.py` now calls `ui.app.main()`.
- `main_window.py`: `MainWindow(ctx, load_engine=None)` with a `QStackedWidget` of the screens `home, review, export, restore, cases, settings` (the last four are label placeholders), `current_screen_name()`, `screen_names()`, `show_home/review/export/restore/cases/settings`, `review_screen`, signals `analysisProgress(int, str)`, `analysisFinished()`, `analysisFailed(str)`, module-level `show_error(parent, message)` and `ask_redline(parent) -> bool` (both monkeypatchable), and `HomeScreen` (drop zone, status "Loading…"/"Ready"/"Analysing…", progress bar with a step text, notices line).
  - `open_files(paths, redline_split, case_id=None)`: `None` opens each `.docx` quickly on the GUI thread and asks `ask_redline` once if any has tracked changes (never for a PDF; a file that cannot be opened is left to the analysis to report). With `case_id` the case is loaded from `ctx.case_store` and the analysis is seeded with its entries; the review is built with `reserved=[entry.placeholder …]` (R61) and the case stays on the window as `pending_case` (also `sources` and `redline_split` stay, for Task 22's `ExportOptions`). ONE `CaseLists([], [], set())` is made per analysis and given to both `analyze` and `ReviewState.from_analysis`. A request made while the engine is loading is queued and run when it is ready; a request made while an analysis runs is refused with a message; an engine that failed to load fails every later request at once.
  - Expired cases are purged when the window is built; `MaskError`/`OSError` become a line on the home screen and nothing else. Closing the window hides it and waits for the threads (an analysis cannot be interrupted, and a running QThread must never be destroyed).
  - A small tool bar (Home, Review, Restore, Cases, Settings). "Review" is disabled until a review exists and brings back the review as the owner left it. "Continue to export" (Task 21) shows the `export` placeholder for now.
- `workers.py`: `AnalysisWorker(QThread)` runs `load_sources` → `combined_text` → `analyze`; `progress(int, str)` at 5 loading / 25 reading / 40 finding / 85 grouping / 100 done, `finished((sources, analysis))`, `failed(message)` (MaskError → its message; OSError → "The file could not be read: " + `strerror` (no file name); anything else → "Something went wrong while analysing the file.", logging only `type(error).__name__`). `EngineWorker(QThread)` (`loaded(engine)`, `failed(message)`) makes the engine in a thread; `load_default_engine()` is looked up when the thread runs so a test can replace it. One content-free log line: `engine loaded seconds=…`.
- `drop_zone.py`: `DropZone(QFrame)`: accepts `.docx`/`.pdf` in any case (ignores other files; a mixed drop gives only the contracts), emits `filesDropped(list[Path])`, "Choose files…" button with `QFileDialog.getOpenFileNames(..., "Contracts (*.docx *.pdf)")`, a hint label, a drag-over highlight; a disabled zone takes nothing.
- `theme.py`: `TYPE_COLOURS` (12 distinct pastel hex strings, black text on each is above 12:1), a small stylesheet that uses the system palette (follows dark mode), `apply_theme(app)`.
- `review_screen.py`: a minimal stub in this commit (`load`, `group_count`, `review`, `combined`) so `review_screen: ReviewScreen` exists; Task 21 replaces it.

**Task 17 hand-offs (done here as decided)**

- `errors.KeyStoreError(MaskError)`. `KeychainKeyStore` raises it for `keyring.errors.KeyringError` (read or write) with "The MASK could not reach the macOS Keychain. The key that locks your saved cases is kept there. Unlock your Keychain …" and for a damaged item (was `ValueError`) with the old message plus what to do ("… delete that item in Keychain Access"). The damaged item is still never replaced.
- `CaseStore._scan` catches `OSError` too (the file counts as unreadable).
- `tests/fixtures/keystore.py`: autouse fixture `no_real_keychain` puts `keyring.backends.fail.Keyring` in place for every test and restores the previous keyring.

**One change outside the UI and the hand-offs: `export.load_sources` for a `.doc` file.** The brief's `test_unsupported_file_shows_message` opens `not-a-docx.doc` and expects "save as .docx". `export._load` refused every other suffix with "The MASK reads Word (.docx) and PDF files.", which has no such advice, so the brief's test could not pass. I added an `elif suffix == ".doc"` branch that raises `UnsupportedFileError(NOT_A_DOCX_MESSAGE)` ("This is not a Word .docx file. If it is an old .doc, open it in Word and save as .docx.", the message `DocxPackage.open` already gives for an old binary file). Other suffixes keep their message (the existing `.txt` test still passes). New test `test_an_old_doc_file_is_told_to_be_saved_as_docx` in `tests/test_export.py`.

### Tests (Task 20)

New files: `tests/ui/{__init__,conftest,test_app,test_drop_zone,test_home,test_qt_modules,test_theme,test_workers}.py`, `tests/fixtures/ui.py` (`app_ctx`), rewritten `tests/test_main.py`; extended `tests/keystore/{test_crypto,test_cases}.py`, `tests/fixtures/keystore.py`, `tests/test_export.py`.

- The brief's four are in `tests/ui/test_home.py` (`test_home_to_review`, `test_unsupported_file_shows_message`, `test_scanned_pdf_message`, `test_progress_reaches_100`).
- Controller's list: `ask_redline` asked for supply-03 and not for supply-01 (also: once for three files, never for a PDF, not asked when the caller answers, a file that cannot be opened is left to the analysis); `open_files` with `case_id` seeds and reserves (placeholder kept, numbering goes on after the key, case gone / case damaged are reported); the engine gate (gated by a `threading.Event`: nothing runs until the engine is released, then the queued request runs; an engine that cannot load fails the queued request and later ones); `KeyStoreError` raised under the fail backend (and for a refused read, a failed write, damaged items); purge failure (Keychain and disk) does not stop the window, an expired case is deleted on opening.
- Others: exact progress marks, signals arrive in the GUI thread, failure messages, an unexpected error is logged by its kind only (a planted "Secret Client Ltd" in the error text is not in the log or the message), Settings validation, `build_context`, `main()` error paths, drop events (real `QDragEnterEvent`/`QDropEvent` sequence), palette checks (distinct, valid, contrast ≥ 7), the stylesheet parses (Qt reports nothing; a control proves the check can fail), only QtCore/QtGui/QtWidgets are imported and no module outside `ui` imports Qt, closing the window waits for a running analysis, `python -m themask` in a process of its own (offscreen, stand-in engine, loop that returns at once): window visible, exit 0, log and cases folder made, network guard on.
- `tests/ui/conftest.py`: autouse guard replaces `QMessageBox.critical/warning/information/question` and the three `QFileDialog` getters by a function that fails the test, so an unexpected dialog fails instead of hanging the suite; `restore_logging` is autouse there too.

### TDD evidence (Task 20)

RED, hand-offs: `uv run pytest tests/keystore -q`
```
tests/keystore/test_crypto.py:15: in <module>
    from themask.errors import CaseCorruptError, KeyStoreError, MaskError
E   ImportError: cannot import name 'KeyStoreError' from 'themask.errors'
1 error in 0.09s
```
RED, `.doc` message: `uv run pytest tests/test_export.py -q -k "old_doc or only_word_and_pdf"`
```
E   AssertionError: assert 'open it in Word and save as .docx' in 'The MASK reads Word (.docx) and PDF files.'
1 failed, 1 passed, 34 deselected
```
RED, UI: `uv run pytest tests/ui tests/test_main.py -q -x`
```
tests/ui/test_app.py:16: in <module>
    from themask.ui import app
E   ModuleNotFoundError: No module named 'themask.ui'
1 error in 0.05s
```
(expected: the package did not exist; the first run after the package existed failed only on my own test mistakes, listed below.)

GREEN (final, after both commits): `uv run pytest -q -p no:cacheprovider` → `2710 passed in 82.98s`. At the first commit the suite was `2654 passed in 112.91s`. Per area: keystore + export 143, `tests/ui` 163 (Task 20: 107; Task 21: 56), `tests/test_main.py` 3.

Mistakes in my own tests that the first runs found and I fixed (no source change): `qtbot.waitSignals([finished, failed])` waits for both, so each failing-worker test sat in the 60 s timeout (a 6 minute run; replaced by `waitUntil`); Qt delivers a `QDropEvent` sent with `sendEvent` only to the widget that accepted a drag-enter first (tests now send the enter); the QPoint constructors of `QDragEnterEvent` and `QColor.isValidColor` are deprecated in PySide 6.12 (tests use the QPointF constructor and `QColor(x).isValid()`) so the output is pristine.

### Decisions worth knowing

- The `.doc` test above can only be reached by `open_files` with a `.doc` path: the drop zone and the file dialog filter refuse other suffixes (controller decision 7), so in the app an owner who drops an old `.doc` just gets the "not allowed" cursor and the hint text. If you want them to see the "save as .docx" advice, the drop zone would have to accept `.doc` too (one line in `SUFFIXES`, but then `contract_paths` is also the filter of the file dialog and must keep two lists). I did not do it.
- `AnalysisWorker.finished(object)` shadows QThread's own `finished()`; Qt still sends the original to anyone who connects by its signature (checked). The window waits for the thread with `wait()` before it lets go of it.
- "grouping" (85) is sent when `analyze` returns: the pipeline finds and groups in one call, so the step cannot be sent in the middle without changing detection code.
- `Settings.load` clamps nothing: a retention outside 1–365 days is the default (30), because 0 would delete every case at the next start.

---

## Section 2: Task 21, review screen

### What I implemented

`src/themask/ui/review_screen.py` (710 lines):

- `ReviewScreen(QWidget)`: `load(review, combined)` (raises `ValueError` if `review.text != combined.text`), `group_count()`, `review`, `combined`, `text` (read-only `QTextEdit`), `tree`, `tree_item_for(group_id)` (`ValueError("There is no such group.")` for an unknown id), `highlight_count()`, `hide_selection(type)`, `export_button`, signal `exportRequested()`; also `hide_button` (with a menu of the 12 types, each with a colour swatch), `merge_button`, `split_button`, `always_button`, `never_button`, `warnings_label`, `summary_label`, `tooltip_at(point)`.
- Text pane: each file's text under a header line (its name; " (after)" is dropped when no file has a "(before)" version). Every active find gets a background in `TYPE_COLOURS[type]` with black text; a group to check has a dotted underline and the tooltip "check: The MASK is not sure about this one. …". All highlights are set in ONE `setExtraSelections` call after every change. The occurrences of the selected group(s) are drawn darker so the owner sees where they are (without it a read-only pane shows no marker after the scroll; not in the brief, say if you want it out).
- The pane and the text agree exactly. `_TextMap` converts between pane positions (UTF-16 units) and text indexes: a character outside the BMP is two units, a header and the gap between files have no index, `\r` is shown as a space (a CR+LF would collapse into one break and shift every later position) and a lone surrogate as `?`; each file's text is checked to take exactly the room it should (a mismatch raises instead of drawing on the wrong text). `hide_selection` clips the pane's selection to one file's text and reads the value from `review.text[start:end]`, never from the pane (the pane shows a no-break space as a plain space). A selection over two files, or only over a file name, or nothing is explained with `show_notice` (module-level, monkeypatchable like `show_error`) and changes nothing.
- List: one top-level line per group "canonical — N times — [PLACEHOLDER]" ("1 time"), swatch icon, check box = `set_group_enabled`, column 1 "check" (amber badge) when flagged; one child line per occurrence with the words around it and a box = `set_occurrence_enabled`. A group that is off greys its occurrences but keeps their own boxes. Long lines are cut in the middle so the placeholder stays visible, and the full line is the tooltip. A change of the review (hide, merge, split, lists) rebuilds the list from the state (it re-sorts findings), keeping open groups open and selecting the group the action made; ticking a box only redraws the highlights and the summary.
- Selection: a click on a highlight (hit test on the document layout, scroll-aware) selects its group's line and does not scroll the pane away; dragging to select text is not a click; selecting a group puts the text cursor at its first occurrence (an occurrence line: that occurrence) and brings it to the middle of the pane. Merge needs ≥ 2 groups, Split needs occurrences of one group and not all of them, Always/Never hide need one group (or occurrences of one) and act on its canonical value; the model's refusals ("Only groups of the same type can be merged." …) and a list that cannot be saved are shown with `show_notice`. Continue to export is always enabled.
- Warnings strip from `review.warnings`; summary "45 values · 61 places will be hidden · 4 to check".
- `main_window.py`: `exportRequested` → `show_export()`.

### Timing (the controller asked to note it)

Offscreen, default font, 500 highlights in a 70,000-character text (about 30 pages), `ReviewScreen` shown:

| Step | Time |
|---|---|
| `load()` including layout and paint of the pane (`grab()`) | 0.14 s |
| switching a group off, redraw included | 0.02 s |
| `load()` alone (widget not shown) | 0.015 s |

Limit in the test: 2 s each. Analysis of supply-10 (the 30-page corpus file) itself takes 2.2 s; the engine loads in 1.9 s (checked end to end with the real engine in its QThread through `ui.app.main()`).

### Tests (Task 21)

`tests/ui/test_review_screen.py` (52) and `tests/ui/test_navigation.py` (4); fixtures `supply_08_analysis` (session) and `review_screen` in `tests/fixtures/ui.py` (supply-08.docx through `load_sources`, `combined_text`, `analyze`, `ReviewState.from_analysis` with one `CaseLists`; the groups are copied, so a test cannot spoil the next).

- The brief's five, as written.
- Controller's three: untick one occurrence updates the plan and the highlights; merge of two selected groups updates the tree; selecting a group moves the text cursor to its first occurrence.
- Exactness: the pane is header + combined text; every highlight lies exactly on its find (text and position) with the colour of its type and black text; two files with a header each, an emoji and a CR+LF before the finds; a selection in the second file hides the right text; a selection over two files or over a file name is refused; a selection reaching into a header is clipped; a no-break space is taken from the text.
- Behaviour: boxes follow the state, a switched-off group greys its occurrences and keeps their switches, ticking back restores, the summary, warnings, export with nothing to hide, load replaces everything, a review of another text is refused; hide menu has the 12 types; split rules; merge of different types refused; Always/Never hide put the canonical on the list (saved to `lists.json`), work from an occurrence, need one group, a list that cannot be saved is explained; a real mouse click on a highlight selects its group and the cursor stays in the clicked occurrence; a drag is not a click; the "check" tooltip (also through a real `QHelpEvent` and `QToolTip`); a group switched off can still be found; selected group's finds stand out; performance.
- Mutation check (temporary edits, each reverted, `git diff` clean afterwards): ignoring astral characters → 5 tests fail; not replacing CR → 5 fail; letting a click scroll → 1; no darker colour → 1; not greying → 1; ignoring occurrence boxes → 2; reading the value from the pane → 1; no dotted underline → 1; drawing disabled groups → 7.

### TDD evidence (Task 21)

RED: `uv run pytest tests/ui/test_review_screen.py -q` against the Task 20 stub: `45 failed, 6 errors` (13× `'ReviewScreen' object has no attribute 'tree_item_for'`, 13× `… 'text'`, 8× `… 'tree'`, 3× `… 'highlight_count'`, and the 6 errors `module 'themask.ui.review_screen' has no attribute 'show_notice'` from the `notices` fixture).
GREEN: `52 passed in 5.9 s` for that file; whole suite `2710 passed in 82.98s`.

---

## Files changed (both commits, `git diff --stat 8d991e5 HEAD`: 29 files, +4153/−62)

Source: `README.md` (the entry point exists now), `src/themask/{__main__,errors,export}.py`, `src/themask/keystore/{cases,secrets}.py`, `src/themask/ui/{__init__,app,drop_zone,main_window,review_screen,theme,workers}.py`.
Tests: `tests/fixtures/{keystore,ui}.py`, `tests/keystore/{test_cases,test_crypto}.py`, `tests/test_export.py`, `tests/test_main.py`, `tests/ui/{__init__,conftest,test_app,test_drop_zone,test_home,test_navigation,test_qt_modules,test_review_screen,test_theme,test_workers}.py`.

## Self-review

- Completeness: every item of both briefs and of the 14 controller decisions is done; see the lists above for the three places I went beyond or around them.
- Beyond the brief (all small, say if any should go): the tool bar and the "Review" action (so the owner can leave the review and come back without losing their work), the darker colour for the selected group, the summary line, swatch icons, `tooltip_at`/`screen_names`/`is_analysing`/`wait_for_workers`/`show_export` as public methods, one log line for the engine load, the two import-guard tests, `hide()` before the wait in `closeEvent`.
- Quality: `ruff format` applied to every file I wrote; one `# noqa: BLE001` pair in `workers.py` and one in `main_window.py` (a thread and a best-effort pre-check must not die of an unexpected error; logging the traceback would break the content-free log rule).
- The drop zone's minimum height (`setMinimumHeight(220)`) was found with an offscreen screenshot after the first commit (the hint text was clipped) and so landed in the second commit, not the first.
- Not verified on a real Mac: everything ran offscreen. Not exercised: a drag from Finder, the native file dialog, the Keychain permission prompt, macOS dark mode as the system draws it (I rendered offscreen screenshots with a dark palette: highlights, header and list were legible), `Briefcase` packaging.

## Concerns for the controller

1. `src/themask/export.py` changed (the `.doc` branch, 5 lines + docstring). Task 15 is still under review; if its review also edits `_load`, expect a small merge conflict.
2. File sizes: `review_screen.py` 710 lines and `main_window.py` 496 lines (it also holds `HomeScreen`). Each has one purpose and I did not split them (boilerplate rule), but `HomeScreen` → `home_screen.py` and `_TextMap` → `text_map.py` would be easy moves if you want smaller files.
3. Always hide / Never hide act at once, with no confirmation, and change the owner's lists for every future document (Settings, Task 23, is where they undo it). Always hide writes the plain canonical value (a `CUSTOM` entry), not `TYPE:value`, so in later documents a company on the list is `[CUSTOM_n]`.
4. Closing the window or quitting during an analysis waits for it (up to the length of the analysis; the window is hidden first).
5. The `export`, `restore`, `cases` and `settings` screens are label placeholders; "Continue to export" only shows the export placeholder until Task 22.
6. Other subagents' pytest runs were running at the same time on this machine, so the suite's wall time in the log (83 to 133 s) varies.
7. Both commits carry the boilerplate trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` as the dispatch said, not the `Claude Sonnet 5.5` line the harness's own attribution reminder suggests.
