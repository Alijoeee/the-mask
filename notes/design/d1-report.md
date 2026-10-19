# D1 report: shell, theme and home screen (design pass, branch `design-d1`)

Worktree `/home/user/the-mask-worktrees/design-d1`, off `4bbde49` (= design-v1 = mac-v1). UI only: nothing of
detection, export, leak check, restore, keystore or the network guard was touched (the diff is `src/themask/ui/`,
`tools/` and `tests/ui/`). Nothing was pushed, no Briefcase build, no other worktree touched.

**Status: DONE_WITH_CONCERNS** (the concerns are in section 8; the work is finished and the gate is green).
Full suite 3,614 passed, 8 skipped (the dispatch's 3,343 + 271); ruff, ruff format and mypy clean.

Commits (oldest first, Conventional Commits, trailer `Co-Authored-By: Claude Sonnet 5.5`):
- `51ec241` feat(ui): warm theme with light and dark palettes
- `8b8f2ce` chore(ui): illustrations drawn by tools/make_art.py
- `4146e37` feat(ui): line icons drawn from the mockups' paths
- `5cf5005` feat(ui): the drop zone as a card with an illustration
- `2a881ea` feat(ui): the Settings window
- `31a1e53` feat(ui): sidebar window with a unified toolbar and a Settings window, and the home screen as a drop card
- `85e4c0a` chore(ui): tools/make_shots.py takes pictures of the windows
- `18f2bb4` fix(ui): Return in the Settings window saves and presses no other button
- `d2bb431` feat(ui): the drop title is set tight, a switched-off card dims its caption, and the stylesheet's own parts are tested drawn
- `3288d1d` fix(ui): Export… keeps its dots in the tool bar; the recent cases are off while analysing and ask a refusing Keychain once
- `b106274` chore(ui): the pictures show a neutral output folder

The two things D2 and D3 need first are in section 2 (the surface of `MainWindow`) and its merge notes.

## 1. What I built, item by item

### a) `src/themask/ui/theme.py` (tokens, palettes, stylesheet, appearance, fonts)
- `Tokens` (frozen dataclass) with the brief's light and dark values as plain constants, `tokens(appearance)`.
  The brief's tokens are there unchanged; the mockups needed a few more, which I added (they are in the mockups'
  markup, not in the brief's list): `control` (light = #FFFFFF, dark #33312D from the brief), `hairline` (row
  separators and hover fill: #EFEBE5 / #3A3733), `accent_hover` (#8F4C1D / #F0A370), `on_accent` (#FFFFFF),
  `notice_card_bg` (#FFF9E6 / #3D3320), `success_text` (#2E7D4F / #5CC27F).
- `palette(appearance) -> QPalette` (Window, Base, Text, Button, Highlight, Accent, Link, PlaceholderText, the
  disabled group, ...), `stylesheet(appearance) -> str` (a `string.Template` filled from the tokens: general rules
  `_TEMPLATE` for buttons, fields, lists, group boxes, progress, notices, drop card; and `_SHELL` for the tool bar,
  the primary action, the sidebar notes and the home screen), `current_appearance()` (`THEMASK_APPEARANCE`
  light|dark, else `QStyleHints.colorScheme()` through `system_scheme()`, else light), `apply(app)` (palette +
  stylesheet + system font at 13 px; an `AppearanceFollower` child of the application installs again on
  `colorSchemeChanged`, once however often `apply` is called), `appearance_of(palette)` and `tokens_of(widget)`
  (a widget that paints itself asks its own palette which appearance it is in), `body_font()`, `serif_font()`
  (Iowan Old Style, Palatino, Georgia; 14.5 px by the point size so it is 14.5 px on the Mac and elsewhere),
  `mono_font()`. `TYPE_COLOURS` and `set_status` are unchanged. `app.main()` calls `theme.apply`.
- The brief's "apply_theme" became `apply`; `app.py` imports the module (`theme.apply(application)`), so the two
  `test_app.py` monkeypatches point at `app.theme.apply`.

### b) `tools/make_art.py` and `src/themask/ui/art/`
- Pillow drawing (8x supersample, BOX reduction, round caps, strokes centred on the outline as in SVG, two text
  lines at 50 % opacity) of the mask-on-document illustration, 112x88 and 224x176, and the document-with-check,
  64 and 128 px, each light and dark: eight committed PNGs (`mask-light.png`, `mask-light@2x.png`, ... `check-dark@2x.png`).
  Colours are the theme's accent, accent-soft and panel (a test compares them with the tokens).
- `themask.ui.art`: `pixmap(name)` (device pixel ratio 2 for `@2x` names, `FileNotFoundError` for a missing one),
  `icon(kind, appearance)` (the 1x and the 2x as one `QIcon`), and `Illustration(kind)`, a widget that draws the
  picture in the appearance of its palette (so it follows light/dark with the window) and dimmed while disabled.
  `art/` is a package (the `__init__.py` is the helper): `tests/ui/test_qt_modules.py` now looks at subfolders of
  `ui` too (see section 3).

### c) `src/themask/ui/icons.py`
Mask (document + mask), Restore (key), Cases (archive box), sidebar toggle and the find-field magnifier as
`QPainterPath`s built from the SVG path data of the mockups (a small `svg_path` parser for M L H V C S Z, absolute and
relative). `draw(painter, name, rect, colour)`, `pixmap(...)`, `icon(name, colour, size)` (1x and 2x pixmaps, so crisp
at both). The search icon is there for the find field (D2) and the Cases filter (D3).

### d) `MainWindow` (`main_window.py`) and its parts (`sidebar.py`, `widgets.py`, `SettingsWindow`)
- `setUnifiedTitleAndToolBarOnMac(True)`; one `QToolBar` (`objectName mainToolBar`, not movable, not floatable, top only,
  no context menu) holding: `sidebar_toggle` (icon only, 30x26, accessibleName/tooltip "Hide sidebar" / "Show sidebar"
  by what a press does), `title_block` (two centred, eliding lines: title and caption), and the `primary_action`
  (`QAction`; Home "Review", Review "Export…", Restore "Restore", Cases "New case"; off while a file is analysed).
  Text and enabled state follow the screen; the tool button shows the dots of "Export…" (Qt strips them from the icon text
  unless `setIconText` says otherwise: found by a test, see 5).
- `Sidebar` (220 px, chrome colour, line at its right edge): `SidebarItem`s (custom-painted `QPushButton`s: 34 high,
  radius 8, icon + label, the chosen one on the accent with white text, hover, focus ring for keyboard focus only,
  dimmed when off), Tab-focusable, Up/Down move between them, Space/Return press. A click only asks
  (`sectionRequested`); the window says which is chosen (Mask also stands for the Review screen). The note at the foot per
  screen: home = status dot + "Engine ready · offline" (follows the engine: loading / problem) and "Settings: The MASK ›
  Settings… (⌘,)"; review = the legend (six swatches from `TYPE_COLOURS`); restore and cases = the mockups' sentences
  (the cases sentence says the days the settings keep a case, 30 by default).
- Settings left the sidebar: `settings_action` (`MenuRole.PreferencesRole`, `QKeySequence.Preferences`, with `Ctrl+,` where
  the platform has no binding, as offscreen/Linux) in the File menu (a Mac moves it to the application menu), opening
  `SettingsWindow(QDialog)` (in `settings_screen.py`; titled "Settings", `Qt.Tool`, not modal) that hosts the unchanged
  `SettingsScreen`. Also in the File menu: `choose_action` "Choose file…" (⌘O) which opens the home zone's file dialog.
- Crossfade: `_show(name)` puts the new screen in place at once and lays a picture of the old one over it that fades out
  (`QGraphicsOpacityEffect` + `QPropertyAnimation`, `FADE_MS = 120`); module flag `main_window.ANIMATIONS`, set False by
  `tests/ui/conftest.py` (`no_animations`), and no fade for a window that is not showing or the same screen.
- Kept: `open_files`, `is_analysing`, `BUSY_MESSAGE`, `screen_names`, `current_screen_name`, `show_home/_review/_export/
  _restore/_cases/_settings`, the screen attributes (`home`, `review_screen`, `restore_screen`, `cases_screen`,
  `settings_screen`), `export_dialog`, `sources`, `redline_split`, `pending_case`, every signal. `screen_names()` is now
  `["home", "review", "restore", "cases"]` (Settings is a window), `show_settings()` opens the window.
  While a file is analysed: the sidebar, the Settings action and its window, the primary action and the file chooser are off.

### e) The home screen (`home_screen.py`, `drop_zone.py`)
- Centred column, 640 max, in a scroll area (so a small window scrolls); `DropZone` is the drop card (44/32/36 padding,
  radius 16, panel, illustration 112x88, "Drop a contract here" 22/600 (tight by 0.2 px as in the mockup), the caption
  "Word or PDF. Confidential values are swapped for placeholders before anything leaves this Mac.", "Choose file…" + "or
  press ⌘O"); drag over = accent border + accent-soft background (the `dragOver` property as before). `choose_button`,
  `title_label`, `hint_label` kept. The status line ("Ready" is not shown, the others are), the progress bar and the step
  text sit in the card's caption area (`DropZone.status_layout`); `notice_label` and `refused_label` are the notice band
  under the card in the notice colours.
- "RECENT CASES" (the text is "Recent cases", drawn upper case by the font, so a screen reader reads words): up to three
  rows from `ctx.case_store.list()`, newest first: code chip (mono, accent on accent-soft), file names (600; "Case K4F7"
  if a case holds none), caption from the `CaseSummary` by `describe_case`: "Exported today at 14:02 · 14 values hidden ·
  expires in 30 days" / "Exported yesterday · 2 files · 21 values hidden · expires in 29 days" (also "N days ago", "on
  2026-10-01", "expires in less than a day", "expired"), and a "Restore" link per row (accessible name "Restore with case
  K4F7") that shows Restore with that case chosen (`restoreRequested` -> `MainWindow.show_restore(case_id)`, the same path
  as "Restore from this case" in Cases); an "All cases" link (-> Cases). Hidden when there are no cases. Refreshed when the
  home screen is shown. The links are off while a file is analysed. A refusing Keychain is asked once per session.
- `DropZone` also takes `art` ("mask"/"check"), `choose_text` and `shortcut_hint` for the screens that want another card
  (the Restore card of D3); with none it looks as before but in the new card style.

### f) Tests
See section 4 (changed) and 5 (new, with RED then GREEN).

### g) Gate
See section 7.

## 2. The surface for D2 and D3 (integration at merge time)
Everything below is on `MainWindow`, documented in the module docstring, covered by tests in `tests/ui/test_shell.py`:
- `show_screen(name)`: "home" | "review" | "restore" | "cases"; each refreshed as its own `show_...` does ("review" only
  once a file was analysed, else nothing); `KeyError` for any other name ("settings" is `show_settings()`).
- `set_title(title, caption="", *, screen=None)`: the two lines of the tool bar for the screen that shows, or for `screen`
  (kept until it shows). Defaults: home "The MASK"; review "supply-01.docx" / "Review · 14 values found · 2 to check"
  (set once by `show_review` from the file names and `review.counts()`: D2 keeps it live); restore "Restore" / "Put the real
  values back into the file an AI tool returned"; cases "Cases" / "The keys that put real values back · kept on this Mac,
  encrypted".
- `primary_action` (`QAction`) and `set_primary(screen, text, run, enabled=None)`: what it is called and does on a screen and
  when it is on (default wiring: home -> go to the review; review -> `show_export`; restore -> `restore_screen.restore_button`
  `.click()` and mirrors that button's enabled state; cases -> `show_home`). `refresh_chrome()`: a screen whose state changed
  calls it to have the primary action and the file chooser checked again.
- `add_toolbar_widget(screen, widget)`: puts a widget in the tool bar just before the primary action while that screen
  shows (the review's "Redline split" check box).
- Unchanged names the screens keep: `review_screen.export_button`, `restore_screen.restore_button` ... until D2/D3 remove them.
  Until then the Review and Restore screens show their own primary button as well as the tool bar's (two accent buttons).

Merge notes: `theme.py` is additive since `4146e37` (the shell rules are a second template `_SHELL` joined in `stylesheet()`,
so a screen's rules can go in `_TEMPLATE` or a template of their own without touching mine). `drop_zone.py`, `home_screen.py`,
`settings_screen.py`, `sidebar.py`, `widgets.py`, `main_window.py`, `app.py` are D1's; a D3 that rewrote `DropZone` from
`4146e37` will conflict in `drop_zone.py`: take D1's constructor (`art`, `choose_text`, `shortcut_hint`, `status_layout`).

## 3. Existing tests that changed, and why
(none deleted; renamed only where the old name would lie, with a comment in the test)
- `tests/ui/test_app.py` (2 lines): `monkeypatch.setattr(app, "apply_theme", ...)` -> `app.theme, "apply"`; the theme
  function is `theme.apply` now and `app` imports the module.
- `tests/ui/test_theme.py`: the placeholder-colour tests are unchanged in what they check (black text on a tint is
  measured as a contrast now); `test_the_stylesheet_is_understood_by_qt` runs for both appearances on `stylesheet(a)`
  (there is no `STYLESHEET` constant any more); `test_apply_theme_gives_the_application_the_stylesheet` became
  `test_apply_installs_the_palette_the_stylesheet_and_the_system_font_at_13_pixels` (+ the dark twin).
- `tests/ui/test_qt_modules.py::test_no_core_module_imports_qt`: it skipped files whose parent folder is `ui`; `ui/art/`
  (the helper next to the PNGs) is part of the interface, so it now skips any file below a `ui` folder. The rule it guards
  (only `themask.ui` imports Qt) is unchanged.
- `tests/ui/test_drop_zone.py`: three assertions follow the mockup's copy ("Choose files…" -> "Choose file…", the caption
  sentence, "Drop your contracts here" -> "Drop a contract here"); new tests for the card, the illustration, the
  status area, the drag-over look in both appearances, the title's letter spacing.
- `tests/ui/test_home.py`: `screen_names()` is `["home","review","restore","cases"]` (comment says why); the parameter
  `("show_settings","settings")` of `test_each_screen_can_be_shown` is a test of its own, `test_the_settings_can_be_shown_as_a_
  window_over_the_screen_that_shows`; `test_an_error_while_the_review_is_built...` checks the primary action and the sidebar
  instead of the tool bar's Review/Home buttons; `show_settings()` in two tests about files opened "from another screen" is
  `show_restore()`/`show_cases()` (the Settings are no longer a screen, and those tests are about leaving the home screen);
  two renames: `test_the_tool_bar_is_off_while_a_file_is_analysed_and_on_again_after` -> `test_the_sidebar_and_the_settings_
  are_off_while_a_file_is_analysed_and_on_again_after` and `test_the_tool_bar_comes_back_when_the_analysis_fails` ->
  `test_the_sidebar_comes_back_when_the_analysis_fails` (the old tool bar's job is the sidebar's; both have a comment). The
  three tool-bar helpers (`toolbar`, `toolbar_actions`, `click_in_tool_bar`) went with the buttons they clicked.
- `tests/ui/test_navigation.py`: `actions_of` -> `click_section`; one rename, `test_the_tool_bar_moves_between_the_screens` ->
  `test_the_sidebar_moves_between_the_screens`; the Review/Settings/Cases/Restore steps go through the primary action, the
  sidebar and `settings_action`; same assertions otherwise.
- `tests/ui/conftest.py`: autouse `no_animations` (sets `main_window.ANIMATIONS = False`).
- Not touched: every other test (restore, review, export, cases/settings screens, workers, detection, ...).

## 4. New tests (files, what they cover)
| file | tests | covers |
|---|---|---|
| `tests/ui/test_theme.py` (extended) | 44 | both token sets (the brief's values), palettes from tokens, contrast >= 4.5:1 (text/secondary on every ground; accent-on-soft, notice, danger, success text), `THEMASK_APPEARANCE` override (case, blanks, junk), system scheme and "unknown -> light", `apply` installs palette + stylesheet + 13 px font, follows `colorSchemeChanged` (light -> dark -> light), a forced look ignores the system, `apply` twice = one follower, serif/mono/body fonts, stylesheet parses in Qt for both appearances |
| `tests/ui/test_theme_shell.py` | 18 | the stylesheet of the window's parts drawn in both appearances: tool bar, primary action on/off, sidebar, notice band, code chip, row hairline, link, dimmed card caption |
| `tests/ui/test_art.py` | 19 | the eight PNGs exist at 112x88 / 224x176 / 64 / 128, ratio 2 for `@2x`, `make_art` regenerates them byte for byte (and twice the same), colours = theme tokens, shapes (page, face, eyes, check), `Illustration` follows the palette and dims |
| `tests/ui/test_icons.py` | 26 | five icons at 1x/2x and any size, line drawings in the colour given, shapes of the mockups, `svg_path` parser |
| `tests/ui/test_widgets.py` | 11 | `ElidedLabel` (ellipsis, tooltip, grows/shrinks), `LinkButton`, `Swatch`, keyboard-focus rule |
| `tests/ui/test_sidebar.py` | 24 | 220 wide, three items in order, one chosen, click asks / window decides, off/on, arrows + Space/Return, drawn on the accent in both appearances, dimmed, focus ring only for keyboard focus, the four notes (exact copy), engine dot colours |
| `tests/ui/test_settings_window.py` | 13 | dialog titled "Settings", Tool, not modal, hosts the screen, Esc closes, reload on open, stale lists reloaded on activation unless typed, Return saves and presses nothing else |
| `tests/ui/test_shell.py` | 66 | unified-toolbar call, the fixed tool bar and its three parts in order, toggle (name flips, hides/shows, works during analysis), titles per screen and `set_title`, primary action per screen (enabled rules, Export… dots, Restore mirrors the button, off while analysing), `show_screen`, `set_primary`, `refresh_chrome`, `add_toolbar_widget`, sidebar follows screens and is off during analysis (also after a failure), notes follow screens, engine status, Settings action (role, shortcut, menu, opens window, off while analysing, closes with the window), Choose file… (⌘O), crossfade (flag off in tests; on: overlay, 120 ms, ends, restarts, no fade for same screen/hidden window), Tab order, shortcuts by keyboard, narrow window |
| `tests/ui/test_recent_cases.py` | 33 | `describe_case` (today/yesterday/days/date, files, values, expiry, expired), rows from two saved cases and from the `exported` fixture, at most three, newest first, no section when none, Restore link -> Restore with that case chosen, All cases -> Cases, links off while analysing, unreadable store (Keychain / disk) leaves no section, a refusing Keychain asked once |
| `tests/ui/test_shots.py` | 16 | `tools/make_shots.py`: every screen in both appearances, sizes, colours of the chrome per appearance, mockups' captions, leaves nothing changed |
| `tests/ui/test_drop_zone.py` (extended) | +8 (33 in all) | card copy, illustration/choose text/shortcut hint, padding, status area order, drag-over look in both appearances, letter spacing |

## 5. RED then GREEN
RED = the new test file run before the code it tests existed (or with the fix taken out); GREEN = the same file after.
- theme: `uv run pytest -q tests/ui/test_theme.py` RED `ImportError: cannot import name 'Tokens' from 'themask.ui.theme'`
  (1 error during collection) -> GREEN 44 passed (after fixing two bugs of my own tests: a label never shown does not take the
  application palette until it is; `setPixelSize` leaves `pointSizeF()` at -1).
- art: RED `ImportError: cannot import name 'art' from 'themask.ui'` -> GREEN 19 passed.
- icons: RED `ImportError: cannot import name 'icons'` -> first GREEN run crashed intermittently (`Fatal Python error:
  Segmentation fault` in `test_an_icon_that_does_not_exist_is_refused`: `pixmap()` raised while its `QPainter` was still open
  on the `QPixmap`); fixed (name checked before the painter, `try/finally painter.end()`), 8 clean repeat runs, 26 passed.
- widgets / sidebar / settings window / recent cases: RED `ImportError` on the missing module -> GREEN (11 / 24 / 13 / 33).
- shell: RED `uv run pytest -q tests/ui/test_shell.py` = `52 failed in 50.53s` (no toolbar, sidebar, primary action, settings
  action yet) -> GREEN 66 passed after `main_window.py`.
- Bugs a test found after the first GREEN (each shown RED with the fix taken out, GREEN with it):
  1. `SettingsWindow`: in a `QDialog` Return pressed the first auto-default button, so Return in the folder field opened the
     folder dialog (`AssertionError: The test opened a dialog that nobody can answer.` x2). Fixed: no button is auto-default,
     Save is the default.
  2. Tool bar "Export…" showed as "Export": a `QToolButton` shows the action's *icon text*, which Qt makes of the text without
     "…" (`assert 'Export' == 'Export…'`). Fixed with `setIconText`.
  3. A refusing Keychain was asked again at every visit to the home screen (`listed == 2` vs 1): now once per session.
- theme_shell: 16 of 18 passed at once; the two RED were the dimmed caption of a disabled card (`'#7e776e' in {'#a39b91', ...}`)
  -> GREEN after the rule `QFrame#dropZone QLabel#dropHint:disabled`.

## 6. Screenshots (offscreen `grab()`, Qt on this Linux box: Fusion style, Inter font; menu bar hidden as the Mac shows it in the system bar)
Made by `uv run python tools/make_shots.py DIR --review FILE.docx` (made-up cases K4F7 and Z8Q2 as in the mockups, a fixed clock at
15:30, a case store and key in memory; the same script is what `tests/ui/test_shots.py` runs).
After, `/home/user/the-mask-notes/notes/design/d1-shots/`:
- `home-light.png`, `home-dark.png` (1180x760): the mockup's home screen with two recent cases
- `settings-light.png`, `settings-dark.png` (680x640): the Settings window
- `restore-light.png`, `restore-dark.png`, `cases-light.png`, `cases-dark.png`, `review-light.png`, `review-dark.png` (1180x760): the
  shell (tool bar title/caption/primary action, sidebar, notes at the foot) on the screens D2/D3 still have to redo; their
  contents are the old screens in the new theme
Before (the same screens at `4bbde49`, light only: the old app had no dark theme of its own, and Qt offscreen cannot switch the
system to dark): `before-home-light.png`, `before-settings-light.png`.

What the screenshots cannot show (see section 8): the Mac's native unified title bar and tool bar, the system menu bar, native
controls under the stylesheet.

## 7. Gate (run from the worktree, on the clean tree at `b106274`)
```
$ uv run pytest -q
3614 passed, 8 skipped in 443.63s (0:07:23)          (exit 0)
$ uv run ruff check src tests tools packaging
All checks passed!
$ uv run ruff format --check src tests tools packaging
158 files already formatted
$ uv run mypy src
Success: no issues found in 58 source files
```
An earlier full run, on the same code before the last four small commits, said `3595 passed, 8 skipped in 458.98s`. The UI directory
alone (`uv run pytest -q tests/ui`) is about 2.5 minutes; the new UI test files were also run three times in a row for flakiness
(198 passed each time).

## 8. Concerns and decisions (read these)
1. **Contrast of three approved pairs is under 4.5:1** (the tokens are the mockups', so I kept them; every pair the brief's test names
   passes). Measured: white on the accent 4.36:1 light and 2.88:1 dark (primary buttons, the chosen sidebar item); the accent as text
   on a panel 4.36:1 light, on accent-soft 3.5:1 light (links, the code chip); tertiary on a panel 3.0:1 light, 3.2:1 dark (hints,
   "or press ⌘O"; disabled text is exempt). One-token fixes if the owner wants them: `on_accent` dark `#1E1D1B` (5.9:1), accent light
   `#AD5E27` (white 4.8:1, on ground 4.6:1), chip text `accent_text_on_soft` (6.6:1). Noted in the `Tokens` docstring.
2. **Mockup versus brief**: the "RECENT CASES" header is 13/600 in the mockup and 11/600 in the brief; I followed the mockup
   (exact spacing and colours were to come from the mockups). The home tool bar shows one line ("The MASK") as the mockup does: the
   caption line is hidden when empty.
3. **Not verifiable on this box (Linux, offscreen)**: the Mac's native unified title bar and tool bar (the call is made; the tool bar
   is also given the chrome colour by the stylesheet, which may paint over the unified material), where the Mac puts `Settings…`
   (the preferences role moves it to the application menu; the File menu keeps "Choose file…"), `Qt.Tool` for the Settings window as
   the brief says (on macOS a tool window is a utility panel and hides while the app is not active), and how stylesheet-drawn
   widgets sit beside native-styled ones (combo boxes, spin box, check boxes, scroll bars are still native until D2/D3 style them).
   The screenshots are Qt's Fusion style. Worth a look at the owner's smoke test; `app.setStyle("Fusion")` in `theme.apply` would be
   the one-line fallback if the native style fights the stylesheet (not done: not checkable here).
4. **No card shadow** (the light mockup has `0 1px 2px rgba(31,29,26,.04)`): a stylesheet cannot draw one and it is 4 % alpha.
5. **⌘O is the File menu's "Choose file…"** (works from every screen, off while analysing or while the engine loads), not a shortcut of the
   home screen only; if files chosen that way are refused, the home screen comes up so the notice is seen. If D3 wants ⌘O to choose the
   AI's file on the Restore screen, `MainWindow._choose_triggered` has to dispatch by screen (a one-line change for the integrator).
6. **Interim state**: the Review screen still has its own "Continue to export" and Restore its own "Restore"/"Restore text", so those
   two screens show two accent buttons until D2/D3 remove theirs. The tool bar's Export… / Restore work today.
7. **README** still says "Choose files…", "Continue to export" and where the Settings are; I left it so as not to collide with D2/D3,
   who edit the same paragraph: one pass at the end.
8. **Size**: `main_window.py` 617 -> 880 lines although `HomeScreen` (110) moved out. New modules: `sidebar.py` 320, `home_screen.py`
   347, `widgets.py` 108, `icons.py` 186, `art/__init__.py` 73. I judged one 1,300-line file worse than the split; say if you want it back.
9. **Added on purpose (not in the brief)**: `show_screen`, `set_primary`, `refresh_chrome`, `add_toolbar_widget` (the controller's
   integration surface); `SettingsScreen.has_unsaved_edits()` / `is_stale()` + window reload on activation (a window that stays open
   beside the review would otherwise Save stale lists over a value just added with "Always hide"); Save as the Settings window's
   default button; recents links off while analysing; the Keychain asked once; `Tokens` extras listed in 1a.
10. **Review caption is set once** when the review is shown ("Review · 41 values found · 0 to check"); D2 should keep it live through
    `set_title(..., screen="review")`.
11. **Tests that read pixels** (`test_shots.py`, `test_theme_shell.py`, the sidebar/drop-zone ones) depend on layout constants (tool bar
    padding 16, sidebar items at y 64-98); change those and the coordinates move.
12. `tools/make_shots.py --review` loads the language model (about 5 s); without it the pictures need no engine.

## 9. Self-review (my own diff, read once more before reporting)
- Completeness: every item of the dispatch's a) to g) is there (see section 1); the brief's exact copy is used verbatim: "Drop a
  contract here", the caption sentence, "Choose file…", "or press ⌘O", "Recent cases", "All cases", "Restore", "Engine ready · offline",
  "Settings: The MASK › Settings… (⌘,)", the restore and cases notes, the toolbar titles/captions, "Hide sidebar".
- Found and fixed while reading/running: a `QPainter` left open on a pixmap when an icon name was wrong (intermittent segfault); Return in a
  dialog pressing the wrong button; the dots lost from "Export…"; the Keychain asked at every visit; a `QAction.trigger()` that ignores
  `enabled` (every slot of an action checks it); refused files chosen with ⌘O on another screen (the notice was on a screen nobody saw);
  weak assertions in my tests (an always-true `assert Qt.AlignmentFlag...`, a disjunction, a placeholder test) removed.
- Quality: ruff (check and format) and `mypy --strict src` clean; no new Qt module (only QtCore/QtGui/QtWidgets); nothing logged that was not
  logged before (no log call was added; the home screen never logs file names); no network; the Keychain is never touched in tests
  (the case store of the tests has its key in memory); the app, not the tests, applies the theme (tests/ui calls `theme.apply` only in
  the tests of the theme and of the pictures, which put the look back).
- Discipline: only the additions listed in 8.9 beyond the brief. The stylesheet is data in `theme.py`; no colour appears in a
  widget except the placeholder tints (the legend), which come from `TYPE_COLOURS`.
