## Global Constraints

- **Repository location:** `~/Developer/the-mask`, not the iCloud-synced Desktop (Briefcase cannot build inside iCloud folders, and a 1 GB virtualenv must not sync). Task 1 moves the spec there and leaves a pointer in `~/Desktop/Claude Projects/the-mask/README.md`.
- **Python 3.12.x** (`.python-version` = `3.12`), managed with `uv`. All commands below run as `uv run …` from the repo root.
- **No network, ever.** No code path may open a socket; Task 19 installs a socket guard at startup, and no dependency may need the network at runtime (spaCy model bundled as a pinned wheel; `tldextract` forced to its bundled snapshot).
- **Licences:** permissive (MIT/BSD/Apache-2.0/MPL for dev tools) or LGPL used as a library. No GPL/AGPL anywhere in the installed environment (so: no PyInstaller, no Nuitka, no PyMuPDF; Qt modules limited to QtCore/QtGui/QtWidgets). Task 1 adds a test that fails on any GPL/AGPL distribution.
- **Placeholder format:** `[TYPE_N]`, types exactly `PERSON, COMPANY, AMOUNT, PERCENT, QUANTITY, EMAIL, PHONE, ADDRESS, IBAN, ID, URL, CUSTOM`; numbering per type, in order of first appearance.
- **Visible by default:** defined terms (Buyer, Supplier, Party, Agreement, Schedule…), clause numbers and headings, dates, durations and notice periods, governing-law jurisdictions.
- **Exact copy, verbatim from the spec:**
  - Banner (top of every masked file): `Confidential values in this document are replaced by placeholders such as [COMPANY_1]. Keep them unchanged.`
  - Image note: `[image removed]`; embedded object note: `[embedded object removed]` (designer's call).
  - AI instruction (8.8): `This document uses placeholders such as [PERSON_1] and [AMOUNT_2] instead of confidential values. Keep every placeholder exactly as written, including the square brackets, in your answer and in any file you create. Do not guess the real values. Please give your result as a Word (.docx) file.`
  - Restore report: `{n} placeholders restored, {m} need your check.`
  - Masked file name: `MASKED-<CODE>.docx`, `<CODE>` = 4 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`; multi-file `MASKED-<CODE>-1.docx`, `-2`…; redline `MASKED-<CODE>-before.docx` / `-after.docx`. Restored file: `<original stem> – restored.docx`, never overwriting (append ` (2)`, ` (3)`…).
- **Originals are never modified.** Every writer works on a copy in memory or a new path.
- **The log never contains document content**: counts, types, durations and file sizes only.
- **Key storage:** AES-256-GCM; master key in macOS Keychain (service `The MASK`, account `master-key`); default retention 30 days.
- **Pass marks (spec §9)** are enforced by `tests/test_passmarks.py` (Task 24) and must pass before Task 25.
- **Commits:** Conventional Commits, one per task step that says "Commit"; each message ends with the attribution trailer this session requires (`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`).
- **Progress reporting (owner's request):** the implementer updates the session scratchpad file `ilerleme/the-mask-build.json` (`{"ad":"The MASK build","yuzde":<task_no/26*100>,"adim":"Task N: <name>"}`) when starting each task, and every subagent writes its own `ilerleme/<its description>.json`. See memory note `progress-mod-isler`.
- **Test data:** made-up documents only (Task 4/5 corpus). Never a real contract.

