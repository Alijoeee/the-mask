### Task 1: Repository, toolchain, licence gate

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`, `src/themask/__init__.py`, `src/themask/about.py`, `src/themask/errors.py`, `tests/conftest.py`, `tests/test_licences.py`, `tests/test_about.py`
- Move: `~/Desktop/Claude Projects/the-mask/docs/` → `~/Developer/the-mask/docs/`; create pointer `~/Desktop/Claude Projects/the-mask/README.md` ("The code lives in ~/Developer/the-mask")

**Interfaces:**
- Produces: `about.APP_NAME = "The MASK"`, `about.OWNER_NAME: str` (placeholder `"<owner name — set in about.py>"`), `about.VERSION = "0.1.0"`; `errors.MaskError(Exception)` base with `user_message: str`, subclasses `UnsupportedFileError`, `ProtectedFileError`, `ScannedPdfError`, `CaseCorruptError`, `LeakBlockedError`.
- Produces: `conftest.py` fixtures `data_dir` (tmp path) and the env `QT_QPA_PLATFORM=offscreen` set at import.

- [ ] **Step 1: Create the repo and move the docs**

```bash
mkdir -p ~/Developer/the-mask && mv "$HOME/Desktop/Claude Projects/the-mask/docs" ~/Developer/the-mask/ && printf '# The MASK\n\nThe code lives in `~/Developer/the-mask` (outside iCloud).\n' > "$HOME/Desktop/Claude Projects/the-mask/README.md" && cd ~/Developer/the-mask && git init -b main
```

- [ ] **Step 2: Write `pyproject.toml`**

`[project]` name `the-mask`, package `themask` (src layout; `[build-system] requires = ["hatchling"]`, `[tool.hatch.build.targets.wheel] packages = ["src/themask"]`), `requires-python = ">=3.12,<3.13"`. Dependencies pinned exactly: `PySide6-Essentials==6.12.0`, `presidio-analyzer==2.2.364`, `spacy==3.8.16`, `en_core_web_md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl`, `python-docx==1.2.0`, `lxml==6.1.3`, `pdfplumber==0.11.10`, `cryptography==50.0.2`, `keyring==25.7.0`, `schwifty==2026.7.3`, `python-stdnum==2.2`, `phonenumbers==9.0.41`, `rapidfuzz==3.14.6`, `platformdirs==4.13.4`, `tldextract==5.4.0`. Dev group: `pytest==9.1.1`, `pytest-qt==4.5.0`, `Faker==40.43.0`, `reportlab==5.0.1`, `pillow==13.0.0`, `ruff==0.17.1`, `mypy==2.4.0`, `briefcase==0.4.6`. `[tool.pytest.ini_options] testpaths=["tests"]`, markers `slow`; `[tool.ruff] line-length=100`; `[tool.mypy] ignore_missing_imports=true, strict=true` on `src`. Leave `[tool.briefcase]` for Task 25.

- [ ] **Step 3: Write the failing licence test**

```python
# tests/test_licences.py
from importlib.metadata import distributions
ACCEPT = ("MIT", "BSD", "Apache", "LGPL", "MPL", "PSF", "Python Software Foundation", "ISC", "Unlicense", "Zlib", "HPND", "MIT-CMU", "CNRI")
def licence_of(dist) -> str:
    md = dist.metadata
    expr = md.get("License-Expression") or md.get("License") or ""
    cls = "; ".join(c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::"))
    return f"{expr}; {cls}"
def acceptable(text: str) -> bool:
    alternatives = [a.strip() for a in text.replace(";", " OR ").split(" OR ")]
    return any(any(ok.lower() in a.lower() for ok in ACCEPT) and "AGPL" not in a for a in alternatives)
def test_no_gpl_or_agpl_in_environment():
    bad = [f"{d.metadata['Name']}: {licence_of(d)}" for d in distributions()
           if ("GPL" in licence_of(d).upper() and not acceptable(licence_of(d)))]
    assert bad == []
```
Also `tests/test_about.py`: `APP_NAME == "The MASK"`, `VERSION == "0.1.0"`, `issubclass(LeakBlockedError, MaskError)`.

- [ ] **Step 4: Install and run; expect failure**

Run: `cd ~/Developer/the-mask && uv sync && uv run pytest -q`
Expected: FAIL (`ModuleNotFoundError: themask`) — and note the printout of `uv sync` shows the spaCy model wheel downloaded once.

- [ ] **Step 5: Create `src/themask/__init__.py`, `about.py`, `errors.py`, `tests/conftest.py`**

`conftest.py`: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at top; fixture `data_dir(tmp_path) -> Path`.

- [ ] **Step 6: Run tests, lint, types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all pass; the licence test passes (PySide6's `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` is accepted through its LGPL alternative).

- [ ] **Step 7: Write `README.md` (run from source: `uv run python -m themask`) and commit**

```bash
git add -A && git commit -m "chore: scaffold The MASK repo with pinned toolchain and licence gate"
```

---

