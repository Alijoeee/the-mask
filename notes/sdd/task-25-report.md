# Task 25 report: The MASK.app for the owner's Mac (Briefcase, ad-hoc signed)

Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-25`, branch `task-25` (from `mac-v1` 6bec7ea).
Commit: `1cdb13a build: Briefcase packaging for macOS, ad-hoc signed` (8 files, 430 insertions, 1 deletion).
Scope as ruled in R89: Steps 1-4 and 7 (icon, Briefcase configuration, build script, first build with
size and signature checks, README). Step 5 (install into /Applications and open) and Step 6 (the owner's
offline smoke test) are not done, by instruction. Nothing was installed into /Applications and the app was
never opened with the real Keychain or the real data folder.

## 1. In plain words

The app builds. `bash packaging/build_mac.sh` makes `build/themask/macos/app/The MASK.app` (547 MiB, one
arm64 slice, ad-hoc signed, signature verifies deeply) and a zip of it. I started the built app without a
window (offscreen, with a temporary data folder and a temporary home): it loaded its language model in 1.7 s,
opened no internet connection, and made files only in the temporary data folder. I also ran the bundle's own
Python over a Word and a PDF contract: analysis, masking, leak gate and the encrypted case file all work
from inside the bundle, with no value of the contract left in the masked file.

Four values in the brief could not be used as written, each for a reason I checked in Briefcase's own
code or in the build (section 3): the macOS minimum is 14.0 not 13.0; the app section has no `requires`
list; `project_name` and `version` are not repeated in `[tool.briefcase]`; and Briefcase insists on a licence,
which the project does not have. One more thing is the owner's call: the real minimum macOS (section 7, concern 1).

## 2. What I implemented

| File | What |
|---|---|
| `packaging/make_icon.py` | Pillow draws an eye mask (warm white, eye holes cut out, soft shadows) on a dark rounded square on Apple's 1024 px icon grid (824 px body, transparent margin), at 2x and reduced for smooth edges. `iconutil` builds the `.icns` from the ten standard sizes (16 to 512, and the @2x forms). `uv run python packaging/make_icon.py [out_dir]`. Deterministic: two runs give identical sha256 for both files. No `__init__.py` on purpose (a package called `packaging` would hide the one pip and pytest import). |
| `packaging/icon/themask-1024.png` | 92,093 bytes, 1024x1024 RGBA, corner pixel transparent. |
| `packaging/icon/themask.icns` | 310,397 bytes. `file` says: `Mac OS X icon, 310397 bytes, "ic12" type`. |
| `packaging/build_mac.sh` | `set -euo pipefail`; works from any directory; removes `build/themask` and old `dist/*.app.zip` first (see 3f); then `uv run briefcase create macOS app`, `build macOS app`, `package macOS app -p zip --adhoc-sign`, all with `--no-input`; prints the paths of the app and the zip. |
| `pyproject.toml` | `[tool.briefcase]` (bundle `local.themask`, licence), `[tool.briefcase.app.themask]` (formal name "The MASK", one-line description, `sources = ["src/themask"]`, `icon = "packaging/icon/themask"`), `[tool.briefcase.app.themask.macOS]` (`universal_build = false`, `min_os_version = "14.0"`, `requires = []`). |
| `README.md` | New section "Install on your Mac" (build, install on this Mac, open on another Mac, where the data and log live, no network, a DIY `lsof` check). The "run from source" section is unchanged. The lint line of "Develop" now lists `src tests tools packaging`. |
| `.gitignore` | `.briefcase/` (Briefcase 0.4.6 makes its build venv there). `build/` and `dist/` were already ignored; `logs/*.log` (Briefcase writes one when a command fails) is covered by `*.log`. |
| `tests/test_packaging.py` | Five tests, see section 5. |

## 3. Deviations from the brief and the controller's decisions, with the evidence

a. **`min_os_version = "14.0"`, not "13.0".** I built with 13.0 first, as specified. `briefcase create` stopped at
   "Installing requirements" (exit code 200):

   ```
   ERROR: Could not find a version that satisfies the requirement PySide6-Essentials==6.12.0 (from versions: 6.6.0, ... 6.11.2)
   ERROR: No matching distribution found for PySide6-Essentials==6.12.0
   This may be because an arm64 wheel that is compatible with Python 3.12 and a minimum macOS version of 13.0 is not available.
   ```

   Why: Briefcase runs `pip install --platform macosx_13_0_arm64 --only-binary :all:`, and `uv.lock` shows that
   PySide6-Essentials 6.12.0 and shiboken6 6.12.0 exist only as `cp310-abi3-macosx_14_0_universal2.whl`.
   14.0 is the lowest value pip accepts for the pinned wheel, so it is the small fix. (It also becomes
   `LSMinimumSystemVersion` in Info.plist: 14.0.) The dependency pins are untouched. See concern 1 for what 14.0 does and does not promise.

b. **No `requires` list in the app section.** Briefcase 0.4.6 reads `[project]` itself: `config.py`,
   `merge_pep621_config`, "Briefcase requires is cumulative over PEP621 dependencies". So the 15 pinned
   runtime dependencies (the model wheel URL included, same strings, same order) already are the app's
   requirements. I measured what a copy does: with the 15 pins pasted into `[tool.briefcase.app.themask]`
   Briefcase gets 30 requirements, 15 distinct. A copy would be installed twice and is exactly the drift
   the controller wanted to prevent. The drift guard is therefore a test of the effective list (section 5), not of two lists.
   `requires = []` in the macOS section is kept as the brief has it; it is inert (an empty list adds nothing).

c. **No `project_name` and no `version` in `[tool.briefcase]`.** Both come from `[project]` (`the-mask`,
   `0.1.0`), where `maybe_update` in the same function fills them. `project_name = "The MASK"` is not a valid
   PEP 621 name and makes Briefcase print a warning banner on every command ("may become an error in a
   future version"); I saw that banner in the first attempt. The macOS app template does not use
   `project_name` at all (I grepped the template: it uses formal_name, app_name, bundle, version, module_name,
   min_os_version, universal_build and a few more). A second `version` would be a third place to bump
   (Task 1's report flagged this); the test ties the Briefcase version to `about.VERSION`.

d. **`license = "LicenseRef-Proprietary"`** in `[tool.briefcase]`. Briefcase 0.4.6 refuses to read a config without a licence
   ("does not contain a valid PEP 639 license definition"), and `[project]` has none ("license from pyproject" was not available;
   Task 1's report: the owner's decision). I put "all rights reserved" so the build runs; the macOS app template does not use the
   licence anywhere in its output. The owner can change the line whenever they choose a licence.

e. **The description is set in the app section**, because `[project].description` is 83 characters and Briefcase warns above 80.
   The app's: "Masks confidential values in contracts before they go to an AI tool." (68).

f. **The zip is `dist/The MASK-0.1.0.app.zip`**, not `The MASK-0.1.0.zip`: that is how Briefcase 0.4.6 names a macOS zip
   (`distribution_path` in `platforms/macOS/__init__.py`). The script prints the real path.

g. **`--no-input` and a clean build in the script.** If `build/themask` exists, `briefcase create` asks "overwrite?" and, without an
   answer (or with `--no-input`), aborts quietly and the next two commands go on to build and zip the OLD app. A second run after
   a merge would then ship stale code. So the script deletes `build/themask` and the old zip first; every run is a clean build.
   `--no-input` turns any unexpected prompt into an error instead of a hang. I ran the script twice (the second time over an existing
   `build/` and `dist/`): both exit 0.


## 4. The build, and the checks of Step 4

Versions: Briefcase 0.4.6 (`uv run briefcase --version`); builder Python 3.12.14 (the worktree's `.venv`, uv 0.12.5); the Python inside the
app is Python.framework **3.12.10** (Briefcase support package `Python-3.12-macOS-support.b10`; `sys.version` and its Info.plist say 3.12.10, the
support package's `VERSIONS` file says "Python version: 3.12.14", the builder's); stub `GUI-Stub-3.12-b16`; app template
`briefcase-macOS-app-template` v0.4.6, sha be2db76a7e4d17ba54cd61c749e3f326e1503233; build machine macOS 27.0.1 (26A434), arm64.

Time: about 3 minutes the first time the wheels were fetched, 1 min 43 s with warm caches (log: `time bash packaging/build_mac.sh`).
Downloads: template (git), support package, stub (S3), 147 pip downloads incl. the model wheel from GitHub. No other network use.

| Check | Command | Result |
|---|---|---|
| Size | `du -sh "build/themask/macos/app/The MASK.app"` | **547M** (546.5 MiB = 559,660 KiB = about 573 MB in Finder's units). Limit 600M: 53 MiB to spare. |
| Where the size is | `du -sh` of the parts | `Resources/app_packages` 440M (PySide6 192, en_core_web_md 54, phonenumbers 22.5, spacy 21.5, pycountry 21.3, numpy 20.5, PIL 11.2, lxml 10.8, cryptography 10.7), `Frameworks` (Python.framework) 102M (stdlib 63, of which `test/` 31), `Resources/app` 740K, `_CodeSignature` 3.2M. |
| Signature | `codesign -dv --verbose=2 ... \| grep -E 'Signature=adhoc\|Identifier'` | `Identifier=local.themask.themask`, `flags=0x2(adhoc)`, `Signature=adhoc`, `Format=app bundle with Mach-O thin (arm64)`, `TeamIdentifier=not set`, `Sealed Resources ... files=10622` |
| Signature verifies | `codesign --verify --deep --strict --verbose=2 ...` | `valid on disk`, `satisfies its Designated Requirement` (exit 0). The designated requirement is `cdhash H"3c8f8cba..."`: the app's identity to macOS is its exact bytes (see concern 3). |
| Info.plist | PlistBuddy | `CFBundleIdentifier local.themask.themask`, `CFBundleShortVersionString 0.1.0`, `LSMinimumSystemVersion 14.0`, `MainModule themask` |
| The model is inside | `Resources/app_packages/en_core_web_md/` (54M; `en_core_web_md-3.8.0/` with `meta.json`, `config.cfg`, `ner/`, `parser/`, `tok2vec/`, `vocab/`, ...) and `en_core_web_md-3.8.0.dist-info/` | present (the engine's own `spacy.util.is_package` check needs the dist-info, and passes inside the bundle) |
| Our YAML | `Resources/app/themask/detect/nlp_config.yaml` | present. `diff -r src/themask "Resources/app/themask" -x __pycache__` prints nothing: the bundled code is the source, 43 .py files. It is the only non-.py file in `src/themask`. |
| Other data files | `presidio_analyzer/conf/*.yaml` (16 files), `tldextract/.tld_set_snapshot` | present |
| Nothing dev-only inside | `ls app_packages \| grep -i -E '^(pytest\|briefcase\|ruff\|mypy\|faker\|reportlab\|cookiecutter\|dmgbuild)'` | none. 74 distributions in all. (Pillow IS inside: pdfplumber depends on it. reportlab is not.) |
| The zip | `dist/The MASK-0.1.0.app.zip` | 194,205,742 bytes. `ditto -x -k` into an empty folder gives the same 15,747 entries as the built app, framework symlinks intact, and `codesign --verify --deep --strict` on the copy passes. |
| Offline start, no window | `HOME=<tmp>/home THEMASK_DATA_DIR=<tmp>/data QT_QPA_PLATFORM=offscreen "The MASK.app/Contents/MacOS/The MASK"`, waited for the log | log: `themask.ui.workers INFO engine loaded seconds=1.70` (first build: 1.79), process alive until I sent SIGTERM (exit 143), `lsof -i -a -p <pid>` printed nothing (no internet sockets), only `cases/` and `logs/themask.log` were made, the temporary home stayed empty. stderr held only the stub's "No Python NSLog handler found" notice and two Qt offscreen notices. The Keychain is not asked at start: `CaseStore._scan` fetches the key only when a case file exists, and the temporary folder had none. |

Extra checks I made because the owner will rely on the zip and on the Keychain code, none of them part of the brief:

1. **In-bundle functional probe (31/31 passed, both builds).** A throw-away C launcher (in the scratchpad, not in the repo) `dlopen`s the bundle's own
   `Python.framework` and calls `Py_BytesMain`, with the same `sys.path` as the stub (`Resources/app`, `Resources/app_packages`). The probe script checks: all 17 key
   modules (themask, PySide6, spacy, the model, lxml, pdfplumber, pypdfium2, cryptography, keyring, docx, presidio, tldextract, phonenumbers, schwifty, stdnum, rapidfuzz, platformdirs)
   are imported from inside the bundle; Qt's plugin path is inside it and `libqcocoa.dylib` is there; `keyring.get_keyring()` is `keyring.backends.macOS.Keyring`
   (backend discovery through the dist-info works in the bundle; the Keychain itself is not touched); the network guard raises on a socket; `Engine()` loads;
   then for `supply-01.docx` and `supply-01.pdf` of the corpus: load, analyse (43 groups each), `export_case` (not blocked, no leak hits), none of the 41 values of `supply-01.truth.json`
   is left in the masked file, and the case is saved encrypted with `cryptography` (in-memory key, not the Keychain) and read back with 43 key entries.
2. **Qt's Cocoa platform starts from the bundle:** `QApplication` with the `cocoa` plugin from the bundle's PySide6 reports `cocoa`, style `macos`, one screen (no window shown, no data touched).
3. **Static link check** of all 454 Mach-O files: every `@rpath`, `@loader_path` and `@executable_path` reference resolves inside the bundle, except 37 references in optional Qt
   pieces that need Qt add-on frameworks PySide6-Essentials does not ship (23 in QML plugins, 7 in Designer plugins, 7 in the SQL drivers, the virtual keyboard, the QtPdf image plugin and a QML profiler plugin). A QtWidgets app loads none of them.
4. **minos scan** (the macOS version each binary says it needs, arm64 slice): 26.0 in 29 files (27 PySide6 Python modules, 2 shiboken6); 14.4 in 208 (Qt frameworks and plugins);
   14.0 in 19 (numpy); 13.0 in 1 (pypdfium2); 11.0 in 196 (Python.framework, spaCy, PIL, lxml, thinc, rapidfuzz). See concern 1.

## 5. Tests and TDD evidence

`tests/test_packaging.py` (5 tests; Briefcase's own `parse_config`, the function `briefcase create` calls, reads `pyproject.toml` with a mock console):

1. `test_briefcase_installs_exactly_the_runtime_dependencies`: the effective `requires` of the macOS app equals `[project].dependencies`, string for string.
2. `test_briefcase_reads_the_configuration_without_a_warning`: no warning banner, no warning.
3. `test_the_bundle_carries_the_name_and_version_the_app_reports`: `formal_name == APP_NAME`, `version == VERSION`.
4. `test_the_sources_icon_and_architecture_are_those_of_the_plan`: sources, `__main__.py`, the `.icns` the config names exists (Briefcase only prints a notice for a missing icon and uses its own), `universal_build is False`.
5. `test_make_icon_builds_the_png_and_an_icns_with_every_size` (skipped without `iconutil`): runs the script in a subprocess into `tmp_path`; the PNG is 1024x1024 RGBA with a transparent corner; the `.icns` starts with `icns` and its header length is the file's; `iconutil --convert iconset` takes it apart again into exactly the ten expected files and sizes.

RED, before any implementation (`uv run pytest tests/test_packaging.py -q -p no:cacheprovider`):

```
FAILED tests/test_packaging.py::test_briefcase_installs_exactly_the_runtime_dependencies
FAILED tests/test_packaging.py::test_briefcase_reads_the_configuration_without_a_warning
FAILED tests/test_packaging.py::test_the_bundle_carries_the_name_and_version_the_app_reports
FAILED tests/test_packaging.py::test_the_sources_icon_and_architecture_are_those_of_the_plan
FAILED tests/test_packaging.py::test_make_icon_builds_the_png_and_an_icns_with_every_size
5 failed in 0.21s
```
The four configuration tests: `BriefcaseConfigError: Briefcase configuration error: No tool.briefcase section in pyproject.toml`. The icon test: `.venv/bin/python: can't open file '.../packaging/make_icon.py': [Errno 2] No such file or directory`. Both expected: neither exists yet.

GREEN, after the script and the configuration: `5 passed in 0.95s`.

Mutation checks (each broken `pyproject.toml` fails exactly the intended test; the file was restored, sha256 equal):

| Break | Failing test |
|---|---|
| the 15 pins copied into the app section | 1 (30 != 15 requirements) |
| a macOS-level extra requirement | 1 |
| `project_name = "The MASK"` in `[tool.briefcase]` | 2 (the warning banner) |
| `version = "0.1.1"` | 3 |
| `formal_name = "The Mask"` | 3 |
| `icon = "packaging/icon/themaks"` | 4 |
| `universal_build = true` | 4 |

## 6. Quality gates (final tree)

```
uv run ruff check src tests tools packaging     All checks passed!
uv run ruff format --check src tests tools packaging   119 files already formatted
uv run mypy src                                 Success: no issues found in 43 source files
uv run pytest -q                                2724 passed in 87.67s (the five new tests included; the run before it, 92.70s, gave the same 2724)
uv run pytest tests/test_licences.py -q         42 passed (the licence gate is green; Briefcase's tooling, text-unidecode under R4, did not trip it)
```
No warning or error in the pytest output (grep for warn, error, deprecat: nothing).

## 7. Concerns and decisions for the controller

1. **The real macOS minimum is not 14.** `min_os_version = "14.0"` is only what pip needs for the wheel tag. The Qt frameworks say 14.4, but PySide6 6.12.0's own
   Python modules (`QtCore.abi3.so`, `QtGui`, `QtWidgets`, shiboken6, 29 files in all) are marked `minos 26.0` (SDK 26.0), both slices. dyld does not enforce this for a loaded library
   (I made a dylib marked minos 99.0 and `ctypes.CDLL` loaded it on macOS 27.0.1), so it may still run on 14 or 15, but a library built for 26 can use symbols that older systems lack. I could only
   test on this Mac, macOS 27.0.1. If you want Info.plist to tell the truth, set `min_os_version = "26.0"` (pip accepts it, all wheels are tagged 14 or lower); the README says "macOS 14 or later" and
   would change to 26. Your call; 14.0 is what I committed. The owner's Mac is on 27, so nothing changes for the smoke test.
2. **Deviations 3a-3g above** from the binding decisions. Each is a change of how, not of what: the app has the same 15 pins, name, version, icon, one arm64 slice. If you prefer the literal copies of
   `requires`, `project_name` and `version`, they can be added back; the tests would then fail on purpose (1: 30 requirements; 2: the banner), so the reason stays visible.
3. **Keychain prompts after each rebuild (my reading of how macOS works, not tested: I did not touch the Keychain).** The app's designated requirement is its cdhash, so every rebuilt app is a new program to macOS
   and it may ask again whether it may use the "The MASK" Keychain item. The README says so and says to choose Always Allow. This is the "ACL prompt" the earlier reviews left to the owner's smoke test.
4. **Size margin:** 547 MiB against 600M. If a later task adds weight, there are about 35 MiB of Qt that this app never loads (QML 20 MiB, translations 14, Designer/Assistant/Linguist/qmlls tools) and about 31 MiB of
   Python's `test` package, which Briefcase's `cleanup_paths` could remove. I did not trim anything: no need yet, and a trimmed Qt is one more thing to test.
5. **`std-nslog` is not installed** (the stub prints "No Python NSLog handler found" to stderr when started from a terminal). With it, stdout and stderr would go to the system log. I left it out: the macOS `requires` are empty as
   decided, and an app that handles contract text is better without a second place that text could land in by mistake.
6. **Not verified, by instruction or because it needs a person:** the real window under Cocoa (the platform plugin starts, no window was shown), the Dock icon, a file dragged from Finder, the native file dialog,
   Keychain prompts, anything on a macOS other than 27.0.1, a Mac other than this one (Gatekeeper's behaviour for the zip; the README text on that comes from Apple's documented behaviour, macOS 15 removed Control-click Open, not from a test).
7. **Left in the worktree** (all git-ignored): `build/` (646M: the app and Briefcase's support folder), `dist/` (the zip), `.briefcase/` (Briefcase's build venv). The scratch files of my checks are in the session scratchpad
   (`verify_bundle.sh`, `headless_run.sh`, `probe/`), not in the repo.
8. **Commit trailer:** the boilerplate prescribes `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; a generic attribution note in my session named a different model line. I used the boilerplate's, as the repo's earlier commits do.

## 8. Self-review

- Completeness: Steps 1-4 and 7 done; the brief's Interfaces are met except where section 3 says otherwise. `file packaging/icon/themask.icns` reports "Mac OS X icon". The script ends by printing the app and the zip paths.
- Quality: the first draft of `make_icon.py` had a leftover variable and an awkward shadow layer; both gone (one `shadow_of` helper serves both shadows). The glyph is centred optically: the measured bounding-box centre of the mask is (511.5, 512.0) in a 1024 picture.
  I looked at the icon at 16, 32, 64, 128, 256 and 512 px on a light and a dark background: it reads as a mask at every size.
- Discipline: no extra dependency, no trimming, no change to any source file. The only edits outside the brief's file list are `.gitignore` (`.briefcase/`) and the lint line in the README.
- Testing: tests check behaviour that nothing else checks (the effective requirement list Briefcase will use, the warnings, the icon file Briefcase would silently replace); mutation checks above prove each one can fail; output pristine.
- The directory is called `packaging/` as the brief says. It has no `__init__.py`, so it cannot hide the PyPA `packaging` package (pytest's `pythonpath = ["."]` would otherwise put it first). Verified: the whole suite passes.

## 9. Do it yourself

```bash
cd /Users/alijoeee/Developer/the-mask-worktrees/task-25
uv run pytest tests/test_packaging.py -q                     # 5 passed
file packaging/icon/themask.icns                             # Mac OS X icon ...
bash packaging/build_mac.sh                                  # 2-3 min, ends with the two paths
du -sh "build/themask/macos/app/The MASK.app"                # 547M
codesign -dv --verbose=2 "build/themask/macos/app/The MASK.app" 2>&1 | grep -E 'Signature=adhoc|Identifier'
codesign --verify --deep --strict --verbose=2 "build/themask/macos/app/The MASK.app"
find "build/themask/macos/app/The MASK.app" -name nlp_config.yaml -o -name meta.json -path '*en_core_web_md*'
# start it without a window, a temporary home and data folder, no Keychain:
T=$(mktemp -d); mkdir -p "$T/home" "$T/data"
HOME="$T/home" THEMASK_DATA_DIR="$T/data" QT_QPA_PLATFORM=offscreen "build/themask/macos/app/The MASK.app/Contents/MacOS/The MASK" &
sleep 12; cat "$T/data/logs/themask.log"                      # ... engine loaded seconds=...
lsof -i -a -p $!                                              # prints nothing
kill $!
```

---

## Fix report: ruling R92 (minimum macOS 26.0)

**Ruling.** Declare what the wheels support: `min_os_version = "26.0"` (PySide6's Python modules carry minos 26.0; 14.0 would
promise a floor the bundle cannot honour), "macOS 26 or newer" in the README's install section, the test that pins the effective
`requires` list stays, everything else in concerns 2-3 accepted as built, commit, no rebuild.

**This supersedes** every "14.0" and "macOS 14 or later" above (section 3a, the Info.plist row of section 4, concern 1 of section 7,
and the README of commit 1cdb13a). Those describe the first commit. Concern 1 is closed.

**Commit:** `b6e838e build: ask for macOS 26 or newer, as the PySide6 modules do (R92)` (3 files, 46 insertions, 9 deletions).

### What changed

| File | Change |
|---|---|
| `pyproject.toml` | `min_os_version = "26.0"` (was "14.0"). The comment says why: PySide6 6.12 and shiboken6 are tagged `macosx_14_0`, which is all pip checks, but their Python modules are marked as needing macOS 26.0. The next build writes `LSMinimumSystemVersion 26.0` into Info.plist. |
| `README.md` | The install section says the app "needs macOS 26 or newer", and that the other Mac "needs macOS 26 or newer as well". Every macOS the app now asks for is 15 or later, and macOS 15 removed Control-click and Open, so the "or, on macOS 14, Control-click" alternative is gone: the paragraph gives Open Anyway only, with one sentence saying the older way no longer works. |
| `tests/test_packaging.py` | One new test, written first (below). The five existing tests are untouched, the one for the effective `requires` list included. |

**The one addition beyond the ruling:** `test_the_bundle_asks_for_a_macos_new_enough_for_pyside6`. The ruling's reason is a fact about the wheels, so
the test reads that fact instead of repeating the number: with `vtool` it takes the minos of the arm64 slice of every `*.abi3.so` that sits
directly in the installed PySide6 and shiboken6 packages (the dev environment holds the very wheel the bundle is made from), and asserts
that the declared `min_os_version` is at least the highest. It fails if the number is ever lowered again, and also if a later PySide6 bump needs more than 26.
Skipped without `vtool` (part of the Xcode tools Briefcase needs anyway). It stands on its own: delete it and nothing else changes.

### TDD evidence

RED, with `min_os_version = "14.0"` still in place (`uv run pytest tests/test_packaging.py -q -p no:cacheprovider`):

```
>       assert declared >= needed
E       assert (14, 0) >= (26, 0)
FAILED tests/test_packaging.py::test_the_bundle_asks_for_no_older_a_macos_than_pyside6_needs
1 failed, 5 passed in 1.11s
```

(Expected: the PySide6 and shiboken6 modules need 26.0, the configuration declared 14.0. The test was renamed afterwards to the better English above; nothing else changed.)

GREEN, after the change to 26.0: `6 passed in 1.28s`.

Mutation check of the new test (pyproject restored afterwards, sha256 equal): declared 25.0 fails, 14.0 fails, 26.0 passes, 27.0 passes.

### Why no rebuild was needed, and what I checked instead

pip's own tag logic (`pip._internal.utils.compatibility_tags.get_supported`, cp312, platform `macosx_26_0_arm64`) accepts 1230 tags against 582 at
`macosx_14_0_arm64`, a superset, and all 74 wheels installed in the bundle built earlier are installable at 26.0 (read from their `.dist-info/WHEEL`
tags). So `briefcase create` picks the same wheels, numpy's `macosx_14_0_arm64` among them. The Briefcase check that the app's minimum is not below the support
package's (11.0) holds. Expected difference in the next bundle: `LSMinimumSystemVersion` 26.0, hence a new cdhash. Nothing else.

The `build/` and `dist/` in the worktree still hold the 14.0 build from before (their Info.plist says 14.0); the controller's final build replaces them.

### Gates on the final tree

```
uv run ruff check src tests tools packaging            All checks passed!
uv run ruff format --check src tests tools packaging   119 files already formatted
uv run mypy src                                        Success: no issues found in 43 source files
uv run pytest -q                                       2725 passed in 88.37s (the new test included; 2724 before)
```
No warning or error in the pytest output. The full suite ran just before the rename of the new test (its name only); after the rename I ran
ruff format, ruff check and `tests/test_packaging.py` again: clean, `6 passed in 1.35s`. The licence gate is part of the suite and passed.

### Still open

Only that the app has been run on macOS 27.0.1 alone, so the floor it now declares, 26, is the wheels' word, not something I could try on a Mac running 26.

---

## Fix report: review round 1 (Importants 1 and 2, rulings R93 and R94, minors M1-M4 and M9)

**Commit:** `001e7d6 build: lock the bundle's packages, trim what the app never runs, README fixes (review 1)` (7 files, 497 insertions, 18 deletions), on top of b6e838e.
One rebuild, as allowed, after the last change to a file the build reads. The tree was not yet committed when it ran, so its log says so
(`Built from commit b6e838e` and `WARNING: there are changes that are not committed`): that is the new line of the script doing its job.

### In plain words

Briefcase used to install the 15 top-level pins and let pip pick the newest of everything else, so the app held two packages the tests never ran on
(certifi, filelock). Now pip is told to keep to `uv.lock`, a new check proves the finished app has exactly the 74 locked packages at the locked versions
(and the script refuses to make the zip if not), and about 36 MiB of things the app never runs, among them 43 console scripts that carried the build folder
and the user name, are no longer in the app. The README no longer suggests `ditto` onto an older app, which merges instead of replacing.

### What changed

| Finding | Change | Where |
|---|---|---|
| IMPORTANT 1: `ditto` onto an existing app merges | The install section says: if an older app is in Applications, quit it and move it to the Trash first (Finder's Replace is fine); the Terminal way is `rm -rf "/Applications/The MASK.app"` and then `ditto`, run in the repository's root folder (the path stays relative, the section says from where) | `README.md` |
| IMPORTANT 2 / R93: transitive packages float | `uv export --locked --no-dev --no-hashes --no-emit-project --no-annotate --format requirements-txt -o build/constraints.txt --quiet` runs before `briefcase create`; the macOS section passes `requirement_installer_args = ["--constraint", "./build/constraints.txt"]`; new `tools/check_bundle_lock.py`, run between `briefcase build` and `briefcase package`, prints its result and fails the script on any difference | `packaging/build_mac.sh`, `pyproject.toml`, `tools/check_bundle_lock.py`, `tools/__init__.py` |
| R94 (minors 6-7): what the app never runs | `cleanup_paths` (14 globs, below) | `pyproject.toml` |
| M1 | "any attempt by the app's own code to open an internet connection fails", and "the evidence is what the system sees, not that promise" before the `lsof` check | `README.md` |
| M2 and M9 | the macOS prompt for the Documents folder at the first export; the repository must not be in a folder iCloud syncs (README and script header); if the app does not open, start the binary from Terminal to see the errors Finder hides | `README.md`, `packaging/build_mac.sh` |
| M3 | the script checks a zip exists before printing it (`nullglob`), prints `git rev-parse --short HEAD`, warns when the tree is dirty, says so when it is not a git checkout | `packaging/build_mac.sh` |
| M4 | the macOS-floor test pads both version tuples to three numbers before comparing, and skips with a reason when `vtool -h` (tried once) does not print its usage, i.e. when `/usr/bin/vtool` is only the Xcode stub | `tests/test_packaging.py` |
| (the README sizes) | about 535 MB and about 185 MB, from this rebuild | `README.md` |

**The `cleanup_paths`**, all as `**/...` globs below `build/themask/macos/app`: `app_packages/bin`; `PySide6/Designer.app`, `Assistant.app`, `Linguist.app`;
`PySide6/lrelease`, `lupdate`, `qmlformat`, `qmllint`, `qmlls`, `svgtoqml`; `PySide6/scripts`; `PySide6/Qt/libexec`; `PySide6/Qt/qml`;
`PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib`. No Qt framework is touched (QtNetwork, QtSql, QtQuick, QtQml stay: 78 frameworks).
*My reading of R94:* "the qmlls/uic/rcc/pyside6-* tools" is all of Qt's development tools, so besides qmlls, uic and rcc I also removed the rest of `Qt/libexec`
(qmlcachegen, qmlimportscanner, qmltyperegistrar), lrelease, lupdate, qmlformat, qmllint, svgtoqml and `PySide6/scripts` (the code behind the pyside6-* commands,
whose console scripts were in `bin/`). Nothing imports any of them: a grep of `PySide6/__init__.py` and `src/` finds no use, and the in-bundle probe below passes. Easy to narrow if you disagree.

### The question asked: how Briefcase 0.4.6 takes the constraint

- Key: `requirement_installer_args` (an `AppConfig` field, `config.py`). It is passed as `extra_installer_args=app.requirement_installer_args` at
  `platforms/macOS/__init__.py:353` (the single install pass of a non-universal build), on to `VirtualEnvironment.install_requirements`
  (`integrations/virtual_environment/base.py`), which appends it to pip's arguments after `--target`, `--platform` and `--only-binary :all:`.
  In the macOS section it replaces any app-level value (only requires, sources, test_requires, test_sources and permission add up).
- Path handling: `resolve_relative_args` (`integrations/file.py:184`) turns an argument into an absolute path against the project folder only if it starts with `./` or `../`
  (`RELATIVE_PATH_RE`) and the file exists. `build/constraints.txt` without the `./` would be handed to pip as typed and found (or not) relative to pip's working directory.
  So the value is `./build/constraints.txt`; and a missing file stops pip with an error instead of being skipped.
- Two things I tested rather than assumed: pip 26.2.1 accepts the model's `name @ URL` line in a constraints file (made a wheel by hand, `--no-index`), so the export is used whole;
  and `uv export -o FILE` also prints the whole file twice (80 lines on stdout, again on stderr), so the script adds `--quiet`. With `--quiet` a stale lock still stops the script: the error
  `The lockfile at uv.lock needs to be updated, but --locked was provided` is shown and the exit status is 2 (tried on a copy of the repository whose `pyproject.toml` I had changed).

### The new check, `tools/check_bundle_lock.py`

`uv run python -m tools.check_bundle_lock [path/to/The MASK.app]` (default: the app the script builds). It reads the dist-infos in the app's `app_packages`
(`importlib.metadata`), takes the packages `uv export --locked --no-dev --no-hashes --no-emit-project --no-annotate --format requirements-txt` lists, drops those whose marker is false
on this system (colorama is for Windows, jeepney and secretstorage for Linux), and prints one line per difference: a version that differs, a package in the app that the lock does not
hold for this Mac, a locked package missing from the app. Exit status 0 none, 1 differences, 2 the check could not be made (no app, no uv, uv failed). A package locked by the URL of a wheel
(the model) has the version of the wheel. The build script and the check ask uv with the same arguments, and a test sees to it that they stay the same.

### Evidence before the rebuild (nothing was built for these)

| What | Result |
|---|---|
| The check on the earlier app still in `build/` (built before R92 and before this round: macOS 14.0, no constraint) | `The app does not match uv.lock (2 differences): certifi is 2026.10.18 in the app, 2026.7.22 in uv.lock; filelock is 4.2.4 in the app, 4.2.1 in uv.lock`, exit 1: exactly the reviewer's 72 of 74, and no other kind of difference (so the marker logic agrees with pip's choices for the whole closure). Without an app: `There is no app at ...: build the app first.`, exit 2 |
| pip's own resolution with the constraint | `pip install --dry-run --target <tmp> --platform macosx_26_0_arm64 --only-binary :all: --constraint build/constraints.txt <the 15 requirements>` (the arguments Briefcase uses): exit 0, 74 packages would be installed, the check's `differences()` against the lock: none (certifi 2026.7.22, filelock 4.2.1) |
| The 14 cleanup globs on the old app | each matches exactly one item, about 30 MiB apparent size in all (`qml` 14.5, `qmlls` 4.9, `Assistant.app` 2.5, `qmlformat` 2.2, ...) |

### TDD evidence

RED, before any implementation:

```
tests/test_check_bundle_lock.py:  ModuleNotFoundError: No module named 'tools.check_bundle_lock'   (collection error, 1 error)
tests/test_packaging.py:          KeyError: 'requirement_installer_args'   and   KeyError: 'cleanup_paths'   -> 2 failed, 7 passed in 1.30s
```
Expected: neither the module nor the two settings existed. (The first draft of one message in the module said "does not lock it here" where the test said "for this Mac": the test won, the module was changed.)

GREEN: `tests/test_check_bundle_lock.py` 10 passed; with `tests/test_packaging.py` (now 9 tests) `19 passed in 1.88s`.

The tests: `test_check_bundle_lock.py` has made-up bundles for every kind of difference, versions compared as versions (`2026.07.22` equals `2026.7.22`), the model's wheel version, an unreadable export line refused,
the real `uv export` of this repository (every pinned runtime dependency is in the lock at its pin: the lock and `pyproject.toml` agree), and `main` for exit 0, 1 and 2 (skipped without uv).
`test_packaging.py` gains `test_briefcase_installs_the_versions_uv_locks` (the installer argument, the file the script writes, the same uv arguments as the check, the script runs the check),
`test_the_cleanup_paths_drop_what_the_app_never_runs` (the listed items are there, no framework, every PySide6 path matches something in the installed PySide6),
`test_the_build_script_is_valid_bash`.

Mutation checks (files restored afterwards, sha256 equal; each fails exactly the intended test): installer argument without `./`; no installer argument; the script writing another file; the script and the check asking uv differently;
the script not running the check; a misspelt PySide6 glob (`Desinger.app`); a Qt framework in the cleanup list; the qml tree missing from it; a bash syntax error in the script.
For M4: with a stub `vtool` first on the PATH the macOS-floor test is `SKIPPED ... vtool is not available: it comes with Xcode's command line tools`, with the real one it passes; `padded((26,)) == padded((26, 0, 0))` and `padded((26, 0)) >= padded((26, 0, 1))` is False.
For M3 I ran the script's tail by itself: clean tree prints the app, the zip and `Built from commit 001e7d6` with no warning; with a stray file the warning appears; in an empty folder it stops with `briefcase package made no zip in dist/.` (exit 1);
outside a git checkout it says so.

### The rebuild, and the numbers

`bash packaging/build_mac.sh`: exit 0, 1 min 24 s with warm caches (another agent's pytest was using a core at the same time). Its log shows, in order: the model's wheel and the 74 packages installed with the constraint, `Removing unneeded app bundle content...`,
the signing, then `The app's 74 packages are the 74 that uv.lock locks for this Mac, at the locked versions.`, the zip, and the two lines about the commit.

| Check | Before (547M build) | Now |
|---|---|---|
| `du -sh "build/themask/macos/app/The MASK.app"` | 547M (546.5 MiB) | **510M** (510.2 MiB = 522,428 KiB, about 535 MB in Finder's units); 36.4 MiB less; 90 MiB under the 600M limit. `app_packages` 405M (440M), `Frameworks` 102M, `app` 740K |
| `codesign -dv --verbose=2` | `Signature=adhoc` | `Signature=adhoc`, `flags=0x2(adhoc)`, `Identifier=local.themask.themask`, `Format=app bundle with Mach-O thin (arm64)`, `TeamIdentifier=not set` |
| `codesign --verify --deep --strict --verbose=2` | valid | `valid on disk`, `satisfies its Designated Requirement` (exit 0); the designated requirement is the new cdhash `H"1500da69b973fab995759d25f280075d62e91d73"` |
| Info.plist | `LSMinimumSystemVersion 14.0` | `LSMinimumSystemVersion` **26.0** (R92 now in a build), version 0.1.0, identifier `local.themask.themask` |
| `grep -rl "$HOME" <app>` | 43 files, all in `app_packages/bin` | **nothing**, in the whole app (and in `app_packages`); nor for `alijoeee`, `the-mask-worktrees` or `.briefcase` |
| the 14 cleanup paths | present | all 14 gone; Qt frameworks stay (QtCore, QtGui, QtWidgets, QtNetwork, QtSql, QtQuick, QtQml and the rest: 78), `platforms/` keeps `libqcocoa`, `libqminimal`, `libqoffscreen` |
| certifi / filelock in the app | 2026.10.18 / 4.2.4 | 2026.7.22 / 4.2.1, the lock's; 74 dist-infos; `tools.check_bundle_lock` also run on its own: exit 0 |
| Files | 15,747 entries; 454 Mach-O | 13,648 entries; 366 Mach-O; sealed resources 8,646 files (was 10,622) |
| The zip | 194,205,742 bytes | 182,618,652 bytes; `ditto -x -k` gives the same 13,648 entries and a signature that verifies deeply |
| Offline start without a window (offscreen Qt, temp home, temp data folder) | engine loaded in 1.7 s | `engine loaded seconds=1.76` in the log; the process lives until my SIGTERM (exit 143); `lsof -i -a -p <pid>` prints nothing (no sockets); only `cases/` and `logs/themask.log` were made, the temp home stayed empty; stderr: the stub's NSLog notice and two Qt offscreen notices, as before |
| The bundle's own Python, 31 checks | 31/31 | 31/31: all 17 modules from the bundle, Qt plugin path and `libqcocoa.dylib`, keyring's macOS backend found, guard blocks sockets, `Engine()` loads, supply-01 as Word and as PDF analysed (43 groups), exported without leak hits, none of the 41 truth values left, case saved encrypted and read back |
| Qt's Cocoa platform from the bundle | `cocoa`, style `macos` | the same, with the virtual keyboard plug-in, the QML tree and Qt's tools gone |
| Static link check | 37 unresolved references (23 in QML plugins, 7 Designer plugins, 7 elsewhere) | 12: 0 in QML plugins (the tree is gone), 7 Designer plugins, 5 elsewhere (three SQL drivers, the QML profiler plugin, the QtPdf image plugin), all optional Qt pieces a widgets app never loads |

### Gates

```
uv run ruff check src tests tools packaging            All checks passed!
uv run ruff format --check src tests tools packaging   121 files already formatted
uv run mypy src                                        Success: no issues found in 43 source files
uv run pytest -q                                       2738 passed in 93.75s (2725 before: 10 + 3 new)
```
No warning or error in the pytest output; the licence gate is part of the suite. The only edit after that run was the two sizes in the README, a document no test reads.

### Open points

- `Qt/plugins/designer/*` (7 dylibs for Qt Designer), the SQL drivers (`sqldrivers/`), the QML debugger plugins (`qmltooling/`) and the QtPdf image plugin are still in the app, because R94 did not list them and they are small; they are the next candidates if more has to go.
- The constraint makes `uv lock --upgrade` change the app on purpose: the next build holds whatever the lock holds, and the check follows the lock. If the lock is out of date with `pyproject.toml`, the script stops at its first command (`uv export --locked`).
- The build, the zip, the checks and `build/constraints.txt` are in the worktree (git-ignored). The final build after the last merge is the controller's, and will be from a clean tree.
- Unchanged from before: only macOS 27.0.1 was ever run; no real window was opened, no Keychain touched.

### Do it yourself

```bash
cd /Users/alijoeee/Developer/the-mask-worktrees/task-25
uv run pytest tests/test_check_bundle_lock.py tests/test_packaging.py -q       # 19 passed
bash packaging/build_mac.sh                                                    # 1.5-3 min; look for "The app's 74 packages are the 74 that uv.lock locks"
uv run python -m tools.check_bundle_lock                                       # exit 0; a lock-drifted app prints what differs and exits 1
du -sh "build/themask/macos/app/The MASK.app"                                  # 510M
codesign --verify --deep --strict --verbose=2 "build/themask/macos/app/The MASK.app"
grep -rl "$HOME" "build/themask/macos/app/The MASK.app"                        # prints nothing
ls "build/themask/macos/app/The MASK.app/Contents/Resources/app_packages/bin"  # No such file or directory
/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" "build/themask/macos/app/The MASK.app/Contents/Info.plist"   # 26.0
```
