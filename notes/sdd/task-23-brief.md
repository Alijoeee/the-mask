### Task 23: Restore, Cases and Settings screens

**Files:**
- Create: `src/themask/ui/restore_screen.py`, `src/themask/ui/cases_screen.py`, `src/themask/ui/settings_screen.py`
- Modify: `src/themask/ui/main_window.py` (navigation; `purge_expired` on startup), `src/themask/ui/app.py` (About with `OWNER_NAME`, `VERSION`)
- Test: `tests/ui/test_restore_screen.py`, `tests/ui/test_cases_settings.py`

**Interfaces:**
- Produces `class RestoreScreen(QWidget)` (`load_file(path)`, `case_combo` with the case id as item data, `altered_list: QListWidget` with check boxes, `restore_button`, `restore_text_button`, `paste_box`, `result_box`, `report_label`, signal `restoreFinished()`): a `DropZone` for the AI's `.docx` and a paste box (`QPlainTextEdit`) with **Restore text**; a case combo (`suggest_cases` order over all stored cases, most recent preselected when no placeholders match); when `plan_restore` has altered items, a list with checkboxes "These placeholders were changed by the AI — restore them?" and **Restore** applies `confirm_altered` to the ticked set (implementation: build a `Case` view containing only ticked altered entries); result panel with `RestoreReport.summary()`, the unknown list, and **Show in Finder**; restored text appears in a read-only box with **Copy**.
- Produces `class CasesScreen(QWidget)` (`table: QTableWidget`, `delete_button`, module-level `confirm(parent, message) -> bool`): table of `CaseSummary` (id, created, expires, files, entries), **Delete**, **Delete all** (both confirm), **Restore from this case**, **Add file to this case** (→ `MainWindow.open_files(paths, None, case_id)`).
- Produces `class SettingsScreen(QWidget)` (`always_edit`, `never_edit: QPlainTextEdit`, `retention_spin`, `save_button`, `about_label`): editable always-hide and never-hide lists (`UserLists`, one entry per line), retention days spin box (1–365, default 30), output folder picker, About box (`APP_NAME`, `VERSION`, `OWNER_NAME`, "Runs fully offline. Restored text you copy is on the clipboard in clear.").

- [ ] **Step 1: Write the failing tests**

```python
def test_restore_docx_flow(qtbot, app_ctx, exported):                      # exported fixture: (masked_path, case) saved in app_ctx.case_store
    masked, case = exported; ai = simulate_ai(masked, masked.parent / "ai.docx"); s = RestoreScreen(app_ctx); qtbot.addWidget(s)
    s.load_file(ai); assert s.case_combo.currentData() == case.id and s.altered_list.count() == 1
    s.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(s.restoreFinished, timeout=30000): qtbot.mouseClick(s.restore_button, Qt.MouseButton.LeftButton)
    assert s.report_label.text().endswith("need your check.") and (masked.parent / "ai – restored.docx").exists()
def test_restore_text_flow(qtbot, app_ctx, exported):
    _, case = exported; s = RestoreScreen(app_ctx); qtbot.addWidget(s); s.paste_box.setPlainText(f"Dear {case.entries[0].placeholder},"); s.case_combo.setCurrentIndex(s.case_combo.findData(case.id))
    qtbot.mouseClick(s.restore_text_button, Qt.MouseButton.LeftButton); assert case.entries[0].value in s.result_box.toPlainText()
def test_cases_screen_delete(qtbot, app_ctx, exported, monkeypatch):
    monkeypatch.setattr(cases_screen, "confirm", lambda *a: True); c = CasesScreen(app_ctx); qtbot.addWidget(c); assert c.table.rowCount() == 1
    c.table.selectRow(0); qtbot.mouseClick(c.delete_button, Qt.MouseButton.LeftButton); assert c.table.rowCount() == 0 and app_ctx.case_store.list() == []
def test_settings_lists_and_retention(qtbot, app_ctx):
    s = SettingsScreen(app_ctx); qtbot.addWidget(s); s.always_edit.setPlainText("Project Falcon\nSite 7"); s.retention_spin.setValue(14); qtbot.mouseClick(s.save_button, Qt.MouseButton.LeftButton)
    assert UserLists.load(lists_path()).always_hide == ["Project Falcon", "Site 7"] and app_ctx.settings.retention_days == 14
def test_about_shows_owner(qtbot, app_ctx): s = SettingsScreen(app_ctx); qtbot.addWidget(s); assert OWNER_NAME in s.about_label.text() and VERSION in s.about_label.text()
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: restore, cases and settings screens"`

---

