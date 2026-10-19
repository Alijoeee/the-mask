# Review of Tasks 22+23 — export dialog; restore, cases and settings screens

Plain review in lean mode (ruling R59). Reviewer: Claude Sonnet 5.5, 2026-10-19.
Subject: branch `task-22` at `49d69ca` (worktree `/home/user/the-mask-worktrees/task-22`). I edited,
committed and switched nothing there; `git status` is clean after all my runs.

**Note on the review package.** `task22-ccf74ed..49d69ca.diff` does not hold the Task 22 export dialog:
`d06fb7f` was committed on the branch before `mac-v1` was merged into it (`ccf74ed`), so
`export_dialog.py`, `test_export_dialog.py`, the `show_export` wiring and `tests/helpers.analysed` sit in
the base of that diff. I read them from the tree and from `git diff 0baa904..49d69ca` (6,115 lines, 23
files; kept at `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/full-0baa904..49d69ca.diff`). Everything below covers both tasks.

**Scratch files** (mine, outside the repository; the labels are used below):
- diff of both tasks against mac-v1: `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/full-0baa904..49d69ca.diff`
- probes file: `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/t22/probes/test_probe_t22.py`
- stress files: `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/t22/probes/test_stress_gc.py`, `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/t22/probes/test_stress_gc2.py`, `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/t22/probes/test_stress_gc3.py`
- plugin that turns the collector back on: `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/t22/plug/gc_back_on.py`
- logs of every run and the scripts that made them: `/tmp/claude-0/-home-user-the-mask/12765d91-280c-5da7-8bff-4a2c38dc5193/scratchpad/review/t22/`

## Verdict

**NEEDS FIXES: one Important item (I-1, R103 (b) is only partly met), no Critical.** Everything else in the
two briefs, the dispatch decisions and R103 is met. No leak path and no crash path was found, and I-1 is the
only way I found for a case other than the owner's choice to end up in a restored file. The code is careful and
the tests are real: I read all of `test_restore_screen.py` and most of the other new tests, ran `tests/ui` five times and
the whole suite once (nothing flaky) and added probes of my own. I-1 is small: one branch in
`_order_cases` and the assertions that encode it.

## Findings

### Critical

None.

### Important

**I-1. A case the owner chose by hand is replaced by another case, without a question, when the other
case holds more of the placeholders.** R103 (b) says "a hand pick stays"; the controller accepted the
reading "a hand pick lasts until its restore or the next file". The code ends it in a third way.

- Where: `src/themask/ui/restore_screen.py:509-516` (`_order_cases`: `keep = None  # the owner's case fits
  worse than another: the better fit is offered`), reached with `insist=False` from `load_file` (:422) and
  `_text_changed` (:603). The module docstring says both "it stands while that is edited" (:14-16) and
  "unless the owner chose a case and it fits as well" (:9-10); the report (section 2, reading 2) gives only
  the first.
- Reproduction (the probes file, run against the worktree):
  (a) A1A1 holds the person and the company, B2B2 the person only. `refresh_cases("B2B2")` ("Restore from
  this case"), then `load_file` of a file with `PERSON_1 ... COMPANY_1`: the combo shows A1A1
  (`PROBE-B selected after drop: A1A1`). With the file loaded first and `refresh_cases("B2B2")` after it,
  B2B2 stays (test `test_the_case_asked_for_in_the_cases_screen_wins_over_a_better_fit`, :712): the same
  request wins or loses depending on the order.
  (b) Paste `[PERSON_1] and [COMPANY_1]`, pick B2B2 by hand, append a line to the paste box: A1A1
  (`PROBE-C pick before edit: B2B2 after edit: A1A1`).
- Why it matters: placeholder names repeat from case to case, which is why R103 exists. A file that really
  belongs to the chosen case never fits another case better, so the override fires when the file carries
  a placeholder the chosen case lacks, for instance one the AI added or numbered on (a `[COMPANY_3]` that
  another contract's key holds). The owner's explicit choice is then swapped for the screen's guess, the
  only sign is that the combo and the preview change, and the next click on Restore writes the other
  contract's values.
- Fix (small): in `_order_cases` honour `chosen` always: delete the `keep = None` branch (the `insist`
  parameter then has no job and can go). The pick then ends only with `_spend_choice` or the next
  `load_file`, as accepted. Update the docstrings above, `test_the_owner_s_case_is_kept_while_it_fits_as_well_as_the_best`
  (:678; its last three lines assert the override), `test_a_text_that_makes_another_case_the_best_fit_reads_the_file_again_for_it`
  (:405; the paste after the pick), and add sequence (a) as a test. If a guard is wanted for "a pick made for an
  earlier pasted text" it has to ask (show `choose_label`) or end the pick when the paste box is
  emptied; it must not switch.
- If the controller keeps the safety net instead: park it with a `Ruling:` line (a stronger-fitting case
  replaces a hand pick; cost if wrong: the wrong contract's values in the restored file when an AI numbers
  on a placeholder another case holds).

### Minor (reported and parked; no fix round asked)

- **M-1. A file that cannot be read leaves the previous file on screen.** `restore_screen.py:413-415`
  (`load_file` returns early). Probe A: restore a good file, then drop `corrupt.docx`: the status line says
  "This is not a Word .docx file. ...", but the label still names the good file, Restore stays enabled and
  the old result panel stays visible. Harmless (Restore restores the file the label names) but it reads as
  if nothing was refused. Clear the file state, or at least the result panel, on a failed load.
- **M-2. A file name that points to a case which is not saved says nothing.** `matcher.py:104-114`
  returns None for a code that is no stored case; the screen then ranks by placeholders and, with one case
  or one strictly better fit, preselects silently although the name says `B2C3` (expired or deleted). R103
  does not ask for more and the preview shows the values; one line ("The file name says case B2C3, which is
  not saved on this Mac.") would close it.
- **M-3. Delete all is off while the Keychain refuses.** `cases_screen.py:186-192, 222-230`: the table is
  empty and `delete_all_button` needs rows, but `CaseStore.delete_all` needs no key
  (`keystore/cases.py:132-139`); spec 8.6 promises "delete ... all cases at any time". Agrees with the
  report's concern 6.
- **M-4. Up to three Keychain reads at start-up.** The purge (`main_window.py:267`, `_purge_expired_cases`
  :560), the Restore screen (`restore_screen.py:403` -> `refresh_cases` :438) and the Cases screen
  (`cases_screen.py:148`) each open the case folder and ask the Keychain for the key
  (`KeychainKeyStore` does not cache, `keystore/secrets.py:48-66`) when a case file exists.
  `show_restore` and `show_cases` refresh anyway, so the constructors' loads only serve tests. An unsigned
  build may show three Keychain prompts at launch. Load lazily on first show.
- **M-5. `OWNER_NAME` is still the placeholder** (`about.py:3`): the About box says "Made by <owner name —
  set in about.py>" until the owner sets it (the plan says so; owner action before the app is shared).
- **M-6. A held tracked-change row has a check box that may do nothing.** `restore_screen.py:196-203`: for a
  place where several placeholders meet in one change, ticking changes nothing (test :312 says "no restore
  puts it back, confirmed or not", R96); for a placeholder a change runs through, ticking does restore it.
  Both rows read the same, so the owner cannot tell which. Word the first as "cannot be restored here" or
  leave its box out.
- **M-7. "Add file to this case" drops non-contract files silently.** `cases_screen.py:247-253`
  (`contract_paths(ask_for_files(self))`); the home screen names such files (`filesRefused`), this path
  does not. The dialog's filter makes it rare.
- **M-8. Copy gives no sign that it worked, and the success text does not say "keep the file name".**
  `export_dialog.py:347-348`, `_saved_text` :324-343. R103 (a) relies on AI tools keeping
  `MASKED-<code>.docx` (the report's concern 5).
- **M-9. QLabel text format.** `refused_label` (`main_window.py:111`), `file_label`, `saved_label`,
  `check_label`, `unknown_label` (`restore_screen.py:315, 337-341`) keep Qt's auto-detect, so a file name
  such as `A <b>x</b>.doc` would be drawn as markup; `preview_label` and `about_label` are already
  `PlainText`. Cosmetic; set `Qt.TextFormat.PlainText` on them.
- **M-10. Duplication and size.** `_count` is copied four times (`cases_screen.py:79`, `export_dialog.py:90`,
  `restore_screen.py:104`, `review_screen.py:89`). `restore_screen.py` is 732 lines (the case-choice state
  `_manual / _for_next_file / _unclear / _ranked_on / _ranked_name` and its four methods would be a small class
  of their own), `main_window.py` 617 (HomeScreen, about 100 lines, could leave). `settings_screen.py:109,
  208` import `RETENTION_DAYS` and `settings_path` from `themask.ui.app` inside functions to dodge a cycle;
  they belong in a small module of their own. The final review already has the splits on its list.
- **M-11. The report says the 6 skips are macOS-only tests.** They are the six IPv6 variants of
  `tests/test_netguard.py:85` ("This computer has no sockets of that family"). No macOS-only test skips in
  `tests/`.
- **M-12. For the final review: the app-side exposure behind the garbage-collector fixture** (section D):
  not a fix-round item here.

## A. Briefs and dispatch decisions, one by one

Verdicts: met / partly / not met. Lines are in `/home/user/the-mask-worktrees/task-22`.

**Task 22: the export dialog** (`src/themask/ui/export_dialog.py`)

| Item | Verdict | Where |
|---|---|---|
| `ExportDialog(QDialog)`, `run(sources, review, options, ctx)` runs `export_case` in a `QThread` with a progress bar; `save_case = ctx.case_store.save` | met | `ExportWorker` :94-142, `run` :205-231, busy bar :168-170 (the export cannot say how far it is) |
| Signal `finishedExport()`, `result`, `copy_button`, `summary_text()` | met | :154, :200-203, :173-175, :248-252 |
| Success view: outputs; "Also found in the masked copy — not marked by you:"; "Left visible on purpose:" (`allowed_hits`); "Not checkable (too short):" (`unverifiable`) | met | `_show_saved` :289-295, `_saved_text` :324-343, strings :76-78 |
| Copy instruction puts `AI_INSTRUCTION` on the clipboard | met | :347-348 (brief's test :95) |
| Show in Finder through a monkeypatchable module-level `reveal(path)` | met | `reveal` :85-87, `_show_in_finder` :350-354; `tests/ui/conftest.py` `no_real_finder` makes any real `openUrl` fail a test |
| Blocked view "Saving blocked: a marked value is still present", each `LeakHit.part` + context, `copy_button` disabled, only Back to review | met | `_show_blocked` :297-303, `BLOCKED` :69, `_hit_line` :357-362, `_offer` :312-322 (brief's test :108) |
| `ExportResult.leak_hits` = blocking leftovers only, `allowed_hits` separate | met | blocked view reads `leak_hits`, saved view `allowed_hits` |
| Errors as plain text, `finishedExport` still emitted, only the error type logged | met | `ExportWorker.run` :133-140 (MaskError -> `user_message`, OSError -> `strerror`, other -> `_LOG.error("... error=%s", type(error).__name__)`), `_show_failed` :305-310, no engine :222-224 |
| `tests/helpers.analysed(ctx, paths)` | met | `tests/helpers.py:68-74` |
| MainWindow wiring: `ExportOptions(out_dir, redline_split, retention_days, existing_case, existing_codes = case ids + unreadable stems)` | met | `main_window.py:305-335` `show_export`, `_case_codes` :337-343 (R74), `_export_closed` :345-348; the window waits for the export on close :585-586 |
| Brief's three tests | met | `tests/ui/test_export_dialog.py:95, 108, 139` (verbatim) + 23 more |

**Task 23: restore, cases, settings, window polish**

| Item | Verdict | Where |
|---|---|---|
| RestoreScreen interface: `load_file`, `case_combo` (id as item data), `altered_list` with check boxes, `restore_button`, `restore_text_button`, `paste_box`, `result_box`, `report_label`, `restoreFinished`; a DropZone for the AI's `.docx` | met | `restore_screen.py:407, 284, 319, 320, 331, 324, 348, 335, 259, 305-314` |
| `plan_docx` + `restore_docx(confirm_altered = ticked ordinals, True when all ticked, expected_sha256 = plan.sha256)`, the fingerprint ALWAYS (R96) | met | `_plan_file` :581-593, `_confirmation` :225-233, `_restore_file_with` :627-655; a file without a plan is planned again first and never restored without the fingerprint :632-640 |
| "The file changed since it was checked" shown, list made again | met | :643-650 (`FILE_CHANGED_MESSAGE` from `docx_restore`) |
| A held tracked-change item's row says it stands for every placeholder in that change | met | `_row_text` :196-203, `TRACKED_NOTE` :97, `_written` :168-177 (see M-6 for the check box) |
| Paste box re-plans on every text change | met | `textChanged` :326 -> `_text_changed` :595-605 -> `_replan_text` :559-565 |
| Case combo in `suggest_cases` order, most recent preselected when nothing matches | met | `_order_cases` :497-536 |
| Result panel: `RestoreReport.summary()`, unknown list, Show in Finder, Copy for restored text | met | `_show_result` :698-720, :727-732 |
| CasesScreen: `CaseSummary` table, `confirm(parent, message)` module-level, Delete / Delete all (both confirm; Delete all takes unreadable files and crash leftovers), Restore from this case, Add file to this case -> `open_files(paths, None, case_id)`, unreadable files listed with Delete | met | `cases_screen.py:61-66, 152-168, 255-300, 302-323, 242, 247-253`; `main_window.py:263-264, 434-435`; keystore :132-152 |
| SettingsScreen: always/never one per line -> `UserLists` at `lists_path()`, `ctx.user_lists` updated in place, retention 1-365 (default 30), folder picker (monkeypatchable), Save, About with `APP_NAME`/`VERSION`/`OWNER_NAME` and "Runs fully offline. Restored text you copy is on the clipboard in clear." | met | `settings_screen.py:200-250` (`_save`), :116-118, :193-198, :44-48 (see M-5) |
| `purge_expired` on start-up | met | `main_window.py:267, 560-569` (a failure is a note on the home screen) |
| Polish: second `open_files` while one is queued -> `BUSY_MESSAGE` | met | `main_window.py:413-415` (`_analysis` or `_queued`) |
| Polish: try/except around the review-building step, exception TYPE only logged | met | `main_window.py:483-500` (`_LOG.error("review failed error=%s", ...)`), nothing of the window changes when it fails (screen loaded first :296-303) |
| Polish: tool-bar navigation off while `is_analysing()` | met | `_set_navigation` :391-395, off in `_start` :474, on in `_release_analysis` :519 |
| Polish: refused `.doc` names on screen, never logged | met | `drop_zone.py` `filesRefused`, `main_window.py:431-432, 595-603` (`test_files_that_were_not_opened_are_named_on_the_home_screen` asserts the names are absent from the log) |
| `exported` fixture | met | `tests/fixtures/ui.py:80-102` |
| Brief's five tests | met | `tests/ui/test_restore_screen.py:122, 136`; `tests/ui/test_cases_settings.py:112, 449, 459` (verbatim; the two files hold 77 and 36 test functions in all) |

**R103**

| Item | Verdict | Where |
|---|---|---|
| (a) `suggest_cases(text, cases, file_name=None)` prefers the one case whose code is a whole token of the file name | met | `matcher.py:104-139` (`case_in_file_name`: runs of letters and digits, case-folded; two codes or none tell nothing); screen passes the name :421-422 and `None` for pasted text :598; my probe D: `MASKED-K4F7.docx`, `_final`, `(1)`, en dash, `masked-k4f7 – reviewed`, `K4F7 v2`, `-1-before`, `.DOCX` all pick K4F7; `MASKEDK4F7.docx`, `K4F7-M5N6.docx`, full-width letters pick nothing |
| (b) a tie that no file name decides: nothing preselected, "Several cases fit this file — choose one.", Restore (and Restore text) disabled until the owner chooses; a hand pick stays | **partly** | asks/disables/sentence met: `_is_a_guess` :157-165, `_order_cases` :518-533, `_show_choice_notice` :538-542, `_update_state` :576-579; **the hand pick can be replaced: I-1** |
| (c) combo titles carry code, date, original file names; a read-only label previews up to five "[PLACEHOLDER] → value" pairs, never logged | met | `_case_title` :122-130, `_preview` :141-154 (`PREVIEW_LINES = 5`, plain text :294, values cut at 60 characters), `_update_state` :571-575; `test_the_values_of_the_preview_are_never_logged` |
| Accepted readings 1, 3, 4, 5 (no fit: newest preselected; same sentence for text; case-insensitive; text after a file ranks for the text) | as the report says | tests named in the report exist and pass |
| Reading 2 (a hand pick lasts until its restore or the next file) | partly | I-1 |

## B. The rules

- **Originals never modified: met.** The screens open nothing for writing. `restore_docx` writes a new file with
  `open("xb")` (`docx_restore.py:_new_file`), never over a file; `test_the_restored_file_is_a_new_one_beside_the_ai_s`
  compares the AI's bytes before and after. Export is unchanged (Task 15).
- **The log never gets content or file names: met.** `grep` of every logging call in `src/themask/ui`: six
  `_LOG` calls (`export_dialog.py:139`, `main_window.py:493`, `restore_screen.py:688`, `workers.py:97, 139,
  142`); the three new ones write `error=<type name>` only, `workers.py:142` the engine's load time. None
  in `cases_screen`, `settings_screen`, `matcher`, `keystore`. No `print`, no `warnings`. Tests assert it for
  the review step, the export, the restore, the refused names and the preview values. My probe E ran a
  whole restore flow (file and text) at DEBUG level: `caplog.text == ''`.
- **Qt imports: met.** `tests/ui/test_qt_modules.py:25-36` walks `rglob("*.py")` over `src/themask`, so the new
  modules are covered without a list to keep; it passes; `grep` shows only QtCore, QtGui, QtWidgets.
- **No network: met.** No socket/urllib/http/QtNetwork/subprocess in `src/themask/ui`. Show in Finder is
  `QDesktopServices.openUrl(QUrl.fromLocalFile(folder))`, a local folder. The suite runs under the
  network guard (`tests/conftest.py`).
- **Keychain untouched in tests: met.** The autouse `no_real_keychain` fixture, the in-memory key store
  in `app_ctx`, and the `tests/test_main.py` subprocess uses an empty data folder (`_scan` returns before it
  asks for the key).
- **Clipboard warning: met.** The About sentence (`settings_screen.py:44-48`, exact) and the tooltip of the
  restore Copy button (`restore_screen.py:346`). The export's Copy puts only `AI_INSTRUCTION` there.
- **Threading: met.** The three QThread workers hold plain Python data (paths, `ReviewState`, `ExportOptions`,
  `Engine`, `UserLists`, `ctx.case_store.save`, a bound method of a plain class) and send plain payloads
  (`Signal(object)`); nothing in a worker touches a widget. `ExportWorker` signals reach the dialog queued
  (`test_the_files_are_made_in_a_thread_and_reported_in_the_window_s` compares thread ids). The dialog
  cannot be closed while its worker runs (`reject` :254-259; every button is hidden and disabled while it
  works :312-322), the window waits for it on close (`main_window.py:585-586`) and `app.main` calls
  `wait_for_workers()` again after `exec` (`app.py:158-159`); the worker is joined (`wait`) before `deleteLater`
  in `_release_worker` :277-281. Restore, Cases and Settings run in the GUI thread (a restore takes about
  20 ms for the largest corpus contract; a very large file would freeze the window for a moment, not
  break it).

## C. The keystore changes (`src/themask/keystore/cases.py`)

**Minimal, necessary, tested, and nothing weakened: met.** Against `mac-v1` the net change is two methods and a
rebuilt `list`: `delete_unreadable(name)` (:141-152) and `load_all()` (:169-179); `list()` (:181-196) is
`load_all()` without the keys and behaves as before (`test_list_is_load_all_without_the_keys`). The Cases screen
needs the first to delete a damaged file or a copy made in Finder (`CaseStore.delete(stem)` cannot name those);
the Restore screen needs the second to rank every case by its placeholders with one Keychain read. Deletion
reaches only a path the last listing reported (`path not in self.unreadable` -> `ValueError`): `dir / name`
for `../outside.mask`, `/etc/passwd`, `sub/K4F7.mask`, `.`, `..`, `""` and `notes.txt` is never in that list;
a case that opens is refused; a file that is gone is no error. Neither method writes anything, so no
plaintext. `delete_all` is unchanged against `mac-v1` (the report's note about removing a reset refers to
the checkpoint, not `mac-v1`). Tests: `tests/keystore/test_cases.py` +90 lines (four `load_all` tests incl.
newest-first, ties by id, empty folder; four `delete_unreadable` tests incl. a parametrised guard over seven
names; the Keychain-reads-once assertion extended to `load_all`).

## D. The segmentation-fault workaround (`tests/ui/conftest.py:42-57`)

**Short answer for the final review: the workaround is test-only, it is needed, and it works. I found no path in
`src/` where a Python wrapper of a Qt widget is created, held or released by a worker thread, and I could not
make the crash happen with anything the app does while a worker runs. It does hide an exposure the app shares in
kind but not in size: the crash needs a LARGE tree of wrapped widgets taken apart while a worker's collector
runs, and the app does that only when no worker is alive. No action is needed for these tasks; one optional
hardening is named at the end.**

1. **What the fixture is.** `collect_in_the_main_thread_only` (autouse, per test, `gc.disable()` before and
   `gc.enable()` after; pinned by `tests/ui/test_workers.py:37-41`). It covers `tests/ui` only. The only other
   test that starts the app, `tests/test_main.py`, runs it in a subprocess with the normal collector, a stand-in
   engine and an event loop that returns at once, so no worker and no window teardown overlap there.
2. **The diagnosis holds; I reproduced the crash here.** With a scratch plugin that turns the collector back on
   after the fixture (the plugin above), `PYTHONMALLOC=debug pytest tests/ui/test_home.py -q` died
   with exit 139 in 1 of 6 runs (`Fatal Python error: Segmentation fault`; current thread = `AnalysisWorker.run`,
   `workers.py:90`, inside a pdfminer parse, marked `Garbage-collecting`; main thread in pytest-qt's
   `waitSignal` -> `QEventLoop.exec`, `test_home.py:73`), the other five ran clean. With the fixture:
   0 crashes in 5 runs of `test_home.py` + `test_export_dialog.py` under the same allocator and in 5 runs of
   `tests/ui` (one of them inside the whole-suite run).
3. **A model of the mechanism (the stress files).** A `QThread` that allocates
   cyclic garbage and forces `gc.collect()` about 170 times in 12 seconds, while the GUI thread destroys widgets
   inside a real `QEventLoop` (so the interpreter lock is released as in `waitSignal`), `PYTHONMALLOC=debug`,
   one process per trial:
   - **whole `MainWindow`s** (all five screens, hundreds of wrapped widgets) created and `deleteLater`'d in a
     loop: **5 of 6 trials crashed** (exit 139), every time with the worker inside `gc.collect()` marked
     `Garbage-collecting` and the GUI thread in `loop.exec()`: the signature of the suite crash;
   - **`ExportDialog`s** (about a dozen wrapped widgets) created and `deleteLater`'d, about 2,500 times in 8 trials: **no crash**;
   - **what the owner can reach while a worker runs** (the Restore change list cleared and refilled with up to
     25 checkable rows, the Cases table rebuilt with 1-5 rows, the case box rebuilt), about 2,600 rounds in 8
     trials, and as many in an earlier variant that used `processEvents` instead of a real event loop: **no crash**.
   So the race is real and grows with the size of the tree that is torn down next to a collecting worker: a
   dialog-sized or item-sized teardown did not trigger it in 24 trials (8 with dialogs, 16 with item rebuilds), a
   window-sized one did in 5 of 6. (The model forces a full collection every 65 ms, far more often than the app's
   workers cause one.)
4. **Where the app tears widgets down, and what runs then.**
   - The one widget tree the app destroys while it runs is the export dialog: `MainWindow._export_closed` ->
     `dialog.deleteLater()` (`main_window.py:345-348`). The dialog cannot close while its `ExportWorker` runs
     (`export_dialog.py:254-259`), and the analysis cannot be running behind a modal dialog, so no worker is alive then.
   - The window and its screens are taken apart once, at exit, after `wait_for_workers()` has joined every thread
     (`app.py:158-159`, `main_window.py:573-592`).
   - List, table and case-box items are rebuilt on the Restore, Cases and Review screens. The Review screen only
     reloads after the analysis thread is joined (`_analysis_finished` -> `_release_analysis` -> `show_review`). Restore and Cases can be
     used while the **engine loads** (the first seconds after launch; the tool bar is off only during an analysis,
     `main_window.py:474`), and the `EngineWorker` is allocation-heavy then. That is the only overlap I found; it
     is item-sized (the second bullet of point 3), which did not crash.
5. **Can a wrapper of a widget be released from a worker thread in the app? No path found.** The workers hold plain
   Python data only: `AnalysisWorker` (`workers.py:48-110`) paths, engine, lists, key entries; `EngineWorker` a
   factory; `ExportWorker` (`export_dialog.py:94-142`) sources, `ReviewState`, `ExportOptions`, engine, lists and
   `ctx.case_store.save` (a bound method of a plain class); their signals carry plain results. All three `QThread`
   objects are made in the GUI thread, joined with `wait()` and `deleteLater()`'d there (`main_window.py:514-519,
   552-556, 573-586`; `export_dialog.py:237-246, 277-281`). The only way left would be a reference cycle holding a
   widget wrapper that a collecting worker frees; the screens are parented (C++-owned, long-lived), the connections
   use bound methods or short lambdas of long-lived objects, and the one parentless-looking object, the dialog, is
   parented to the window.
6. **If it ever hit.** The app would quit (segmentation fault). No data is at risk: cases are written to a temporary
   file and renamed (`keystore/cases.py` `save`), the originals and the AI's file are never written to; at worst a
   half-written `... - restored.docx` could be left next to the AI's file by a restore that was running.
7. **Options for the final review (the controller's call).** (a) `gc.disable()` in `app.main` and collect from the
   GUI thread only (`QTimer`: a young collection every second or so, a full one every 30 s and after each worker
   ends): removes the overlap by construction, about 15 lines, plus a test that the collector is off in the app;
   (b) switch the tool bar off while the engine loads too (cheap, but it stops the owner from restoring a file while
   the engine loads, which needs no engine); (c) wait for a PySide6 that does not do this (6.12.0 is pinned). My view:
   none is needed for Tasks 22+23; (a) is the cheap insurance if the final review wants zero exposure.

## E. Tests

- `uv run --no-sync pytest tests/ui tests/keystore -q -p no:cacheprovider` -> `462 passed in 61.63s (0:01:01)`.
- `uv run --no-sync pytest -q -p no:cacheprovider` (whole suite) -> `3041 passed, 6 skipped in 224.06s (0:03:44)`
  (not 6 minutes). The 6 skips: see M-11.
- Flakiness: `pytest tests/ui -q` three more times -> `341 passed in 61.15s`, `62.87s`, `65.19s`;
  `PYTHONMALLOC=debug pytest tests/ui/test_home.py tests/ui/test_export_dialog.py -q` five times -> `71 passed`
  each (47-50 s). With the first run and the full run `tests/ui` was green five times; no flaky test, the
  wall-clock test (500 highlights) included.
- `ruff check --no-cache src tests tools` -> `All checks passed!`; `ruff format --check --no-cache src tests
  tools` -> `134 files already formatted`; `mypy src` (cache outside the worktree) -> `Success: no issues
  found in 52 source files`.
- The brief's eight tests (three for Task 22, five for Task 23) exist verbatim and pass (locations in
  section A). Test functions per file: `test_export_dialog.py` 26, `test_restore_screen.py` 77,
  `test_cases_settings.py` 36, `test_matcher.py` 21, `keystore/test_cases.py` 47 (parametrised ones expand to more cases).
- `git diff --check 0baa904..49d69ca` is clean; `pyproject.toml` and `uv.lock` are unchanged; no TODO, FIXME,
  `print` or `breakpoint` in the new code; every `noqa` and `type: ignore` has a reason.

## F. Reasonableness

Good overall. What the owner would trip over is in M-1 (a refused file still looks loaded), M-5 (the About
box shows the owner placeholder), M-6 (a tick that does nothing), M-3 (cannot clear cases while the Keychain
refuses) and M-8 (no sign that Copy worked). Wording is plain and consistent ("Saving blocked: ...", "Several
cases fit this file — choose one.", "N placeholders restored, M need your check."). Dead code: none found
(`is_running` is used by the tests only, which is fine for a state query). Duplication and sizes: M-10.

## Residual risks the controller may want in the final review (not findings)

1. **Count-based preselection is still a guess when exactly one case fits strictly better.** R103 asks only
   for ties. A stray placeholder that another case happens to hold (see I-1's explanation) tips the
   preselection to that case with no question; the file name (R103 (a)) and the preview are the guards.
   Asking whenever the best case does not hold every placeholder of the file and another case holds one
   would close it; that is a ruling, not a fix for this round.
2. **The file name only helps when the AI tool keeps it.** When it renames the file and two cases fit alike
   the owner is asked, which is the intended outcome.
3. The garbage-collector exposure: section D.

## Commands I ran, and their last lines

All from `/home/user/the-mask-worktrees/task-22`, with `uv run --no-sync`, `-p no:cacheprovider` and
`PYTHONDONTWRITEBYTECODE=1`, so that the worktree stayed as it was (`git status --short` prints nothing).

| Command | Last line |
|---|---|
| `pytest tests/ui tests/keystore -q` | `462 passed in 61.63s (0:01:01)` |
| `pytest -q` (whole suite) | `3041 passed, 6 skipped in 224.06s (0:03:44)` |
| `pytest tests/ui -q` (three times) | `341 passed in 61.15s`, `341 passed in 62.87s`, `341 passed in 65.19s` |
| `PYTHONMALLOC=debug pytest tests/ui/test_home.py tests/ui/test_export_dialog.py -q` (five times) | `71 passed in 50.24s`, `50.15s`, `49.86s`, `47.05s`, `49.01s` |
| `ruff check --no-cache src tests tools` | `All checks passed!` |
| `ruff format --check --no-cache src tests tools` | `134 files already formatted` |
| `mypy --cache-dir=<scratch> src` | `Success: no issues found in 52 source files` |
| `pytest tests/test_netguard.py -q -rs` | `SKIPPED [6] tests/test_netguard.py:85: This computer has no sockets of that family.` / `21 passed, 6 skipped in 3.64s` |
| `git diff --check 0baa904..49d69ca` | (nothing: clean) |
| probes file: `pytest <probes file> -c pyproject.toml --rootdir=. -p tests.conftest -p tests.ui.conftest -s` | `5 passed in 4.11s` (probe A = M-1; B and C = I-1; D = the file-name rows of section A; E = empty log) |
| `PYTHONPATH=<plugin dir> PYTHONMALLOC=debug pytest tests/ui/test_home.py -q -p gc_back_on` (six times, collector on) | `43 passed in 37.75s` (x5: 37.75, 39.07, 37.51, 42.68, 37.85) and once `exit 139`: `Fatal Python error: Segmentation fault ... Garbage-collecting` |
| `STRESS_KIND=dialogs STRESS_SECONDS=12 PYTHONMALLOC=debug pytest <stress file 2> ...` (eight times) | all `exit 0`, e.g. `STRESS kind=dialogs rounds=321 gc-passes-in-worker=192` |
| the same with `STRESS_KIND=screens` (eight times with stress file 2, eight with stress file 1) | all `exit 0`, e.g. `STRESS kind=screens rounds=319 gc-passes-in-worker=169` |
| the same with `STRESS_KIND=windows` and the third stress file (six times) | `exit 139` five times (`Fatal Python error: Segmentation fault`, worker `Garbage-collecting`, GUI thread in `loop.exec()`), `exit 0` once (`rounds=23`) |

NEEDS FIXES: I-1 - a case the owner chose by hand (in the case box or with "Restore from this case") is replaced by another case that holds more of the placeholders, without a question (`restore_screen.py:509-516`, reached from `load_file` :422 and `_text_changed` :603); R103 (b) "a hand pick stays" and the accepted reading "a hand pick lasts until its restore or the next file" are only partly met. Fix: honour `chosen` always in `_order_cases`, update the two tests that assert the override (:405, :678), add the Cases-screen sequence as a test; or park it with a `Ruling:` line.
