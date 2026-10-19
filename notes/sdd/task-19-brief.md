### Task 19: Paths, content-free logging, network guard

**Files:**
- Create: `src/themask/logging_setup.py`, `src/themask/netguard.py`, `src/themask/__main__.py` (temporary: guard → logging → print version)
- Modify: `src/themask/paths.py` (`log_dir`), `src/themask/detect/engine.py` (log counts only)
- Test: `tests/test_netguard.py`, `tests/test_logging.py`

**Interfaces:**
- Produces: `class NetworkBlockedError(OSError)`; `install_network_guard() -> None` (replaces `socket.socket.connect`, `connect_ex`, `sendto`, `bind`, `listen`, `socket.create_connection`, `socket.getaddrinfo` with functions raising `NetworkBlockedError("The MASK never uses the network.")`; sets `tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)` before Presidio imports; idempotent); `setup_logging(level="INFO") -> Path` (RotatingFileHandler 1 MB × 3 in `log_dir()`, format with timestamp, module, message).
- Rule enforced by test: log lines carry counts/types/durations only.
- `tests/conftest.py` calls `install_network_guard()` at import from this task on, so the whole suite proves the app needs no network.

- [ ] **Step 1: Write the failing tests**

```python
def test_guard_blocks_connect():
    install_network_guard()
    with pytest.raises(NetworkBlockedError): socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(NetworkBlockedError): socket.getaddrinfo("example.com", 443)
def test_url_recognizer_works_offline(engine, caplog):
    install_network_guard(); fs = engine.analyze("see https://www.northwind.example/terms"); assert any(f.type == PlaceholderType.URL for f in fs) and "Public Suffix List" not in caplog.text
def test_log_has_no_document_content(corpus, engine, lists, tmp_path, monkeypatch):
    monkeypatch.setenv("THEMASK_DATA_DIR", str(tmp_path)); log = setup_logging("DEBUG")
    srcs = load_sources([corpus / "supply-01.docx"], False); review = ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set())); export_case(srcs, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None)
    text = normalize(log.read_text()); assert text
    for t in json.loads((corpus / "supply-01.truth.json").read_text()): assert normalize(t["value"]) not in text, t["value"]
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: network guard, offline tldextract and content-free logging"`

---

