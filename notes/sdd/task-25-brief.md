### Task 25: The MASK.app for the owner's Mac

**Files:**
- Create: `packaging/icon/themask.icns`, `packaging/icon/themask-1024.png`, `packaging/make_icon.py` (Pillow draws a simple mask glyph; `iconutil` builds the `.icns`), `packaging/build_mac.sh`
- Modify: `pyproject.toml` (`[tool.briefcase]`), `README.md` ("Install on your Mac")

**Interfaces:**
- `[tool.briefcase]`: `project_name = "The MASK"`, `bundle = "com.<owner-domain-or-name>.themask"` (owner's call; default `local.themask`), `version = "0.1.0"`, `[tool.briefcase.app.themask]` `formal_name = "The MASK"`, `sources = ["src/themask"]`, `requires` = the runtime dependencies from Task 1 (same pins, including the model wheel URL), `icon = "packaging/icon/themask"`; `[tool.briefcase.app.themask.macOS]` `universal_build = false`, `min_os_version = "13.0"`, `requires = []`.
- `packaging/build_mac.sh`: `uv run briefcase create macOS app && uv run briefcase build macOS app && uv run briefcase package macOS app -p zip --adhoc-sign`, then prints the path of `dist/The MASK-0.1.0.zip`.

- [ ] **Step 1: Make the icon** — `uv run python packaging/make_icon.py` → `packaging/icon/themask.icns` exists (`file` reports "Mac OS X icon").
- [ ] **Step 2: Add the Briefcase configuration** to `pyproject.toml`.
- [ ] **Step 3: Build** — `bash packaging/build_mac.sh` (the build itself downloads Briefcase's Python support package and the wheels once; the finished app never touches the network). Expected: ends with `dist/The MASK-0.1.0.zip`; `build/themask/macos/app/The MASK.app` exists.
- [ ] **Step 4: Verify size and signature** — `du -sh "build/themask/macos/app/The MASK.app"` → under 600M; `codesign -dv --verbose=2 "build/themask/macos/app/The MASK.app" 2>&1 | grep -E 'Signature=adhoc|Identifier'` → shows `Signature=adhoc`.
- [ ] **Step 5: Install and launch** — `ditto "build/themask/macos/app/The MASK.app" "/Applications/The MASK.app" && open "/Applications/The MASK.app"`. Expected: the window opens, no security dialog, the home screen says the engine is loaded within ~10 s.
- [ ] **Step 6: Offline smoke test (owner at the keyboard)** — turn Wi-Fi off; drop `tests/corpus/generated/supply-01.docx`; review; export to `~/Documents/The MASK`; open the masked file in Word (banner first, placeholders, no logo, no comments; File → Properties shows no author); run `lsof -i -a -p $(pgrep -f "The MASK.app")` → prints nothing (no sockets); turn Wi-Fi back on. Record the result in `docs/acceptance/2026-10-xx-mac-smoke.md`.
- [ ] **Step 7: Write "Install on your Mac" in README** (copy the `.app` to Applications; on another Mac: right-click → Open, or System Settings → Privacy & Security → Open Anyway) and commit — `git add -A && git commit -m "build: Briefcase packaging for macOS, ad-hoc signed"`

---

