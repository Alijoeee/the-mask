# Handover — The MASK, Mac phase (controller session 1 → session 2)

Written 2026-10-18 by the first controller session, at the owner's request to continue in a fresh chat.

## What this is

The MASK: an offline macOS (later Windows) desktop app that swaps confidential values in contracts for `[TYPE_N]` placeholders before the document goes to an AI tool, and restores them afterwards. Owner: the user (GitHub `Alijoeee`). Design: `docs/superpowers/specs/2026-10-17-the-mask-design.md` (binding authority). Plan: `docs/superpowers/plans/2026-10-17-the-mask-mac-v1.md` (26 tasks). Execution method chosen by the owner: **subagent-driven development** (`superpowers:subagent-driven-development`), with the owner's standing instruction to **run independent tasks in parallel**.

## Where everything lives

- Repo `/Users/alijoeee/Developer/the-mask`, branch `mac-v1`; `main` holds only the docs commit. Remote: private GitHub `https://github.com/Alijoeee/the-mask` — **push `mac-v1` after every merge** (owner's instruction).
- Ledger: `.superpowers/sdd/2026-10-17-the-mask-mac-v1/progress.md` — every task's state, every `Ruling:` (R1–R29 so far), deferred minors, notes "for Task N dispatch". **Read it before dispatching anything.** Tasks with a `complete` line are done; never re-dispatch them.
- Briefs `task-N-brief.md`, reports `task-N-report.md`, review packages `review-<base>..<head>.diff`, `global-constraints.md` (hand to every reviewer), `implementer-boilerplate.md` (hand to every implementer) — all in the same workspace folder.
- Worktrees: `/Users/alijoeee/Developer/the-mask-worktrees/task-N` (branch `task-N`), one per parallel implementer; create from the current `mac-v1` head with `git worktree add -b task-N ../the-mask-worktrees/task-N mac-v1`; after merge: `git worktree remove --force` + `git branch -d`.
- Progress cards for the owner's live panel (İşler mod): write `/private/tmp/claude-501/<this-session's scratchpad>/ilerleme/*.json` — the mod is per session; the new session must install its own copy (see memory note `progress-mod-isler`: copy `~/.claude/dev-mods/<old-session-id>/isler/` to the new session id folder and set `KOK` to the new scratchpad root), then write `the-mask-build.json` for the controller and tell each subagent to write `task-N.json` with `ad` = the Agent description.

## Process that worked (keep it)

1. For each task: `bash <skill>/scripts/task-brief PLAN N` (briefs 2–26 already exist), dispatch an implementer (Agent tool, background, `model` set explicitly: `sonnet` for mechanical/well-specified work, `opus` for Word-XML surgery, detection and UI integration), prompt = one line of context + brief path + boilerplate path + worktree instructions + "controller decisions" (the ledger's notes for that task) + progress card + report path.
2. On DONE: `bash <skill>/scripts/review-package PLAN BASE HEAD` (BASE = the branch point), dispatch a reviewer (task-reviewer template; `opus` for leak-critical diffs, `sonnet` otherwise) with brief, report, package, `global-constraints.md` and the task's controller decisions.
3. Findings: Important/Critical → resume the implementer via SendMessage with findings verbatim (rounds 1–3), scoped re-review (re-review template, `sonnet`); minors → ledger as deferred; conflicts with the plan → a `Ruling:` line in the ledger (what / why / cost if wrong).
4. Clean → merge into `mac-v1` (`--ff-only` when possible, else `--no-edit` merge), run `uv run pytest -q && uv run ruff check src tests tools && uv run mypy src` on `mac-v1`, remove the worktree, **push**, ledger `Task N: complete (...)`.
5. Commit trailer for commits the controller makes: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; subagents' own model trailers (Opus/Sonnet) were accepted as accurate attribution.
6. The owner's usage limit (Max plan, 5-hour window) interrupted agents three times; the harness saves their work — resume them with SendMessage after the reset, never restart.

## State at handover (update the line below when the three in-flight tasks land)

- Merged on `mac-v1` at 109cbf8 and pushed: Tasks 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 17 (12 of 26). Full suite green (uv run pytest -q), ruff and mypy clean. Nothing in flight; no worktrees left.
- Start with **Task 8** (its dependencies 6 and 7 are merged), then T9 ‖ T14 (T14 needs 10–13 ✓).
- Remaining waves (dependency order, from the ledger): T8 → T9 ‖ T14 → T15 → T16 ‖ T18 ‖ T19 → T20 ‖ T24 → T21 ‖ T22 → T23 → T25 → T26 (owner's manual round trip).

## Rulings that shape the remaining tasks (full text in the ledger)

- R2: `load_sources` prepares packages (accept/reject + clean), text is extracted from the prepared copies, export masks those same copies.
- R3/R14/R19/R26: leak check signature takes `entries`; scans text-bearing content incl. attribute values and %-decoded instructions/targets; digit-only values on digit boundaries; values under 4 normalised chars reported as "not checkable"; raw-bytes scan only for ≥6-char non-digit values.
- R10: case files have no plaintext header; `CaseStore.list()` decrypts.
- R12/R13 (engine), R21/R25 (rules), R16/R17/R22/R24/R28/R29 (cleaner), R23/R27 (masker) — already implemented in merged or in-flight tasks.
- Notes for Task 8: call `find_defined_terms` itself; names beat terms (a defined term equal to a company's variant must not suppress the sweep); filter blank variants; spaCy `max_length` — analyse per file.
- Notes for Task 15: SourceDoc carries `pkg_after`/`pkg_before`; OSError from open/save must be caught.
- Notes for Task 16: paragraph grouping threshold = 2 × median intra-paragraph line gap (corpus PDFs have 9 pt paragraph gaps, 3 pt line gaps); headings ≥ 12 pt bold.
- Notes for Task 18: strip the banner before `plan_restore`; convert "\t"/"\n" in restored values to `w:tab`/`w:br`; identifier-like tokens (`ID-4711`) match as altered placeholders.
- Notes for Task 19: keep the `presidio-analyzer` logger at WARNING; remove the README's `python -m themask` note once `__main__` exists.
- Notes for Task 20: `KeyStoreError(MaskError)` for keyring failures; `CaseStore._scan` must also catch OSError; autouse fixture installing `keyring.backends.fail.Keyring` in tests; startup `purge_expired` must survive key-store errors.
- Notes for Task 23: Cases screen shows `case_store.unreadable` and offers deletion; "Add file to this case" calls `open_files(paths, None, case_id)`.
- Notes for Task 24: the deferred detection minors (clause/statute numbers as AMOUNT/ID, bracketed durations, "assume" vs "sum", bad-checksum IBAN, departments as PERSON, KG/Corporation/Limited guards, address span past the country, int() on ≥4,301 digits, etc.) are tuned there; exclude `existing_placeholders` documents from the final round-trip assertion.
- Notes for Task 25: smoke test with supply-05 (image) and supply-02 (comments), not supply-01; the owner opens a file in Word by hand; Wi-Fi-off test is the owner's.

## Owner preferences

- Parallel execution of independent tasks; keep the live progress panel updated; continue overnight without check-ins; Remote Control on; GitHub push after every merge; plain-language status when asked; cost awareness (Max plan limits — resume agents after a limit reset).
