### Task 22: Export dialog

**Files:**
- Create: `src/themask/ui/export_dialog.py`
- Modify: `src/themask/ui/main_window.py` (wire `exportRequested` → dialog)
- Test: `tests/ui/test_export_dialog.py`

**Interfaces:**
- Consumes: `export_case`, `ExportResult`, `AI_INSTRUCTION`, `Settings.out_dir`.
- Produces: `class ExportDialog(QDialog)` with `run(sources, review, options, ctx)` (runs `export_case` in a worker with a progress bar; `ctx.case_store.save` is the `save_case` callback), signal `finishedExport()`, `result: ExportResult`, `copy_button: QPushButton`, `summary_text() -> str`; `analysed(ctx, paths) -> tuple[list[SourceDoc], ReviewState]` helper in `tests/helpers.py`; on success shows the output file names, the `unmarked` list under "Also found in the masked copy — not marked by you:", a **Copy instruction** button (puts `AI_INSTRUCTION` on the clipboard) and **Show in Finder**; on `blocked` shows "Saving blocked: a marked value is still present" with each `LeakHit.part` and `context`, and only a **Back to review** button. `summary_text()` for tests.

- [ ] **Step 1: Write the failing tests**

```python
def test_success_shows_outputs_and_instruction(qtbot, app_ctx, corpus, tmp_path):
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"]); d = ExportDialog(); qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=60000): d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert "MASKED-" in d.summary_text() and not d.result.blocked
    qtbot.mouseClick(d.copy_button, Qt.MouseButton.LeftButton); assert QApplication.clipboard().text() == AI_INSTRUCTION
def test_blocked_shows_hits(qtbot, app_ctx, corpus, tmp_path, monkeypatch):
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"])
    monkeypatch.setattr(export_dialog, "export_case", lambda *a, **k: ExportResult(None, [], [LeakHit("word/header1.xml", "[COMPANY_1]", "… [COMPANY_1] …")], [], AI_INSTRUCTION, True))
    d = ExportDialog(); qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=10000): d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert "blocked" in d.summary_text().lower() and "word/header1.xml" in d.summary_text() and not d.copy_button.isEnabled()
def test_case_saved(qtbot, app_ctx, corpus, tmp_path):
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"]); d = ExportDialog(); qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=60000): d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert [s.id for s in app_ctx.case_store.list()] == [d.result.case.id]
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: export dialog with leak block, outputs and instruction copy"`

---

