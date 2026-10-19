### Task 26: Owner acceptance: the real round trip

**Files:**
- Create: `docs/acceptance/2026-10-xx-round-trip.md`

- [ ] **Step 1:** In The MASK.app, mask `tests/corpus/generated/supply-01.docx` (made-up data only). Copy the instruction.
- [ ] **Step 2:** For each of **Copilot**, **Claude** and **ChatGPT**: upload the masked file with the instruction and the prompt "Review this agreement for risks to the Buyer and return a revised version as a Word file." Download the Word file.
- [ ] **Step 3:** Restore each file in The MASK.app with the case preselected. Expected: every placeholder restored or listed under "need your check"; no invented values; banner gone.
- [ ] **Step 4:** Record per tool: placeholders survived (yes/no, which changed), restore report line, anything odd. Expected: all three "placeholders survive and restore" (spec §9).
- [ ] **Step 5:** `git add -A && git commit -m "docs: Mac acceptance round trip with three AI tools"`. Then the Windows-phase plan can start once Bunzl IT has answered spec §14.

---

## Self-review notes (filled in by the plan author)

- Spec coverage: §4 round trip → Tasks 15, 18, 22, 23, 26; §8.1 → 2, 8; §8.2 → 6, 7, 8, 24; §8.3 → 9, 21; §8.4 Word → 10–13, 15; §8.4 PDF → 16; §8.5 → 14, 15; §8.6 → 17; §8.7 → 18, 23; §8.8 → 2, 22; §8.9 (several files, add a file to an existing case) → 8, 15, 20, 23; §8.10 Mac → 1, 19, 25; §9 → 24, 25, 26; §10 clipboard note → Settings About copy (Task 23). Windows items deferred by design.
- Names used across tasks: `DocText/Segment/TextNode` (10 → 13, 18), `replace_in_paragraph` (13 → 18), `Group/KeyEntry/MaskPlan` (2 → 8, 9, 13, 14, 15, 18), `CombinedText` (8 → 15, 21), `ExportResult/LeakHit` (14, 15 → 22), `CaseStore/CaseSummary` (17 → 20, 23), `simulate_ai` helper defined once in `tests/helpers.py` (Task 18) and reused (23, 24).
