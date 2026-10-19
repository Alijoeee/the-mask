# The MASK — handover from the cloud session (session 3) to the next local session, 2026-10-19

Written for the controller of the next session, which the owner runs locally in a new chat. Everything
below is on GitHub (github.com/Alijoeee/the-mask). Read in this order: this file, then `notes/RULINGS.md`
(every ruling R1–R124 in plain language, the owner's steps, the known limits), then `notes/sdd/progress.md`
(the ledger; the "Session 3" and "Design pass" sections at the end are what happened in the cloud), then
`notes/design/design-v1-brief.md` and the D1/D2/D3 reports.

## Where everything is (branches on origin)
- `main` — the docs-only commit 4253722. Untouched. Merging mac-v1 into it is the owner's decision.
- `mac-v1` at **4bbde49** — the finished Mac-phase build: all 25 build tasks, the final whole-branch review
  and its 20-item fix wave; 3,343 tests green incl. slow; pass marks 913/913, 320/320, 0 never-hide hits,
  28/28 round trip. THIS is what the owner builds and smoke-tests (`bash packaging/build_mac.sh`,
  RULINGS.md "The remaining local step", then the Wi-Fi-off smoke test and Task 26).
- `design-v1` at 4bbde49 — the design-pass integration branch (= mac-v1; nothing merged into it yet).
- `design-d1` at 6bbc73a — D1 (shell, theme, illustrations, icons, Settings window, home screen, R124
  contrast) COMPLETE, NOT YET REVIEWED. 12 commits on 4bbde49. Report: notes/design/d1-report.md;
  screenshots: notes/design/d1-shots/. Gate at its head: tests/ui 640 passed; full suite 3,614 at b106274.
- `design-d2` — D2 (review screen): see "State of D2/D3" below.
- `design-d3` at **a7934c6** — D3 (export sheet in four states, restore screen as cards, cases table and
  detail card, shared `cards.py`/`restore_parts.py`) COMPLETE, NOT YET REVIEWED. 4 commits on D1's 4146e37.
  Report: notes/design/d3-report.md (saved by the controller; section 10 = the exact wiring for the
  integration step and the DropZone adoption). Gate at its head: tests/ui 603, full suite 3,593 green.
- `task-22`, `task-24`, `task-25` — old checkpoint branches, all merged into mac-v1; delete at will.
- `controller-notes` — this folder: ledger, briefs, reports, RULINGS.md, the design brief, the mockup sources
  (`notes/design/mockups/`), the reports and screenshots of the design pass.
- The approved mockups as a page (private to the owner): https://claude.ai/artifact/PHVFzBRjUm7WQBEYnpbNof

## State of D2/D3 at the end of the cloud session
(Filled in at the end of the session — see the last lines of the ledger for the exact SHAs and status.)
D2 and D3 were branched from design-d1's commit 4146e37 (theme + art + icons) under ruling R123, so each
branch contains D1's first three commits and NOT D1's shell; D2 touched only review_screen.py and its
tests; D3 only export_dialog.py, restore_screen.py, cases_screen.py and their tests. Both are to be reviewed
and merged AFTER D1, in this order: merge design-v1 (with D1) into the task branch first, resolve (D3 must
take D1's DropZone constructor: `art`, `choose_text`, `shortcut_hint`, `status_layout`), gate, review, merge.

## The next steps, in order (lean method, R59/R118: sonnet implementers, plain reviews, ≤ 2 fix rounds)
1. **D1 review**: package `git diff 4bbde49..6bbc73a`; reviewer gets the brief, the mockups Main*.dc.html,
   d1-report.md, the screenshots, global-constraints.md, rulings R118–R124; checklist = the brief's "Window
   structure" and "Screen 1", the kept widget names, the Settings action (PreferencesRole, ⌘,), the
   crossfade flag, the contrast test, the art determinism test, Qt-modules test green. Fix rounds, then
   merge into design-v1, full gate (`uv run pytest -q`, ruff check src tests tools packaging, mypy src),
   push design-v1.
2. **D2 and D3**: as above (merge design-v1 in first). The wiring both need from the window (D1's surface on
   MainWindow: `show_screen(name)`, `set_title(title, caption, screen=)`, `primary_action` +
   `set_primary(screen, text, run, enabled)`, `refresh_chrome()`, `add_toolbar_widget(screen, widget)`) is
   done in an **integration step** after both merge: connect each screen's `title()`/`titleChanged` to
   `set_title`, its primary to `set_primary` (Review "Export…", Restore "Restore", Cases "New case" →
   `newCaseRequested` → show_screen("home")), the review's redline check box via `add_toolbar_widget`,
   remove the screens' own accent buttons, one README pass (D1's concern), regenerate screenshots with
   `tools/make_shots.py`. One commit, a plain review, merge.
3. **Whole-diff UI review** (opus) of `git diff mac-v1..design-v1`, one fix wave, scoped re-review — if the
   budget allows; otherwise the owner judges the real app and the next budget pays for it.
4. **D4** (ruling R122 items 1–2, detection; guard = the pass marks and the round trip) and **D5** (R122
   items 3–4, UI). D2 reserved the "Not sure — hide?" section for D4's output.
5. **After the owner's smoke test**: mac-v1 ← design-v1 on the owner's word, then the final build again.

## Environment on the Mac
`uv sync --locked`; `uv run pytest -q` (~7 min; the macOS-only tests run there too); screenshots offscreen
with `QT_QPA_PLATFORM=offscreen THEMASK_APPEARANCE=light|dark uv run python tools/make_shots.py <dir>`
(D1's tool; see d1-report.md); the Keychain is never touched by tests (fail backend fixture). The native
Mac look (unified toolbar, app-menu Settings, Qt.Tool window) could not be checked offscreen in the cloud —
the owner's first local run of design-v1 is where that is verified.

## Rules that bind the next controller (unchanged)
The design document is binding; rule on conflicts with `Ruling: <what> — <why> — <cost if wrong>` in the
ledger, numbering on from R125. Never merge main. Never touch the owner's Keychain. No real contracts in
tests. Push the working branch after every merge and the notes branch after every ledger change. Report in
plain language; the owner reads RULINGS.md. A user-side interruption of the controller's turn cancels its
background agents (session 3 lost two hours to that): after any interruption, check the live-agent list.
