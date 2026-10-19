# Pointers for the final whole-branch review (built from the ledger in session 3)

Curated from every `MUST-FIX`, `parked`, `minor (deferred)` and `→ final` line of `notes/sdd/progress.md`
(line numbers refer to the ledger as it stood at 0baa904 + session 3's first entries). "Status" is the
controller's reading of later tasks — the reviewer verifies on the code, never trusts it.

Scope of the fix wave (ONE subagent, one list): section A, everything the final reviewer rates
Critical/Important, the items section B marks "→ final fix wave", and cheap robustness items the reviewer
confirms. Everything else stays parked and is listed for the owner in notes/RULINGS.md.

## A. MUST-FIX (Task 14 leak check, ledger line 326) — not triage, fix

1. A value ending ".00" followed by a plain space and three digits is no longer found ("1,250.00 100 units"):
   the zero extension moves the match end past the folded ".00" and the R70 thousands rule then fires.
   Fix: a decimal part ends a number; when the match took in a decimal point (or cents follow the
   unextended end) do not apply the plain-space thousands rule on the right. (src/themask/leakcheck.py)
2. The byte-scan length threshold is measured on the folded key ("EUR 10.00" → "eur10" is no longer
   searched in bytes). Fix: measure normalize(form) as R14 (b) says.
3. Two amount groups whose values fold alike ("EUR 1,250.00" and "EUR 1,250" are two groups) share one
   fold key, so a leftover is attributed to the first placeholder. Fix: attribute a shared fold to every
   entry that folds to it. (R84's twin gate has replaced R60's counting, so the gating consequence is
   gone; the attribution still decides what the export dialog shows under "left visible on purpose"
   and "also found" — verify what remains.)

## A2. External review findings (owner-supplied 2026-10-19, confirmed by the controller) — MUST-FIX, with their rulings

4. R100 — type-specific grouping identity (amounts/percentages/quantities on the number fold + currency/unit; e-mails and web addresses case-folded with punctuation kept; phones/IBAN/ID alphanumeric): "EUR 1.25" vs "EUR 125", "$100" vs "€100", "a.b@example.com" vs "ab@example.com" must be separate groups and restore to their own values. src/themask/detect/grouping.py `_by_value`, seed matching in pipeline.py; reuse leakcheck's fold rather than a second copy (the review's architectural point: one shared set of value-comparison rules).
5. R101 — remove every media part and every reference to it (picture bullets in numbering.xml, w:background, theme images, headers/footers, glossary); the export gate fails closed on any remaining media part or image-type relationship. src/themask/docx/cleaner.py `_sweep`/`_referenced`, src/themask/export.py gate.
6. R102 — scan namespace declarations and non-standard element/attribute names; strip unused declarations. src/themask/leakcheck.py `_element` (lxml nsmap), cleaner.
7. R103 — (restore screen; sent to the Tasks 22+23 implementer first; the fix wave verifies) file-name code preference in suggest_cases, no preselection on ambiguity, case titles with file names, placeholder → value preview.
8. R104 — zip limits in DocxPackage.open (entries, per-entry and total expanded size, capped inflate).
9. README: no stale wording that export/restore are future work (the external review saw such wording on the packaging branch).

## B. Parked items with a leak, restore or crash angle (verify; fix if Important)

- Task 11 (line 164, "→ final fix wave"): `_restore` in src/themask/docx/revisions.py assumes a *Change
  record sits inside its own property element; a misplaced record (which Word never writes) makes
  reject_all clear content (w:sectPrChange directly in w:body empties the body). Fix: map each record to
  its owning element and only remove misplaced records. Status: unresolved.
- Task 11 (line 163): w14:conflictIns / w14:conflictDel (co-authoring conflicts) are neither resolved nor
  counted by has_revisions. Status: unresolved; decide whether the cleaner must drop them (unread text
  could leak) or the leak check already catches them (raw scan).
- Task 12 (line 191, "→ final fix wave"): the emptied-link unwrap starts at the hidden run's immediate
  parent, so a w:sdt / w:dir / w:bdo between the hyperlink and the hidden run leaves the mailto Target in
  the rels (the leak check's relationship-target scan blocks such an export, not a leak). Fix: unwrap
  every w:hyperlink / w:fldSimple with no w:r descendant after the hidden pass. Three untested branches
  (VML textbox guard, replace-whole fallback, fldData drop). Status: unresolved.
- Task 12 (lines 179, 192): partially hidden field markers leave unbalanced fldChars; a linked inline
  picture keeps its URL on the note when wrapped in w:hyperlink; VML v:fill r:id picture fills,
  am3d:model3d, base64 w:fldData, external saveThroughXslt path remain (documented class); a media part
  reachable via an orphan/duplicate relationship survives; a:hlinkClick on kept drawings keeps
  target/tooltip (values covered by Task 13's hyperlink logic — verify); VML href / o:hrlabel survive.
- Task 13 (line 198): unquoted multi-word field values containing a field-name word are kept whole and
  unquoted backslash-led words are treated as switches (UNC paths) — the leak check must block these
  (R31); `_blanked` is O(words × edits) per instruction (2.4 s on a 61k-char instruction); the text path
  has no guard against a plan replacement inside an existing body placeholder (R44 keeps exact
  placeholders out of detection — confirm the pipeline can never emit one).
- Task 14 (lines 313, 322, 327): byte scan decodes only UTF-8/UTF-16 (latin-1 "Café Noël" missed;
  compressed streams invisible); the zip archive comment is not searched; namespace declaration URIs
  unsearched (customXml removed by the cleaner); glossary exemption pattern open-ended (glossary
  removed); rId/GUID collisions with short digit-only needles; R31 exempts any unquoted word after a
  format switch (matches the masker); blocks over 8,192 characters lose the R31 exemption (false hits);
  instruction edges can glue to shown text; a damaged theme part stops cleaning with the misleading
  "not a .docx" message (fails closed); one link may count twice; byte scan 0.47 s/MB unbounded;
  hyphenated words fold onto a glued short name (false block); R69 hides every "shall" in a context for
  a key "S. Hall"; "10.00%" counted checkable though "10%" never is; cents rule errs to block;
  R70 gap "No. 100 1,250.00".
- Task 15 (lines 364, 369; R86 note line 363): R86 adds the review's canonical to a stored entry's
  variants without `_key_variants`' filters (a bare surname could enter the key after a split — false
  block only); NB1 hand-built overlapping groups; a visible e-mail containing a URL's domain still
  blocks; leak_hits and allowed_hits share one list object on success; an empty out_dir is left behind
  on failure; the R86 question: should ReviewState refuse merges that change a reserved placeholder's
  value? (decide; a ruling either way).
- Task 18 (lines 338, 342, 394, 420): a key holding the same placeholder twice lets the last entry win
  silently (does Case validate it? decide); banner paragraphs with extra children (bookmark, proofErr,
  tracked insertion) are emptied, not deleted; a fallback copy that differs from its Choice is restored
  silently; the AI deleting one banner word becomes an invented whole-value tracked change; a '>' line
  after a quoted banner and a numbered-item banner stay; a dropped '[' leaves a stray ']' after
  confirmation; OSError from a missing src / read-only out_dir not in the docstring; error-path tests
  missing; private cross-module import of `_comment_parts` (M6 — verify it became public).
- Task 8 (lines 237, 280): parked sweep shapes — a swept surname before a connective and a capitalised
  non-name word ("Smith in London") stays visible unless the engine found it; an engine-found heading
  word or month tagged PERSON is hidden as that person; "Dear Smith" read as one two-word person;
  "Smith/Jones" a flagged company; `_PARTICLES` duplicates `contract_rules._NAME_PARTICLES`,
  `_LEADING_THE` and `_NAMES` each defined twice; grouping.py runs a small sweep of its own.
- Task 9 (lines 292, 300): hide_text cannot reach text inside a switched-off group/occurrence (raises
  "hidden already" or silently keeps it visible — fix: treat inactive findings as takeable and clear the
  matching disabled indexes); after a partial never-hide of a shorter form, add_always_hide / hide_text
  of that form is a silent no-op; merging a group switched off whole by never-hide into an enabled group
  takes the term back into the merged variants; add_* mutate the lists before save (an OSError leaves an
  unsaved entry in memory); review._canonical duplicates grouping._canonical with different tie-breaks.
  These are owner-visible review limits (the owner sees the text), not leaks — rate accordingly.
- Task 6 (line 136, robustness): patterns.py `int()` on a run of ≥ 4,301 digits raises ValueError
  (Python's int-string limit) — a document with such a run would crash the analysis. Fix: short-circuit
  above ~18 digits. Status: check whether Task 24's tuning already guards it.
- Task 2 (line 71): MaskPlan sorts on start only and does not reject start < 0 or end < start — sort by
  (start, end) and validate. Status: unresolved unless a later task touched model.py.
- Task 1 (line 55): LeakBlockedError is unused (export reports leaks via ExportResult.blocked) —
  keep or remove.
- Task 19 (lines 345, 352, 380): the guard covers Python-level sockets only (the owner's Wi-Fi-off smoke
  test is the real proof — RULINGS.md says so); guard state is module-level and set last; `_write_to`
  trusts the handler-name registry; `decision_process` should join the held loggers; the UI tests'
  restore_logging fixture does not restore pdfminer; Windows: socket.sendmsg needs a hasattr skip
  (Windows phase, not now).
- Task 25 (line 423): tools/check_bundle_lock.py raises an uncaught ValueError on an unreadable export
  line (exit 1 with a traceback instead of the promised 2); icon files not validated by a test;
  make_icon hides iconutil's stderr; an empty platforminputcontexts/ folder and PySide6's
  entry_points.txt naming removed scripts; Designer plugins, SQL drivers, QML debugger plugins and the
  QtDesigner/QtHelp/QtLottie/QtQuickTimeline/QtQuickVectorImage frameworks still shipped (LGPL-or-GPL
  wheel — matters only if the app leaves the owner's Macs; Windows-phase SBOM).

## C. Timing tests that flake under machine load ("final fix wave loosens wall-clock limits")

- tests/pdf: `test_twenty_four_pages_are_read_quickly` (line 287).
- tests/test_leakcheck.py: `test_thirty_pages_are_scanned_in_under_two_seconds` (line 399).
- tests/ui: the 2 s wall limit on the 500-highlight test (line 375).
- Task 7's wall-clock limits on the rule patterns (line 155).
Rule for the fix: keep each test meaningful (a quadratic blow-up must still fail) — raise the limit
or mark `slow`, never delete.

## D. Deferred minors already tuned by Task 24 (verify only if cheap)

Task 6 → Task 24 (lines 125, 135, 136): clause/statute numbers as AMOUNT/ID, bracketed durations,
"assume" vs "sum", bad-checksum IBAN, sort-code label, `_LABEL_TO_VALUE` tab gap, date-veto score floor,
hyphenated account numbers, bare rare TLDs, date residuals glued to neighbours. Task 7 → Task 24
(lines 155, 161, 184): departments after "Attention:", KG/Corporation/Limited guards, five-digit
quantities as addresses, address spans past the country, legal-form-less parties, mixed party lists,
`goes_on`, `_PARTIES_START` gaps, single-line model findings. Task 8 → Task 24 (lines 216, 236, 264):
"N records" quantities, a person span across a sentence end, national/international phone forms,
company short name made of a contract word, short first names. Task 13 → Task 24 (line 198) above.
Task 24's own parked list (lines 408, 417): "Either/Neither Party", "GMT"/"EC", "the Federal Republic of
Germany" as flagged COMPANY groups; address after a postcode takes in "Attention Finance"/"KvK 12345678";
", Clause 12 applies" after an address swallowed; year ranges before "records"; two parties in one
hyphenated header under one placeholder; "John Carter - Managing Director" keeps the title word;
`uv run python tools/make_corpus.py` needs -m. The pass marks (913/913, 320/320, 0, < 60 s) are the
measure — a tuning item that is still wrong but inside the marks stays parked.

## E. Structure and test-quality minors (triage only; no fix unless trivial and risk-free)

- Duplicated relationship plumbing in docx/cleaner.py vs DocxPackage (line 179): promote
  relationships()/content_types()/is_referenced()/cascading remove_part — a refactor for the Windows
  phase unless the reviewer finds a behavioural difference.
- Module sizes: cleaner.py 1,029, leakcheck.py 1,083, contract_rules.py ~1,250, review_screen.py 710,
  main_window.py ~500+ (now larger with Task 23): triage a split for the Windows phase.
- Duplicated vocabularies (contract_rules vs textnorm, line 155; grouping vs contract_rules, line 237;
  XML-name constants masker vs reader, line 172).
- Test inflation and gaps listed per task (lines 55–58, 74, 84, 116, 166, 172, 192, 327, 342, 394).
- Docs: README BIC check-digit claim (line 149), stale "20 contracts" docstring, "thirty pages" test name
  on a 24-page file, masker docstrings saying "the way the leak check decides" (line 313).
- Tasks 20+21 (line 375): closeEvent blocks for a running analysis; scroll-to-occurrence tested by cursor
  position only — the rest of that line was handed to Tasks 22+23 (verify in their diff).

## F. Questions the final review answers with a ruling

1. R86: should ReviewState refuse a merge/split that changes a reserved (stored) placeholder's value?
2. Case key with a duplicate placeholder: validate in Case.from_json / CaseStore.save, or document?
3. LeakBlockedError: keep (documented reserve) or remove.
4. w14:conflictIns/conflictDel: cleaner drops them (and notes it) or documented limit.
