### Task 9: Review state (the logic behind the review screen)

**Files:**
- Create: `src/themask/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `Analysis`, `Group`, `UserLists`, `sweep`, `flexible_pattern`.
- Produces: `class ReviewState` with `from_analysis(analysis: Analysis, user_lists: UserLists, case_lists: CaseLists) -> ReviewState`; `text: str`; `groups: list[Group]`; `set_group_enabled(group_id: str, enabled: bool)`; `set_occurrence_enabled(group_id: str, finding_index: int, enabled: bool)`; `hide_text(value: str, type: PlaceholderType) -> Group` (new group, numbered next for its type, swept across the text; if the text equals an existing group's variant, the occurrence joins that group instead); `merge(group_ids: list[str]) -> Group` (same type only, else `ValueError`; keeps the lowest placeholder number, union of variants, canonical = longest); `split(group_id: str, finding_indexes: list[int]) -> Group`; `add_always_hide(value: str)` (persists to `UserLists` and calls `hide_text`), `add_never_hide(value: str)` (persists, disables matching groups); `mask_plan() -> MaskPlan` (enabled groups' active findings only); `key_entries() -> list[KeyEntry]` (enabled groups; `value` = canonical; `variants` = all variants seen); `counts() -> ReviewCounts(groups: int, enabled: int, needs_check: int, replacements: int)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_disable_group_removes_replacements(review):           # fixture: ReviewState over analyze() of "Acme Supplies Ltd and Northwind Trading B.V. appoint John Smith. Project Falcon starts now; Project Falcon ends later. Acme signs." → groups in order [COMPANY_1] Acme, [COMPANY_2] Northwind, [PERSON_1] John Smith
    n = len(review.mask_plan().replacements); gid = review.groups[0].id
    review.set_group_enabled(gid, False); assert len(review.mask_plan().replacements) == n - len(review.groups[0].findings)
def test_disable_single_occurrence(review):
    gid = review.groups[0].id; review.set_occurrence_enabled(gid, 0, False); assert review.groups[0].findings[0].start not in {r.start for r in review.mask_plan().replacements}
def test_hide_text_sweeps(review):
    g = review.hide_text("Project Falcon", PlaceholderType.CUSTOM); assert len(g.findings) == review.text.count("Project Falcon") and g.placeholder == "[CUSTOM_1]"
def test_merge_keeps_lowest_number(review):
    a, b = review.groups[0], review.groups[1]; m = review.merge([a.id, b.id]); assert m.placeholder == min(a.placeholder, b.placeholder, key=lambda p: int(p.split("_")[1].rstrip("]"))) and len(review.groups) == 2
def test_split(review):
    g = review.groups[0]; new = review.split(g.id, [0]); assert len(new.findings) == 1 and new.placeholder != g.placeholder
def test_never_hide_disables(review, lists):
    v = review.groups[0].canonical; review.add_never_hide(v); assert not review.groups[0].enabled and v in lists.never_hide
def test_key_entries_match_plan(review):
    assert {r.placeholder for r in review.mask_plan().replacements} == {e.placeholder for e in review.key_entries()}
```

- [ ] **Step 2–5:** verify failure → implement → verify pass (+ lint/types) → `git commit -m "feat: review state with enable, hide, merge, split and lists"`

---

