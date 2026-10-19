### Task 21: Review screen

**Files:**
- Create: `src/themask/ui/review_screen.py`
- Test: `tests/ui/test_review_screen.py`

**Interfaces:**
- Consumes: `ReviewState`, `Analysis`, `CombinedText`.
- Produces: `class ReviewScreen(QWidget)` with `load(review: ReviewState, combined: CombinedText)`, `group_count() -> int`, `review: ReviewState`, `text: QTextEdit`, `tree: QTreeWidget`, `tree_item_for(group_id) -> QTreeWidgetItem` (column 1 shows `check` when flagged), `highlight_count() -> int`, `hide_selection(type: PlaceholderType)`, `export_button: QPushButton`, signal `exportRequested()`; layout: left a read-only `QTextEdit` showing the combined text with each active finding highlighted (background colour per type from `theme.TYPE_COLOURS`, a dotted underline + "check" tooltip for `needs_check`, file headers for each part), right a `QTreeWidget` of groups ("canonical — N times — [PLACEHOLDER]", checkbox per group and per occurrence, "check" badge), a warnings strip (from `Analysis.warnings`), and actions: **Hide selection** (type menu; enabled when text is selected), **Merge** (≥ 2 groups selected), **Split** (occurrences selected), **Always hide**, **Never hide**, **Continue to export** (disabled while zero groups are enabled? No: allowed — the owner may export a document with nothing to hide; the dialog then says so). Clicking a highlight selects its group; selecting a group scrolls to its first occurrence.

- [ ] **Step 1: Write the failing tests**

```python
def test_tree_matches_state(review_screen):
    s, st = review_screen; assert s.tree.topLevelItemCount() == len(st.groups) and s.tree.topLevelItem(0).text(0).endswith(st.groups[0].placeholder)
def test_untick_group_updates_plan_and_highlight(qtbot, review_screen):
    s, st = review_screen; n = len(st.mask_plan().replacements); item = s.tree.topLevelItem(0); item.setCheckState(0, Qt.CheckState.Unchecked)
    assert len(st.mask_plan().replacements) < n and s.highlight_count() == len(st.mask_plan().replacements)
def test_hide_selection(qtbot, review_screen):
    s, st = review_screen; i = s.text.toPlainText().index("Project Falcon"); c = s.text.textCursor(); c.setPosition(i); c.setPosition(i + len("Project Falcon"), c.MoveMode.KeepAnchor); s.text.setTextCursor(c)
    s.hide_selection(PlaceholderType.CUSTOM); assert any(g.canonical == "Project Falcon" for g in st.groups) and s.tree.topLevelItemCount() == len(st.groups)
def test_needs_check_marked(review_screen):
    s, st = review_screen; flagged = [g for g in st.groups if g.needs_check]; assert flagged and all(s.tree_item_for(g.id).text(1) == "check" for g in flagged)
def test_export_signal(qtbot, review_screen):
    s, _ = review_screen
    with qtbot.waitSignal(s.exportRequested): qtbot.mouseClick(s.export_button, Qt.MouseButton.LeftButton)
```
(`review_screen` fixture: analysis of `supply-08.docx` — the `shared_surname` document that also contains "Project Falcon" twice.)

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: review screen with highlights, grouped list and actions"`

---

