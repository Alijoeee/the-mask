# Task 18 report: Restore (text half, ruling R75)

**Status:** DONE_WITH_CONCERNS (text half). The Word half (docx_restore.py, simulate_ai, the masked_case fixture, test_docx_restore.py) waits for Task 15, as R75 rules.
**Branch / worktree:** task-18 at /Users/alijoeee/Developer/the-mask-worktrees/task-18, from mac-v1 at 7548a97.
**Commit:** 16c9c3d feat: restore placeholders into pasted text with altered-form confirmation

## What I implemented

- `src/themask/restore/report.py`: `RestoreItem(match, entry, status)` and `RestoreReport(restored, altered_restored, needs_check, unknown, banner_removed)` with `summary()` = `f"{restored} placeholders restored, {len(needs_check)} need your check."`. Both are plain `@dataclass` as the brief says. `RestoreStatus = Literal["exact", "altered", "unknown"]` is a type alias for the status.
- `src/themask/restore/matcher.py`:
  - `plan_restore(text, case)`: one item per `find_placeholders` match, in text order (decision 1). In the key and exact gives "exact"; in the key and altered gives "altered"; not in the key, in any form, gives "unknown" with entry None. The lookup uses the match's canonical `placeholder`. Matches on a banner or instruction line are not planned.
  - `suggest_cases(text, cases)`: sorted by (number of DISTINCT canonical placeholders in the text that the case's key holds, created_at), newest first. Python's sort is stable, so equal keys keep their input order. Cases that hold none still come back, last and newest first (decision 5).
  - `banner_spans(text)`: an extra public helper beyond the brief. Both `plan_restore` and `restore_text` need it, and text.py imports matcher.py, so it lives here. It returns the (start, end) span of each line that, after collapsing whitespace (`" ".join(line.split())`, which also trims), equals BANNER_TEXT or AI_INSTRUCTION (decision 3, R76). Each span also takes ONE following blank (whitespace-only) line. Lines come from `str.splitlines(keepends=True)`, so `\n`, `\r\n`, `\r`, U+2028/U+2029, `\v` and `\f` all end a line, and the pieces join back into the exact original text. The Word half can reuse it for each paragraph.
- `src/themask/restore/text.py`: `restore_text(text, case, confirm_altered)` (decisions 2 and 4).
  - Exact items are always replaced by `entry.value`. Altered items are replaced only when `confirm_altered` is set; otherwise they stay as written and go to `needs_check`.
  - Unknown items stay as written. `unknown` lists each raw text once, in order of first appearance (`dict.fromkeys`).
  - The banner/instruction spans are deleted. All edits are applied right-to-left on the original offsets. The replaced span is the match's whole span, so `**[AMOUNT_1]**` loses its asterisks.
  - `restored` counts exact + confirmed altered; `altered_restored` counts the confirmed altered ones; `banner_removed` is set when any span was removed.
  - No two edits overlap: matches never overlap each other, and any match that overlaps a banner span is left out of the plan.
- `src/themask/restore/__init__.py`: a package docstring only (same pattern as docx/, detect/, pdf/).
- Tests: `tests/fixtures/restore.py` holds the brief's `CASE` and `NOW` as importable constants (same pattern as `tests.fixtures.leak.MASKED_ENTRIES`); the masked_case fixture will join it later. `tests/restore/__init__.py` (empty), `tests/restore/test_matcher.py` (10 tests), `tests/restore/test_text.py` (12 tests, 28 cases).

No docx imports, no Qt, no logging. The only dependencies are themask.model, themask.placeholders and themask.instruction (decision 7).

## Interpretations (please confirm)

1. **suggest_cases ignores the banner and instruction lines, as plan_restore does.** Otherwise the banner's [COMPANY_1] example, which nearly every key holds, would put a case level with the one the text comes from, and the newer case would win on age. This is pinned by `test_the_banners_example_does_not_count_for_a_case`. If you want the literal reading (every match in the text counts), it is a one-word change (`_placeholders` to `find_placeholders`) plus dropping that test.
2. `unknown` is deduplicated by raw text, so "[PERSON_9]" and "person_9" are listed separately (decision 2: "their raw text is listed once each").
3. `needs_check` items keep their match offsets in the INPUT text (banner included), not in the output.

## Tests and results

- The brief's four for this half: `test_text_exact_and_altered` (I also assert decision 4's "2 placeholders restored, 1 need your check."), `test_banner_removed`, `test_suggest_cases`, `test_template_brackets_untouched`.
- Decision 8 extras:
  - unknown listed once though it appears twice;
  - placeholders that touch: three cases, including `[AMOUNT_1][PERSON_1]**[COMPANY_1]**.` confirmed and `[COMPANY_1][PERSON_1]**[AMOUNT_1]**` unconfirmed;
  - each spec 8.7 altered form (`PERSON_1`, `[PERSON 1]`, `[person_1]`, `\[PERSON_1\]`, `**[PERSON_1]**`), listed with its entry until confirmed and restored once confirmed;
  - the instruction line removed (R76), alone and together with the banner;
  - the R44 corollary: `company_2` next to a real `[COMPANY_2]` is planned "altered" and left with confirm_altered=False, while the exact one is restored;
  - `ID-4711` planned "unknown" and left even when confirmed;
  - suggest_cases tie broken by created_at, cases holding none last and newest first, newest first when the text has no placeholders, distinct counting across exact and altered forms.
- Decision 3 edges: extra and no-break spaces, Windows line breaks, banner mid-text (only one blank line removed), banner without a following blank line, banner as the last line.
- Guards: an empty text and plain prose ("Company 1", "[Name]") change nothing and report zeros.
- Results: `uv run pytest tests/restore -q` gave 38 passed in 0.08s. Full suite: `uv run pytest -q` gave **2501 passed in 50.03s** (baseline 2463 + 38), no warnings. `uv run ruff check src tests tools`: All checks passed. `uv run ruff format --check` on the new files: 8 files already formatted. `uv run mypy src`: Success, no issues in 36 source files.

## TDD evidence

- **RED 1** (tests written, no code): `uv run pytest tests/restore -q` gave `ModuleNotFoundError: No module named 'themask.restore'`, with 2 errors during collection. Expected: the package did not exist.
- **RED 2** (report dataclasses plus stubs: plan_restore returns [], suggest_cases returns the input order, restore_text returns the text unchanged with an empty report): **36 failed, 3 passed**, all failures on assertions. Two of the passes were expected (`test_nothing_to_plan` and `test_nothing_to_restore` guard against over-matching). The third, an offset test, passed vacuously on an empty plan, so I removed it. The banner test already pins offsets in the one case where they could drift.
- **GREEN:** `uv run pytest tests/restore -q` gave 38 passed. The full suite and all checks are as above.
- **Mutation check:** I applied 22 deliberate bugs one at a time and ran the restore tests after each; **22/22 caught**, and the sources were restored after each run (38 pass). The bugs:
  - banner matches planned;
  - no whitespace collapse;
  - blank line not taken;
  - every blank line taken;
  - instruction not treated as an own line;
  - altered planned as exact;
  - key looked up by raw text;
  - occurrences counted instead of distinct placeholders;
  - tie given to the older case;
  - cases holding none dropped;
  - banner counted for a case;
  - altered replaced unasked;
  - altered never replaced;
  - unknown not deduplicated;
  - unknown sorted instead of kept in order;
  - edits applied left to right;
  - altered_restored not counted;
  - restored counting exact only;
  - banner_removed never set;
  - banner lines kept in the text;
  - confirmed items still listed;
  - summary counting unknown too.

## Files changed (all new)

- /Users/alijoeee/Developer/the-mask-worktrees/task-18/src/themask/restore/__init__.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/src/themask/restore/report.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/src/themask/restore/matcher.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/src/themask/restore/text.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/tests/fixtures/restore.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/tests/restore/__init__.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/tests/restore/test_matcher.py
- /Users/alijoeee/Developer/the-mask-worktrees/task-18/tests/restore/test_text.py

## Self-review

- Fixed before committing:
  - two unclear comments in matcher.py ("touches" became "overlaps");
  - short parametrize ids for the banner cases (the ids had been the whole banner text);
  - removed the vacuous offset test.
- Accepted:
  - `restore_text` calls `banner_spans` and then `plan_restore`, which calls it again. That is one extra linear pass over the lines, kept because plan_restore's signature is fixed and the code stays plain.
  - Right-to-left slicing (decision 2) is O(text length x edits). Measured: 64 KB with 2,100 placeholders takes 14 ms; 322 KB with 10,500 takes 151 ms; 920 KB with 30,000 takes 1.06 s. That is fine for pasted chat text, and the Word half works per paragraph.
- Probed and safe:
  - a value that itself looks like a placeholder ("PERSON_1 Holdings") is never re-scanned, because restore makes one pass;
  - a banner whose [COMPANY_1] the AI escaped is not removed, but its `\[COMPANY_1\]` goes to needs_check, so it is never swapped silently;
  - a banner followed by U+2029 paragraph separators is removed.

## Concerns / questions for the controller

1. **A banner the AI rewrote stays (decision 3 is strict equality).** The masked file's banner is italic, so a markdown copy of it reads `*Confidential values … Keep them unchanged.*`. A blockquote (`> …`), a leading BOM or escaped brackets `\[COMPANY_1\]` also fail the comparison. In those cases the line is not removed, and its exact [COMPANY_1] is restored into the sentence ("…placeholders such as Acme Supplies Ltd. Keep them unchanged.") and counted in `restored`. It is never a wrong value, but the note stays and the count is one too high. This affects pasted text only, since Word paragraph text carries no markdown. Possible fix if wanted: compare after stripping a BOM, a leading `> ` and one matching pair of `*`/`_`/`**`/`__` round the line, with each placeholder written in its canonical form. I did not build it because decision 3 says "equals".
2. **A lone bracket is eaten on confirm.** "[Buyer, PERSON_1]" gives raw "PERSON_1]". Decision 2 replaces the whole span, so a confirmed restore gives "[Buyer, John Smith", and the closing bracket that belonged to the surrounding text is gone. This happens only after the owner's confirming click, and needs_check shows "PERSON_1]". The AI might equally have dropped one bracket of the placeholder, so I left it as decided.
3. **A key holding one placeholder twice:** the last entry wins silently (plan_restore builds a dict). `ReviewState.key_entries()` gives one entry per group, so the pipeline should never produce this, but nothing in Case or CaseStore enforces it. A guard (for example, treating such a placeholder as needs-check) would need a ruling; I flag it rather than invent a status.
4. **Commit trailer:** I used `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, the attribution this session requires. Previous Opus implementer commits use the same trailer, and the global constraint ties the trailer to "the attribution trailer this session requires". The boilerplate's Fable 5.1 line is the controller's own trailer.

## Next (after Task 15 merges)

Merge mac-v1 into task-18, then build the Word half:
- `restore_docx` over TEXT_PARTS + word/comments.xml through `replace_in_paragraph`, with values containing \t or \n turned into w:tab/w:br (handover note);
- the banner paragraph and the empty paragraph after it removed;
- per-paragraph planning via `plan_restore`/`banner_spans` and one merged report;
- `<stem> – restored.docx`, adding (2), (3) as needed;
- `simulate_ai` in tests/helpers.py, `masked_case` in tests/fixtures/restore.py, and the brief's three docx tests.

---

## Fix report 1: rulings R78 and R79 (commit 05270ef)

The controller confirmed two choices: suggest_cases ignores banner and instruction lines, and `banner_spans()` is public. Concern 3 (a key holding one placeholder twice) is deferred to the final review.

### What changed

- **R78** (src/themask/restore/matcher.py):
  - `banner_spans` now compares `textnorm.normalize(line)` with `normalize(BANNER_TEXT)` / `normalize(AI_INSTRUCTION)`, which keeps letters and digits only, case-folded and NFKC. The comparison used to be on whitespace-collapsed text.
  - A banner or instruction the AI rewrote is therefore still removed: in italics, as a `> ` quote, after a BOM, with escaped brackets, or with changed spacing.
  - A line with any word of its own on it (for example "Note: <banner>") stays, and its placeholders are restored like any others.
  - The "line plus one following blank (whitespace-only) line" rule is unchanged.
- **R79** (matcher.py, text.py):
  - New public `restore_span(match) -> (start, end)`: the stretch a restore replaces. It is the whole token unless the token has a bracket on one side only. Then it is only the type name through the number, so the one-sided bracket stays, together with its escape, its width, the spaces between it and the name, and any markdown markers round both. (Example: "[Buyer, **PERSON_1]**" becomes "[Buyer, **John Smith]**".)
  - It reads the token's parts with the grammar's own `_TOKEN_RE` (`fullmatch` on `match.raw`; open/close/type/number groups) instead of re-encoding the bracket forms. Restorer.py importing the reader's `_CHARACTERS` is the accepted precedent. If `fullmatch` somehow failed, it falls back to the whole span; there are no asserts in src.
  - `restore_text` replaces `restore_span(item.match)` instead of the match's whole span. The Word half will use the same helper.
  - The match itself is unchanged: needs_check still shows the token as matched ("PERSON_1]").

### Covering tests (22 new cases)

- tests/restore/test_text.py:
  - `test_a_banner_the_ai_rewrote_is_still_removed`: italic, quoted, byte-order-mark, escaped-brackets and spacing variants, plus the instruction quoted in italics with escaped brackets after a BOM;
  - `test_a_line_with_more_than_the_banner_on_it_stays`;
  - `test_a_bracket_on_one_side_only_belongs_to_the_text_round_it`: closing "[Buyer, PERSON_1]" gives "[Buyer, John Smith]"; opening "[PERSON_1, the Buyer]" gives "[John Smith, the Buyer]"; also escaped, spaced, full-width and bold forms. Each case checks the unconfirmed run lists the raw token and changes nothing.
- tests/restore/test_matcher.py:
  - `test_a_banner_the_ai_rewrote_is_not_planned`;
  - `test_restore_span`: whole span for balanced, bracketless, escaped and bold tokens; name and number only for one-sided ones.

### Commands and output

- RED:
  - `uv run pytest tests/restore -q`: test_matcher failed at import (`cannot import name 'restore_span'`).
  - `uv run pytest tests/restore/test_text.py -q`: **12 failed, 29 passed**. These are the 6 R78 cases (for example, the italic banner was not removed) and the 6 R79 cases (for example, `'For [Buyer, John Smith now.' != 'For [Buyer, John Smith] now.'`). The "line with more on it stays" guard passed before and after the change, as it should.
- GREEN:
  - `uv run pytest tests/restore -q`: **60 passed**.
  - `uv run pytest -q`: **2523 passed in 50.63s** (2501 + 22), no warnings.
  - `uv run ruff check src tests tools`: All checks passed. `ruff format --check`: 8 files already formatted. `uv run mypy src`: no issues in 36 source files.
- Mutation round 2: **29/29 caught**.
  - The new R78 mutations: back to the strict compare; substring instead of whole line; case not folded.
  - The new R79 mutations: always the whole span; always name and number only; opening bracket not kept; closing bracket not kept; spaces next to the bracket replaced; restore_span unused.
  - The earlier mutations whose targets still exist all still fail the tests.
  - "Confirmed items still listed" was re-run on its new target line and caught. The old "no whitespace collapse" mutation is superseded by "back to the strict compare".

### Residuals (probed; cosmetic, never a wrong value)

- In a quoted banner followed by a quote's empty line (`>`), that `>` line stays: under the kept rule, blank means whitespace-only.
- A banner written as a numbered list item ("1. <banner>") stays, because the "1" is a word of its own, and its [COMPANY_1] is restored into the sentence.
- R79's flip side: when the AI dropped the placeholder's OWN opening bracket ("Dear PERSON_1], thanks"), a confirmed restore leaves a stray "]" ("Dear John Smith], thanks"). The owner sees the token "PERSON_1]" before confirming.

---

## Word half (commit 4420dd9)

Branch task-18. mac-v1 was merged into it twice: at 66b92b2 (Task 15) and at 90b9fca (Tasks 20+21). The second merge landed while I was working, around the account-limit interruption. All uncommitted edits survived; I checked them and verified the state afresh. That merge only touched `export.py` (a `.doc` message), which does not affect this work.

### What I implemented

- **src/themask/restore/docx_restore.py**: `restore_docx(src, case, confirm_altered, out_dir=None) -> (Path, RestoreReport)`.
  - The file is read into memory with `DocxPackage.open`. `src` is never written to, and its bytes are unchanged (tested).
  - It walks every `w:p` of `pkg.TEXT_PARTS` plus the comment parts. Comment parts are found the way the cleaner finds them: by name, content type or relationship, via the cleaner's private `_comment_parts`, the same private-import precedent as `_CHARACTERS`. Only `word/comments.xml` holds paragraphs.
  - Each paragraph is planned on its `paragraph_nodes(p, "accepted")` text with the text half's rules (statuses, confirm_altered, R79 brackets, R78 banner lines), with one report across all parts. Unknown placeholders are listed once for the whole file.
  - Values are written through `replace_in_paragraph`, so a value takes the formatting of the placeholder's first run, also across split runs.
  - **Banner / instruction** (decision 1):
    - A paragraph directly in `w:body` whose whole text is an own line (R78 normalised comparison) has the line cut and is then deleted, together with the paragraph right after it when that one is empty (only pPr and empty runs).
    - Where a container must keep a paragraph (table cell, header or footer, note, comment, text box), the paragraph is emptied, not deleted.
    - A paragraph that still holds anything after the cut (for example, a picture) is kept.
    - A paragraph whose pPr ends a section (`w:sectPr`) is never deleted, as either the banner or its follower; this is a safety addition.
    - A banner line inside a longer paragraph (after a soft break) is cut out of it.
  - **Decision 3:** placeholders that overlap a `w:instrText` node are skipped and not reported. Link targets (rels) and bookmark names (attributes) are outside the text map. All three are documented in the module docstring.
  - **Output:** `"<stem> – restored.docx"` (U+2013) in `out_dir`, created when missing as export does, or else next to `src`. If that name is taken, " (2)", " (3)" … are tried.
    - `_new_file` reserves the name with an exclusive create (`"xb"`), then `DocxPackage.save` writes into it; the file is unlinked if saving fails.
    - It does not reuse export's `_write_new`, because importing `themask.export` would make restore depend on detection, the leak check and PDF modules. The naming rule is the same.
  - **A text box's `mc:Fallback` copy** (Word writes one for old readers) is restored the same way, through a second `TextRestorer` whose report is discarded, so it is counted once. Masked files have no fallbacks (R16), but a file the AI saves through Word gets them back.
- **src/themask/docx/restorer.py** (decision 2): a keyword-only opt-in `breaks=False` on `replace_in_paragraph`.
  - With it, each "\t"/"\n" of a new text becomes a `w:tab`/`w:br` in the same run, and the text after it becomes a new node of the same kind. The new nodes join the `edited` set, so empty ones are deleted and edge spaces are preserved.
  - Two values in one node are handled; replacements still run right to left. The default is unchanged, and the masker's 56 tests pass.
- **src/themask/restore/text.py:** the per-text rules moved into `TextRestorer(case, confirm_altered)` with `.edits(text, keep=()) -> [(start, end, new)]` and a running `.report`. `restore_text` now uses it, with unchanged behaviour (all 60 text and matcher tests pass), and `restore_docx` uses it per paragraph.
- **tests/helpers.py `simulate_ai(masked, out) -> Path`** (decision 4). It is deterministic: byte-identical output, fixed zip dates. Each change happens only where its placeholder exists, so Task 24 can run it on every corpus file. The changes:
  - the first [PERSON_1] becomes "[PERSON 1]", the only altered form (Task 23 expects `altered_list.count() == 1`);
  - every [AMOUNT_1] gets a bold run of its own;
  - the first [COMPANY_1] is split across two runs. The first half is in italics and its run carries `w:rsidR=SPLIT_RSID`, which is how Word marks the parts of a split run.
  - a "[PERSON_9]" note paragraph is added at the end of the body, with a comment on it holding [COMPANY_1]. If the file has no comments, `word/comments.xml`, its relationship and its Override are added.
  - the banner paragraph is copied once more, just before the note.
  - It uses zipfile and lxml directly (like `plant`), not the code under test.
- **tests/fixtures/restore.py `masked_case`** (module scope): supply-01 reviewed with `tests.helpers.reviewed` and exported with `export_case` into a session temp folder. It uses its own `UserLists([], [])` and sets `THEMASK_DATA_DIR` to a temp folder during the export, because a module fixture is set up before the per-test data-dir fixture.

### Tests (tests/restore/test_docx_restore.py, 18 functions, 21 cases)

- The brief's `test_docx_roundtrip`, `test_docx_formatting_kept` and `test_never_overwrites`.
- The decision 5 extras:
  - headers, footnotes and comments restored, with an unknown placeholder listed once and a summary of "5 placeholders restored, 0 need your check.";
  - the split placeholder comes back in its first run: the value sits in the `SPLIT_RSID` run, the run's properties equal the first half's (italics included), and no "ANY_1]" is left anywhere;
  - comments restored (the brief's raw check, and the comment text);
  - nothing restored inside the banner before it is deleted (banner, instruction and rewritten banner: `restored == 1`, nothing listed, and only one of the two empty paragraphs goes);
  - " (2)" naming;
  - src bytes unchanged, and the output goes next to src;
  - the round-trip summary, worked out from the masked file: M exact key placeholders plus one comment gives "M+1 restored, 0" when confirmed and "M restored, 1" when not (needs_check holds "[PERSON 1]");
  - a file with no placeholders comes back unchanged (same part names, every part's canonical XML equal) with "0 placeholders restored, 0 need your check.".
- Decision 2: "Line 1\nLine 2" and "Name:\tValue" in one run give the children [t, br, t, tab, t].
- Decision 3: a HYPERLINK instruction keeps "mailto:[PERSON_1]" and only the result is restored.
- Further cases:
  - the banner emptied (not deleted) in a header and when it sits beside a picture;
  - a section-ending paragraph never deleted;
  - a banner line cut out of a longer paragraph;
  - a text box and its fallback both restored and counted once;
  - confirm_altered and R79 in Word ("[Buyer, John Smith]").

### Commands and output

- RED 1: `uv run pytest tests/restore/test_docx_restore.py -q` failed with `ModuleNotFoundError: No module named 'themask.restore.docx_restore'`.
- RED 2 (a stub that copies the file and reports nothing): **18 failed, 2 passed**. The two passes were the guards that should pass trivially: the AI file untouched, and a file without placeholders coming back unchanged.
- GREEN: `uv run pytest tests/restore -q` gives 81 passed in about 6 s; the one export per module takes about 1 s once the session engine and corpus exist.
- Full suite: **2797 passed in 82.37s** (2776 after the second merge, plus 21), no warnings. `uv run ruff check src tests tools`: All checks passed. `ruff format --check` on the 12 touched files: clean. `uv run mypy src`: no issues in 48 source files.
- Mutation rounds:
  - **Word half: 20/20 caught.** The mutations: comments not walked; fallback counted; fallback skipped; field instructions restored; breaks written as characters; banner paragraph never deleted; empty follower kept; any follower deleted; deleted outside the body; deleted beside a picture; written over an existing file; out_dir ignored; written next to the working folder; fallback report returned; break tail on the wrong node; marks before the text; tab and break swapped; `keep` ignored; unknown not deduplicated across texts; banner flag reset per text.
  - **Refactored text path: 10/10 caught.**
  - **Section guard: caught.**
  - One mutation ("next to the working folder") wrote four restored files into the worktree root during its run. They were made-up corpus data, untracked, and I removed them; the worktree is clean.

### Concerns / questions for the controller

1. **Tracked changes in the AI's file.** Paragraphs are read in the accepted view, so placeholders inside the AI's tracked deletions (`w:del`, `w:moveFrom`) are left as placeholders. Insertions and unchanged text are restored. If the owner later rejects such a deletion in Word, "[PERSON_1]"-style text reappears there; it is never a wrong value. This matters when an AI edits with Track Changes on (Copilot in Word).
   - A fix would be a second pass per paragraph in the rejected view, limited to rejected-only nodes and not double-reported: about 25 lines plus tests.
   - Not built, since no decision covered it. Please rule.
2. **Decision 3's limit, as documented:** a HYPERLINK field or link whose address holds a placeholder keeps it, while the shown text is restored. Masked files have their link addresses masked, so this affects AI files that keep such fields.
3. Private imports: `_comment_parts` from the cleaner and `_TOKEN_RE` from placeholders, following the accepted `_CHARACTERS` precedent.
4. For Word files, `needs_check` items carry offsets relative to their own paragraph's text. The UI uses the raw token and the entry, so this is harmless; noted for Task 23.
5. Still deferred from earlier: a key holding one placeholder twice, for the final review.

---

## Fix report 2: ruling R88, the AI's tracked changes (commit 773878f)

Before starting I ran `git merge mac-v1 --no-edit`, giving 9c632e5 (mac-v1 at 6bec7ea: Task 19's logging test). It changed nothing restore uses.

### What changed

- **src/themask/restore/docx_restore.py:**
  - **Insertions (`w:ins`, `w:moveTo`) were already restored**, since they are part of the accepted view the first pass reads. The new test confirms it: before the change, its accepted-view assertion passed and only the rejected view failed.
  - **New second pass `_restore_taken_out`.** It runs only for a paragraph that holds `w:del` or `w:moveFrom`. It reads the paragraph in the rejected view after the first pass.
  - **It plans only text that the rejected view alone holds:** `keep` covers every node that is also in the accepted view, plus field instructions (`w:delInstrText` included). It writes through `replace_in_paragraph(p, "rejected", …, breaks=True)`.
  - **Deleted and moved-away placeholders** get the same statuses, the same confirm_altered rule, R79 brackets and the deleted run's own formatting. They are counted in the same report.
  - **Shared text is planned and reported once.** An unchanged unconfirmed altered placeholder is not listed twice.
  - **Module docstring:** the earlier "tracked deletions left as they are" limit is replaced by the R88 behaviour.
- **src/themask/restore/text.py:** `TextRestorer.edits` now leaves a banner line that overlaps `keep` as it is: not cut and not flagged, and its example placeholders are still not planned. This keeps the second pass from ever changing text that both views share.
  - Example: the AI tracked-changed only the banner's example, deleting `[COMPANY_1]` and inserting `[COMPANY_2]`. In the rejected view the line reads as the banner again, but it is mostly shared text, so it stays whole.
  - A banner that the AI deleted in full lies entirely inside the deletion, so it is cut out of the deletion and `banner_removed` is set. Rejecting the deletion therefore cannot bring back a note with a real value in it.

### Covering tests (7 new cases in tests/restore/test_docx_restore.py)

- The ruling's test, `test_tracked_changes_of_the_ai_are_restored_in_both_views`:
  - The setup is a deleted bold run holding "[PERSON_1]" and an inserted italic run holding "[COMPANY_1]".
  - Accepted view: "Signed by Acme Supplies Ltd today." Rejected view: "Signed by John Smith today."
  - The delText run keeps `w:b`; the inserted run keeps `w:i`.
  - The summary is "2 placeholders restored, 0 need your check."
- `test_a_move_is_restored_where_it_went_and_where_it_came_from`: moveFrom and moveTo are both restored, and restored == 2.
- `test_a_deletion_follows_the_same_rules_and_nothing_is_reported_twice[False/True]`. The setup: unchanged "person_1 met ", then a deletion holding "[PERSON_1], person_1 and [PERSON_9]".
  - Unconfirmed: restored 1, needs_check lists ["person_1", "person_1"] (the unchanged one once, the deleted one once), unknown ["[PERSON_9]"].
  - Confirmed: restored 3, altered 2.
- `test_a_banner_the_ai_deleted_goes_and_is_not_restored`: the banner is cut out of the deletion, banner_removed is set, and restored == 1.
- `test_restoring_what_the_ai_took_out_never_changes_the_text_both_views_share`: the case where the AI changed only the banner's example; both views keep their text, and restored == 0.
- `test_a_line_break_in_a_value_the_ai_deleted_is_written_as_word_writes_it`: the deleted run becomes [delText, br, delText].

### Commands and output

- RED: `uv run pytest tests/restore/test_docx_restore.py -q` gave **5 failed, 21 passed**. For example, the rejected view read 'Signed by [PERSON_1] today.' instead of 'Signed by John Smith today.', and a moved '[AMOUNT_1] is due.' stayed.
- GREEN: `uv run pytest tests/restore -q` gives **88 passed**.
- Full suite: `uv run pytest -q` gives **2807 passed in 90.78s**, no warnings. `uv run ruff check src tests tools`: All checks passed. `ruff format --check` on the 12 touched files: clean. `uv run mypy src`: no issues in 48 source files.
- Mutation round: **8/8 caught**, and the sources were left unmutated:
  - no second pass;
  - moves not treated as taken out;
  - shared text planned again;
  - second pass made in the accepted view;
  - second pass reported apart;
  - banner lines ignoring keep;
  - second pass without breaks (missed at first; caught after adding the delText line-break test);
  - the old "keep ignored" mutation, re-checked on the new `kept()` helper.

### Residual

- A banner line that both views partly share, with only its example changed by the AI, keeps its deleted example as a placeholder inside the deletion. That placeholder is The MASK's own example, not a value of the document.

---

## Fix report 3: review fix round 1, C1/R90, I1/R91, M4, M6 (commit 6fe634e)

### C1, ruling R90: a tracked change inside a placeholder

**What changed (src/themask/restore/docx_restore.py).**
- **Plan both readings first.** A paragraph with tracked changes is planned in both readings, accepted and rejected, before anything is changed.
- **Tokens and places.** Each placeholder ("token") in each reading records the text nodes it covers and the tracked change each lies in. Tokens of the two readings that cover a character of the same node are grouped as one place, in document order.
- **What happens at each place:**
  - **Plain.** A token of shared text that both readings show alike, or a token wholly inside one insertion or one deletion, is put back where it stands. Shared text is put back once.
  - **Straddle.** Anything else is a placeholder a change runs through. It becomes one plan item with reason `TRACKED_CHANGE` ("changed inside a tracked change"). Its status is the weakest of its forms: unknown, then altered, then exact.
  - **Rewrite.** When every form is exact or confirmed, the place is rewritten as one whole-value change: a new `w:del` holding the rejected reading's text with its value, and a new `w:ins` holding the accepted reading's. They use the place's first run's `rPr` and copy the AI change's attributes other than `w:id` (author, date). They get fresh ids above the part's highest `w:id`.
  - **Left.** Otherwise the place is left untouched and listed in `needs_check`.
- **Applying without breaking positions:**
  1. Split the boundary nodes of each straddle (`_isolate`). Splitting `w:t` inside its run changes no reading's text or positions.
  2. Make the rejected-reading edits; they touch only text that reading alone holds.
  3. Make the accepted-reading edits.
  4. Rewrite the straddles by node identity (`_anchor` / `_prune`).
- **Banner cuts in the rejected reading** remove only rejected-only text nodes, so a shared tab or break is never cut.

**Interpretations (please confirm):**
- When both readings' restored texts are equal (for example, an AI-inserted bracket, confirmed), the place becomes a plain run with no tracked change. A del/ins of the same value would be noise.
- A token that only one reading sees, because the change glues a letter to it (the AI deleted an "X" after "PERSON_1"), is treated as a straddle even though its nodes share one context. This is stricter than the ruling's literal test: the other reading keeps "PERSON_1X" rather than becoming "John SmithX", since it may be an identifier.
- A place where several tokens of one reading meet (a deletion across "1] and [COMPANY_") is held: listed with the reason, never guessed.
- An unknown straddle goes to `needs_check` (with its reason), not to `unknown`.
- R79 brackets do not apply inside a straddle. It is a whole-token change, as the ruling says.

**Covering tests (tests/restore/test_docx_restore.py):**
- a digit changed inside "[COMPANY_1]": both readings right; the redline is [del Acme…, ins Brightwater…] with the AI's author and date and two distinct ids; "1 placeholders restored, 0 need your check.";
- a word-level swap of parties between shared brackets: the redline is the swap of values; "2 restored";
- a type change;
- an inserted bracket, unconfirmed (left and listed, status altered, with the reason) and confirmed (both readings "Signed by John Smith.", no change left);
- an unconfirmed altered straddle and an unknown straddle, left and listed; the altered one confirmed by its ordinal gives one change of values;
- half a placeholder inserted (the rejected reading keeps "2]");
- the glued case;
- a deletion across two placeholders (held).

### I1, ruling R91: confirmation by number and a Word dry run

**What changed:**
- `RestoreItem` gains `part=""`, `ordinal=-1` and `reason=""`, all defaulted, so the brief's shape still works.
- `plan_restore` numbers its items 0..n-1.
- `TextRestorer` takes `confirm_altered: bool | Collection[int]`: True confirms all, False none, a collection exactly those ordinals. It numbers every item into one file-wide `plan` with its part.
- New `plan_docx(src, case)` runs the same walk with nothing applied. Each paragraph is planned before it is changed, and no paragraph changes another's text, so the dry run's ordinals are the restore's (tested: `plan_docx` twice gives the same plan).
- `restore_docx` and `restore_text` accept the collection.
- Fallback copies are not in the plan. With a collection, their changed placeholders stay as written: they follow only `True`, so they can never be confirmed by a coincident number.

**Covering tests:**
- `plan_docx` lists the body's altered item, the deletion's exact item and the comment's altered item with parts and ordinals 0, 1, 2. `restore_docx(path, case, {2})` restores the comment's altered item and the deletion, and lists the body's item (part and ordinal shown).
- A fallback copy is never confirmed by chance.
- `restore_text` with {1} restores exactly that altered item (and `set()` confirms none).

### M4: simulate_ai

- `_split_off` now splits any run. Content before the token, whether text, tabs or breaks, goes to a run before it; content after goes to a run after; each run keeps a copy of the `rPr`. The middle run is tracked by position, not text.
- The `w:t` nodes are re-read after every split (`first()`), and the amount loop runs until every [AMOUNT_1] stands alone in a bold run.
- Tests: three hand-made masked files (company and amount in one `w:t`; the amount twice; a run with a tab and a break). The amounts are bold, the split half carries `SPLIT_RSID`, and restoring gives every value with only [PERSON_9] left.

### M6

- `_comment_parts` is now public as `cleaner.comment_parts`. The cleaner and `restore_docx` both use it.

### Commands and output

- RED:
  - With the tests written: `pytest tests/restore -q` failed collection (`cannot import name 'plan_docx'`).
  - With a stub `plan_docx`: **11 failed, 89 passed** (all R90, R91 and M4 tests).
  - The `restore_text` ordinal-set test was written after `TextRestorer` gained collections, so its RED was not observed. The "confirmation sets ignored" mutation proves it fails without the feature.
- GREEN: `pytest tests/restore -q` gives **104 passed**.
- Full suite: **2823 passed in 92.18s**, no warnings. `ruff check src tests tools`: All checks passed. `ruff format --check` on the 13 touched files: clean. `mypy src`: no issues in 48 source files.
- Mutation round, **20/20 caught**:
  - any pair treated as plain;
  - a shared token without a partner treated as plain, and the last node not split (both missed at first; caught after adding the glued test);
  - a straddle taking the first form's status;
  - an unknown straddle going to `unknown`;
  - the readings' values swapped;
  - agreeing readings still written as a change;
  - author and date not copied;
  - one id for both;
  - the first node not split;
  - the accepted edits applied first;
  - tangles not held;
  - no straddle rewrite;
  - the rejected text kept whole;
  - confirmation sets ignored;
  - numbering per text instead of per file;
  - part not set;
  - the fallback following the numbers;
  - `plan_restore` without ordinals;
  - `simulate_ai` keeping stale nodes.
- **The reviewer's probes**, re-run (`r18/probes/p5_tracked.py`, `p5b`, `p5c`, `p8_sim`, and a copy of `p6_misc` in my own scratch folder, since the original's re-run setup trips over the directory it made on its first run):
  - (i2) digit change: accepted "Signed by Mary Jones.", rejected "Signed by John Smith.", 1 restored. The XML is `<w:del w:id="11" w:author="AI tool" …>Acme Supplies Ltd</w:del><w:ins w:id="12" …>Brightwater BV</w:ins>` for the reviewer's digit case.
  - (i3) type change: right.
  - (i4) inserted brackets: listed when unconfirmed; with confirmation, "Signed by John Smith." in both readings.
  - (i5) deleted brackets: listed.
  - (i6) deletion across two placeholders: held.
  - (i10) inserted half placeholder: rejected reading "W 2] end".
  - Word-level swap: right in both readings.
  - The three `simulate_ai` inputs: no crash, values back.
  - Error-path and naming probes: unchanged.
- **Corpus round trip** (my script, every corpus Word file: export, `simulate_ai`, restore confirmed and unconfirmed, checked in both readings). Every value is back, only [PERSON_9] is left, no key placeholder remains in any raw XML part, and plan ordinals run 0..n-1. The only flags were:
  - the unconfirmed runs where [PERSON_1] occurs once (expected: the altered one waits);
  - supply-09, nda-03 and dpa-04, the `existing_placeholders` files, which Task 24 excludes.

### Parked, as instructed

- banner paragraphs with extra children;
- fallback-copy differences (beyond the safety rule above);
- the OSError docstring;
- error-path tests.

---

## Fix report 4: re-review fix round 2, ruling R96 (commit 22bd75b)

### N1: a placeholder inside a changed placeholder's stretch

**What changed (src/themask/restore/docx_restore.py).**
- Planning now works on places (`_Place`). Tokens of the two readings that touch a shared character are grouped as before; each place records its span in document coordinates: a node's place in the paragraph, and the offset.
- A place that is not plain is rewritten over every text node from its first character to its last, so that span is what it takes.
- `_places` repeats until stable: when a non-plain place's span holds a character of another place, the two are merged into a held place (`_Place.held_at`).
- A held place is numbered once with `TRACKED_CHANGE` and the weakest status of its forms, and listed in needs_check. Nothing in it is rewritten or counted as restored. `plan_docx` shows the same single item, since it runs the same code.

**Tests:** `test_a_placeholder_inside_a_changed_placeholders_stretch_is_held_with_it`, with four cases:
- deleted first (the reviewer's prefix/suffix redline);
- inserted first;
- a changed form "company_1" inside, with confirmation;
- one form in each reading (a merged place that the ordinary classification would not hold; the ruling holds it).

Each checks both readings unchanged, one needs_check item with the reason, restored 0, altered_restored 0, unknown [], and the plan listing one item with the same ordinal. `test_a_placeholder_right_after_a_changed_one_stays_its_own` pins the boundary: a placeholder touching the stretch but with no character in it is still restored ("2 restored").

### Item 2: a crash guard for a banner cut and a changed placeholder on one line

**What changed:**
- The tracked path computes both readings' banner cuts without noting them (`TextRestorer.banner_cuts(..., note=False)`).
- If the paragraph has any cut and any place that is not plain, all its cuts are dropped and every such place is held, before anything is numbered or counted. The banner removal is noted only when the cuts stay.
- Interpretation: the guard works per paragraph, not per line. It is the ruling's "skips a paragraph that anchors a straddle", and it also keeps held places' text intact.

**Test:** `test_a_banner_line_that_would_cut_a_changed_placeholder_stays`. The accepted reading is the banner; the rejected reading holds `[COMPANY_2]` with a change through it. The result: no crash, both readings unchanged, one held item with the reason, banner_removed False, restored 0.

### Item 3: a full confirmation set restores fallback copies

**What changed:** `restore_docx` works out `_confirms_every_change`:
- True gives yes, False gives no.
- A collection is checked against a plan of `pkg.copy()`: yes when it holds the ordinal of every "altered" item.

The fallback-copy restorer gets that boolean. A set that leaves any changed placeholder out still keeps fallback copies as written, so no coincident number can confirm one.

**Test:** `test_a_set_that_confirms_every_changed_placeholder_restores_fallback_copies`. With {0, 1} (every altered ordinal), both text-box copies are restored and the report reads "2 placeholders restored, 0 need your check.". The earlier test, where {0} leaves the fallback as written, still passes.

### Item 4: the fingerprint for Task 23

**What changed:**
- New `report.RestorePlan(items, sha256)`. `plan_docx` returns it, with the SHA-256 of the file's bytes; its callers and tests now read `.items`.
- `restore_docx(..., expected_sha256: str | None = None)` checks the file's SHA-256 first. When it differs, it raises `MaskError(FILE_CHANGED_MESSAGE)` ("The file changed since it was checked. Load it again.") before anything is read or written.
- The hash is taken from the file just before it is opened. Only a change in that instant would go unnoticed, so I did not change `DocxPackage.open` to read from given bytes.

**Test:** `test_a_restore_refuses_a_file_that_changed_since_it_was_planned`. The fingerprint equals the file's SHA-256. The unchanged file restores with it. After the file is rewritten, the restore raises MaskError with the exact message and creates no output folder.

### Commands and output

- RED:
  - The new tests failed collection (`cannot import name 'FILE_CHANGED_MESSAGE'`).
  - With a temporary stub (the constant, a plan wrapper with `.items`, and `expected_sha256` accepted but ignored): **6 failed, 104 passed**. They were the three N1 cases, the banner guard, the full set and the fingerprint.
- GREEN: `pytest tests/restore -q` gives **112 passed**, including the two cases added after the first green run (one form each, and the boundary).
- Repro re-run (`t18/n1_probe.py`):
  - N1 deleted first, inserted first and the altered form are all held, both readings untouched, "0 placeholders restored, 1 need your check.", with a one-item plan.
  - The banner/straddle case: no crash; the line stays, and `[COMPANY_2]` is held and listed.
- Mutation round, **10/10 caught**:
  - places never merged;
  - a merged place not held (caught only after adding the one-form-each case);
  - `covers` counting a touching boundary (caught by the boundary test);
  - the banner cut kept beside a changed placeholder;
  - the banner noted though the cut is dropped;
  - a held place counted as restored;
  - the fallback ignoring a full set;
  - a full set required to exceed every change;
  - the fingerprint not checked;
  - the plan without a fingerprint.
- **28-file round trip** (every corpus Word file: export, `simulate_ai`, restore with True, False and the set of every altered ordinal, each given the plan's `expected_sha256`):
  - The fingerprint check passed every time.
  - The full set gives the same accepted and rejected texts as True on all 28 files.
  - Confirmed restores bring back every value in both readings, leave only [PERSON_9], and leave no key placeholder in any raw part.
  - The only flags are supply-09, nda-03 and dpa-04, the `existing_placeholders` files that Task 24 excludes, as in the earlier rounds.
- Full suite: **2831 passed in 99.25s**, no warnings. `ruff check src tests tools`: All checks passed. `ruff format --check` on the 13 touched files: clean. `mypy src`: no issues in 48 source files.

### Parked, as instructed

- The invented tracked change when the AI deletes one banner word.
- The earlier parked items: banner paragraphs with extra children, fallback-copy differences, the OSError docstring, error-path tests.
