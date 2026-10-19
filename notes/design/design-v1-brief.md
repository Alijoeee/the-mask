# The MASK — design pass "design-v1": brief for the implementers

Owner's decisions (2026-10-19): one window with a sidebar like Mail/Notes; branded and warm; built from the
approved mockups at https://claude.ai/artifact/PHVFzBRjUm7WQBEYnpbNof (ten artboards: Mask, Review, Export
sheet, Restore, Cases — each in light and dark). The mockups' source files are in this folder
(`mockups/*.dc.html`): read them for exact copy, spacing and colours. This is a UI-only pass: no change to
detection, export, leak check, restore, keystore or the network guard. Branch `design-v1` off mac-v1 4bbde49;
mac-v1 itself stays untouched until the owner's smoke test is done.

## Hard constraints (unchanged from the Mac phase)
- Qt modules: QtCore, QtGui, QtWidgets only (tests/ui/test_qt_modules.py guards it). No QtSvg, no QtQuick,
  no QtNetwork. Illustrations are PNGs (1x and 2x) drawn by a Pillow script (`tools/make_art.py`, like
  packaging/make_icon.py) and committed under `src/themask/ui/art/`, loaded with QPixmap; or drawn with
  QPainter where simpler (the sidebar icons: 18 px line icons as QPainterPath — crisp at any scale).
- Everything testable offscreen (pytest-qt, QT_QPA_PLATFORM=offscreen). The suite stays green: existing UI
  tests are ADAPTED to the new structure, never deleted; keep the public widget attribute names the tests use
  (`drop_zone`, `status_label`, `review_screen`, `restore_screen.case_combo`, `altered_list`,
  `restore_button`, `restore_text_button`, `paste_box`, `result_box`, `report_label`, `better_fit_label`,
  `cases_screen.table`, `delete_button`, `settings_screen.always_edit/never_edit/retention_spin/save_button/
  about_label`, `ExportDialog.run/result/copy_button/summary_text/finishedExport`, `open_files`,
  `is_analysing`, `BUSY_MESSAGE`, module-level `confirm`/`reveal`) unless a rename is unavoidable — then
  rename in the tests too, with the reason in the report.
- The log never holds document content or file names; no network; the Keychain is never touched in tests.
- Exact copy from the design document stays exact: the banner, the AI instruction, the restore report line
  "{n} placeholders restored, {m} need your check.", the file names.
- Accessibility: real buttons, labels for every input, `accessibleName` on icon-only buttons, keyboard
  navigation (Tab order, Space toggles a group's switch, ⌘F focuses the find field, ⌘O opens a file,
  ⌘, opens Settings, Esc closes a sheet), contrast ≥ 4.5:1 for text in both modes.

## The look (tokens — put them in `src/themask/ui/theme.py`, one place)
Light: ground #FBFAF8 · chrome (sidebar, toolbar) #F3F0EB · panel #FFFFFF · border #E6E1DA · border-strong
#D9D2C8 · text #1F1D1A · secondary #6B655E · tertiary #9B948B · accent #B5642A · accent-soft #F4E4D8 ·
accent-text-on-soft #7A4019 · notice-bg #FFF4CE / #FFF9E6 · notice-border #ECD48B · notice-text #5B4300 ·
success #2E9E5B on #EAF4E6 · danger #B3261E · table-head #F7F4EF.
Dark: ground #1E1D1B · chrome #262523 · panel #2C2A27 · control #33312D · border #3A3733 · border-strong
#4A4640 · text #F2EEE8 · secondary #A39B91 · tertiary #7E776E · accent #D9834A · accent-soft #3F2E24 ·
accent-text-on-soft #F0C9A8 · notice-bg #3D3320 · notice-border #5A4A1E · notice-text #F3D8A0 · success
#3FB46F on #1F3326 · danger #FF6B61 · table-head #302E2A.
The twelve placeholder tints (TYPE_COLOURS) stay as they are and are used ONLY inside the document text and
as the 10 px chips in the inspector; black text on them in both modes (as today).
Mode: follow the system appearance (QStyleHints.colorScheme(), re-applied on colorSchemeChanged); a
`THEMASK_APPEARANCE=light|dark` environment variable forces one for tests and screenshots.
Typography: the system font (QFont from QFontDatabase.systemFont(GeneralFont)); sizes 13 body, 11
secondary/captions, 15 card titles, 17 sheet titles, 22 the home title; weights 400/600. The document pane
uses a serif (Iowan Old Style → Palatino → Georgia fallback via QFont families) at 14.5 px, line height 1.7.
Spacing on an 8-point grid: 16 px panel padding, 20–32 px screen margins, 12–16 px gaps; corners 8 px on
controls, 12–16 px on cards, 7 px on buttons; one primary button per screen (accent background, white text,
weight 600); secondary buttons bordered.

## Window structure (`src/themask/ui/main_window.py`, `app.py`)
- `QMainWindow`, `setUnifiedTitleAndToolBarOnMac(True)`, a `QToolBar` on top that is not movable/floatable:
  a sidebar toggle (icon-only, accessible name "Hide sidebar"), a centred title block (two lines: the
  screen's title and a one-line caption — e.g. "supply-01.docx" / "Review · 14 values found · 2 to check"),
  and at the right the screen's primary action (Review → "Export…", Restore → "Restore", Cases → "New
  case"; Home → "Review" disabled until an analysis is loaded). The old five text buttons go.
- A `QSplitter`-free fixed sidebar (220 px) on the left, `QListWidget` or a column of flat `QToolButton`s with
  the three sections Mask / Restore / Cases (18 px line icons + label; the selected one on the accent
  background with white text, radius 8, height 34); the bottom of the sidebar holds the context block
  (home: engine status dot + "Engine ready · offline" and the Settings hint; review: the legend; restore and
  cases: the one-paragraph note from the mockups).
- Settings leaves the sidebar: `QAction` with `MenuRole.PreferencesRole`, shortcut ⌘, (QKeySequence.Preferences),
  in the application menu; it opens `SettingsWindow` (a `QDialog`, non-modal, `Qt.Tool`-style window titled
  "Settings") hosting the existing `SettingsScreen` widget unchanged in behaviour; About stays inside it.
- Screens live in a `QStackedWidget` as today; the sidebar and the toolbar's primary action follow the current
  screen. Navigation disabled while `is_analysing()` as today (the sidebar items grey out).
- Crossfade between screens (QGraphicsOpacityEffect + QPropertyAnimation, 120 ms; skipped under tests via a
  module-level `ANIMATIONS = True` the UI conftest sets False).

## Screen 1 — Mask (home)
Centred column, max width 640: the drop card (`DropZone`, now a panel: border, radius 16, white/panel
background, 44/32/36 padding; the mask illustration 112×88 from `art/`; title "Drop a contract here" 22/600;
caption "Word or PDF. Confidential values are swapped for placeholders before anything leaves this Mac.";
"Choose file…" secondary button + "or press ⌘O" tertiary text). Drag-over state: accent border and
accent-soft background. Below: "RECENT CASES" header (11/600 secondary, uppercase) with an "All cases" link
(opens Cases); a panel listing up to three cases (code chip in accent on accent-soft, mono; file names 600;
caption "Exported today at 14:02 · 14 values hidden · expires in 30 days"; a "Restore" link per row that opens
Restore with that case chosen). The status/notice labels of today (`status_label`, `step_label`,
`notice_label`, `refused_label`) stay but move into the drop card's caption area and a notice band under it,
in the notice colours.

## Screen 2 — Review
`ReviewScreen` becomes a two-pane layout: the document pane (panel background, 36/44 padding, serif) on the
left, and a 300–360 px inspector on the right separated by a border. Inspector top: a find field (search
icon, placeholder "Find in document  ⌘F", `QLineEdit` with `ClearButtonEnabled`) and two half-width secondary
buttons "Hide selection" / "Show always" (the existing hide_text / never-hide actions). Middle: a scroll area
with sections per type family ("COMPANIES · 2", "PEOPLE · 2", "AMOUNTS, PERCENTAGES · 2", "ADDRESSES, E-MAIL,
BANK · 3" — group the twelve types this way), each row: 10 px tint chip, canonical (600), caption
"[COMPANY_1] · 6 places · also “Northwind”, “the Buyer’s group”" (secondary 11), a switch (QCheckBox styled
as a toggle, accent-coloured), a "CHECK" pill (notice colours, 10/700) on flagged groups; the selected row on
accent-soft; clicking a row selects it and scrolls the document to its first place; Space toggles; ↑/↓ move.
Footer: "12 hidden · 2 to check · 0 shown on purpose" left, "Space toggles · ↑↓ moves" right. The document
pane keeps today's highlight behaviour (tints, darker tint for the selected group, click-to-select) and the
summary line moves to the toolbar caption. The redline-split check box sits in the toolbar before "Export…".
Keep today's keyboard and selection logic; only the presentation and the grouping of rows change.

## Screen 3 — Export sheet
`ExportDialog` becomes a sheet: on macOS `setWindowModality(Qt.WindowModal)` + `Qt.Sheet`; elsewhere a
centred modal dialog; 560 px wide, no title bar text. Progress state: the progress bar and "Masking…"
caption. Success state exactly as the mockup: green check 56 px + "Masked copy saved" (17/600) + "Every
marked value was replaced and checked twice. Nothing of the original left this Mac."; the file card
(document icon, "MASKED-K4F7.docx", caption "Documents › The MASK · case K4F7 · 14 values hidden · key kept
for 30 days", "Show in Finder" via the monkeypatchable `reveal`); the instruction box on accent-soft ("Next:
upload the masked copy with this instruction", "Copy instruction" primary, the AI_INSTRUCTION text verbatim);
a `QToolButton` disclosure "Details · n left visible on purpose · n not checkable · n found unmarked" that
expands the three lists with today's headings ("Also found in the masked copy — not marked by you:", "Left
visible on purpose:", "Not checkable (too short):"); buttons "Back to review" (secondary) and "Done"
(primary). Blocked state: a red-tinted header "Saving blocked: a marked value is still present", each
LeakHit's part + context in a list, only "Back to review". Error state: plain text, "Back to review".
`summary_text()` keeps returning the plain-text summary the tests read.

## Screen 4 — Restore
Two cards side by side (wrap on narrow windows): the file card (`DropZone` variant: the document-with-check
illustration 64 px, file name 15/600, caption "Dropped just now · 14 placeholders found · case K4F7 fits
best", "Choose another file…") and the paste card ("Or paste the AI’s answer" label, `paste_box`, "Restore
text" secondary button). Below: the case card — "Case" label, `case_combo` (titles "K4F7 · supply-01.docx ·
today 14:02 · 14 values"), the green "Chosen from the file name" / the R106 `better_fit_label` / the R103
"Several cases fit this file — choose one." texts, and the value preview as a 3-column grid of
"[PLACEHOLDER] → value" (mono placeholder in secondary) with "and n more". Then the notice card "These
placeholders were changed by the AI — restore them?" with `altered_list` rows (mono token, explanation,
check boxes); then the result card (green check, `report_label` with the exact report line, the "Saved as …
next to the AI’s file. Unknown: …" caption, "Show in Finder"). `result_box` (restored text, read-only) with
its "Copy" button shows in place of the result card for pasted text.

## Screen 5 — Cases
Toolbar primary "New case" (goes Home). A filter field (260 px) and three actions at the right: "Restore
from this case", "Add a file to this case", "Delete…" (danger text). The table (`table`, QTableWidget with a
styled header row in table-head colour, 11/600 uppercase secondary; columns Code (mono, accent) / Files /
Exported / Expires / Values; the selected row on accent-soft; an expiry within 7 days in the danger colour);
unreadable files as grey rows with their own "Delete" button (today's behaviour). Below: the selected-case
card ("CASE K4F7", file name 15/600, "Masked copy: MASKED-K4F7.docx in Documents › The MASK", "What it holds:
14 values: 2 companies, 2 people, …", the Keychain sentence). "Delete all" moves into the Delete… menu
(QToolButton with a menu: "Delete this case", "Delete all cases") — both still confirm via `confirm`.

## Delivery
Three tasks, each in its own worktree branch off design-v1, each with a plain review and at most two fix
rounds (R59 lean mode), merged into design-v1 by the controller after its gate:
- **D1 — shell and theme**: theme.py tokens and both palettes, appearance switching, typography, the
  stylesheet, `tools/make_art.py` + the PNG set (mask 112×88 and 224×176; document-with-check 64/128;
  key, archive box if used), the sidebar, toolbar, Settings window, crossfade, the home screen. Tests:
  structure (sidebar items, toolbar actions, Settings action role and shortcut, appearance switch, home
  screen widgets), screenshots under both appearances saved to the report folder for the owner.
- **D2 — review screen** (after D1 merges): the two-pane layout, the inspector, grouping, keyboard.
- **D3 — export sheet, restore, cases** (after D1 merges, parallel to D2).
Then one UI review of the whole design-v1 diff (opus), one fix wave, push; mac-v1 ← design-v1 only on the
owner's word after the smoke test.
Each implementer: Conventional Commits with its model's Co-Authored-By trailer; report to
notes/design/<task>-report.md with before/after screenshots (offscreen `grab()` at 1180×760, light and dark).
