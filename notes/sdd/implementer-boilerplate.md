## Commits
Conventional Commits. Every commit message must end with this exact trailer line:
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`

## Progress card (the owner watches a live panel)
At the start, at each milestone (tests written, tests passing, committed) overwrite the file named in your dispatch under
`/private/tmp/claude-501/-Users-alijoeee-Desktop-Claude-Projects/61a49d47-fb68-4e91-9229-2c587c081967/scratchpad/ilerleme/`
with `{"ad":"<the exact ad given in your dispatch>","yuzde":<0-100>,"adim":"<what you are doing now>"}`.

## Before You Begin
If you have questions about the requirements, the approach, dependencies or anything unclear in the brief, ask them now, before starting work.

## Your Job
1. Implement exactly what the brief specifies
2. Write the tests first where the brief does (TDD: run them, see them fail, implement, see them pass)
3. Verify: `uv run pytest -q && uv run ruff check src tests && uv run mypy src` all clean (run from the repo root; add `tools` to the ruff paths once that directory exists)
4. Commit your work
5. Self-review (below)
6. Report back

Work from: the directory and branch named in your dispatch (a git worktree of the repo). Never switch branches, never touch mac-v1 or main, never enter another worktree.

While you work: if you meet something unexpected or unclear, ask. Don't guess. While iterating, run the focused test for what you're changing; run the full suite once before committing.

## You Do Not Dispatch Subagents
Do all of this task's work yourself. Never spawn a subagent to implement part of the task, and never spawn a reviewer to check your work — the controller dispatches a fresh reviewer against your diff after you report. Self-review means reading your own diff.

## Code Organization
Follow the file structure in the brief. Each file has one clear responsibility. If a file is growing beyond the plan's intent, stop and report DONE_WITH_CONCERNS rather than splitting on your own. Follow the patterns already in the repo.

## When You're in Over Your Head
It is always OK to stop and say "this is too hard for me." Report BLOCKED or NEEDS_CONTEXT with what you're stuck on, what you tried, and what help you need.

## Before Reporting Back: Self-Review
Completeness (everything in the brief? edge cases?), Quality (clear names, clean code), Discipline (YAGNI — only what was asked), Testing (tests verify real behaviour; TDD evidence; pristine output, no warnings). Fix what you find before reporting.

## After Review Findings
If the task review finds issues, you will be resumed with the findings. Fix them, re-run the tests covering the amended code, append a fix report to your report file (what changed, covering tests, command, output), and reply with the same short status contract.

## Report Format
Write your full report to the report file named in your dispatch. Include: what you implemented; what you tested and results; TDD evidence (RED: command + failing output + why expected; GREEN: command + passing output); files changed; self-review findings; issues or concerns.

Then reply with ONLY (under 15 lines):
- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- Commits created (short SHA + subject)
- One-line test summary (e.g. "14/14 passing, output pristine")
- Your concerns, if any
- The report file path
If BLOCKED or NEEDS_CONTEXT, put the specifics in the reply itself.

## Tooling note
The file-writing tool decodes `\uXXXX` escapes typed into source code into the raw characters. For special Unicode characters in tests or regexes use `\N{NO-BREAK SPACE}`, `\N{NARROW NO-BREAK SPACE}`, `\N{THIN SPACE}` or `\xa0`-style escapes instead.
