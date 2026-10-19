# D2 report: the review screen (design pass "design-v1")

Worktree `/home/user/the-mask-worktrees/design-d2`, branch `design-d2`, from `4146e37` (D1's theme, art and icons).
Status: **DONE_WITH_CONCERNS** (concerns in section 8; none blocks the merge).

Commits (Conventional Commits, trailer `Co-Authored-By: Claude Sonnet 5.5`):

| SHA | Subject |
|---|---|
| `6ec9a3e` | feat(ui): the review as a document with an inspector |
| `0f67066` | test(ui): the review in both appearances, and the pictures for the owner |

Nothing is pushed. Only the files R123 allows were touched (`git diff --stat 4146e37..HEAD` lists exactly these):
`src/themask/ui/review_screen.py` (rewritten around the old logic), `src/themask/ui/review_inspector.py` (new),
`tests/ui/test_review_screen.py` (adapted and extended), `tests/ui/test_review_inspector.py`, `tests/ui/test_review_look.py`,
`tests/ui/review_samples.py` (all new). No change to `review.py`, detection, export, leak check, restore, keystore or the network guard; no new Qt
module (QtCore, QtGui, QtWidgets only in `src`); nothing is logged.

## 1. What was built, item by item

**(a) Two panes** (`ReviewScreen._arrange`, `_page_margins`, `_show_text` in `review_screen.py`)
- Left: the document on a page: panel background (palette role Base), `serif_font()` at 14.5 px, a fixed line height of 24.65 px (= 1.7 x 14.5,
  as CSS means it), 14 px between paragraphs, 44 px left and right and 36 px above and below (the document's root frame margins, so the scroll bar
  stays at the edge and the text map is untouched). The name of each file sits on a band in the `table_head` token. The mockup's closing line
  ("Headers and footers follow the body. Hidden text and pictures were taken out before this view.") is a quiet label under the page, outside the
  document (so `toPlainText()` and the UTF-16 map are unchanged).
- Today's highlight behaviour is untouched: type tints with black ink, darker tint for the selected group, dotted underline and the tooltip "check" for
  a group to check, a click on a find selects its group (and does not scroll away), selecting a group scrolls to its first place.
- Right: `Inspector` (`review_inspector.py`), minimum 300 and maximum 360 px (the layout gives it 1/4 of the width, so it is 300 up to about
  1200 px and 360 from 1440 px), a 1 px border on its left in the `border` token, ground background.

**(b) Inspector top**
- `find_field` (`QLineEdit`, `ClearButtonEnabled`, magnifier from `icons.icon("search")`, placeholder exactly "Find in document  ⌘F" with two spaces,
  accessible name "Find in document"). No search existed in the old screen, so it is the simple one: typing selects the first hit from the cursor on
  (a longer text keeps the hit it started on), Return goes to the next, it wraps at the end, and a text that is nowhere turns the field red (stylesheet
  from `danger`), sets the accessible description "No match" and leaves the cursor and selection where they were. ⌘F is a `QShortcut(QKeySequence.Find)`
  in the window of the screen (`find_shortcut`, `focus_find()`), active only while the screen is visible. A hit is a text selection, so "Hide selection"
  works on it.
- `hide_button` "Hide selection" (today's type menu and `hide_text`), `never_button` "Show always": the text selected in the page if there is one, else the
  selected group (today's never-hide). Both are plain bordered buttons, half width each.

**(c) Inspector middle** (`GroupTree`, `GroupRow`, `ToggleSwitch`, `sections()` in `review_inspector.py`; `_rebuild`, `_make_group` in `review_screen.py`)
- Sections in this order, empty ones left out: "NOT SURE — HIDE? · n", "COMPANIES · n" (COMPANY), "PEOPLE · n" (PERSON), "AMOUNTS, PERCENTAGES · n"
  (AMOUNT, PERCENT, QUANTITY), "ADDRESSES, E-MAIL, BANK · n" (ADDRESS, EMAIL, PHONE, IBAN, ID, URL), "OTHER · n" (CUSTOM). Within a section, the order of
  the document.
- Row: 10 px chip in the type tint; the canonical form (13 px, 600); the caption (11 px, secondary) `[COMPANY_1] · 6 places · also “Northwind”, “the Buyer’s
  group”`: placeholder, places, up to two other spellings the document really shows (not the sweep's variants) and then "…", and for a group to check
  why when the group says ("found by the model only" when every find is the model's, "too short for the leak check" by `leakcheck.unverifiable`); a "CHECK"
  pill (10 px, 700, `notice_bg` / `notice_text`); the switch, a real `QCheckBox` (`ToggleSwitch`, 32 x 18, accent track when on, accessible name "Hide <value>").
  Captions wrap (up to three lines) as the mockup's do; rows are as tall as they need.
- The selected row is on `accent_soft`; a click selects the group and scrolls the page to its first place (the old logic); Space switches the current line; the
  arrow keys move (headings are not lines, so they are passed over); Right/Left open and close the places of a group; double click does too.
- The places of a group (the old per-occurrence lines with their own check box) are the lines under its row, closed until opened. Merge by selecting two groups,
  split by selecting places: both still work with a multi-selection.
- Context menu of a row (right click and the menu key): "Hide always", "Show always", "Split", "Merge with…" (a submenu of the other groups of the same type; with
  two or more groups selected, a plain "Merge selected groups"), and "Show places" / "Hide places". The actions that cannot be done are greyed out.
- "Not sure — hide?" (`asks_about`): the groups with `needs_check` that are switched off and that the owner has not answered. Same row shape, a "Hide" and a "Show"
  button instead of the switch (accessible names "Hide <value>" / "Show <value>"); hidden when empty. Hide switches the group on (and it goes back to its family);
  Show keeps it visible and it is not asked about again until the next `load`; "Show always" (button or menu) on such a group is an answer too; Space on the row is Hide.
  See concern 1 for what this means for a group the owner switches off by hand.

**(d) Footer**: `counts_label` "12 hidden · 2 to check · 0 shown on purpose" and `hint_label` "Space toggles · ↑↓ moves", live. The three numbers share the groups
(hidden = on and sure, to check = on and marked, shown on purpose = off): the mockup's 12 + 2 + 0 = its "14 values found".

**(e) Title and window wiring**: `ReviewScreen.title() -> ("supply-01.docx", "Review · 14 values found · 2 to check")` and `titleChanged(str, str)` (sent when either line
changes: on `load` and after each change of the counts). Several files read "a.docx and b.pdf" / "a.docx and 2 more"; a before/after pair is one file. The old
`summary_label` is gone. Nothing about the redline check box is on the screen (it stays the window's `redline_split`). `exportRequested` is unchanged; the screen's own
"Continue to export" button is no longer shown (`export_button` stays as a hidden button that emits the same signal, see concern 2).

**Theme (R124)**: every colour comes from `theme.tokens_of(widget)` at paint time, so the screen follows light and dark with no wiring and holds no colour of its own
(a test reads both source files and fails on a `#RRGGBB`, on `.tertiary` or on "white"). Text on the accent (the knob, the tick of a place) is `on_accent`;
captions, headings, hints and the magnifier are `secondary` (never `tertiary`); on a selected row the caption is `accent_text_on_soft`. The literals the old file had
(`#8A4B00` underline, `#E4E4E4` header band, the black outline of the menu swatches) are gone: the underline is a dark shade of the find's own tint, the band the
`table_head` token, the swatch outline a shade of the tint. Black ink on the tints stays, as the brief says.

## 2. Existing tests that changed, and why (none deleted, none renamed: all 51 test functions are still there)

Adapted in `tests/ui/test_review_screen.py`, each with a comment saying so:
- `test_tree_matches_state`, `test_each_group_is_a_line_with_its_count_and_a_line_for_each_occurrence`, `test_a_selection_in_the_second_file_hides_the_right_text`:
  the line of a group shows its value; the count and the placeholder moved into the caption of its row (`row_for(id).data.caption`).
- `test_needs_check_marked`: "check" was the second column of the line, it is the pill of the row (`row_for(id).pill_box()`).
- `test_the_summary_follows_the_review`: the summary line is `title()[1]`; what is hidden is the footer (`counts_label`). The "N places" count is no longer in the summary.
- `test_merge_*`, `test_groups_of_different_types_are_not_merged`, `test_split_*`, `test_always_hide_*`, `test_the_lists_work_on_the_group_of_a_selected_occurrence`,
  `test_the_lists_need_one_group`, `test_a_list_that_cannot_be_saved_is_explained`: `merge_button`, `split_button`, `always_button` are the actions `merge_action`, `split_action`,
  `always_action` of the context menu (the brief puts them there; the inspector has two buttons), so they `trigger()` where they clicked. `never_button` and `hide_button` keep their names.
- Kept public names: `tree`, `tree_item_for` (items are still the groups, top level, with check state), `text`, `hide_button`, `never_button`, `export_button`, `warnings_label`,
  `group_count`, `highlight_count`, `hide_selection`, `tooltip_at`, `review`, `combined`, `load`, `exportRequested`.
- Tests of other files that use the screen are untouched and pass: `test_navigation.py` (uses `tree.topLevelItem(0).setCheckState` and `tree_item_for`), `test_export_dialog.py` and
  `test_navigation.py` (click `review_screen.export_button`), `test_home.py`, `tests/fixtures/ui.py`.

## 3. New tests and RED -> GREEN

New: `tests/ui/test_review_inspector.py` (47: families and sections, `asks_about`, captions, footer counts, switch, row, pill, selection colour, heading rows, pane, tab order, the
no-literal-colours guard), `tests/ui/test_review_look.py` (11: colours of each part in both appearances, switch of appearance while open, the pictures), and 61 more in
`tests/ui/test_review_screen.py` (sections and counts, captions, CHECK pill, title and `titleChanged`, footer, "Not sure" present / hidden / Hide / Show / Space / tab order /
Show always / Hide always, the switch changing the plan, Space, arrows, places, double click, click selects and scrolls, find field and ⌘F, context menu and Merge with…, Show always on text, page
margins and fonts, widths 300–360, the wheel over a row (a real window-system wheel event), scroll kept on rebuild). Reviews made by hand (`tests/ui/review_samples.py`) are used where
the engine is not the point.

RED (the new and adapted tests against the OLD `review_screen.py` from `4146e37`, new module moved away):
```
$ uv run pytest tests/ui/test_review_inspector.py
E   ModuleNotFoundError: No module named 'themask.ui.review_inspector'     (1 error during collection: 47 tests)
$ uv run pytest tests/ui/test_review_look.py tests/ui/test_review_screen.py -q
76 failed, 45 passed in 17.11s
  AttributeError: 'ReviewScreen' object has no attribute 'title' / 'row_for' / 'section_titles' / 'inspector' / 'counts_label' / 'find_field' / 'titleChanged'
  AttributeError: 'ReviewScreen' object has no attribute 'merge_action' (Did you mean: 'merge_button'?)   (likewise split_action, always_action)
  AssertionError: assert 'Project Falc...— [COMPANY_3]' == 'Project Falcon'
```
(the 45 that passed are the old tests whose behaviour is kept, and the new ones for kept behaviour: keys, selection, double click, expanded groups.)

GREEN (same files, the final code): `uv run pytest tests/ui/test_review_inspector.py tests/ui/test_review_look.py tests/ui/test_review_screen.py -q` -> `171 passed in 22.35s`.

Sensitivity: ten one-line breaks of the code (sections reversed, asked about when switched on, footer counting a check as hidden, Space ignored, `titleChanged` never sent, no regroup after a
switch, three spellings in the caption, selected row uncoloured, find not wrapping, switch not reaching the plan) were each caught by the tests; the code was restored (hashes checked).

## 4. Pictures (offscreen `grab()`, 1180 x 760, THEMASK_APPEARANCE light / dark through `theme.apply`)

In `/home/user/the-mask-notes/notes/design/d2-shots/`:
- `review-light.png`, `review-dark.png`: supply-01.docx as `analysed(...)` gives it, the first company selected (41 values, 0 to check).
- `review-light-checks.png`, `review-dark-checks.png`: supply-08.docx, which has real groups to check (Project Falcon, Mr Edwards, Kraft), with Kraft switched off (so "NOT SURE — HIDE?" shows) and the
  first company selected and open.
They are made by `tests/ui/test_review_look.py -k supply` (`THEMASK_SHOTS_DIR=<folder>`); without the variable the test saves them in its own folder.
Fonts here are the fallbacks (no Iowan Old Style, Palatino, Georgia or SF on this machine), the scroll bars are Linux's, so line breaks and widths will differ a little on the Mac.

## 5. Gate (in the worktree, last lines)

```
$ uv run pytest tests/ui -q                      554 passed in 74.27s (0:01:14)
$ uv run pytest -q                               3544 passed, 8 skipped in 390.39s (0:06:30)
$ uv run ruff check src tests tools packaging    All checks passed!
$ uv run ruff format --check src tests tools packaging   151 files already formatted
$ uv run mypy src                                Success: no issues found in 56 source files
```
Also run with deprecation warnings as errors on the three review test files: clean. Performance (synthetic, 300 groups of 2 places, offscreen): load + first paint 0.25 s, a rebuild
after hide / merge / split / regroup 0.18 s (it was 1 s before the lines were put in the list in one go); the old 500-highlight test still passes.

## 6. What D1 must wire at merge time (exactly)

(Read from `design-d1` at `6bbc73a` with `git show`, nothing checked out; D1's window already has `set_title(title, caption, *, screen=None)`, `set_primary("review", "Export…", self.show_export, ...)`
and `add_toolbar_widget(screen, widget)`, so the merge is three small edits in `main_window.py`.)

1. **Title block**, in `MainWindow.__init__`:
   `self.review_screen.titleChanged.connect(lambda title, caption: self.set_title(title, caption, screen="review"))`
   and in `show_review`, instead of the `self.set_title(", ".join(source.path.name ...), f"Review · ...", screen="review")` block:
   `self.set_title(*self.review_screen.title(), screen="review")`.
   `title()` is `("supply-01.docx", "Review · 14 values found · 2 to check")`; `titleChanged(str, str)` is sent on `load` and whenever either line changes (a switch, a hide, a merge...), so the caption stays live.
   `set_title(screen="review")` already keeps the text for when the review shows, so no extra call is needed on navigation. The screen names several files "a.docx and b.pdf" / "a.docx and 2 more";
   if D1 prefers its own comma-joined names for the first line, use only `title()[1]` for the caption and keep the names.
2. **"Export…"**: `set_primary("review", "Export…", self.show_export, lambda: self._review_ready)` is already what is needed; the screen has no export button of its own to show. `exportRequested` stays connected to
   `show_export` (it only fires from the hidden `export_button`, see concern 2).
3. **"Redline split" check box**: the window's own (`add_toolbar_widget("review", box)`); `MainWindow.redline_split` (set in `show_review`, read in `show_export`) is unchanged and the screen has no redline code.
4. **⌘F**: the screen owns it (`review_screen.find_shortcut`, a window-context `QShortcut(QKeySequence.Find)`, active only while the screen is visible). Do not bind ⌘F again for the review (an ambiguous shortcut fires
   neither). If the window wants one ⌘F for all screens, call `review_screen.focus_find()` from your action and `review_screen.find_shortcut.setEnabled(False)`.
5. The stack gives the screen the whole content area. Its minimum size hint is 436 x 196 (the inspector's 300 and a 136 px page); a window narrower than about 760 px of content leaves the page too narrow to read,
   so keep the window's own minimum above that.
6. Tests on D1's branch that touch the screen: `test_navigation.py` (`tree.topLevelItem(0).setCheckState`, `tree_item_for(...).checkState`, `export_button`) and `test_export_dialog.py` (`export_button`) all keep working against this
   screen as they are (checked on the files of `design-d1`'s tests by reading; on this branch they pass). A hidden button still takes `qtbot.mouseClick`. If D1 retargets them to the primary action, `export_button` (and its `QPushButton`
   import) can be deleted from `review_screen.py`. `README.md` line 29 still says "Continue to export".

## 7. Notes for D4 / D5

- D4 (flagged, shown-by-default groups): they appear in "Not sure — hide?" as soon as they are `needs_check=True, enabled=False` in the `ReviewState`. The one rule is `review_inspector.asks_about`.
- D5 (Hide / Show remembered with an Undo toast): `ReviewScreen._answer_hide` and `_answer_show` are the two slots of the row buttons (`GroupRow.hideClicked` / `showClicked`). Today Hide only switches the group on and Show only
  records the answer for this review; D5 adds `add_always_hide` / `add_never_hide` and the toast there. "Show always" and "Hide always" in the menu already use the lists.

## 8. Concerns and choices the owner may want to change

1. **A flagged group switched off by hand moves up into "Not sure — hide?"** at once (the selection follows it). That is the brief's "until then it lists the CHECK groups that are switched off", read literally; it
   keeps a flagged value that is left visible in front of the owner until they confirm it with Show, which suits a privacy tool, but it makes a row jump when you flip its switch. The alternative (ask only about the
   groups that are off when the review is loaded, which is what D4 will produce) is a few lines in `asks_about` / `_item_changed`. Today no analysis produces such a group, so the section appears only after the owner switches a flagged group off.
2. **`export_button` is a hidden shim** kept because tests in files D1/D3 own click it (see 6.6). It is not in the layout.
3. **Not drawn: the ring round the selected group in the page** (the mockup's `box-shadow`). Qt's character formats cannot draw an outer ring; the brief says to keep today's darker tint, which is kept.
4. **The off-state of the switch** is not in the mockup (it shows a plain checkbox): the track is `border_strong` with a `secondary` outline and a `panel` knob. The on-state knob and the tick use `on_accent`; if D1 gives text-on-accent in dark
   another token, the two places are `ToggleSwitch.paintEvent` and `GroupDelegate.paint`.
5. **The pill text** is the `notice_text` token (as the brief and R124 say), the mockup's own is `#7A4B00`; the magnifier is `secondary` where the mockup has tertiary (R124).
6. **The footer wraps** to two lines on each side at 300 px, as the mockup's flexbox would; the type menu of "Hide selection" still has the tint swatches it had (the brief says the tints are for the page and the chips: say if the menu should go plain).
7. **No visible disclosure arrow** for the places of a group (the mockup has none): double click, Right/Left or "Show places" in the menu open them.
8. **Not verifiable offscreen**: the real fonts and native scroll bars, VoiceOver, and whether Qt redraws the find field's clear button in the new colours when the system changes appearance with text in the field (on the generic style it does, pixel for pixel).
9. **Size**: `review_screen.py` is 1128 lines and `review_inspector.py` 1000. The pure helpers (sections, captions, counts, about 250 lines) could be their own module; I did not split further on my own.
10. One new test uses `PySide6.QtTest.QTest.wheelEvent` (the only way to send a window-system wheel event); `src` still imports QtCore, QtGui and QtWidgets only.
