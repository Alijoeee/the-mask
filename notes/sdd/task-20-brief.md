### Task 20: App shell, home screen, analysis worker

**Files:**
- Create: `src/themask/ui/__init__.py`, `src/themask/ui/app.py`, `src/themask/ui/main_window.py`, `src/themask/ui/drop_zone.py`, `src/themask/ui/workers.py`, `src/themask/ui/theme.py`
- Modify: `src/themask/__main__.py` (→ `ui.app.main()`)
- Test: `tests/ui/test_home.py` (pytest-qt, offscreen)

**Interfaces:**
- Produces: `class AppContext(engine: Engine, user_lists: UserLists, case_store: CaseStore, settings: Settings)` built lazily in `app.main()` (`Settings` = dataclass `retention_days: int = 30`, `out_dir: Path = ~/Documents/The MASK`, loaded/saved as JSON in `data_dir()`); `class MainWindow(QMainWindow)` with `show_home()`, `show_review(sources, analysis)`, `show_restore()`, `show_cases()`, `show_settings()`, `open_files(paths: list[Path], redline_split: bool | None, case_id: str | None = None)` (asks "This file contains tracked changes. Make a before-and-after pair?" when `None` and any source `has_revisions`; with `case_id` the analysis is seeded with that case's entries and the export updates that case); signals `analysisProgress(int, str)`, `analysisFinished()`, `analysisFailed(str)`; `current_screen_name() -> str`; `review_screen: ReviewScreen`; module-level `show_error(parent, message: str)` (a `QMessageBox`, monkeypatched in tests); `class DropZone(QFrame)` emitting `filesDropped(list)` for `.docx`/`.pdf`, with a "Choose files…" button; `class AnalysisWorker(QThread)` with signals `progress(int, str)` (0–100 and a step name: loading → reading → finding → grouping → done), `finished(object)` (`tuple[list[SourceDoc], Analysis]`), `failed(str)` (user_message); the engine is created once in a background thread at startup with a "Loading…" status in the home screen.

- [ ] **Step 1: Write the failing tests**

```python
def test_home_to_review(qtbot, app_ctx, corpus):
    w = MainWindow(app_ctx); qtbot.addWidget(w); w.show()
    with qtbot.waitSignal(w.analysisFinished, timeout=60000): w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert w.current_screen_name() == "review" and w.review_screen.group_count() > 0
def test_unsupported_file_shows_message(qtbot, app_ctx, fixtures, monkeypatch):
    shown = []; monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg)); w = MainWindow(app_ctx); qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000): w.open_files([fixtures / "not-a-docx.doc"], redline_split=False)
    assert shown and "save as .docx" in shown[0]
def test_scanned_pdf_message(qtbot, app_ctx, corpus, monkeypatch):
    shown = []; monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg)); w = MainWindow(app_ctx); qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000): w.open_files([corpus / "scanned-01.pdf"], redline_split=False)
    assert "scan" in shown[0]
def test_progress_reaches_100(qtbot, app_ctx, corpus):
    w = MainWindow(app_ctx); qtbot.addWidget(w); seen = []; w.analysisProgress.connect(lambda p, s: seen.append(p))
    with qtbot.waitSignal(w.analysisFinished, timeout=60000): w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert seen[-1] == 100 and seen == sorted(seen)
```
(`app_ctx` fixture: session `engine`, `lists`, `CaseStore(tmp, MemoryKeyStore())`, default `Settings`.)

- [ ] **Step 2–5:** verify failure → implement → verify pass (`uv run pytest tests/ui -q`) → `git commit -m "feat: app shell with drop zone and threaded analysis"`

---

