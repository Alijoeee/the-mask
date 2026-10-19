# Task 1 report: Repository, toolchain, licence gate

**Status: DONE_WITH_CONCERNS** (all verification green; concerns are informational, see below)
**Commit:** `272fd49 chore: scaffold The MASK repo with pinned toolchain and licence gate` on branch `mac-v1` (parent `4253722`; `main` untouched; working tree clean after commit).

## What I implemented (Steps 2 to 7; Step 1 was the controller's)

- `pyproject.toml`: project `the-mask` 0.1.0, `requires-python = ">=3.12,<3.13"`, hatchling backend with `packages = ["src/themask"]`, the 15 runtime pins and 8 dev pins, `[tool.pytest.ini_options]` (`testpaths`, marker `slow`), `[tool.ruff] line-length = 100`, `[tool.mypy] strict = true, ignore_missing_imports = true, files = ["src"]`. No `[tool.briefcase]` (Task 25). I compared both dependency lists to the brief's text programmatically: all 23 strings identical, same order.
- `.python-version` = `3.12` (written by `uv python pin 3.12`).
- `src/themask/about.py`: `APP_NAME = "The MASK"`, `OWNER_NAME = "<owner name — set in about.py>"` (compared against the brief's text: identical, em dash included), `VERSION = "0.1.0"`.
- `src/themask/errors.py`: `MaskError(Exception)` with `user_message: str` (constructor takes the message positionally and also passes it to `Exception`, so `str(e)` equals it), and subclasses `UnsupportedFileError`, `ProtectedFileError`, `ScannedPdfError`, `CaseCorruptError`, `LeakBlockedError`.
- `src/themask/__init__.py`: re-exports `about.VERSION` as `__version__` (the plan's File Structure lists `__version__`; one source of truth).
- `tests/conftest.py`: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at import, plus fixture `data_dir(tmp_path) -> Path` (returns the fresh per-test `tmp_path`). Nothing else.
- `tests/test_licences.py`: the brief's gate with the `ACCEPT` tuple verbatim plus `"Artistic"` and a one-line comment (resolution 1). I added type hints and wrapped lines to 100 columns; logic unchanged.
- `tests/test_about.py`: the brief's three assertions (`APP_NAME`, `VERSION`, `issubclass(LeakBlockedError, MaskError)`), plus one extra parametrized test (5 cases) that every error class is a `MaskError` and exposes `user_message` (and `str()`), because the brief produces that interface but names no test for it.
- `README.md`: what it is, requirements, run from source (`uv sync`, `uv run python -m themask`), develop commands, what the licence gate does.
- `.gitignore`: unchanged (every entry the brief needs was already there).
- `uv.lock` (1782 lines) is committed: produced by `uv sync`, pins the exact resolved environment.

## uv sync resolution notes (exact)

- **All pins resolved** on CPython 3.12.14 / macOS arm64: `Resolved 120 packages in 2.09s`. No resolver errors, no replacement versions needed (resolution 3 not triggered).
- **Model dependency spelling that worked:** the brief's direct URL, verbatim, in `[project.dependencies]`: `en_core_web_md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl`. **uv accepted it** (resolved it and downloaded the wheel); the `[tool.uv.sources]` fallback was **not** needed.
- **But hatchling refused it** when uv built the project (first `uv sync` failed after resolving and downloading):
  `ValueError: Dependency #4 of field project.dependencies cannot be a direct reference unless field tool.hatch.metadata.allow-direct-references is set to true`.
  Fix: added `[tool.hatch.metadata]` / `allow-direct-references = true` (with a one-line comment) to `pyproject.toml`. This keeps the dependency line exactly as the brief has it; it is the only addition to `pyproject.toml` that the brief did not list.
- **The spaCy model wheel is downloaded once:** first run printed `Downloading en-core-web-md (31.9MiB)` / `Downloaded en-core-web-md`. The second `uv sync` installed from uv's cache: `+ en-core-web-md==3.8.0 (from https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl)`, `Installed 115 packages`.
- `uv.lock` pins the model wheel by URL and hash: `sha256:5e6329fe3fecedb1d1a02c3ea2172ee0fede6cea6e4aefb6a02d832dba78a310`.
- **`Artistic` was needed.** Without it the gate fails with exactly one hit and no other:
  `text-unidecode: Artistic License; Artistic License; GNU General Public License (GPL); GNU General Public License v2 or later (GPLv2+)`.
  Dependency chain (`uv tree --invert --package text-unidecode`): `text-unidecode` ← `python-slugify` ← `cookiecutter` ← `briefcase` (dev group). `uv tree --no-dev` contains no `text-unidecode`, so it is not in the runtime closure. No other GPL/AGPL hit, so BLOCKED was not triggered.

## TDD evidence

**RED 1** (tests written, `uv sync` done, nothing under `src/` yet; expected because `themask` does not exist):
```
$ uv run pytest -q
ERROR collecting tests/test_about.py
tests/test_about.py:3: in <module>
    from themask.about import APP_NAME, VERSION
E   ModuleNotFoundError: No module named 'themask'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.15s
```

**RED 2** (licence gate alone, `ACCEPT` exactly as printed in the brief, before the `Artistic` ruling; expected because of `text-unidecode`):
```
$ uv run pytest -q tests/test_licences.py
E   AssertionError: assert ['text-unidec...ter (GPLv2+)'] == []
E     Left contains one more item: 'text-unidecode: Artistic License; Artistic License; GNU General Public License (GPL); GNU General Public License v2 or later (GPLv2+)'
1 failed in 0.12s
```
This also proves the gate can actually fail on a GPL-bearing distribution (it is not vacuous).

**GREEN** (after adding `"Artistic"` and creating `about.py`, `errors.py`, `__init__.py`, `conftest.py`), the brief's exact chain:
```
$ uv run pytest -q && uv run ruff check src tests && uv run mypy src
........                                                                 [100%]
8 passed in 0.13s
All checks passed!
Success: no issues found in 3 source files
(exit 0)
```
Output is pristine; `uv run pytest -q -W error` also passes (8 passed), so no warnings are hiding. `uv run ruff format --check src tests` reports `6 files already formatted`.

## Additional verification (nothing of this is committed)

- **Fresh clone** of the repo into the scratchpad: `uv sync --locked` then pytest, ruff, mypy: 8 passed, ruff clean, mypy clean. So the commit is self-sufficient and `uv.lock` is in sync with `pyproject.toml` (`uv lock --check` also OK). Clone deleted afterwards.
- **conftest contract** (throwaway test outside the repo, `QT_QPA_PLATFORM` unset in the environment): after loading `tests/conftest.py` the variable is `offscreen`; `data_dir` is an existing, empty `Path` directory and fresh for each test. 4 passed.
- **What the gate sees** (script in `scratchpad/task1-tools/inspect_licences.py`): 115 distributions installed; 5 contain "GPL" and all are legitimately accepted: `pycountry` (`LGPL-2.1-only`), `python-stdnum` (`LGPL`), `PySide6_Essentials` and `shiboken6` (`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, accepted through the LGPL alternative, as the brief predicted), `text-unidecode` (accepted through `Artistic`). No copyleft wording hides from the "GPL" trigger in this environment.

## Self-review findings

- Lines over 100 columns in `about.py` (docstring), `conftest.py` (comment) and `test_licences.py` (the new comment): shortened. The only remaining long lines are `pyproject.toml`'s model URL (cannot be shortened).
- Re-read the staged diff: only the brief's files plus `uv.lock`; no `__pycache__`, `.venv` or `.superpowers` content staged.
- Scope: nothing beyond the brief except the items listed under "Deviations and additions" below.

## Deviations and additions (all small)

1. `[tool.hatch.metadata] allow-direct-references = true` (required, see above).
2. `uv.lock` committed (the brief's `git add -A` includes it; it is the point of pinning).
3. `__init__.py` exports `__version__` from `about.VERSION`.
4. One extra parametrized test for the `user_message` contract.
5. README carries a sentence saying the `python -m themask` entry point arrives in a later step (it does not exist yet; `__main__.py` is created later in the plan). Remove that sentence when the entry point lands.

## Concerns for the controller (informational, none blocks)

1. **The licence gate, as specified, has edges.** I did not change it (the brief gives the code verbatim; the only ruling was `Artistic`), but demonstrated them with synthetic strings:
   - `ACCEPT` entries match as case-insensitive substrings, so short ones match inside ordinary words: `"GPLv3, redistribution permitted under the terms"` is accepted (`MIT` in "per**mit**ted"), `"GPL-3.0-only (see example below)"` too (`MPL` in "exa**mpl**e"). Matters only if a future dependency puts prose or a full licence text in its `License` field.
   - A classifier-only `GNU Affero General Public License v3` contains no "GPL" substring, so the trigger never considers it. (`... (AGPLv3+)` and `AGPL-3.0-...` are caught.)
   - `MIT AND GPL-3.0-only` is accepted (an AND is treated like an OR).
   - Distributions with no licence metadata are invisible to it: `cookiecutter 2.7.1` (dev-only via Briefcase; its `dist-info/licenses/LICENSE` is BSD-style) and `the-mask` itself (no `license` field set; that is the owner's decision).
   None of these occurs in today's environment (checked all 5 GPL-bearing distributions and searched for Affero/"General Public" wording). A hardening follow-up is cheap if you want one.
2. **`MaskError` requires its message** (`CaseCorruptError()` with no argument raises `TypeError`). The plan's downstream uses pass a string (`UnsupportedFileError("...")`, `ScannedPdfError("...")`), but Task 17's `decrypt` is described only as "raises `CaseCorruptError`", so that implementer must supply a message.
3. **Version is written in two places** (`pyproject.toml` and `about.VERSION`; Task 25's Briefcase config will be a third). Only `VERSION == "0.1.0"` is tested, as the brief asks.
4. **Ruff's default rule set does not include E501**, so `line-length = 100` governs `ruff format` only; `ruff check` will not flag long lines. (Formatter output is clean.)

## Files changed (commit `272fd49`, 10 files, +2025)

`.python-version`, `README.md`, `pyproject.toml`, `uv.lock`, `src/themask/__init__.py`, `src/themask/about.py`, `src/themask/errors.py`, `tests/conftest.py`, `tests/test_about.py`, `tests/test_licences.py`.
Not touched: `.gitignore`, `docs/`, `~/Desktop`, branches (`main` still `4253722`).

---

# Fix round 1 (ruling R6): the licence gate is hardened

**Commit:** `ed46990 test: harden the licence gate against GPL and AGPL metadata shapes`. Only `tests/test_licences.py` changed (364 insertions, 20 deletions). It resolves concern 1 of the first report (the gate's edges); the other concerns are unchanged. Branch `mac-v1`, working tree clean.

## What was wrong, reproduced before I changed anything

I ran the review's vectors through the committed gate logic, loaded straight from git HEAD (`scratchpad/task1-tools/red_against_old_gate.py`). The old gate judged 6 of 14 wrongly:

| vector (as the old flat string) | old verdict | wanted |
|---|---|---|
| `GPL-3.0-only`, `AGPL-3.0-only` | fail | fail |
| `MIT AND GPL-3.0-only` | pass | **fail** |
| pasted GPL preamble + its GPLv3 classifier | pass ("per**mit**ted" matched `MIT`, "exa**mpl**e" matched `MPL`) | **fail** |
| pasted AGPL text (no "GPL" in it) | pass, not even examined | **fail** |
| classifier-only `GNU Affero General Public License v3` | pass, not even examined | **fail** |
| `GPL-3.0-only (see example below)` | pass | **fail** |
| `GPL-3.0-or-later; MIT License` | pass | **fail** |
| `LGPL-2.1-only`, `LGPL`, PySide6 dual, text-unidecode dual, `MIT-CMU`, `MPL-2.0` | pass | pass |

Finding (d) also reproduced: with `acceptable = lambda t: True` the committed live test still passed, so nothing proved the gate could fail.

## What changed (R6 points 1 to 4)

The gate now keeps what a distribution declares in three separate pieces (`Declared`: `License-Expression`, legacy `License`, classifiers), because they count differently.

1. **Whole-word matching.** An ACCEPT entry matches only when it is not inside another word: `permitted`, `example`, `sample`, `disclaimer` no longer match `MIT`, `MPL`, `ISC`. A version may follow directly (`LGPLv3`, `Apache2`) and a dash may continue it (`LGPL-2.1-only`, `MIT-CMU`).
2. **Operators and sources.** If `License-Expression` is present it is the whole answer: `OR` is a choice, `AND` needs both sides, classifiers are ignored. Without it, the `License` field counts when it names an acceptable licence; a `License` field that names GPL/AGPL with no acceptable alternative fails whatever the classifiers say; if it says nothing useful (empty, `UNKNOWN`) one acceptable classifier is enough, so a dual LGPL+GPL classifier pair passes. A name never counts as acceptable if it itself names GPL, AGPL, General Public or Affero (the Lesser and Library variants excepted), so the AGPL guard is now case-insensitive and covers spelled-out names.
3. **Trigger** widened to the case-insensitive `GPL|GENERAL PUBLIC|AFFERO`, applied to all three sources with whitespace and line breaks squashed (so a wrapped "General\n Public" is still seen).
4. **Tests** (42 in `tests/test_licences.py`): 20 refused vectors, 16 permitted vectors, 4 "not even examined" vectors, a scan over five planted distributions (real `importlib.metadata` parsing, including a folded multi-line `License:` header) that must report `gpl`, `pasted` and `affero` by name and spare `fine` and `dual`, and the live-environment test, which now calls the same `find_violations` function. All the controller's vectors are in; so is everything from the review's (a) to (d).

## Judgement calls to confirm or overrule

- **A small SPDX parser instead of the literal "split on OR, check AND operands".** The literal reading mis-accepts parenthesised expressions: I checked `(MIT OR GPL-3.0-only) AND GPL-2.0-only` and a plain split says acceptable (wrong), the parser says refused. The parser also understands `WITH` (`GPL-2.0-only WITH Classpath-exception-2.0 OR MIT` passes through its MIT side; the GPL side alone does not) and fails closed on a broken expression.
- **Stricter than "as today" in one place:** a legacy `License` field that names GPL/AGPL and offers no alternative fails even if a classifier says MIT (the review's `GPL-3.0-or-later; MIT License` shape, when it comes from the `License` field). A `License` field that is itself acceptable still rescues GPL classifiers, as ruled (text-unidecode).
- **Prose dual licences are refused, not guessed at.** `Dual licensed under the MIT license or the GPL, at your option` fails (pinned by a test); an SPDX-style `A OR B` passes in either field. This matters for the live environment: **PySide6_Essentials and shiboken6 publish their dual in the legacy `License` field, not `License-Expression`**, so the `License` field is tried as an SPDX expression first.
- A digit may precede an accepted word, so `0BSD` counts as BSD.
- The trigger is exactly the ruled regex. A bare "GNU Public License" (no GPL, General Public or Affero) is therefore not noticed; adding `|GNU` would catch it. Stated in the module docstring.

## Evidence

**RED (test-first):** the new tests written against the not-yet-existing API: `NameError: name 'Declared' is not defined`, `1 error during collection`.

**GREEN, the covering command:** `uv run pytest tests/test_licences.py -q` gives `42 passed in 0.26s`.
**Full chain, once**, then repeated from a fresh clone of the committed tree with `uv sync --locked`: `uv run pytest -q && uv run ruff check src tests && uv run mypy src` gives `49 passed`, `All checks passed!`, `Success: no issues found in 3 source files`, exit 0. Also clean: `ruff format --check` (6 files already formatted), `pytest -W error` (49 passed), no line over 100 columns.

**Live environment still passes, for the right reasons** (`scratchpad/task1-tools/live_and_table.py`). 115 distributions installed; the widened trigger examines exactly the same 5 as before; `find_violations` returns `[]`:

| distribution | decided by | declared |
|---|---|---|
| pycountry 26.2.16 | License-Expression | `LGPL-2.1-only` |
| PySide6_Essentials 6.12.0 | License | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` |
| shiboken6 6.12.0 | License | same |
| python-stdnum 2.2 | License | `LGPL` |
| text-unidecode 1.3 | License | `Artistic License` (its GPL classifiers are the other half of the dual) |

On the earlier 14 vectors the new gate gets 14 of 14 right (old: 8 of 14).

**Mutation testing** (`scratchpad/task1-tools/mutate_gate.py`; each mutation is applied to a scratch copy of the test file, never the repo file, and counts as killed only if the suite then fails): 31 mutants, 31 killed. Examples: `acceptable` always True, trigger never fires, raw-substring matching, AND as OR, OR as AND, trigger back to bare `GPL`, case-sensitive guard, Affero or Lesser exemption dropped, classifiers allowed to override a License-Expression, `WITH` not understood, unbalanced parenthesis not detected, broken expression treated as acceptable, scan returns nothing, metadata fields not read. The first run left two alive (raw substrings, and classifier veto) because the GPL veto alone already caught every GPL-flavoured string; I added vectors that only whole-word matching and the classifier veto can pass (`permitted is not MIT`, `sample is not MPL`, `an AGPL classifier never counts`), then widened the list to 31. (One apparent survivor after a docstring edit was a stale mutation target, not a live mutant; fixed and re-run.)

## Limits that remain (also in the module docstring)

- A distribution with no licence metadata at all is invisible: `cookiecutter 2.7.1` (dev-only via Briefcase; its shipped `LICENSE` is BSD-style) and `the-mask` itself. Licence files are not read.
- Wording that avoids "GPL", "General Public" and "Affero" is not noticed (see above).
- A false refusal is possible for exotic metadata (for example a pasted LGPL text, which quotes the GPL by name). It shows up as a failing test that names the distribution, which is the safe direction.

## Check it yourself

1. `uv run pytest tests/test_licences.py -q` should print `42 passed`.
2. Break the gate on purpose: in `tests/test_licences.py` make `acceptable` start with `return True`, run the same command (tests fail), then `git checkout tests/test_licences.py`.
3. Re-run the review's table against the old logic: `.venv/bin/python scratchpad/task1-tools/red_against_old_gate.py scratchpad/task1-tools/old_licences.py` (scratchpad = the session scratchpad directory).
4. Re-run all mutants: `.venv/bin/python scratchpad/task1-tools/mutate_gate.py <a scratch directory>`.
