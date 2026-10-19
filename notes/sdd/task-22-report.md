# Task 22 + 23 report — export dialog; restore, cases and settings screens

**Status: DONE_WITH_CONCERNS.** Everything the briefs, the controller's dispatch decisions and ruling
R103 require is in place and tested; the concerns (section 6) are decisions for the controller, not
missing work. One finding matters beyond these tasks: the test suite can end in a segmentation fault
(PySide6 / Shiboken race, section 4); I fixed it in the tests and left `src/` alone.

Worktree `/home/user/the-mask-worktrees/task-22`, branch `task-22`. Commits on top of the WIP checkpoint
`42c0b94` (nothing amended, squashed or rebased, nothing pushed), oldest first:

| Commit | What |
|---|---|
| `0140e4a` test: keep the garbage collector out of the worker threads of the UI tests | the segfault fix (section 4) |
| `56c6246` feat: suggest_cases puts the case whose code is in the file's name first (R103) | R103 (a), `restore/matcher.py` |
| `2df47eb` fix: finish the restore and cases screens the interrupted build left half done | the interrupted implementer's uncommitted edits, kept as they were (section 1) |
| `4bea355` fix: the Cases screen says it cannot read the cases instead of that there are none | found in my review |
| `49d69ca` feat: the restore screen refuses to guess between cases that fit alike (R103) | R103 (b), (c) and what goes with them |
| `0cc94ca` fix: a case the owner chose stays chosen; a better fit is pointed out, not forced (R103) | fix round 1, finding I-1 (see "Fix round 1" at the end) |

Gate, run on exactly the tree of `49d69ca`: `uv run pytest -q` 3041 passed, 6 skipped (the IPv6 variants of `tests/test_netguard.py`: no sockets of that family here) in 245 s;
`ruff check src tests tools`, `ruff format --check src tests tools` and `mypy src` clean. Task 22 (the
export dialog, `d06fb7f`) is unchanged by me; I re-read it against its brief and the dispatch decisions
and found nothing to change.

## 1. What I found when I took over

`git status` held uncommitted edits to six files (the interrupted implementer's, about 15 minutes of
work). I read the diff line by line. All of it was correct and finished, so I kept all of it and
committed it as it stood, separately from my own work (commit "fix: finish the restore and cases
screens…"):

| Inherited edit | Verdict |
|---|---|
| `keystore/cases.py`: `delete_all` no longer sets `self.unreadable = []`, and its test is gone from `tests/keystore/test_cases.py` | kept: nothing needs it (every screen lists the store again after a deletion), and it keeps the merged keystore module smaller |
| `restore_screen.py`: `NOT_READ` shared from `cases_screen`; `NOT_WRITTEN` -> `NOT_RESTORED` ("The file could not be restored:") with a test that a vanished AI file is not called unwritable | kept |
| `restore_screen.py`: a file whose plan could not be made (fingerprint `None`) is planned again before a restore, never restored without the fingerprint (R96), with a test | kept |
| `restore_screen.py`: `refresh_cases` keeps the owner's case ("Restore from this case") however it fits (`insist`), with a test | kept; R103 builds on it |
| `restore_screen.py`: `panel.addStretch(0)` so a Word result's lines stay together | kept (checked in an offscreen rendering) |
| `tests/ui/test_navigation.py`: export -> Cases -> Restore round trip through the windows | kept (real engine, ~10 s) |
| `tests/ui/test_cases_settings.py`: a case file copied in Finder is listed as damaged and can be deleted | kept |

I removed nothing of it and redid nothing of it. How far it had got with R103: only the "the owner's
choice stays" half (`insist`); nothing of (a), (b) or (c) existed, so I did them in full, building on
`insist` (and adding to `refresh_cases`: a visit returns early when the cases have not changed).

The checkpoint's own state, which the controller said was unknown: `uv run pytest tests/ui` 308
passed, whole suite 2984 passed, 6 skipped (the IPv6 variants of `tests/test_netguard.py`), before I changed anything.

## 2. What the briefs, the dispatch decisions and R103 require, where it is, and what proves it

All paths are under `/home/user/the-mask-worktrees/task-22`. Test names are in `tests/ui/` unless a path says otherwise.

### Task 22 — the export dialog (committed earlier as d06fb7f; not changed by me)

| Requirement | Where | Proven by |
|---|---|---|
| `ExportDialog(QDialog).run(sources, review, options, ctx)` runs `export_case` in a `QThread` with signals and a progress bar; `save_case = ctx.case_store.save` | `src/themask/ui/export_dialog.py` (`ExportWorker`, `ExportDialog.run`) | `test_export_dialog.py`: `test_the_files_are_made_in_a_thread_and_reported_in_the_window_s`, `test_while_the_files_are_made_the_dialog_shows_progress_and_cannot_be_closed`, `test_a_second_run_is_refused`, `test_the_export_is_given_what_the_context_holds`, the brief's `test_case_saved` |
| Success view: outputs, "Also found in the masked copy — not marked by you:", "Left visible on purpose:" (`allowed_hits`), "Not checkable (too short):", **Copy instruction** (`AI_INSTRUCTION` to the clipboard), **Show in Finder** through the module-level `reveal(path)` | same file, `_show_saved` / `_saved_text` | the brief's `test_success_shows_outputs_and_instruction`, `test_a_save_lists_the_files_the_case_and_offers_the_instruction`, `test_what_was_found_beyond_the_marks_is_listed`, `test_show_in_finder_opens_the_folder_of_the_files`, `test_reveal_asks_the_system_to_open_the_folder` |
| Blocked view "Saving blocked: a marked value is still present" with every `LeakHit.part` and context, `copy_button` off, only **Back to review**; `leak_hits` = blocking leftovers only, `allowed_hits` separate | `_show_blocked`, `BLOCKED` | the brief's `test_blocked_shows_hits`, `test_a_block_names_every_place_and_leaves_only_the_way_back`, `test_the_way_back_closes_the_dialog` |
| Errors in plain words, `finishedExport` still emitted, only the error TYPE logged | `ExportWorker.run`, `_show_failed` | `test_an_export_that_fails_says_why_and_still_finishes` (MaskError, Keychain, disk), `test_an_unexpected_error_is_a_plain_sentence_and_only_its_type_is_logged`, `test_a_context_without_an_engine_is_a_plain_message_too` |
| `summary_text()`, `result`, `finishedExport` | same | used by every test above |
| `tests/helpers.analysed(ctx, paths)` | `tests/helpers.py` | used by the brief's three tests |
| `MainWindow` wires `exportRequested` -> dialog with `ExportOptions(out_dir, redline_split, retention_days, existing_case, existing_codes = case ids + unreadable stems)` | `main_window.py` (`show_export`, `_case_codes`) | `test_continuing_from_the_review_opens_the_dialog_with_the_review_and_the_settings`, `test_a_redline_review_is_exported_as_one`, `test_a_file_added_to_a_case_is_exported_into_that_case`, `test_the_codes_in_use_include_the_case_files_that_cannot_be_read`, `test_a_second_request_while_the_dialog_is_open_is_ignored`, `test_a_store_that_cannot_be_read_is_said_in_words_and_no_dialog_opens`, `test_closing_the_window_waits_for_the_export_to_end` |

### Task 23 — restore, cases and settings screens, main-window polish

| Requirement | Where | Proven by |
|---|---|---|
| RestoreScreen: `plan_docx` / `restore_docx(confirm_altered = ticked ordinals, or True when all are ticked, expected_sha256 = plan.sha256)`, the fingerprint ALWAYS passed (R96); the MaskError text "The file changed since it was checked. Load it again." shown | `restore_screen.py` (`_replan_file`, `_restore_file_with`) | `test_a_file_is_restored_with_the_ordinals_of_the_ticked_lines_and_the_plan_s_fingerprint`, `test_a_file_is_restored_with_true_when_every_line_is_ticked`, `test_a_file_that_changed_under_the_list_is_not_restored_by_that_list`, `test_a_file_that_was_not_planned_is_never_restored_without_the_fingerprint` |
| A held tracked-change item says it stands for every placeholder in that change | `_row_text`, `_written`, `TRACKED_NOTE` | `test_a_place_where_several_placeholders_meet_in_a_change_is_held_and_says_so`, `test_a_placeholder_a_tracked_change_runs_through_says_so_and_waits_for_the_owner` |
| The paste box plans again on every text change (`restore_text` has no fingerprint) | `_text_changed`, `_replan_text` | `test_the_plan_of_the_text_is_made_again_whenever_the_text_changes`, `test_text_is_restored_with_the_ordinals_of_the_ticked_lines_or_true_for_all` |
| Case combo in `suggest_cases` order, most recent preselected when nothing fits | `_order_cases` | `test_the_most_recent_case_comes_first_while_there_is_nothing_to_fit`, `test_the_case_that_holds_most_of_the_placeholders_comes_first_and_is_preselected`, `test_a_file_puts_the_cases_in_order_too` |
| Result panel: `RestoreReport.summary()`, unknown list, **Show in Finder** (monkeypatchable `reveal`), restored text read-only with **Copy** | `_show_result`, `_show_in_finder`, `_copy` | the brief's `test_restore_docx_flow` and `test_restore_text_flow`, `test_the_restored_file_is_a_new_one_beside_the_ai_s`, `test_pasted_text_is_restored_and_can_be_copied` |
| A store that raises MaskError / KeyStoreError / OSError: plain message, never a crash | `refresh_cases`, `_guarded`; `cases_screen.refresh`; `main_window._purge_expired_cases`, `show_export`, `_start` | `test_a_store_that_cannot_be_read_is_said_in_the_screen` (restore and cases), `test_a_folder_that_cannot_be_read_is_said_in_words`, `test_a_failed_clean_up_does_not_stop_the_window` (`test_home.py`), `test_a_case_that_cannot_be_opened_is_reported` (`test_home.py`) |
| CasesScreen: `CaseSummary` table, module-level `confirm(parent, message)`, **Delete** / **Delete all** (both confirm; Delete all also removes unreadable files and crash leftovers), **Restore from this case**, **Add file to this case** -> `MainWindow.open_files(paths, None, case_id)`, unreadable files listed with Delete (Task 17 -> 23 note) | `cases_screen.py`, `main_window.py` (`_add_files_to_case`, `show_restore`), keystore `delete_unreadable` | the brief's `test_cases_screen_delete`, `test_deleting_a_case_asks_first_and_names_it`, `test_delete_all_asks_first_and_takes_every_file_of_the_folder`, `test_a_case_file_that_cannot_be_opened_is_listed_and_can_be_deleted`, `test_a_copy_of_a_case_file_under_another_name_is_listed_and_can_be_deleted`, `test_add_file_to_this_case_asks_for_files_and_hands_them_over_with_the_case`, `test_restore_from_this_case_names_the_case`, `test_a_file_added_to_a_case_from_the_cases_screen_is_analysed_with_that_case` (`test_navigation.py`) |
| SettingsScreen: always / never lists one per line -> `UserLists` at `lists_path()`, updating `ctx.user_lists` in place; retention 1-365; folder picker (monkeypatchable); Save; About with `APP_NAME`, `VERSION`, `OWNER_NAME` and "Runs fully offline. Restored text you copy is on the clipboard in clear." | `settings_screen.py` | the brief's `test_settings_lists_and_retention`, `test_about_shows_owner`, `test_saving_updates_the_lists_the_app_is_using_in_place`, `test_the_retention_runs_from_a_day_to_a_year_and_starts_where_it_is_kept`, `test_the_folder_is_chosen_with_the_system_dialog_and_kept_on_save`, `test_the_about_box_says_what_the_app_is_and_how_it_works` |
| MainWindow polish: a second `open_files` while one is queued is refused (`BUSY_MESSAGE`) | `main_window.open_files` | `test_a_second_request_while_one_runs_is_refused`, `test_a_second_request_while_the_engine_loads_is_refused` (`test_home.py`) |
| ... try/except around the review-building step, only the exception TYPE logged | `_analysis_finished`, `REVIEW_FAILED` | `test_an_error_while_the_review_is_built_is_told_and_only_its_type_is_logged` |
| ... tool-bar navigation off while `is_analysing()` | `_set_navigation` | `test_the_tool_bar_is_off_while_a_file_is_analysed_and_on_again_after`, `test_the_tool_bar_comes_back_when_the_analysis_fails` |
| ... refused `.doc` names shown on screen, never logged | `HomeScreen.show_refused`, `_refused_notice`, `DropZone.filesRefused` | `test_files_that_were_not_opened_are_named_on_the_home_screen` (asserts the names are not in the log), `test_the_advice_about_an_old_doc_is_only_given_for_one`, `test_a_mixed_drop_opens_the_contracts_and_names_the_rest` |
| `exported` fixture | `tests/fixtures/ui.py` | used by the brief's restore and cases tests |
| Only QtCore / QtGui / QtWidgets | all of `src/themask/ui/` | `tests/ui/test_qt_modules.py` (AST guard) |

### R103 — the restore screen no longer guesses which contract a file belongs to

| Item | Where | Proven by |
|---|---|---|
| (a) `suggest_cases(text, cases, file_name=None)`: when exactly one case's code stands in the name as a whole word it ranks first, whatever the overlap; otherwise the ranking is unchanged. New helper `case_in_file_name(file_name, cases)`. The screen passes the dropped file's name, the paste box passes None | `src/themask/restore/matcher.py`; `restore_screen.py` (`load_file`, `_text_changed`, `_ranked_name`) | `tests/restore/test_matcher.py`: `test_the_case_whose_code_is_in_the_file_name_comes_first_whatever_the_overlap`, `test_the_code_counts_as_a_whole_word_in_any_case` (9 names), `test_a_code_inside_a_longer_word_is_not_the_code` (8 names), `test_two_codes_in_one_file_name_tell_nothing`, `test_without_a_file_name_the_ranking_is_the_same_as_before`, `test_the_named_case_comes_first_even_if_it_holds_none_of_the_placeholders`, `test_the_cases_behind_the_named_one_keep_their_order`, `test_case_in_file_name_gives_the_one_case_the_name_holds`; the old `test_suggest_cases` and the ranking tests still pass; screen side: `test_the_ranking_is_given_the_name_of_the_file_and_none_for_pasted_text` |
| (b) Ambiguity: another case holds as many of the file's placeholders as the best one and no file-name match decides -> nothing preselected (index -1), the plain text "Several cases fit this file — choose one.", Restore and Restore text stay off until the owner picks; a case the owner chose by hand stays chosen; exactly one best fit is preselected as before | `restore_screen.py`: `_is_a_guess`, `_order_cases`, `_show_choice_notice`, `choose_label`, `CHOOSE_CASE` | `test_two_cases_that_fit_a_file_alike_are_not_guessed_between` (the newer case is NOT preselected), `test_the_owner_s_choice_is_the_case_the_file_is_restored_with` (Alice Smith written, not Bob Jones), `test_the_code_in_the_name_of_the_file_picks_the_case_without_asking` (MASKED-K4F7 picks the older case; lower case and -1/-2 suffix too), `test_a_name_that_does_not_point_to_one_case_leaves_the_choice_to_the_owner`, `test_pasted_text_is_not_guessed_either`, `test_a_case_the_owner_chose_stays_chosen_while_the_text_changes_and_on_a_visit`, `test_the_one_case_that_fits_best_is_selected_without_a_question` |
| (c) Combo lines carry the code, the original file names and the date (code, date and number of entries when a case stores no file names); under the combo a read-only label previews up to five "[PLACEHOLDER] → value" pairs of the selected case for the placeholders of the file and the pasted text, updated with the selection and the text, never logged | `restore_screen.py`: `_case_title`, `_preview`, `_short`, `preview_label`, `_update_state` | `test_a_case_line_carries_the_code_the_date_and_the_original_files`, `test_a_case_that_stores_no_file_names_is_told_by_its_code_date_and_entries`, `test_the_preview_shows_the_values_the_selected_case_would_put_back` (Alice for K4F7, Bob for M5N6), `test_the_preview_follows_the_text_and_hides_when_there_is_nothing_to_show`, `test_the_preview_names_at_most_five_placeholders_in_the_order_they_stand`, `test_the_preview_shows_a_placeholder_the_ai_changed_too`, `test_the_preview_is_plain_text_and_keeps_a_long_value_short`, `test_the_values_of_the_preview_are_never_logged` |

Readings of R103 I had to choose (conservative; the controller can overrule any of them):

1. **No case fits at all** (every case holds none of the placeholders, or nothing is loaded yet): the
   newest case is still preselected, no question. The brief says so ("most recent preselected when no
   placeholders match"), a question there would show "Several cases fit" on an empty screen, and
   nothing could be written anyway. Test: `test_when_no_case_fits_the_newest_is_selected_and_nothing_is_asked`,
   and the old `test_the_most_recent_case_comes_first_while_there_is_nothing_to_fit`.
2. **How long a hand-chosen case stands.** "A case the owner chose by hand stays chosen" is kept
   while the text is edited and the screen is visited, whatever fits better (as first built, a case that
   fitted better replaced it: finding I-1, Fix round 1 at the end) (`test_a_case_the_owner_chose_stays_chosen...`,
   `test_a_visit_changes_nothing_while_the_cases_are_the_same`). But a choice that outlived its file
   would be the same bug by another road: restore contract 1 with a hand-picked case, drop contract 2,
   and on a tie the old pick would silently apply. So a pick ends with the restore it was made for, and
   when another file is dropped (`test_a_choice_made_for_one_file_is_not_carried_to_the_next`,
   `test_a_choice_ends_with_the_restore_it_was_made_for`); the case asked for with "Restore from this
   case" counts for the next file (`test_the_case_asked_for_in_the_cases_screen_is_for_the_next_file_even_when_one_is_loaded`).
   Cost if the controller wants the literal reading instead: delete `_spend_choice`, the `_for_next_file`
   flag and the `_manual = False` line in `load_file`; one extra click per restore becomes none, and so
   does the protection.
3. **The message says "file" for pasted text too.** One exact sentence, as ruled.
4. **Case-insensitive code match** ("masked-k4f7.docx"): `new_case_code` already compares codes
   case-folded, and some tools lower-case names. A false match needs a 4-character code that is also a
   word in the name.
5. **Pasting text after a file** ranks for the text (it has no name), so a file that was picked by its
   name can fall back to "choose one" when text is pasted that fits two cases alike; clearing the box
   goes back to the file (`test_clearing_the_paste_box_goes_back_to_the_file`).

## 3. TDD evidence

Run from the worktree root. The inherited tests were already green (they are the interrupted
implementer's); the RED outputs below are for what I wrote.

**R103 (a), the matcher** — tests first:

```
$ uv run pytest tests/restore/test_matcher.py -q -x
E   ImportError: cannot import name 'case_in_file_name' from 'themask.restore.matcher'
1 error in 0.24s                                   # RED: the argument and the helper do not exist
$ uv run pytest tests/restore/test_matcher.py -q   # after the change
43 passed in 0.27s                                 # GREEN (19 before, 24 new; the old ranking tests untouched)
```

**R103 (b), (c), the screen** — tests first, against the screen as the interrupted build left it:

```
$ uv run pytest tests/ui/test_restore_screen.py -q
26 failed, 57 passed in 17.68s
  first failure: assert s.case_combo.currentIndex() == -1   ->   0 == -1   (the newer case was preselected)
  the rest: no file-name pick, no choose_label / preview_label, no code+date+entries line, a pick that outlives its file
$ uv run pytest tests/ui/test_restore_screen.py tests/restore -q     # after the change
219 passed in 20.43s   (one old test updated: its premise "a tie goes to the newer case" is what R103 removes)
```

**Three more defects my own review found after the first green**, each RED then GREEN (the fourth, a pick
that outlives its file, is in the R103 list above):

```
paste box cleared          2 failed ("Several cases fit" still shown; the file's case not back)  ->  2 passed
store cannot be read       3 failed (Cases and Restore say "no cases" beside the Keychain message) ->  122 passed
visit after a restore      1 failed (assert None == 'K4F7': the case went away)                    ->  87 passed
```

**Planted bugs** (a copy of the final tree, one bug at a time, the matching test file run): 13 of 13
caught — an underscore joining words of a name, a case-sensitive code, two codes picking the first, the
name ignored in the ranking, the screen not passing the name, the paste box given the file's name, a
tie not asked about, "no fit" asked about, a name that decides still asking, six preview lines instead
of five, the preview read as rich text, a pick that outlives its file, a pick that outlives its restore.

**The gate**, on the tree of `49d69ca` (run before the commits were made; the files were compared afterwards):

```
$ uv run pytest -q
3041 passed, 6 skipped in 244.90s (0:04:04)          # the 6 skips: the IPv6 variants in tests/test_netguard.py
$ uv run ruff check src tests tools          All checks passed!
$ uv run ruff format --check src tests tools 134 files already formatted
$ uv run mypy src                            Success: no issues found in 52 source files
```

Before I changed anything the checkpoint gave 2984 passed, 6 skipped. The difference, 57, is all new
tests: 24 in `tests/restore/test_matcher.py`, 32 in `tests/ui/test_restore_screen.py`, 1 in `tests/ui/test_workers.py`.
No wall-clock test failed in any of my runs (the 500-highlight test passed every time), so nothing was re-run alone.
Each intermediate commit was also checked in its own copy of the tree (`git archive`): `0140e4a` 60 passed
(workers, home), `56c6246` 136 passed (restore), `2df47eb` 359 passed (restore screen, cases/settings, navigation,
keystore, restore), `4bea355` 91 passed (cases/settings, restore screen).

## 4. A segmentation fault in the suite (found while gating; fixed in the tests only)

**What happened.** My first full run died with `Fatal Python error: Segmentation fault` at 92 %, in
`tests/ui/test_home.py` (Task 20's file, which runs before my UI tests), in a worker thread,
and the faulthandler said `Garbage-collecting`. **It predates my changes**: the unchanged checkpoint
`42c0b94` (extracted with `git archive` into a scratch folder) crashes the same way, third run of a loop
of `PYTHONMALLOC=debug pytest tests/ui/test_home.py` (`exit 139`, the same `Garbage-collecting` in
`AnalysisWorker.run`); a UI-only run with a GC probe died at `test_home.py:73`; in my worktree the same
file under `PYTHONMALLOC=debug` died in about 2 runs of 5. The crash depends on timing, so the
checkpoint's own full run passed, and 8 runs under gdb were clean (slower, different timing).

**Cause** (a core file, `gdb thread apply all bt`):

- main thread: `QEventLoop::exec` (pytest-qt's `waitSignal`) -> `QCoreApplicationPrivate::sendPostedEvents`
  -> `QObject::event` (a `DeferredDelete` of an EARLIER test's window) -> `QWidget::~QWidget` ->
  `QObjectPrivate::deleteChildren` -> ... -> `Shiboken::Object::destroy` -> `Shiboken::GilState` ->
  `PyGILState_Ensure`, waiting for the interpreter lock;
- crashing worker thread (the test's `AnalysisWorker`): inside CPython's cyclic garbage collector, in
  libshiboken's traverse function for a wrapper object, SIGSEGV.

So PySide6 6.12.0 takes the C++ side of a widget apart without holding the lock while another thread's
garbage collection walks the same wrapper. pytest-qt only `deleteLater()`s the widgets of a test, so the
deletion lands in the next test that runs an event loop, which is the test with a worker thread.

**Fix** (`0140e4a`, tests only): an autouse fixture in `tests/ui/conftest.py` switches automatic garbage
collection off while a UI test runs and on again after it; the first allocation after the test collects
what it left, in the main thread. Evidence: `test_home.py` under `PYTHONMALLOC=debug`, 10 runs, 10 clean (it
crashed in 2 of 5 comparable runs before); two full runs (3040 and 3041 passed), no crash; the UI suite
got faster (57 s against 70 s). `test_the_garbage_collector_is_off_while_a_test_runs` pins it.

**The app.** Nothing is changed in `src/`. The same overlap is possible in the app, in a narrow window:
a worker thread that starts a collection at the moment the main thread takes widgets apart (a table or
tree being cleared, a dialog or a finished `QThread` being deleted). The engine load at start (about 2 s,
allocation heavy) is the likeliest: the owner can click to the Cases screen meanwhile and that clears a
table. The analysis and the export run while a progress screen or a modal dialog stands, where nothing is
taken apart. Choices for the final fix wave, the controller's call: (a) switch automatic collection off
at start and collect from a main-thread timer (every few seconds and after each worker ends); (b) keep the
tool bar off while the engine loads too (it is already off during an analysis); (c) pin or wait for a
PySide6 that does not do this (the lock holds 6.12.0).

## 5. Self-review (I read my own diff and the inherited code once more)

Found and fixed while doing it (each with a failing test first):

- **A stale notice**: clearing the paste box left "Several cases fit this file — choose one." on screen
  with nothing to fit. The cases are now ranked again for what is left (the file, or nothing).
  `test_clearing_the_paste_box_takes_back_the_question_its_text_raised`, `..._goes_back_to_the_file`.
- **A hand-picked case outliving its file** (see reading 2 above), which would have reopened the very
  hole R103 closes. `test_a_choice_made_for_one_file_is_not_carried_to_the_next` and three more.
- **A visit after a restore took the case away** (the pick was used up, the screen was ranked again on
  every visit). A visit now changes nothing while the cases are the same.
  `test_a_visit_changes_nothing_while_the_cases_are_the_same` (RED first: the case went to None).
- **"No cases yet" / "There is no saved case" shown next to "could not reach the Keychain"**: both
  screens now say only that the cases cannot be read (RED: three failing assertions, then green).
- **The one pre-R103 test whose premise R103 removes**: `test_the_owner_s_case_is_kept_while_it_fits_as_well_as_the_best`
  asserted that on a tie the NEWER case is preselected. It now asserts that nothing is selected and the
  owner is asked; the rest of that test was unchanged in the first round (Fix round 1 below changes its
  tail: a clearly better fit is now pointed out, no longer offered in place of the owner's case). It was the
  only existing test I changed in the first round.
- A segmentation fault in the suite (section 4).

Checked and fine: no `TODO`, no `print`, every `noqa` / `type: ignore` in `src/themask/ui` is explained
(five broad `except Exception` that must not end a thread or the app, one `QDialog.result` override
the brief demands); the log calls in `src/themask/ui` write the exception type and counts only (grep:
six `_LOG` calls: five write `error=<type name>`, one the engine's load time); the restore preview and
the combo lines are on screen only; nothing in the screens touches the Keychain (the autouse
`no_real_keychain` fixture stays); the keystore stays at two small additions, both with tests.

Rendered the screens offscreen to PNG to look at the layout (empty, ambiguous, chosen with preview,
Word result, text result, Cases, Settings): nothing overlaps or is cut at 1180 x 700.

## 6. Concerns

1. **A PySide6 / Shiboken race that crashes the test run, and could in theory crash the app (section 4).**
   I fixed the tests; I did not touch production code. The controller should decide on the app side.
   Until `0140e4a` is merged, any other full run in the cloud can die the same way (`Fatal Python error:
   Segmentation fault`, `Garbage-collecting`, exit 139); that is this flake, not a failing test: run again.
2. `OWNER_NAME` in `src/themask/about.py` is still the placeholder `<owner name — set in about.py>`; the
   About box shows it. The owner fills it in before the app is shared (the plan says so).
3. Size: `src/themask/ui/main_window.py` is 617 lines (HomeScreen, MainWindow, helpers; the final review
   already has it on its list for a split) and `restore_screen.py` is now 732 lines (file and text
   sources, the case choice, the result panel). I did not split either, as the instructions say.
4. R103 readings 1-5 above (no fit, how long a pick stands, one sentence for file and text,
   case-insensitive code, pasting after a file).
5. The restore screen can only use the file's name if the AI tool keeps it; when it renames the file
   and two cases fit alike, the owner is asked (one more click, as R103 states). The export dialog does
   not tell the owner to keep the name; that would be a small addition to its success text if wanted.
6. If the Keychain refuses, the Cases screen shows the message and an empty table; "Delete all" is off
   because it has no rows to count, so the owner cannot clear cases from the app until the Keychain
   answers. `CaseStore.delete_all` itself needs no key.
7. `tests/ui/test_navigation.py::test_a_masked_file_goes_from_the_export_through_the_cases_to_the_restored_file`
   runs the real engine and an export (about 10 s); it is the one test that goes through every screen.

## 7. Files changed since the checkpoint (`git diff 42c0b94 HEAD --stat`)

```
 README.md                        |   4 +-   (one sentence: the restore screen never guesses the case)
 src/themask/keystore/cases.py    |   1 -    (inherited: delete_all no longer resets `unreadable`)
 src/themask/restore/__init__.py  |   3 +-   (docstring)
 src/themask/restore/matcher.py   |  34 ++-  (R103 a: file_name argument, case_in_file_name)
 src/themask/ui/cases_screen.py   |  14 +-   (unreadable store: message only)
 src/themask/ui/restore_screen.py | 217 +++  (R103 b, c; inherited fingerprint/choice fixes)
 src/themask/ui/theme.py          |   1 +    (QLabel#preview)
 tests/keystore/test_cases.py     |  10 -    (inherited: the test of the removed reset)
 tests/restore/test_matcher.py    | 102 +++  (24 new tests)
 tests/ui/conftest.py             |  21 +-   (GC fixture)
 tests/ui/test_cases_settings.py  |  20 ++   (inherited copy test; unreadable-store assertions)
 tests/ui/test_navigation.py      |  41 ++   (inherited round trip through the windows)
 tests/ui/test_restore_screen.py  | 495 +++  (R103 and the rest; one old test updated)
 tests/ui/test_workers.py         |   8 +    (GC guard test)
 14 files changed, 909 insertions(+), 62 deletions(-)
```

The keystore, which the controller wanted kept to the minimum: the net change against the merged
module is two methods, both tested in `tests/keystore/test_cases.py` — `delete_unreadable(name)`
(the Cases screen deletes one damaged file or a copy made in Finder; only a name the last listing reported
can be deleted, nothing outside the folder) and `load_all()` (every case with its key, one key fetch, which
the Restore screen needs to rank the cases by their placeholders; `list()` is now built on it and behaves as
before). Both could be done with the old API (`delete(stem)`, `list()` + `load(id)` for each case) at the cost
of a loose guard and one key fetch per case; I kept them because the first is safer and the second avoids a
partial failure half way through the cases. Say the word and they go.

## Fix round 1 (review finding I-1)

**The finding.** A case the owner chose by hand, or came with from the Cases screen ("Restore from this
case"), was replaced by another case that holds more of the placeholders, without a question
(`_order_cases`, the `keep = None` branch). Probe B: `refresh_cases("B2B2")`, then `load_file` of a file
where A1A1 fits better -> A1A1 selected; with the file loaded first and the request second B2B2 stayed, so
the same request gave different results by order. Probe C: pick B2B2 by hand, edit the paste box -> A1A1.
I reproduced both on `49d69ca` first (probe C printed `A1A1 / B2B2 / A1A1` for before the pick, picked,
after an edit; the restore the screen then offered wrote Alice Smith's values although the owner had
asked for Bob Jones's case).

**What changed** (commit `0cc94ca`, `src/themask/ui/restore_screen.py` plus one README clause):

- `_order_cases(chosen)` honours `chosen` ALWAYS: the branch that dropped a chosen case which holds fewer
  placeholders than the best fit is gone, and with it the `insist` parameter (`refresh_cases` no longer
  needs it). The only things that end a pick are the ones already ruled: its restore, and the next file
  (the case asked for in the Cases screen counts for the next file).
- New plain notice under the case box, `better_fit_label`: "Another case fits this file better — check the
  case." (exact words from the controller). It shows while another case holds MORE of the placeholders of the
  text the cases were last ranked on (the file, or the pasted text) than the selected case, and goes when
  the selected case is the best fit or the owner picks the better one. It never changes the selection and
  never switches Restore / Restore text off (the owner chose). It follows the combo however the selection
  changed (a click, `setCurrentIndex`, the Cases screen, a store that changed) because it is worked out
  in `_update_state`, which every re-plan ends with.
- `_is_a_guess` became a method and, with the new notice, shares a small memo (`_fit_of`: how many
  placeholders each case holds of the ranked text, looked up once per ranking), so a paste-box keystroke does
  not parse the text once per case.
- Docstrings (module, class, `refresh_cases`, `_order_cases`) say what is now true; the README says a
  chosen case is never replaced.

**Tests** (`tests/ui/test_restore_screen.py`, 99 now, was 87):

- The two that asserted the old override are changed to assert the new behaviour:
  `test_a_text_that_another_case_fits_better_does_not_take_the_owner_s_case_away` (was `..._makes_another_case_the_best_fit_reads_the_file_again_for_it`:
  B2B2 stays after the paste, the file's ticks stay, the notice shows, Restore stays enabled, picking
  A1A1 re-reads the file and hides the notice) and `test_the_owner_s_case_is_kept_whatever_the_text_says`
  (was `..._kept_while_it_fits_as_well_as_the_best`: its last three lines asserted the override; the notice
  now comes and goes with the text and the pick never moves).
- `test_the_case_asked_for_in_the_cases_screen_wins_over_a_better_fit` gains the notice and the preview
  (`[PERSON_1] → John Smith`, B2B2's pair only).
- The controller's Cases-screen sequence, as `test_the_case_asked_for_in_the_cases_screen_stays_though_the_file_fits_another_better`
  (K4F7 holds person + company, M5N6 the person only): "Restore from this case" M5N6, load a file that fits K4F7
  better -> M5N6 stays, the notice shows with the exact words, Restore is enabled, the preview is `[PERSON_1] → Bob Jones`,
  the fit line says 1 of 2.
- Order independence (probe B): `test_the_case_asked_for_stays_whichever_comes_first` (2 cases: asked first,
  file first).
- Probe C: `test_a_case_picked_by_hand_stays_when_the_text_is_edited_and_another_fits_better`, ending with a
  restore that writes "Bob Jones and [COMPANY_1]" (the chosen case, not the better one).
- `test_a_chosen_case_is_used_for_the_restore_whatever_fits_better` (Word file: Bob Jones written, company left,
  reported as not in the case).
- The notice itself: `test_the_hint_goes_when_the_owner_picks_the_better_case`,
  `test_the_hint_follows_the_selection_however_it_changed` (no click, and -1),
  `test_the_hint_follows_the_cases_the_store_holds` (a better case appears, then is deleted),
  `test_a_case_named_by_the_file_stays_and_a_better_fit_is_pointed_out`,
  `test_there_is_no_hint_when_no_case_fits_better_than_the_one_selected` (fit alike, nothing fits, no placeholder).

TDD: the new and changed tests were written first against `49d69ca`: `14 failed, 84 passed` (the probe-B
tests failed on `assert 'K4F7' == 'M5N6'`, the restore test on "Alice Smith signs for Northwind Trading B.V."
where "Bob Jones signs for [COMPANY_1]." was owed, the rest on the missing `better_fit_label`); after the
change all pass. Eight planted bugs, one at a time in a copy of the tree, all caught: the screen replacing
a chosen case again, the notice never shown, shown for every selected case, shown on a tie, a fit
remembered across rankings, Restore switched off while it shows, Restore text switched off while it shows,
other words. I also looked at the screen offscreen (yellow notice under the case box, preview of M5N6's
pair, Restore enabled).

**Readings I chose** (the controller can overrule):

1. The notice is about the SELECTED case, however it was selected: a case picked by the owner, asked for in
   the Cases screen, picked by a file name (`MASKED-<code>`), or the best fit (then nothing fits better, so no
   notice). A file name that points to a case with fewer of the file's placeholders therefore selects it (the
   name still decides) and shows the notice.
2. "More" counts placeholders only. A hand pick that differs from the case a file name points to is not
   flagged unless another case also holds more placeholders.
3. With a file and pasted text both on the screen the notice speaks about whichever the cases were last
   ranked on, as the ranking itself does; the sentence says "file" for both, as the other sentence does.

**Still as it was (not part of this round):** a pick made for pasted text that was never restored stays for the
next pasted text, and on a tie nothing says so (the reviewer's note under I-1); the minors M-1 to M-10 and the
residual risks of the review are parked, not touched.

**Wording note from the reviewer, applied above:** the 6 skipped tests are the IPv6 variants at
`tests/test_netguard.py:85` ("This computer has no sockets of that family."), not macOS-only tests; the
three places in this report that said macOS-only are corrected.

**Commands and their last lines** (worktree root, tree = the fix-round commit):

```
$ uv run pytest tests/ui/test_restore_screen.py -q      # the screen's own file, after the change
99 passed in 17.61s                                      # 98 + the store test; was 87 before the round
$ uv run pytest tests/ui -q
353 passed in 66.27s (0:01:06)
$ uv run pytest -q
3053 passed, 6 skipped in 232.96s (0:03:52)             # 3041 + 12 new; the 6 skips: IPv6 variants, tests/test_netguard.py
$ uv run ruff check src tests tools
All checks passed!
$ uv run ruff format --check src tests tools
134 files already formatted
$ uv run mypy src
Success: no issues found in 52 source files
```

`git status` is clean at `0cc94ca`; the gate ran on exactly that tree before the commit.
